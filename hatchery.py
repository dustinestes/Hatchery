import atexit
import json
import os
import shutil
import socket
import subprocess
import threading
import time

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for

from lib import config
from lib import db
from lib import clutch as clutch_lib
from lib import hatch as hatch_lib
from lib import alerts as alerts_lib
from lib import media_inspect as media_inspect_lib
from lib import import_files as import_files_lib
from lib import provision as provision_lib
from lib import nest_key_expiry as nest_key_expiry_lib
from lib import library as library_lib
from lib import nest_cache as nest_cache_lib
from lib import nests as nests_lib
from lib import settings_io as settings_io_lib
from lib.clutch import VMConfig, GuestOS
from lib.nest_transport import NestConnectionConfig
from pydantic import ValidationError
from lib.providers.base import BaseProvider
from lib.providers.factory import (
    NoNestSelectedError,
    UnknownNestError,
    UnsupportedProviderError,
    get_provider,
)
from lib.validators.builtins import register_builtins
from lib.validators.scheduler import run_validator, start_scheduler
from lib.validators.settings import list_validator_configs, migrate_bg_interval

# Tracks (session_id, vm_name) pairs currently being provisioned so the sync
# loop does not spawn duplicate threads.
_provisioning: set[tuple[str, str]] = set()
_provisioning_lock = threading.Lock()

app = Flask(__name__, template_folder="templates/ui")
app.secret_key = os.environ.get("HATCHERY_SECRET_KEY", "dev-secret-change-in-production")

_CLUTCH_ALERT_PREFIX = "Invalid Clutch file:"


def _sync_requirements() -> None:
    """Re-evaluate Controller requirements via the controller_requirements validator."""
    from lib.validators.scheduler import run_validator

    run_validator("controller_requirements", trigger="schedule")


def _clutch_error_detail(filename: str, error: str) -> str:
    """Strip redundant file context and Pydantic noise from a clutch load error."""
    file_header = f"Invalid Clutch file '{filename}':\n"
    if error.startswith(file_header):
        lines = error[len(file_header) :].splitlines()
        parts = [
            line.strip().removeprefix("clutch: ").removeprefix("Value error, ")
            for line in lines
            if line.strip()
        ]
        return "; ".join(parts)
    return error


def _sync_clutches() -> None:
    """Validate Clutch files via the clutch_files validator."""
    from lib.validators.scheduler import run_validator

    run_validator("clutch_files", trigger="schedule")


def _check_winrm(ip: str, port: int = 5985, timeout: float = 5.0) -> bool:
    """Return True if a TCP connection to the WinRM port succeeds."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _provision_vm_thread(
    session_id: str,
    vm_name: str,
    ip: str,
    admin_username: str,
    admin_password: str,
) -> None:
    """Run pending automation scripts for a VM sequentially, updating DB state per script."""
    try:
        scripts = hatch_lib.get_vm_scripts(session_id, vm_name)
        data_dir = config.data_dir()

        for script in scripts:
            if script["status"] == "succeeded":
                continue

            sname = script["script_name"]
            hatch_lib.add_event(
                session_id,
                vm_name,
                "hatchery",
                "INFO",
                f"Starting script: {sname}",
                script_name=sname,
            )
            hatch_lib.set_script_status(session_id, vm_name, script["run_order"], "running")
            script_path = data_dir / "automation" / "scripts" / sname

            try:
                exit_code, output = provision_lib.run_script(
                    ip,
                    admin_username,
                    admin_password,
                    script_path,
                    parameters=script.get("parameters") or {},
                )
            except Exception as exc:
                hatch_lib.add_event(
                    session_id,
                    vm_name,
                    "hatchery",
                    "ERROR",
                    f"Script failed: WinRM connection error - {exc}",
                    script_name=sname,
                )
                hatch_lib.set_script_status(
                    session_id,
                    vm_name,
                    script["run_order"],
                    "failed",
                    exit_code=-1,
                    output=str(exc),
                )
                _mark_remaining_skipped(session_id, vm_name, scripts, script["run_order"])
                hatch_lib.set_vm_status(session_id, vm_name, "failed")
                return

            for event in hatch_lib.parse_hatch_event_lines(output):
                hatch_lib.add_event(
                    session_id,
                    vm_name,
                    "script",
                    event["level"],
                    event["message"],
                    script_name=sname,
                    component=event["component"],
                    received_at=event["received_at"],
                )

            if exit_code != 0:
                hatch_lib.add_event(
                    session_id,
                    vm_name,
                    "hatchery",
                    "ERROR",
                    f"Script failed: {sname} - Exit Code: {exit_code}",
                    script_name=sname,
                )
                hatch_lib.set_script_status(
                    session_id,
                    vm_name,
                    script["run_order"],
                    "failed",
                    exit_code=exit_code,
                    output=output,
                )
                _mark_remaining_skipped(session_id, vm_name, scripts, script["run_order"])
                hatch_lib.set_vm_status(session_id, vm_name, "failed")
                return

            hatch_lib.add_event(
                session_id,
                vm_name,
                "hatchery",
                "INFO",
                f"Script complete: {sname} - Exit Code: {exit_code}",
                script_name=sname,
            )
            hatch_lib.set_script_status(
                session_id,
                vm_name,
                script["run_order"],
                "succeeded",
                exit_code=exit_code,
                output=output,
            )

            if script["reboot_after"]:
                hatch_lib.add_event(
                    session_id,
                    vm_name,
                    "hatchery",
                    "INFO",
                    f"Rebooting VM after script: {sname}",
                    script_name=sname,
                )
                provision_lib.restart_guest(ip, admin_username, admin_password)
                # Wait for WinRM to come back after restart
                for _ in range(120):
                    time.sleep(5)
                    if _check_winrm(ip):
                        hatch_lib.add_event(
                            session_id,
                            vm_name,
                            "hatchery",
                            "INFO",
                            "WinRM reconnected after reboot",
                            script_name=sname,
                        )
                        break

        hatch_lib.add_event(
            session_id,
            vm_name,
            "hatchery",
            "INFO",
            "All scripts succeeded - VM is fledged",
        )
        hatch_lib.set_vm_status(session_id, vm_name, "fledged")

    finally:
        with _provisioning_lock:
            _provisioning.discard((session_id, vm_name))


def _mark_remaining_skipped(
    session_id: str, vm_name: str, scripts: list[dict], failed_order: int
) -> None:
    for s in scripts:
        if s["run_order"] > failed_order and s["status"] == "pending":
            hatch_lib.set_script_status(session_id, vm_name, s["run_order"], "skipped")


def _spawn_provision_thread(
    session_id: str, vm_name: str, ip: str, admin_username: str, admin_password: str
) -> None:
    with _provisioning_lock:
        if (session_id, vm_name) in _provisioning:
            return
        _provisioning.add((session_id, vm_name))
    t = threading.Thread(
        target=_provision_vm_thread,
        args=(session_id, vm_name, ip, admin_username, admin_password),
        daemon=True,
    )
    t.start()


def _sync_hatch_status() -> None:
    """Monitor active VMs: advance through hatching→provisioning→fledged, cull if gone."""
    sessions: list[dict] = []
    for nest in nests_lib.list_nests():
        sessions.extend(hatch_lib.list_sessions(nest["id"]))
    monitored = [
        (
            s["id"],
            s.get("nest") or nests_lib.default_nest_id() or "",
            v["vm_name"],
            v.get("libvirt_uuid"),
            v["status"],
        )
        for s in sessions
        for v in s["vms"]
        if v["status"] in ("hatching", "provisioning", "fledged")
    ]
    if not monitored:
        return

    providers: dict[str, BaseProvider | None] = {}

    def _provider_for(nest_id: str) -> BaseProvider | None:
        if nest_id not in providers:
            try:
                providers[nest_id] = _provider(nest_id)
            except (NoNestSelectedError, UnknownNestError, UnsupportedProviderError):
                providers[nest_id] = None
        return providers[nest_id]

    for session_id, nest_id, vm_name, libvirt_uuid, vm_status in monitored:
        if not libvirt_uuid:
            continue
        provider = _provider_for(nest_id)
        if provider is None:
            continue

        current_name = provider.get_vm_name_by_uuid(libvirt_uuid)
        if current_name is None:
            hatch_lib.set_vm_status(session_id, vm_name, "culled")
            hatch_lib.archive_if_terminal(session_id)
            continue

        if current_name != vm_name:
            hatch_lib.update_vm_name(session_id, vm_name, current_name)
            vm_name = current_name

        if vm_status == "hatching":
            # Windows installation sends ACPI power-off at several points (e.g. end of
            # OOBE). Restart the VM so installation continues to the desktop and WinRM.
            # Scoped to hatching only — fledged VMs are left to the user. Post-install
            # script reboots arrive as on_reboot events (not power-off), so they never
            # leave the VM in "shut off" and this branch does not interfere with them.
            try:
                is_shut_off = provider.get_status(current_name) == "shut off"
            except Exception:
                is_shut_off = False
            if is_shut_off:
                try:
                    hatch_lib.add_event(
                        session_id,
                        vm_name,
                        "hatchery",
                        "INFO",
                        f"Starting VM: virsh start {current_name}",
                    )
                    provider.start_vm(current_name)
                except Exception:
                    pass
                continue

            ip = provider.get_vm_ip(current_name)
            if not ip:
                continue
            if not _check_winrm(ip):
                continue

            db_record = hatch_lib.get_vm_record(session_id, vm_name)
            admin_username = (db_record or {}).get("admin_username") or ""
            admin_password = (db_record or {}).get("admin_password") or ""

            # Gate on the setup-complete flag so automation never starts while
            # FirstLogonCommands (SSH install, WinRM config, etc.) are still running.
            if not provision_lib.check_setup_complete(ip, admin_username, admin_password):
                continue

            # Import first-boot setup events before deleting guest artifacts.
            try:
                setup_log = provision_lib.read_setup_log(ip, admin_username, admin_password)
                for event in hatch_lib.parse_hatch_event_lines(setup_log):
                    hatch_lib.add_event(
                        session_id,
                        vm_name,
                        "script",
                        event["level"],
                        event["message"],
                        script_name="hatchery-setup.ps1",
                        component=event["component"],
                        received_at=event["received_at"],
                    )
                provision_lib.delete_setup_log(ip, admin_username, admin_password)
            except Exception:
                pass

            # Flag confirmed — delete it immediately so the guest stays clean.
            try:
                provision_lib.delete_setup_flag(ip, admin_username, admin_password)
            except Exception:
                pass

            scripts = hatch_lib.get_vm_scripts(session_id, vm_name)
            if scripts:
                n = len(scripts)
                hatch_lib.add_event(
                    session_id,
                    vm_name,
                    "hatchery",
                    "INFO",
                    f"Windows setup complete - starting provisioning "
                    f"({n} script{'s' if n != 1 else ''})",
                )
                hatch_lib.set_vm_status(session_id, vm_name, "provisioning")
                _spawn_provision_thread(
                    session_id,
                    vm_name,
                    ip,
                    admin_username,
                    admin_password,
                )
            else:
                hatch_lib.add_event(
                    session_id,
                    vm_name,
                    "hatchery",
                    "INFO",
                    "Windows setup complete - no automation scripts configured",
                )
                hatch_lib.set_vm_status(session_id, vm_name, "fledged")

        elif vm_status == "provisioning":
            # Re-spawn provision thread if app restarted mid-provisioning.
            with _provisioning_lock:
                already_running = (session_id, vm_name) in _provisioning
            if not already_running:
                ip = provider.get_vm_ip(current_name)
                if ip and _check_winrm(ip):
                    db_record = hatch_lib.get_vm_record(session_id, vm_name)
                    hatch_lib.reset_scripts_for_retry(session_id, vm_name)
                    _spawn_provision_thread(
                        session_id,
                        vm_name,
                        ip,
                        (db_record or {}).get("admin_username") or "",
                        (db_record or {}).get("admin_password") or "",
                    )


def _sync_nest_key_expiry() -> None:
    """Evaluate Nest SSH identity expiry via the nest_key_expiry validator."""
    from lib.validators.scheduler import run_validator

    run_validator("nest_key_expiry", trigger="schedule")


def _background_loop(stop_event: threading.Event) -> None:
    """Hatch lifecycle poller only — validators run on their own scheduler (#268)."""
    while not stop_event.wait(config.bg_interval()):
        _sync_hatch_status()


_bg_stop_event: threading.Event | None = None


def _start_background_thread() -> threading.Event:
    """Start the hatch status poller; store the stop event on the module for tests."""
    global _bg_stop_event
    stop = threading.Event()
    _bg_stop_event = stop
    t = threading.Thread(target=_background_loop, args=(stop,), daemon=True)
    t.start()
    atexit.register(stop.set)
    return stop


def _provider(nest_id: str | None = None) -> BaseProvider:
    """Return the Nest provider for ``nest_id`` (sole Nest default when omitted)."""
    return get_provider(nest_id)


config.load()
config.init_data_dir()
db.init_db(config.data_dir() / "hatchery.db")
config.bind_db()
if config.nest_local_enabled():
    nests_lib.ensure_local_nest()
nests_lib.migrate_legacy_ssh_identities()

register_builtins()
migrate_bg_interval()

_runtime_services_started = False


def start_runtime_services() -> None:
    """Start hatch poller + validator scheduler (idempotent; worker-only under gunicorn).

    Must not run in the gunicorn arbiter: its stale ``config.get()`` snapshots used to
    rewrite all of ``app_settings`` and clobber Settings UI saves (#366).
    """
    global _runtime_services_started
    if _runtime_services_started:
        return
    _runtime_services_started = True
    for _vcfg in list_validator_configs():
        if _vcfg.get("enabled") and not _vcfg.get("stub"):
            try:
                run_validator(_vcfg["id"], trigger="schedule")
            except Exception:
                pass
    _sync_hatch_status()
    _start_background_thread()
    start_scheduler()


@app.before_request
def _ensure_runtime_services() -> None:
    """Cover ``gunicorn hatchery:app`` and tests; ``hatchery serve`` also uses post_fork."""
    start_runtime_services()


@app.context_processor
def inject_plane_status():
    from lib import plane_status as plane_status_lib

    status = plane_status_lib.footer_status()
    return {
        "hatchery_ok": status["hatchery_ok"],
        "hatchery_title": status["hatchery_title"],
        "hatchery_dot": status["hatchery_dot"],
        "nests_ok": status["nests_ok"],
        "nests_title": status["nests_title"],
        "nests_dot": status["nests_dot"],
        "nest_total": status["nest_total"],
        "library_enabled": status["library_enabled"],
        "libraries_visible": status["libraries_visible"],
        "libraries_ok": status["libraries_ok"],
        "libraries_title": status["libraries_title"],
        "libraries_dot": status["libraries_dot"],
    }


def _scan_dir(subdir: str, extensions: list[str] | None = None) -> list[str]:
    """Return sorted filenames from a data subdirectory."""
    path = config.data_dir() / subdir
    if not path.exists():
        return []
    files = []
    for f in sorted(path.iterdir()):
        if f.is_file():
            if extensions is None or f.suffix.lower() in extensions:
                files.append(f.name)
    return files


_SCRIPT_LANGUAGES = {
    ".ps1": "PowerShell",
    ".sh": "Shell",
    ".bash": "Shell",
    ".py": "Python",
    ".bat": "Batch",
    ".cmd": "Batch",
}

_SCRIPT_CONTENT_MAX_BYTES = 1_048_576  # 1 MiB


def _script_language(name: str) -> str:
    from pathlib import Path

    ext = Path(name).suffix.lower()
    if not ext:
        return "Unknown"
    return _SCRIPT_LANGUAGES.get(ext, ext.lstrip(".").upper() or "Unknown")


# Clutch control-plane formats (YAML today; extend for Docker Compose / etc.).
_CLUTCH_LANGUAGES = {
    ".yaml": "YAML",
    ".yml": "YAML",
}


def _clutch_language(name: str) -> str:
    from pathlib import Path

    ext = Path(name).suffix.lower()
    if not ext:
        return "Unknown"
    return _CLUTCH_LANGUAGES.get(ext, ext.lstrip(".").upper() or "Unknown")


def _resolve_script_path(name: str):
    """Return the path to a script under automation/scripts/, or None if invalid."""
    from pathlib import Path

    safe = Path(name).name
    if not safe or safe in (".", ".."):
        return None
    scripts_dir = (config.data_dir() / "automation" / "scripts").resolve()
    candidate = (scripts_dir / safe).resolve()
    try:
        candidate.relative_to(scripts_dir)
    except ValueError:
        return None
    return candidate


def _scan_script_inventory() -> list[dict]:
    """Return inventory metadata for files in automation/scripts/."""
    from datetime import datetime, timezone

    subdir = "automation/scripts"
    path = config.data_dir() / subdir
    if not path.exists():
        return []
    items = []
    for f in sorted(path.iterdir()):
        if not f.is_file():
            continue
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        modified = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        items.append(
            {
                "name": f.name,
                "relative_path": f"{subdir}/{f.name}",
                "absolute_path": str(f.resolve()),
                "language": _script_language(f.name),
                "modified_at": modified,
            }
        )
    return _enrich_library_inventory(items, domain="scripts")


def _scan_media_inventory(target: str) -> list[dict]:
    """Return enriched inventory for media/<target>/ (iso or virtio)."""
    return _enrich_library_inventory(
        media_inspect_lib.scan_media_dir(target),
        domain="media",
        media_target=target,
    )


def _scan_clutch_inventory() -> list[dict]:
    """Return enriched inventory metadata for clutches/*.yaml."""
    from datetime import datetime, timezone

    subdir = "clutches"
    path = config.data_dir() / subdir
    if not path.exists():
        return []
    items = []
    for f in sorted(path.glob("*.yaml")):
        if not f.is_file():
            continue
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        modified = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        items.append(
            {
                "name": f.name,
                "relative_path": f"{subdir}/{f.name}",
                "absolute_path": str(f.resolve()),
                "language": _clutch_language(f.name),
                "modified_at": modified,
            }
        )
    return _enrich_library_inventory(items, domain="clutches")


def _enrich_library_inventory(
    items: list[dict],
    *,
    domain: str,
    media_target: str | None = None,
) -> list[dict]:
    """Attach Library provenance / drift fields when Library is enabled."""
    if not config.library_enabled() or not items:
        for item in items:
            item.setdefault("drift_state", "local")
            item.setdefault("orphan", False)
            item.setdefault("orphan_reason", "")
            item.setdefault("library_provenance", None)
        return items
    try:
        from lib import library_drift as drift
        from lib import library_provenance as prov

        cids, bids = drift.connection_and_binding_ids()
        return prov.enrich_inventory(
            items,
            domain=domain,
            connection_ids=cids,
            binding_ids=bids,
            media_target=media_target,
        )
    except Exception:
        for item in items:
            item.setdefault("drift_state", "local")
            item.setdefault("orphan", False)
            item.setdefault("orphan_reason", "")
            item.setdefault("library_provenance", None)
        return items


def _script_used_by() -> dict[str, list[dict]]:
    """Map script basename → [{clutch, vm}, ...] from all loadable Clutches."""
    from pathlib import Path

    clutches_dir = config.data_dir() / "clutches"
    usage: dict[str, list[dict]] = {}
    if not clutches_dir.exists():
        return usage
    for path in sorted(clutches_dir.glob("*.yaml")):
        try:
            clutch = clutch_lib.load(path)
        except Exception:
            continue
        clutch_file = Path(path).name
        for vm in clutch.vms:
            for script in vm.automations:
                usage.setdefault(script.name, []).append(
                    {"clutch": clutch_file, "clutch_name": clutch.name, "vm": vm.name}
                )
    return usage


# ── Navigation panes ──────────────────────────────────────────────────────────


@app.route("/")
def dashboard():
    return render_template("index.html", active_pane="dashboard")


@app.route("/nests")
def nests():
    from lib import nest_reachability as nr

    registered = nests_lib.list_nests()
    for nest in registered:
        nest["reachability_ok"] = (
            (nr.get_snapshot().get("nests") or {}).get(nest["id"], {}).get("ok", True)
        )
        nest["reachability_label"] = nr.nest_reachability_label(nest["id"])
        nest["reachability_dot"] = nr.nest_dot_class(nest["id"])
    return render_template(
        "nests.html",
        active_pane="nests",
        nests=registered,
        selected_nest_id=registered[0]["id"] if registered else "",
    )


@app.route("/clutches")
def clutches():
    items = _scan_clutch_inventory()
    return render_template(
        "clutches.html",
        active_pane="clutches",
        clutch_files=[i["name"] for i in items],
        clutch_inventory=items,
        library_connections=(
            library_lib.parse_connections(config.library_connections(), enforce_expiry_future=False)
            if config.library_enabled()
            else []
        ),
        library_bindings=_library_reattach_bindings("clutches"),
        library_cache_sync_url=url_for("api_library_cache_sync"),
        library_cache_reattach_url=url_for("api_library_cache_reattach"),
    )


@app.route("/automation")
def automation():
    return redirect(url_for("automation_scripts"))


@app.route("/automation/scripts")
def automation_scripts():
    return render_template(
        "automation_scripts.html",
        active_pane="automation_scripts",
        scripts=_scan_script_inventory(),
        used_by=_script_used_by(),
        library_connections=(
            library_lib.parse_connections(config.library_connections(), enforce_expiry_future=False)
            if config.library_enabled()
            else []
        ),
        library_bindings=_library_reattach_bindings("scripts"),
        library_cache_sync_url=url_for("api_library_cache_sync"),
        library_cache_reattach_url=url_for("api_library_cache_reattach"),
    )


@app.route("/media")
def media():
    return redirect(url_for("media_iso"))


@app.route("/media/iso")
def media_iso():
    return render_template(
        "media_inventory.html",
        active_pane="media_iso",
        pane_title="ISO",
        pane_subtitle="Inventory of OS install media in the data directory.",
        nav_label="ISO media files",
        stub_text="Select an ISO to inspect",
        inspect_url_prefix="/api/media/iso/",
        delete_url_prefix="/api/media/iso/",
        import_url=url_for("api_import_media_iso"),
        import_accept=".iso",
        items=_scan_media_inventory("iso"),
        used_by=media_inspect_lib.media_used_by("os_media"),
        empty_subdir="media/iso/",
        item_kind="ISO",
        library_media_target="iso",
        library_catalog_url=url_for("api_library_media", target="iso"),
        library_pull_url=url_for("api_library_media_pull"),
        library_cache_sync_url=url_for("api_library_cache_sync"),
        library_cache_reattach_url=url_for("api_library_cache_reattach"),
        library_connections=(
            library_lib.parse_connections(config.library_connections(), enforce_expiry_future=False)
            if config.library_enabled()
            else []
        ),
        library_bindings=_library_reattach_bindings("media", media_target="iso"),
        inventory_api_url=url_for("api_media_iso"),
    )


@app.route("/media/virtio")
def media_virtio():
    return render_template(
        "media_inventory.html",
        active_pane="media_virtio",
        pane_title="VirtIO",
        pane_subtitle="Inventory of VirtIO driver media in the data directory.",
        nav_label="VirtIO media files",
        stub_text="Select a VirtIO file to inspect",
        inspect_url_prefix="/api/media/virtio/",
        delete_url_prefix="/api/media/virtio/",
        import_url=url_for("api_import_media_virtio"),
        import_accept=".iso",
        items=_scan_media_inventory("virtio"),
        used_by=media_inspect_lib.media_used_by("virtio_drivers"),
        empty_subdir="media/virtio/",
        item_kind="VirtIO file",
        library_media_target="virtio",
        library_catalog_url=url_for("api_library_media", target="virtio"),
        library_pull_url=url_for("api_library_media_pull"),
        library_cache_sync_url=url_for("api_library_cache_sync"),
        library_cache_reattach_url=url_for("api_library_cache_reattach"),
        library_connections=(
            library_lib.parse_connections(config.library_connections(), enforce_expiry_future=False)
            if config.library_enabled()
            else []
        ),
        library_bindings=_library_reattach_bindings("media", media_target="virtio"),
        inventory_api_url=url_for("api_media_virtio"),
    )


def _host_timezone() -> str:
    """Return the host's local IANA timezone name (e.g. 'America/Chicago')."""
    from datetime import datetime

    return str(datetime.now().astimezone().tzinfo)


_SETTINGS_SECTIONS = {
    "general": (
        "General",
        "Application paths, Hatch poll interval, validators, and feature toggles.",
    ),
    "security": (
        "Security",
        "Password visibility and Nest SSH identity expiry alert tiers.",
    ),
    "display": (
        "Display",
        "How timestamps and related values are shown in the UI.",
    ),
    "nests": (
        "Nests",
        "Local and remote Nest endpoints where VMs live.",
    ),
    "library": (
        "Library",
        "Connections and domain bindings for shared Clutches, scripts, and media.",
    ),
}


def _settings_template(
    section: str,
    *,
    form_error: str | None = None,
    form_saved: bool = False,
    cfg_overlay: dict | None = None,
    nest_ssh_identities_json: str | None = None,
    library_enable_hint: bool = False,
    nests_overlay: list | None = None,
):
    import json

    if section not in _SETTINGS_SECTIONS:
        abort(404)
    title, subtitle = _SETTINGS_SECTIONS[section]
    cfg = {**config.get(), **(cfg_overlay or {})}
    identities_json = nest_ssh_identities_json
    if identities_json is None:
        identities_json = json.dumps(cfg.get("nest_ssh_identities") or [], indent=2)
    registered_nests = nests_overlay
    if registered_nests is None and section == "nests":
        registered_nests = nests_lib.list_nests()

    from lib.validators.runs import latest_by_validator
    from lib.validators.settings import get_run_retention, list_validator_configs

    validator_configs = list_validator_configs() if section == "general" else []
    validator_latest = latest_by_validator() if section == "general" else {}
    validators_run_retention = get_run_retention() if section == "general" else 50

    library_api_providers: list = []
    library_forge_providers: list = []
    if section == "library":
        from lib import library_api as library_api_lib
        from lib import library_forge as library_forge_lib

        library_api_lib.register_builtins()
        library_forge_lib.register_builtins()
        library_api_providers = library_api_lib.all_providers()
        library_forge_providers = library_forge_lib.all_providers()

    return render_template(
        "settings.html",
        active_pane=f"settings_{section}",
        section=section,
        pane_title=title,
        pane_subtitle=subtitle,
        cfg=cfg,
        config_file=str(config.CONFIG_FILE),
        host_timezone=_host_timezone(),
        nest_ssh_identities_json=identities_json,
        form_error=form_error,
        form_saved=form_saved,
        library_enable_hint=library_enable_hint,
        nests=registered_nests or [],
        validator_configs=validator_configs,
        validator_latest=validator_latest,
        validators_run_retention=validators_run_retention,
        library_api_providers=library_api_providers,
        library_forge_providers=library_forge_providers,
    )


@app.route("/settings")
def settings():
    """Redirect parent Settings nav to the General section."""
    return redirect(url_for("settings_section", section="general"))


@app.route("/settings/<section>")
def settings_section(section: str):
    if section not in _SETTINGS_SECTIONS:
        abort(404)
    if section == "library" and not config.library_enabled():
        return redirect(url_for("settings_section", section="general", library_required="1"))
    return _settings_template(
        section,
        form_saved=request.args.get("saved") == "1",
        library_enable_hint=request.args.get("library_required") == "1",
    )


@app.route("/settings/<section>", methods=["POST"])
def settings_section_post(section: str):
    from pathlib import Path

    if section not in _SETTINGS_SECTIONS:
        abort(404)
    if section == "library" and not config.library_enabled():
        return redirect(url_for("settings_section", section="general", library_required="1"))

    def _rerender(error, cfg_overlay=None, identities_json=None, nests_overlay=None):
        return _settings_template(
            section,
            form_error=error,
            cfg_overlay=cfg_overlay,
            nest_ssh_identities_json=identities_json,
            nests_overlay=nests_overlay,
        )

    current = config.get()
    new_cfg = {**current}

    if section == "general":
        data_dir_raw = request.form.get("data_dir", "").strip()
        if not data_dir_raw:
            return _rerender("Data directory path is required.")

        bg_interval_raw = request.form.get("bg_interval", "").strip()
        try:
            bg_interval = int(bg_interval_raw)
            if bg_interval < 10:
                raise ValueError
        except ValueError:
            return _rerender(
                "Hatch status poll interval must be a whole number of seconds (minimum 10)."
            )

        new_cfg["data_dir"] = str(Path(data_dir_raw).expanduser())
        new_cfg["bg_interval"] = bg_interval
        library_was_enabled = bool(config.library_enabled())
        library_now_enabled = "library_enabled" in request.form
        new_cfg["library_enabled"] = library_now_enabled
        if library_was_enabled and not library_now_enabled:
            from lib import library_health as library_health_lib

            library_health_lib.resolve_all_library_alerts()

        retention_raw = request.form.get("validators_run_retention", "50").strip()
        try:
            retention = int(retention_raw)
            if retention < 10 or retention > 500:
                raise ValueError
        except ValueError:
            return _rerender(
                "Validator run history retention must be a whole number from 10 to 500."
            )

        from lib.validators.registry import all_validators
        from lib.validators.settings import cleaned_validator_settings

        configs: dict[str, dict] = {}
        for vid in request.form.getlist("validator_id"):
            stub = any(getattr(v, "stub", False) and v.id == vid for v in all_validators())
            interval_raw = request.form.get(f"validator_interval_{vid}", "60").strip()
            try:
                interval = int(interval_raw)
                if interval < 10:
                    raise ValueError
            except ValueError:
                return _rerender(
                    f"Validator interval for '{vid}' must be a whole number of seconds (minimum 10)."
                )
            enabled = (not stub) and (f"validator_enabled_{vid}" in request.form)
            entry: dict = {"enabled": enabled, "interval_seconds": interval}
            v_obj = next((v for v in all_validators() if v.id == vid), None)
            if v_obj is not None and getattr(v_obj, "supports_auto_sync", False):
                entry["auto_sync"] = f"validator_auto_sync_{vid}" in request.form
            configs[vid] = entry

        new_cfg.update(cleaned_validator_settings(configs, retention=retention))
        config.save(new_cfg)
        config.init_data_dir()
        db.init_db(Path(new_cfg["data_dir"]) / "hatchery.db")
        config.bind_db()
        return redirect(url_for("settings_section", section="general", saved="1"))

    if section == "security":
        days_list = request.form.getlist("nest_tier_days_before")
        alerts_list = request.form.getlist("nest_tier_alerts_per_day")
        if len(days_list) != len(alerts_list):
            return _rerender("Nest key alert tiers are incomplete - each row needs both fields.")
        tiers_parsed: list[dict] = []
        try:
            for days_raw, alerts_raw in zip(days_list, alerts_list, strict=True):
                days_before = int(str(days_raw).strip())
                alerts_per_day = int(str(alerts_raw).strip())
                if days_before < 0 or alerts_per_day < 1:
                    raise ValueError("days before must be ≥ 0 and alerts per day ≥ 1")
                tiers_parsed.append({"days_before": days_before, "alerts_per_day": alerts_per_day})
            nest_key_expiry_lib.parse_tiers(tiers_parsed or None)
        except (ValueError, TypeError) as exc:
            return _rerender(
                f"Nest key alert tiers are invalid: {exc}",
                {
                    "nest_key_alert_tiers": [
                        {
                            "days_before": d,
                            "alerts_per_day": a,
                        }
                        for d, a in zip(days_list, alerts_list, strict=False)
                        if str(d).strip().isdigit() and str(a).strip().isdigit()
                    ]
                },
            )

        identities_raw = request.form.get("nest_ssh_identities", "").strip()
        if identities_raw:
            # Legacy field removed from UI — ignore non-empty posts after Nest-row colocation.
            pass

        new_cfg["show_passwords"] = "show_passwords" in request.form
        new_cfg["nest_key_alert_tiers"] = tiers_parsed
        # SSH identity paths/expiry live on Nest rows (Settings → Nests).
        new_cfg["nest_ssh_identities"] = []
        config.save(new_cfg)
        _sync_nest_key_expiry()
        return redirect(url_for("settings_section", section="security", saved="1"))

    if section == "library":
        conn_ids = request.form.getlist("library_conn_id")
        conn_labels = request.form.getlist("library_conn_label")
        conn_types = request.form.getlist("library_conn_type")
        conn_providers = request.form.getlist("library_conn_provider")
        conn_uris = request.form.getlist("library_conn_base_uri")
        conn_tokens = request.form.getlist("library_conn_token")
        conn_expires = request.form.getlist("library_conn_expires_at")
        conn_kinds = request.form.getlist("library_conn_kinds")
        conn_enabled = request.form.getlist("library_conn_enabled")
        n = len(conn_labels)
        if not (
            len(conn_ids) == n
            and len(conn_types) == n
            and len(conn_providers) == n
            and len(conn_uris) == n
            and len(conn_tokens) == n
            and len(conn_expires) == n
            and len(conn_kinds) == n
            and len(conn_enabled) == n
        ):
            return _rerender("Library connections are incomplete - each row needs all fields.")
        raw_conns = []
        for i in range(n):
            raw_conns.append(
                {
                    "id": (conn_ids[i] or "").strip(),
                    "label": (conn_labels[i] or "").strip(),
                    "type": (conn_types[i] or "path").strip(),
                    "provider": (conn_providers[i] or "").strip(),
                    "base_uri": (conn_uris[i] or "").strip(),
                    "token": conn_tokens[i] or "",
                    "expires_at": (conn_expires[i] or "").strip(),
                    "kinds": [k.strip() for k in (conn_kinds[i] or "").split(",") if k.strip()],
                    "enabled": library_lib.parse_enabled(conn_enabled[i], default=True),
                }
            )
        try:
            connections = library_lib.parse_connections(raw_conns)
        except ValueError as exc:
            return _rerender(
                f"Library connections are invalid: {exc}",
                {
                    "library_connections": raw_conns,
                    "library_script_bindings": [],
                    "library_clutch_bindings": [],
                    "library_media_bindings": [],
                },
            )

        bind_ids = request.form.getlist("library_script_bind_id")
        bind_conn_ids = request.form.getlist("library_script_bind_connection_id")
        bind_labels = request.form.getlist("library_script_bind_label")
        bind_filters = request.form.getlist("library_script_bind_filter")
        bind_enabled = request.form.getlist("library_script_bind_enabled")
        bn = len(bind_conn_ids)
        if not (
            len(bind_ids) == bn
            and len(bind_labels) == bn
            and len(bind_filters) == bn
            and len(bind_enabled) == bn
        ):
            return _rerender(
                "Script bindings are incomplete - each row needs a connection and filter."
            )
        raw_binds = []
        for i in range(bn):
            raw_binds.append(
                {
                    "id": (bind_ids[i] or "").strip(),
                    "connection_id": (bind_conn_ids[i] or "").strip(),
                    "label": (bind_labels[i] or "").strip(),
                    "filter": (bind_filters[i] or "*").strip() or "*",
                    "enabled": library_lib.parse_enabled(bind_enabled[i], default=True),
                }
            )
        try:
            bindings = library_lib.parse_script_bindings(raw_binds, connections)
        except ValueError as exc:
            return _rerender(
                f"Script bindings are invalid: {exc}",
                {
                    "library_connections": connections,
                    "library_script_bindings": raw_binds,
                    "library_clutch_bindings": list(
                        config.get().get("library_clutch_bindings") or []
                    ),
                    "library_media_bindings": list(
                        config.get().get("library_media_bindings") or []
                    ),
                },
            )

        clutch_ids = request.form.getlist("library_clutch_bind_id")
        clutch_conn_ids = request.form.getlist("library_clutch_bind_connection_id")
        clutch_labels = request.form.getlist("library_clutch_bind_label")
        clutch_filters = request.form.getlist("library_clutch_bind_filter")
        clutch_enabled = request.form.getlist("library_clutch_bind_enabled")
        cn = len(clutch_conn_ids)
        if not (
            len(clutch_ids) == cn
            and len(clutch_labels) == cn
            and len(clutch_filters) == cn
            and len(clutch_enabled) == cn
        ):
            return _rerender(
                "Clutch bindings are incomplete - each row needs a connection and filter."
            )
        raw_clutches = []
        for i in range(cn):
            raw_clutches.append(
                {
                    "id": (clutch_ids[i] or "").strip(),
                    "connection_id": (clutch_conn_ids[i] or "").strip(),
                    "label": (clutch_labels[i] or "").strip(),
                    "filter": (clutch_filters[i] or "*").strip() or "*",
                    "enabled": library_lib.parse_enabled(clutch_enabled[i], default=True),
                }
            )
        try:
            clutch_bindings = library_lib.parse_clutch_bindings(raw_clutches, connections)
        except ValueError as exc:
            return _rerender(
                f"Clutch bindings are invalid: {exc}",
                {
                    "library_connections": connections,
                    "library_script_bindings": bindings,
                    "library_clutch_bindings": raw_clutches,
                    "library_media_bindings": list(
                        config.get().get("library_media_bindings") or []
                    ),
                },
            )

        media_ids = request.form.getlist("library_media_bind_id")
        media_conn_ids = request.form.getlist("library_media_bind_connection_id")
        media_labels = request.form.getlist("library_media_bind_label")
        media_filters = request.form.getlist("library_media_bind_filter")
        media_targets = request.form.getlist("library_media_bind_target")
        media_enabled = request.form.getlist("library_media_bind_enabled")
        mn = len(media_conn_ids)
        if not (
            len(media_ids) == mn
            and len(media_labels) == mn
            and len(media_filters) == mn
            and len(media_targets) == mn
            and len(media_enabled) == mn
        ):
            return _rerender(
                "Media bindings are incomplete - each row needs a connection, target, and filter."
            )
        raw_media = []
        for i in range(mn):
            raw_media.append(
                {
                    "id": (media_ids[i] or "").strip(),
                    "connection_id": (media_conn_ids[i] or "").strip(),
                    "label": (media_labels[i] or "").strip(),
                    "filter": (media_filters[i] or "*").strip() or "*",
                    "target": (media_targets[i] or "iso").strip() or "iso",
                    "enabled": library_lib.parse_enabled(media_enabled[i], default=True),
                }
            )
        try:
            media_bindings = library_lib.parse_media_bindings(raw_media, connections)
        except ValueError as exc:
            return _rerender(
                f"Media bindings are invalid: {exc}",
                {
                    "library_connections": connections,
                    "library_script_bindings": bindings,
                    "library_clutch_bindings": clutch_bindings,
                    "library_media_bindings": raw_media,
                },
            )

        new_cfg["library_connections"] = connections
        new_cfg["library_script_bindings"] = bindings
        new_cfg["library_clutch_bindings"] = clutch_bindings
        new_cfg["library_media_bindings"] = media_bindings
        config.save(new_cfg)
        from lib import library_health as library_health_lib

        library_health_lib.prune_alerts_for_removed_connections({c["id"] for c in connections})
        return redirect(url_for("settings_section", section="library", saved="1"))

    if section == "nests":
        nest_ids = request.form.getlist("nest_id")
        nest_names = request.form.getlist("nest_name")
        nest_providers = request.form.getlist("nest_provider_type")
        nest_locations = request.form.getlist("nest_location")
        nest_transports = request.form.getlist("nest_transport")
        nest_hosts = request.form.getlist("nest_host")
        nest_ports = request.form.getlist("nest_port")
        nest_ssh_users = request.form.getlist("nest_ssh_user")
        nest_identity_files = request.form.getlist("nest_identity_file")
        nest_cert_paths = request.form.getlist("nest_cert_path")
        nest_identity_expires = request.form.getlist("nest_identity_expires_at")
        nest_known_hosts = request.form.getlist("nest_known_hosts")
        nest_winrm_users = request.form.getlist("nest_winrm_user")
        nest_credential_refs = request.form.getlist("nest_credential_ref")
        raw_nests: list[dict] = []
        for i, nid in enumerate(nest_ids):
            raw_nests.append(
                {
                    "id": nid,
                    "name": nest_names[i] if i < len(nest_names) else "",
                    "provider_type": nest_providers[i] if i < len(nest_providers) else "libvirt",
                    "location": nest_locations[i] if i < len(nest_locations) else "local",
                    "transport": nest_transports[i] if i < len(nest_transports) else "",
                    "host": nest_hosts[i] if i < len(nest_hosts) else "",
                    "port": nest_ports[i] if i < len(nest_ports) else "",
                    "ssh_user": nest_ssh_users[i] if i < len(nest_ssh_users) else "",
                    "identity_file": nest_identity_files[i] if i < len(nest_identity_files) else "",
                    "cert_path": nest_cert_paths[i] if i < len(nest_cert_paths) else "",
                    "identity_expires_at": nest_identity_expires[i]
                    if i < len(nest_identity_expires)
                    else "",
                    "known_hosts": nest_known_hosts[i] if i < len(nest_known_hosts) else "default",
                    "winrm_user": nest_winrm_users[i] if i < len(nest_winrm_users) else "",
                    "credential_ref": nest_credential_refs[i]
                    if i < len(nest_credential_refs)
                    else "",
                }
            )
        try:
            nests_lib.replace_nests(raw_nests)
        except ValueError as exc:
            return _rerender(str(exc), nests_overlay=raw_nests)
        _sync_nest_key_expiry()
        return redirect(url_for("settings_section", section="nests", saved="1"))

    # display
    display_timezone_raw = request.form.get("display_timezone", "UTC").strip()
    if display_timezone_raw not in ("UTC", "local"):
        display_timezone_raw = "UTC"
    new_cfg["display_timezone"] = display_timezone_raw
    config.save(new_cfg)
    return redirect(url_for("settings_section", section="display", saved="1"))


@app.route("/api/settings/export")
def api_settings_export():
    """Download operational Settings as YAML (does not include data_dir)."""
    body = settings_io_lib.dump_yaml(settings_io_lib.export_document())
    return Response(
        body,
        mimetype="application/yaml",
        headers={
            "Content-Disposition": 'attachment; filename="hatchery-settings.yaml"',
        },
    )


@app.route("/api/settings/import", methods=["POST"])
def api_settings_import():
    """Replace operational Settings from a YAML document. Does not change data_dir."""
    text = ""
    upload = request.files.get("file") or request.files.get("settings")
    if upload and upload.filename:
        text = upload.read().decode("utf-8", errors="replace")
    else:
        data = request.get_json(silent=True)
        if isinstance(data, dict) and "yaml" in data:
            text = str(data.get("yaml") or "")
        elif isinstance(data, dict) and "document" in data and isinstance(data["document"], dict):
            try:
                result = settings_io_lib.apply_document(data["document"])
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            _sync_nest_key_expiry()
            return jsonify(result)
        else:
            text = request.get_data(as_text=True) or ""

    if not text.strip():
        return jsonify({"error": "Settings YAML is required"}), 400
    try:
        raw = settings_io_lib.load_yaml(text)
        result = settings_io_lib.apply_document(raw)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    _sync_nest_key_expiry()
    return jsonify(result)


def _library_require_enabled():
    if not config.library_enabled():
        return jsonify({"error": "Library is disabled - enable it under Settings → General."}), 403
    return None


def _library_reattach_bindings(domain: str, *, media_target: str | None = None) -> list[dict]:
    """Bindings for re-attach pickers (id, connection_id, filter, optional target)."""
    if not config.library_enabled():
        return []
    try:
        connections = library_lib.parse_connections(
            config.library_connections(), enforce_expiry_future=False
        )
    except ValueError:
        return []
    key = (domain or "").strip().lower()
    try:
        if key == "scripts":
            binds = library_lib.parse_script_bindings(config.library_script_bindings(), connections)
        elif key == "clutches":
            binds = library_lib.parse_clutch_bindings(config.library_clutch_bindings(), connections)
        elif key == "media":
            binds = library_lib.parse_media_bindings(config.library_media_bindings(), connections)
            if media_target:
                mt = media_target.strip().lower()
                binds = [b for b in binds if str(b.get("target") or "") == mt]
        else:
            return []
    except ValueError:
        return []
    out: list[dict] = []
    for b in binds:
        row = {
            "id": b["id"],
            "connection_id": b["connection_id"],
            "label": b.get("label") or b.get("filter") or "*",
            "filter": b.get("filter") or "*",
            "enabled": bool(b.get("enabled", True)),
        }
        if key == "media":
            row["target"] = b.get("target") or ""
        out.append(row)
    return out


def _reattach_binding_or_error(
    *,
    domain: str,
    connection_id: str,
    binding_id: str | None,
    media_target: str | None = None,
) -> tuple[dict | None, str | None]:
    """Return (binding, None) or (None, error) for reattach (#357, #363, #360)."""
    cid = (connection_id or "").strip()
    binds = [
        b
        for b in _library_reattach_bindings(domain, media_target=media_target)
        if b.get("connection_id") == cid
    ]
    if not binds:
        return None, "Add a Library binding under Settings → Library for this connection first"
    bid = (binding_id or "").strip()
    if not bid:
        return None, "Select a Library binding for this connection"
    for b in binds:
        if b.get("id") == bid:
            return b, None
    return None, "Binding does not belong to that connection"


def _connection_from_request_body(data: dict) -> dict:
    """Normalize a connection object from JSON (Settings test or pull)."""
    raw = data.get("connection")
    if isinstance(raw, dict):
        parsed = library_lib.parse_connections([raw], enforce_expiry_future=False)
        return parsed[0]
    conn_id = str(data.get("connection_id") or "").strip()
    if not conn_id:
        raise ValueError("connection or connection_id is required")
    for conn in config.library_connections():
        if conn.get("id") == conn_id:
            return library_lib.parse_connections([conn], enforce_expiry_future=False)[0]
    raise ValueError(f"Unknown connection id: {conn_id}")


@app.route("/api/library/test-connection", methods=["POST"])
def api_library_test_connection():
    denied = _library_require_enabled()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        conn = _connection_from_request_body(data)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    result = library_lib.test_connection(conn)
    from lib import library_health as library_health_lib

    registered = any(c.get("id") == conn.get("id") for c in config.library_connections())
    library_health_lib.apply_manual_test_result(conn, result, registered=registered)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route("/api/library/test-filter", methods=["POST"])
def api_library_test_filter():
    denied = _library_require_enabled()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        conn = _connection_from_request_body(data)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc), "hits": []}), 400
    filt = str(data.get("filter") or "*")
    domain = str(data.get("domain") or "scripts").strip().lower() or "scripts"
    result = library_lib.test_filter(conn, filt, domain=domain)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route("/api/library/connections", methods=["PUT"])
def api_library_connection_upsert():
    """Upsert one Library connection (scoped Save from Settings → Library)."""
    denied = _library_require_enabled()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    raw = data.get("connection")
    if not isinstance(raw, dict):
        return jsonify({"ok": False, "error": "connection object is required"}), 400
    try:
        parsed = library_lib.parse_connections([raw], enforce_expiry_future=True)[0]
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    cfg = config.get()
    connections = list(cfg.get("library_connections") or [])
    cid = parsed["id"]
    replaced = False
    for i, existing in enumerate(connections):
        if existing.get("id") == cid:
            connections[i] = parsed
            replaced = True
            break
    if not replaced:
        connections.append(parsed)
    config.update_settings({"library_connections": connections})
    from lib import library_health as library_health_lib

    library_health_lib.prune_alerts_for_removed_connections({c["id"] for c in connections})
    return jsonify({"ok": True, "connection": parsed, "created": not replaced})


_BINDING_DOMAIN_KEYS = {
    "scripts": ("library_script_bindings", library_lib.parse_script_bindings),
    "clutches": ("library_clutch_bindings", library_lib.parse_clutch_bindings),
    "media": ("library_media_bindings", library_lib.parse_media_bindings),
}


@app.route("/api/library/connections/<conn_id>", methods=["DELETE"])
def api_library_connection_delete(conn_id: str):
    """Delete one Library connection and cascade-remove bindings that reference it."""
    denied = _library_require_enabled()
    if denied:
        return denied
    cid = str(conn_id or "").strip()
    if not cid:
        return jsonify({"ok": False, "error": "connection id is required"}), 400

    cfg = config.get()
    existing = list(cfg.get("library_connections") or [])
    removed = next((c for c in existing if c.get("id") == cid), None)
    if removed is None:
        return jsonify({"ok": False, "error": "Unknown connection id"}), 404

    data = request.get_json(silent=True) or {}
    delete_git_cache = bool(data.get("delete_git_cache"))
    delete_attributed_cache = bool(data.get("delete_attributed_cache"))

    bindings_removed = 0
    patch: dict = {}
    for cfg_key, _parse in _BINDING_DOMAIN_KEYS.values():
        rows = list(cfg.get(cfg_key) or [])
        kept = [b for b in rows if str(b.get("connection_id") or "") != cid]
        bindings_removed += len(rows) - len(kept)
        patch[cfg_key] = kept

    connections = [c for c in existing if c.get("id") != cid]
    patch["library_connections"] = connections
    config.update_settings(patch)
    from lib import library_health as library_health_lib
    from lib import library_provenance as prov

    library_health_lib.prune_alerts_for_removed_connections({c["id"] for c in connections})

    attributed_deleted: list[str] = []
    if delete_attributed_cache:
        attributed_deleted = prov.delete_attributed_cache_files(
            prov.rows_for_connection(cid),
            data_dir=config.data_dir(),
        )

    git_cache_deleted = False
    git_cache_warning = None
    if delete_git_cache and str(removed.get("type") or "").strip().lower() == "git":
        try:
            git_cache_deleted = library_lib.delete_git_cache(cid)
        except (ValueError, OSError) as exc:
            git_cache_warning = str(exc)

    payload = {
        "ok": True,
        "id": cid,
        "bindings_removed": bindings_removed,
        "git_cache_deleted": git_cache_deleted,
        "attributed_cache_deleted": attributed_deleted,
    }
    if git_cache_warning:
        payload["git_cache_warning"] = git_cache_warning
    return jsonify(payload)


@app.route("/api/library/bindings/<domain>", methods=["PUT"])
def api_library_binding_upsert(domain: str):
    """Upsert one domain binding (scoped Save from Settings → Library)."""
    denied = _library_require_enabled()
    if denied:
        return denied
    key = str(domain or "").strip().lower()
    if key not in _BINDING_DOMAIN_KEYS:
        return jsonify({"ok": False, "error": "domain must be scripts, clutches, or media"}), 400
    data = request.get_json(silent=True) or {}
    raw = data.get("binding")
    if not isinstance(raw, dict):
        return jsonify({"ok": False, "error": "binding object is required"}), 400

    cfg_key, parse_fn = _BINDING_DOMAIN_KEYS[key]
    try:
        connections = library_lib.parse_connections(
            config.library_connections(), enforce_expiry_future=False
        )
        parsed = parse_fn([raw], connections)[0]
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    cfg = config.get()
    bindings = list(cfg.get(cfg_key) or [])
    bid = parsed["id"]
    replaced = False
    for i, existing in enumerate(bindings):
        if existing.get("id") == bid:
            bindings[i] = parsed
            replaced = True
            break
    if not replaced:
        bindings.append(parsed)
    config.update_settings({cfg_key: bindings})
    return jsonify({"ok": True, "binding": parsed, "created": not replaced})


@app.route("/api/library/bindings/<domain>/<binding_id>", methods=["DELETE"])
def api_library_binding_delete(domain: str, binding_id: str):
    """Delete one domain binding."""
    denied = _library_require_enabled()
    if denied:
        return denied
    key = str(domain or "").strip().lower()
    if key not in _BINDING_DOMAIN_KEYS:
        return jsonify({"ok": False, "error": "domain must be scripts, clutches, or media"}), 400
    bid = str(binding_id or "").strip()
    if not bid:
        return jsonify({"ok": False, "error": "binding id is required"}), 400
    cfg_key, _parse = _BINDING_DOMAIN_KEYS[key]
    cfg = config.get()
    bindings = list(cfg.get(cfg_key) or [])
    kept = [b for b in bindings if b.get("id") != bid]
    if len(kept) == len(bindings):
        return jsonify({"ok": False, "error": "Unknown binding id"}), 404
    data = request.get_json(silent=True) or {}
    delete_attributed_cache = bool(data.get("delete_attributed_cache"))
    config.update_settings({cfg_key: kept})
    attributed_deleted: list[str] = []
    if delete_attributed_cache:
        from lib import library_provenance as prov

        attributed_deleted = prov.delete_attributed_cache_files(
            prov.rows_for_binding(bid),
            data_dir=config.data_dir(),
        )
    return jsonify({"ok": True, "id": bid, "attributed_cache_deleted": attributed_deleted})


@app.route("/api/library/scripts")
def api_library_scripts():
    denied = _library_require_enabled()
    if denied:
        return denied
    raw_connections = config.library_connections()
    raw_bindings = config.library_script_bindings()
    try:
        connections = library_lib.connections_for_bindings(raw_connections, raw_bindings)
        bindings = library_lib.parse_script_bindings(raw_bindings, connections)
    except ValueError as exc:
        return jsonify({"error": str(exc), "items": []}), 400
    items = library_lib.catalog_scripts(connections, bindings)
    cached_names = {s["name"] for s in _scan_script_inventory()}
    items = library_lib.annotate_cached(items, cached_names)
    return jsonify({"items": items})


@app.route("/api/library/scripts/pull", methods=["POST"])
def api_library_scripts_pull():
    denied = _library_require_enabled()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        conn = _connection_from_request_body(data)
        relative_path = str(data.get("relative_path") or "").strip()
        if not relative_path:
            raise ValueError("relative_path is required")
        binding_id = str(data.get("binding_id") or "").strip() or None
        overwrite = bool(data.get("overwrite") or data.get("sync"))
        result = library_lib.pull_script(
            conn, relative_path, binding_id=binding_id, overwrite=overwrite
        )
    except FileExistsError as exc:
        return jsonify({"error": str(exc)}), 409
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({"imported": [result["name"]], "sha256": result["sha256"], "errors": []})


@app.route("/api/library/clutches")
def api_library_clutches():
    denied = _library_require_enabled()
    if denied:
        return denied
    raw_connections = config.library_connections()
    raw_bindings = config.library_clutch_bindings()
    try:
        connections = library_lib.connections_for_bindings(raw_connections, raw_bindings)
        bindings = library_lib.parse_clutch_bindings(raw_bindings, connections)
    except ValueError as exc:
        return jsonify({"error": str(exc), "items": []}), 400
    items = library_lib.catalog_clutches(connections, bindings)
    cached_names = set(_scan_dir("clutches", [".yaml"]))
    items = library_lib.annotate_cached(items, cached_names)
    return jsonify({"items": items})


@app.route("/api/library/clutches/pull", methods=["POST"])
def api_library_clutches_pull():
    denied = _library_require_enabled()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        conn = _connection_from_request_body(data)
        relative_path = str(data.get("relative_path") or "").strip()
        if not relative_path:
            raise ValueError("relative_path is required")
        binding_id = str(data.get("binding_id") or "").strip() or None
        overwrite = bool(data.get("overwrite") or data.get("sync"))
        result = library_lib.pull_clutch(
            conn, relative_path, binding_id=binding_id, overwrite=overwrite
        )
    except FileExistsError as exc:
        return jsonify({"error": str(exc)}), 409
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({"imported": [result["name"]], "sha256": result["sha256"], "errors": []})


@app.route("/api/library/media")
def api_library_media():
    denied = _library_require_enabled()
    if denied:
        return denied
    target = (request.args.get("target") or "").strip().lower() or None
    raw_connections = config.library_connections()
    raw_bindings = config.library_media_bindings()
    try:
        connections = library_lib.connections_for_bindings(raw_connections, raw_bindings)
        bindings = library_lib.parse_media_bindings(raw_bindings, connections)
        items = library_lib.catalog_media(connections, bindings, target=target)
    except ValueError as exc:
        return jsonify({"error": str(exc), "items": []}), 400
    if target in ("iso", "virtio"):
        cached_names = {i["name"] for i in media_inspect_lib.scan_media_dir(target)}
    else:
        cached_names = {i["name"] for i in media_inspect_lib.scan_media_dir("iso")} | {
            i["name"] for i in media_inspect_lib.scan_media_dir("virtio")
        }
    items = library_lib.annotate_cached(items, cached_names)
    return jsonify({"items": items})


@app.route("/api/library/media/pull", methods=["POST"])
def api_library_media_pull():
    denied = _library_require_enabled()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        conn = _connection_from_request_body(data)
        relative_path = str(data.get("relative_path") or "").strip()
        target = str(data.get("target") or "").strip().lower()
        if not relative_path:
            raise ValueError("relative_path is required")
        if not target:
            raise ValueError("target is required (iso or virtio)")
        binding_id = str(data.get("binding_id") or "").strip() or None
        overwrite = bool(data.get("overwrite") or data.get("sync"))
        result = library_lib.pull_media(
            conn, relative_path, target=target, binding_id=binding_id, overwrite=overwrite
        )
    except FileExistsError as exc:
        return jsonify({"error": str(exc)}), 409
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({"imported": [result["name"]], "sha256": result["sha256"], "errors": []})


@app.route("/api/library/cache/sync", methods=["POST"])
def api_library_cache_sync():
    """Overwrite one attributed Cached file, then evaluate that row (#308)."""
    denied = _library_require_enabled()
    if denied:
        return denied
    from lib import library_drift as drift
    from lib import library_provenance as prov

    data = request.get_json(silent=True) or {}
    domain = str(data.get("domain") or "").strip().lower()
    name = str(data.get("name") or "").strip()
    media_target = str(data.get("media_target") or data.get("target") or "").strip().lower() or None
    if domain not in ("scripts", "clutches", "media"):
        return jsonify({"ok": False, "error": "domain must be scripts, clutches, or media"}), 400
    if not name:
        return jsonify({"ok": False, "error": "name is required"}), 400
    row = prov.get_for_cache(domain, name, media_target=media_target)
    if row is None:
        return jsonify({"ok": False, "error": "No Library provenance for this cached file"}), 404
    connections = drift.connection_by_id()
    try:
        summary = drift.sync_row(row, connections)
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    if summary is None:
        return jsonify(
            {"ok": False, "error": "Connection missing; re-attach provenance first"}
        ), 400
    drift.reconcile_domain_alerts(auto_sync=False)
    return jsonify(
        {
            "ok": True,
            "imported": [name],
            "sha256": summary.get("cache_sha256"),
            "drift_state": summary.get("drift_state"),
            "cache_drifted": summary.get("cache_drifted"),
            "source_drifted": summary.get("source_drifted"),
            "live_mismatch": summary.get("live_mismatch"),
        }
    )


@app.route("/api/library/cache/reattach", methods=["POST"])
def api_library_cache_reattach():
    """Test path on a connection and rewrite provenance (#308)."""
    denied = _library_require_enabled()
    if denied:
        return denied
    from lib import library_provenance as prov

    data = request.get_json(silent=True) or {}
    domain = str(data.get("domain") or "").strip().lower()
    name = str(data.get("name") or "").strip()
    media_target = str(data.get("media_target") or data.get("target") or "").strip().lower() or None
    relative_path = str(data.get("relative_path") or "").strip()
    binding_id = str(data.get("binding_id") or "").strip() or None
    commit = bool(data.get("commit"))
    if domain not in ("scripts", "clutches", "media"):
        return jsonify({"ok": False, "error": "domain must be scripts, clutches, or media"}), 400
    if not name or not relative_path:
        return jsonify({"ok": False, "error": "name and relative_path are required"}), 400
    from pathlib import Path

    cache_bn = Path(str(name).replace("\\", "/")).name
    path_bn = Path(str(relative_path).replace("\\", "/")).name
    if not cache_bn or path_bn != cache_bn:
        return jsonify(
            {
                "ok": False,
                "error": (
                    "Relative path must match the Cached filename "
                    "(rename is not supported; re-import if the source name changed)"
                ),
            }
        ), 400
    try:
        conn = _connection_from_request_body(data)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    binding, bind_err = _reattach_binding_or_error(
        domain=domain,
        connection_id=str(conn.get("id") or ""),
        binding_id=binding_id,
        media_target=media_target if domain == "media" else None,
    )
    if bind_err or binding is None:
        return jsonify({"ok": False, "error": bind_err or "Invalid binding"}), 400
    filt = str(binding.get("filter") or "*")
    if not library_lib.path_matches_filter(relative_path, filt):
        return jsonify(
            {
                "ok": False,
                "error": (f"Relative path does not match the selected binding filter ({filt})"),
            }
        ), 400
    try:
        tip = library_lib.resolve_source_digest(conn, relative_path)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if tip is None:
        return jsonify(
            {"ok": False, "error": "Path does not resolve on that source (or tip unknown)"}
        ), 400
    kind, digest = tip
    if not commit:
        return jsonify(
            {
                "ok": True,
                "tested": True,
                "source_digest": digest,
                "source_digest_kind": kind,
            }
        )
    try:
        row = prov.reattach(
            domain=domain,
            cache_name=name,
            connection_id=str(conn.get("id") or ""),
            relative_path=relative_path,
            source_type=str(conn.get("type") or ""),
            source_digest=digest,
            source_digest_kind=kind,
            binding_id=binding_id,
            media_target=media_target,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    # Sync state comes from evaluate, not from re-attach (#360).
    from lib import library_drift as drift_lib

    drift_lib.evaluate_one(
        domain,
        name,
        media_target=media_target,
        single_file=True,
    )
    refreshed = prov.get_for_cache(domain, name, media_target=media_target) or row
    return jsonify({"ok": True, "provenance": refreshed})


def _nest_from_request(data: dict) -> NestConnectionConfig:
    """Build NestConnectionConfig from JSON — prefer nest_id from the registry."""
    nest_id = str(data.get("nest_id") or data.get("nest") or "").strip()
    if nest_id:
        nest = nests_lib.get_nest(nest_id)
        if nest is None:
            raise ValueError(f"Unknown Nest id: {nest_id}")
        winrm_password = data.get("winrm_password")
        return nests_lib.to_connection_config(
            nest,
            winrm_password=str(winrm_password) if winrm_password is not None else None,
        )

    location = str(data.get("location") or "local").strip().lower()
    if location not in ("local", "remote"):
        raise ValueError("location must be 'local' or 'remote'")
    if location == "remote":
        # Ad-hoc remote (no nest_id) — construct config so ensure/preflight can fail closed.
        from lib.nest_transport import NestSshConfig

        host = str(data.get("host") or "remote-nest").strip() or "remote-nest"
        return NestConnectionConfig(
            location="remote",
            transport="ssh",
            ssh=NestSshConfig(host=host),
        )
    return NestConnectionConfig(location="local")


def _nest_payload_from_request_body(data: dict) -> dict:
    """Normalize a Nest object from JSON (Settings Test Nest connection)."""
    raw = data.get("nest")
    if isinstance(raw, dict):
        nid = str(raw.get("id") or "").strip() or nests_lib.new_id()
        return nests_lib.normalize_nest({**raw, "id": nid})
    nest_id = str(data.get("nest_id") or "").strip()
    if not nest_id:
        raise ValueError("nest or nest_id is required")
    nest = nests_lib.get_nest(nest_id)
    if nest is None:
        raise ValueError(f"Unknown Nest id: {nest_id}")
    return nest


@app.route("/api/nests/test-connection", methods=["POST"])
def api_nests_test_connection():
    """Test Nest connection (local ack or remote transport check)."""
    data = request.get_json(silent=True) or {}
    try:
        nest = _nest_payload_from_request_body(data)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    winrm_password = data.get("winrm_password")
    nest_body = data.get("nest")
    if isinstance(nest_body, dict) and nest_body.get("winrm_password") is not None:
        winrm_password = nest_body.get("winrm_password")
    result = nests_lib.test_connection(
        nest,
        winrm_password=str(winrm_password) if winrm_password is not None else None,
    )
    return jsonify(result)


def _clutch_artifacts_from_request(data: dict):
    """Load clutch by filename or accept an explicit artifacts list."""
    from pathlib import Path

    clutch_file = str(data.get("clutch_file") or "").strip()
    if clutch_file:
        clutch_obj = _load_clutch(clutch_file)
        return nest_cache_lib.collect_clutch_artifacts(clutch_obj), clutch_obj
    raw_arts = data.get("artifacts")
    if not isinstance(raw_arts, list) or not raw_arts:
        raise ValueError("clutch_file or artifacts[] is required")
    arts: list[nest_cache_lib.CacheArtifact] = []
    for item in raw_arts:
        if not isinstance(item, dict):
            raise ValueError("each artifact must be an object")
        kind = str(item.get("kind") or "").strip()
        basename = str(item.get("basename") or item.get("name") or "").strip()
        if kind not in nest_cache_lib.ARTIFACT_KINDS:
            raise ValueError(f"invalid artifact kind: {kind}")
        if not basename:
            raise ValueError("artifact basename is required")
        sha = item.get("sha256")
        arts.append(
            nest_cache_lib.CacheArtifact(
                kind=kind,  # type: ignore[arg-type]
                basename=Path(basename).name,
                sha256=str(sha).strip() if sha else None,
                absolute_path=str(item["absolute_path"]).strip()
                if item.get("absolute_path")
                else None,
            )
        )
    return arts, None


@app.route("/api/nest-cache/preflight", methods=["POST"])
def api_nest_cache_preflight():
    """Verify Nest cache has required clutch/media artifacts before hatch."""
    data = request.get_json(silent=True) or {}
    try:
        nest = _nest_from_request(data)
        artifacts, _clutch = _clutch_artifacts_from_request(data)
        result = nest_cache_lib.preflight(artifacts, nest=nest)
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc), "issues": []}), 404
    except nest_cache_lib.NestCacheError as exc:
        return jsonify({"ok": False, "error": str(exc), "issues": []}), 501
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc), "issues": []}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "issues": []}), 400
    return jsonify(
        {
            "ok": result.ok,
            "error": None if result.ok else result.error_message(),
            "issues": [
                {
                    "kind": i.artifact.kind,
                    "basename": i.artifact.basename,
                    "relative_path": i.artifact.relative_path,
                    "reason": i.reason,
                    "detail": i.detail,
                    "vm_name": i.artifact.vm_name,
                }
                for i in result.issues
            ],
        }
    )


@app.route("/api/nest-cache/ensure", methods=["POST"])
def api_nest_cache_ensure():
    """Ensure Nest cache has required artifacts (local verify; remote stub)."""
    data = request.get_json(silent=True) or {}
    try:
        nest = _nest_from_request(data)
        artifacts, _clutch = _clutch_artifacts_from_request(data)
        result = nest_cache_lib.ensure(artifacts, nest=nest)
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc), "issues": []}), 404
    except nest_cache_lib.NestCacheError as exc:
        return jsonify({"ok": False, "error": str(exc), "issues": []}), 501
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc), "issues": []}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "issues": []}), 400
    return jsonify(
        {
            "ok": result.ok,
            "error": None if result.ok else result.error_message(),
            "issues": [
                {
                    "kind": i.artifact.kind,
                    "basename": i.artifact.basename,
                    "relative_path": i.artifact.relative_path,
                    "reason": i.reason,
                    "detail": i.detail,
                    "vm_name": i.artifact.vm_name,
                }
                for i in result.issues
            ],
        }
    )


@app.route("/notifications")
def notifications_pane():
    """Redirect parent Notifications nav to the Alerts child pane."""
    return redirect(url_for("alerts_pane"))


@app.route("/notifications/alerts")
def alerts_pane():
    items = alerts_lib.list_recent(500)
    return render_template("alerts.html", active_pane="alerts", items=items)


@app.route("/notifications/events")
def events_pane():
    return render_template("events.html", active_pane="events")


@app.route("/notifications/validators")
def validators_pane():
    from lib.validators.registry import all_validators
    from lib.validators.runs import list_runs

    runs = list_runs(limit=200)
    titles = {v.id: v.title for v in all_validators()}
    return render_template(
        "validators.html",
        active_pane="validators",
        runs=runs,
        validator_titles=titles,
    )


@app.route("/api/validators/runs")
def api_validator_runs():
    from lib.validators.runs import list_runs

    validator_id = request.args.get("validator_id") or None
    status = request.args.get("status") or None
    tier = request.args.get("tier") or None
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        limit = 100
    return jsonify(
        {
            "runs": list_runs(
                limit=limit,
                validator_id=validator_id,
                status=status,
                tier=tier,
            )
        }
    )


# ── Hatch orchestration ───────────────────────────────────────────────────────


_BOOT_KEY_POLL_ATTEMPTS = 60  # poll up to 60s (1s intervals) for VM to reach running state
_BOOT_KEY_SETTLE_SECONDS = 3  # UEFI POST often trails libvirt "running"
_BOOT_KEY_BURST_ATTEMPTS = 60  # send key 60 times (0.5s intervals) = 30s burst
_BOOT_KEY_BURST_INTERVAL = 0.5


def _send_boot_key(provider, name: str) -> None:
    """Wait for VM running, then send KEY_ENTER repeatedly to clear the CD boot prompt.

    Libvirt reports ``running`` as soon as QEMU starts — often before firmware shows
    "Press any key to boot from CD or DVD". A short burst at that moment misses the
    prompt. After a brief settle we keep sending for tens of seconds. Transient
    ``send_key`` failures are ignored so an early miss does not abort the burst.
    """
    for _ in range(_BOOT_KEY_POLL_ATTEMPTS):
        try:
            if provider.get_status(name) == "running":
                break
        except Exception:
            pass
        time.sleep(1)
    time.sleep(_BOOT_KEY_SETTLE_SECONDS)
    for _ in range(_BOOT_KEY_BURST_ATTEMPTS):
        try:
            provider.send_key(name, "KEY_ENTER")
        except Exception:
            pass
        time.sleep(_BOOT_KEY_BURST_INTERVAL)


def _run_hatch_session(
    session_id: str, vms: list, passwords: dict, clutch_file: str, storage_path: str | None = None
) -> None:
    """Background thread: create each VM sequentially and track state in DB."""
    session = hatch_lib.get_session(session_id)
    nest_id = (session or {}).get("nest") or nests_lib.default_nest_id()
    try:
        if not nest_id:
            raise NoNestSelectedError()
        provider = _provider(nest_id)
    except (NoNestSelectedError, UnknownNestError, UnsupportedProviderError) as exc:
        for vm in vms:
            hatch_lib.add_event(
                session_id, vm.name, "hatchery", "ERROR", f"VM creation failed: {exc}"
            )
            hatch_lib.set_vm_status(session_id, vm.name, "failed", error=str(exc))
        return
    for vm in vms:
        try:
            hatch_lib.set_vm_status(session_id, vm.name, "hatching")
            cmd_desc = provider.create_command_description(vm, storage_path=storage_path)
            hatch_lib.add_event(session_id, vm.name, "hatchery", "INFO", f"Creating VM: {cmd_desc}")
            # Start boot key sender before create_vm so it can begin polling immediately.
            # virt-install takes a few seconds; starting concurrently maximises the chance
            # of hitting the BIOS "press any key" window which opens during that time.
            threading.Thread(
                target=_send_boot_key,
                args=(provider, vm.name),
                daemon=True,
            ).start()
            provider.create_vm(vm, admin_password=passwords[vm.name], storage_path=storage_path)
            hatch_lib.add_event(session_id, vm.name, "hatchery", "INFO", "VM created successfully")
            try:
                provider.tag_vm_session(vm.name, session_id, clutch_file)
            except Exception:
                pass  # best-effort: metadata tagging does not block hatching
            try:
                uuid = provider.get_vm_uuid(vm.name)
                if uuid:
                    hatch_lib.set_vm_uuid(session_id, vm.name, uuid)
            except Exception:
                pass  # best-effort: UUID storage does not block hatching
        except PermissionError as exc:
            hatch_lib.add_event(
                session_id,
                vm.name,
                "hatchery",
                "ERROR",
                f"VM creation failed: {str(exc).splitlines()[0]}",
            )
            alerts_lib.record_alert(str(exc).splitlines()[0])
            hatch_lib.set_vm_status(session_id, vm.name, "failed", error=str(exc))
        except Exception as exc:
            hatch_lib.add_event(
                session_id, vm.name, "hatchery", "ERROR", f"VM creation failed: {exc}"
            )
            hatch_lib.set_vm_status(session_id, vm.name, "failed", error=str(exc))


# ── Hatch Clutch ─────────────────────────────────────────────────────────────


def _render_hatch_clutch_form(
    clutch_files,
    preselected="",
    clutch_obj=None,
    form_error=None,
    nests=None,
    selected_nest_id=None,
):
    registered = nests if nests is not None else nests_lib.list_nests()
    nest_id = selected_nest_id or nests_lib.default_nest_id() or ""
    return render_template(
        "hatch_clutch.html",
        active_pane="dashboard",
        clutch_files=clutch_files,
        preselected=preselected,
        clutch_obj=clutch_obj,
        form_error=form_error,
        nests=registered,
        selected_nest_id=nest_id,
    )


def _load_clutch(filename: str):
    """Load a Clutch file from the clutches data directory by bare filename."""
    from pathlib import Path

    safe = Path(filename).name
    return clutch_lib.load(config.data_dir() / "clutches" / safe)


@app.route("/hatch-clutch", methods=["GET"])
def hatch_clutch():
    clutch_files = _scan_dir("clutches", [".yaml"])
    preselected = request.args.get("clutch", "").strip()
    clutch_obj = None
    form_error = None
    if preselected:
        try:
            clutch_obj = _load_clutch(preselected)
        except Exception as exc:
            form_error = str(exc)
    return _render_hatch_clutch_form(clutch_files, preselected, clutch_obj, form_error)


@app.route("/hatch-clutch", methods=["POST"])
def hatch_clutch_post():
    clutch_files = _scan_dir("clutches", [".yaml"])
    filename = request.form.get("clutch_file", "").strip()
    nest_id = request.form.get("nest", "").strip() or nests_lib.default_nest_id() or ""
    if not filename:
        return _render_hatch_clutch_form(
            clutch_files, form_error="Select a Clutch file to hatch.", selected_nest_id=nest_id
        )
    try:
        clutch_obj = _load_clutch(filename)
    except FileNotFoundError:
        return _render_hatch_clutch_form(
            clutch_files,
            preselected=filename,
            form_error=f"Clutch file '{filename}' not found.",
            selected_nest_id=nest_id,
        )
    except Exception as exc:
        return _render_hatch_clutch_form(
            clutch_files, preselected=filename, form_error=str(exc), selected_nest_id=nest_id
        )

    passwords = {
        vm.name: request.form.get(f"credentials[{vm.name}]") or None for vm in clutch_obj.vms
    }
    missing = _missing_passwords(clutch_obj.vms, passwords)
    if missing:
        return _render_hatch_clutch_form(
            clutch_files,
            preselected=filename,
            clutch_obj=clutch_obj,
            form_error=f"Password required for: {', '.join(missing)}",
            selected_nest_id=nest_id,
        )

    if not nest_id:
        return _render_hatch_clutch_form(
            clutch_files,
            preselected=filename,
            clutch_obj=clutch_obj,
            form_error="Select a Nest (or register one under Settings → Nests).",
            selected_nest_id="",
        )

    nest_row = nests_lib.get_nest(nest_id)
    if nest_row is None:
        return _render_hatch_clutch_form(
            clutch_files,
            preselected=filename,
            clutch_obj=clutch_obj,
            form_error=f"Unknown Nest id: {nest_id}",
            selected_nest_id=nests_lib.default_nest_id() or "",
        )

    try:
        _provider(nest_id)
    except UnsupportedProviderError as exc:
        return _render_hatch_clutch_form(
            clutch_files,
            preselected=filename,
            clutch_obj=clutch_obj,
            form_error=str(exc),
            selected_nest_id=nest_id,
        )

    # Operator data_dir is Nest cache for local Nests. Fail before create_vm
    # when required media/scripts are missing (#245). Optional ensure flag runs the
    # ensure path (local = verify; remote copy lands with #215).
    run_ensure = request.form.get("ensure_cache", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    try:
        nest_result = nest_cache_lib.preflight_clutch(
            clutch_obj,
            nest=nests_lib.to_connection_config(nest_row),
            run_ensure=run_ensure,
        )
    except nest_cache_lib.NestCacheError as exc:
        return _render_hatch_clutch_form(
            clutch_files,
            preselected=filename,
            clutch_obj=clutch_obj,
            form_error=str(exc),
            selected_nest_id=nest_id,
        )
    if not nest_result.ok:
        return _render_hatch_clutch_form(
            clutch_files,
            preselected=filename,
            clutch_obj=clutch_obj,
            form_error=nest_result.error_message(),
            selected_nest_id=nest_id,
        )

    session_id = hatch_lib.create_session(filename, clutch_obj.name, nest=nest_id)
    for vm in clutch_obj.vms:
        hatch_lib.add_vm(
            session_id,
            vm.name,
            admin_username=vm.admin_username or None,
            admin_password=passwords.get(vm.name),
        )
        hatch_lib.add_vm_scripts(session_id, vm.name, vm.automations)
        hatch_lib.add_event(
            session_id,
            vm.name,
            "hatchery",
            "INFO",
            f"Hatching clutch: {clutch_obj.name}",
        )

    t = threading.Thread(
        target=_run_hatch_session,
        args=(session_id, clutch_obj.vms, passwords, filename, clutch_obj.storage_path),
        daemon=True,
    )
    t.start()

    return redirect(url_for("nests"))


# ── Clutch builder ───────────────────────────────────────────────────────────


def _parse_automations(raw: str) -> list:
    """Parse the vm_automations[] hidden field value.

    Accepts JSON (new format with optional parameters) or a legacy comma-separated
    string of script names. Always returns a list compatible with AutomationScript.coerce().
    """
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return [a.strip() for a in raw.split(",") if a.strip()]


def _vm_dicts_from_form(form) -> list[dict]:
    """Extract raw VM dicts from form fields without validation, used for error re-renders."""
    names = form.getlist("vm_name[]")
    oses = form.getlist("vm_os[]")
    vcpus_list = form.getlist("vm_vcpus[]")
    ram_list = form.getlist("vm_ram_gb[]")
    disk_list = form.getlist("vm_disk_gb[]")
    os_medias = form.getlist("vm_os_media[]")
    virtio_list = form.getlist("vm_virtio_drivers[]")
    os_config_list = form.getlist("vm_os_config[]")
    admin_username_list = form.getlist("vm_admin_username[]")
    automations_list = form.getlist("vm_automations[]")
    depends_list = form.getlist("vm_depends_on[]")
    result = []
    for i, name in enumerate(names):
        dep_raw = depends_list[i] if i < len(depends_list) else ""
        auto_raw = automations_list[i] if i < len(automations_list) else ""
        result.append(
            {
                "name": name,
                "os": oses[i] if i < len(oses) else "",
                "vcpus": vcpus_list[i] if i < len(vcpus_list) else "2",
                "ram_gb": ram_list[i] if i < len(ram_list) else "4",
                "disk_gb": disk_list[i] if i < len(disk_list) else "60",
                "os_media": os_medias[i] if i < len(os_medias) else "",
                "virtio_drivers": virtio_list[i] if i < len(virtio_list) else "",
                "os_config": os_config_list[i] if i < len(os_config_list) else "",
                "admin_username": admin_username_list[i] if i < len(admin_username_list) else "",
                "automations": _parse_automations(auto_raw),
                "depends_on": [d.strip() for d in dep_raw.split(",") if d.strip()],
            }
        )
    return result


def _vm_list_from_form(form):
    """Parse and validate a list of VMConfig objects from array-notation form fields."""

    names = form.getlist("vm_name[]")
    oses = form.getlist("vm_os[]")
    vcpus_list = form.getlist("vm_vcpus[]")
    ram_list = form.getlist("vm_ram_gb[]")
    disk_list = form.getlist("vm_disk_gb[]")
    os_medias = form.getlist("vm_os_media[]")
    virtio_list = form.getlist("vm_virtio_drivers[]")
    os_config_list = form.getlist("vm_os_config[]")
    admin_username_list = form.getlist("vm_admin_username[]")
    automations_list = form.getlist("vm_automations[]")
    depends_list = form.getlist("vm_depends_on[]")

    if not any(n.strip() for n in names):
        raise ValueError("Add at least one VM before saving.")

    vms = []
    for i, name in enumerate(names):
        depends_raw = depends_list[i] if i < len(depends_list) else ""
        depends_on = [d.strip() for d in depends_raw.split(",") if d.strip()]
        auto_raw = automations_list[i] if i < len(automations_list) else ""
        automations = _parse_automations(auto_raw)
        vms.append(
            VMConfig(
                name=name.strip(),
                os=oses[i] if i < len(oses) else "",
                vcpus=int(vcpus_list[i] or 1) if i < len(vcpus_list) else 1,
                ram_gb=int(ram_list[i] or 1) if i < len(ram_list) else 1,
                disk_gb=int(disk_list[i] or 20) if i < len(disk_list) else 20,
                os_media=(os_medias[i] or "").strip() if i < len(os_medias) else "",
                virtio_drivers=(virtio_list[i] or None) if i < len(virtio_list) else None,
                os_config=(os_config_list[i] or None) if i < len(os_config_list) else None,
                admin_username=(admin_username_list[i] or None)
                if i < len(admin_username_list)
                else None,
                automations=automations,
                depends_on=depends_on,
            )
        )
    return vms


def _missing_passwords(vms, passwords: dict) -> list[str]:
    """Return names of VMs that have admin_username set but no password supplied."""
    return [vm.name for vm in vms if vm.admin_username and not passwords.get(vm.name)]


def _build_template_ctx():
    return dict(
        active_pane="clutches",
        os_types=[e.value for e in GuestOS],
        media_files=_scan_dir("media/iso"),
        virtio_files=_scan_dir("media/virtio"),
        os_config_files=_scan_dir("automation/os_config"),
        scripts_files=_scan_dir("automation/scripts"),
    )


@app.route("/build", methods=["GET"])
def build():
    return render_template("build.html", form_error=None, **_build_template_ctx())


@app.route("/build", methods=["POST"])
def build_post():
    ctx = _build_template_ctx()
    clutch_name = request.form.get("clutch_name", "").strip()
    filename = request.form.get("clutch_filename", "").strip()
    action = request.form.get("action", "save")

    def _rerender(error):
        return render_template(
            "build.html",
            form_error=error,
            form_name=clutch_name,
            form_filename=filename,
            form_vms=_vm_dicts_from_form(request.form),
            **ctx,
        )

    if not filename:
        return _rerender("Filename is required.")
    if not clutch_name:
        clutch_name = filename

    storage_path = request.form.get("storage_path", "").strip() or None

    try:
        vms = _vm_list_from_form(request.form)
        c = clutch_lib.Clutch(name=clutch_name, storage_path=storage_path, vms=vms)
    except ValidationError as exc:
        msgs = [e["msg"].removeprefix("Value error, ") for e in exc.errors()]
        return _rerender("; ".join(msgs))
    except Exception as exc:
        return _rerender(str(exc))

    try:
        clutch_lib.export(c, filename, config.data_dir() / "clutches")
    except FileExistsError:
        return _rerender(f"'{filename}.yaml' already exists.")
    except Exception as exc:
        return _rerender(str(exc))

    saved = filename if filename.endswith(".yaml") else f"{filename}.yaml"

    if action == "save_and_hatch":
        return redirect(url_for("hatch_clutch", clutch=saved))

    return redirect(url_for("build"))


# ── Clutch editor ─────────────────────────────────────────────────────────────


@app.route("/edit", methods=["GET"])
def edit():
    from pathlib import Path as _Path

    filename = request.args.get("clutch", "").strip()
    if not filename:
        return redirect(url_for("clutches"))

    form_error = None
    form_name = ""
    form_storage_path = ""
    try:
        clutch_obj = _load_clutch(filename)
        form_name = clutch_obj.name
        form_storage_path = clutch_obj.storage_path or ""
    except FileNotFoundError:
        return redirect(url_for("clutches"))
    except Exception as exc:
        try:
            raw = clutch_lib.load_raw(config.data_dir() / "clutches" / _Path(filename).name)
            form_name = raw["name"]
            form_storage_path = raw.get("storage_path") or ""
            form_error = str(exc)
        except Exception:
            return redirect(url_for("clutches"))

    current_stem = filename[:-5] if filename.endswith(".yaml") else filename
    return render_template(
        "edit.html",
        form_error=form_error,
        form_name=form_name,
        form_storage_path=form_storage_path,
        form_filename=current_stem,
        current_filename=filename,
        **_build_template_ctx(),
    )


@app.route("/edit", methods=["POST"])
def edit_post():
    from pathlib import Path as _Path

    ctx = _build_template_ctx()
    old_filename = _Path(request.form.get("existing_filename", "").strip()).name
    new_name = request.form.get("clutch_name", "").strip()
    new_filename_raw = request.form.get("clutch_filename", "").strip()
    action = request.form.get("action", "save")

    if not old_filename:
        return redirect(url_for("clutches"))

    def _rerender(error):
        return render_template(
            "edit.html",
            form_error=error,
            form_name=new_name,
            form_filename=new_filename_raw,
            current_filename=old_filename,
            **ctx,
        )

    if not new_filename_raw:
        return _rerender("Filename is required.")

    new_filename = (
        new_filename_raw if new_filename_raw.endswith(".yaml") else f"{new_filename_raw}.yaml"
    )
    if not new_name:
        new_name = _Path(new_filename).stem

    storage_path = request.form.get("storage_path", "").strip() or None

    try:
        vms = _vm_list_from_form(request.form)
        c = clutch_lib.Clutch(name=new_name, storage_path=storage_path, vms=vms)
    except ValidationError as exc:
        msgs = [e["msg"].removeprefix("Value error, ") for e in exc.errors()]
        return _rerender("; ".join(msgs))
    except Exception as exc:
        return _rerender(str(exc))

    clutches_dir = config.data_dir() / "clutches"
    new_path = clutches_dir / new_filename
    old_path = clutches_dir / old_filename

    if new_path != old_path and new_path.exists():
        return _rerender(f"'{new_filename}' already exists.")

    try:
        clutch_lib.save(c, new_path)
        if new_path != old_path:
            old_path.unlink(missing_ok=True)
    except Exception as exc:
        return _rerender(str(exc))

    alerts_lib.resolve_alerts_by_prefix(f"{_CLUTCH_ALERT_PREFIX} '{old_filename}'")
    if new_filename != old_filename:
        alerts_lib.resolve_alerts_by_prefix(f"{_CLUTCH_ALERT_PREFIX} '{new_filename}'")

    if action == "save_and_hatch":
        return redirect(url_for("hatch_clutch", clutch=new_filename))

    return redirect(url_for("edit", clutch=new_filename))


# ── API ───────────────────────────────────────────────────────────────────────


@app.route("/api/import/clutches", methods=["POST"])
def api_import_clutches():
    return _api_import("clutches")


@app.route("/api/import/media/iso", methods=["POST"])
def api_import_media_iso():
    return _api_import("media/iso")


@app.route("/api/import/media/virtio", methods=["POST"])
def api_import_media_virtio():
    return _api_import("media/virtio")


@app.route("/api/import/automation/scripts", methods=["POST"])
def api_import_automation_scripts():
    return _api_import("automation/scripts")


def _api_import(kind: str):
    uploads = request.files.getlist("files")
    if not uploads or all(not f.filename for f in uploads):
        return jsonify({"error": "no files provided", "imported": [], "errors": []}), 400
    try:
        result = import_files_lib.import_uploads(kind, uploads)
    except ValueError as exc:
        return jsonify({"error": str(exc), "imported": [], "errors": []}), 400
    status = 200 if result["imported"] else 400
    return jsonify(result), status


@app.route("/api/media/iso")
def api_media_iso():
    return jsonify(_scan_media_inventory("iso"))


@app.route("/api/media/virtio")
def api_media_virtio():
    return jsonify(_scan_media_inventory("virtio"))


def _api_media_inspect(subdir: str, name: str):
    from datetime import datetime, timezone

    media_path = media_inspect_lib.resolve_media_path(subdir, name)
    if media_path is None or not media_path.is_file():
        return jsonify({"error": "not found"}), 404
    try:
        st = media_path.stat()
        size_bytes = st.st_size
        modified_at = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except OSError:
        return jsonify({"error": "not found"}), 404
    probe = media_inspect_lib.probe_iso(media_path)
    return jsonify(
        {
            "name": media_path.name,
            "relative_path": f"media/{subdir}/{media_path.name}",
            "absolute_path": str(media_path.resolve()),
            "size_bytes": size_bytes,
            "modified_at": modified_at,
            "probe": probe,
        }
    )


@app.route("/api/media/iso/<path:name>/inspect")
def api_media_iso_inspect(name):
    return _api_media_inspect("iso", name)


@app.route("/api/media/virtio/<path:name>/inspect")
def api_media_virtio_inspect(name):
    return _api_media_inspect("virtio", name)


def _api_unlink_inventory_file(path) -> tuple:
    """Unlink a resolved inventory file; return (jsonify_result, status)."""
    if path is None or not path.is_file():
        return jsonify({"error": "not found"}), 404
    try:
        path.unlink()
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "name": path.name}), 200


@app.route("/api/media/iso/<path:name>/delete", methods=["POST"])
def api_media_iso_delete(name):
    return _api_unlink_inventory_file(media_inspect_lib.resolve_media_path("iso", name))


@app.route("/api/media/virtio/<path:name>/delete", methods=["POST"])
def api_media_virtio_delete(name):
    return _api_unlink_inventory_file(media_inspect_lib.resolve_media_path("virtio", name))


@app.route("/api/automation/scripts/<path:name>/delete", methods=["POST"])
def api_automation_script_delete(name):
    return _api_unlink_inventory_file(_resolve_script_path(name))


@app.route("/api/automation/os-config")
def api_automation_os_config():
    return jsonify(_scan_dir("automation/os_config"))


@app.route("/api/automation/scripts")
def api_automation_scripts():
    return jsonify(_scan_script_inventory())


@app.route("/api/automation/scripts/<path:name>/content")
def api_automation_script_content(name):
    """Return read-only text content of a script under automation/scripts/."""
    script_path = _resolve_script_path(name)
    if script_path is None or not script_path.is_file():
        return jsonify({"error": "not found"}), 404
    try:
        size = script_path.stat().st_size
    except OSError:
        return jsonify({"error": "not found"}), 404
    if size > _SCRIPT_CONTENT_MAX_BYTES:
        return jsonify({"error": "file too large", "max_bytes": _SCRIPT_CONTENT_MAX_BYTES}), 413
    try:
        text = script_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return jsonify({"error": "unreadable"}), 500
    return jsonify({"name": script_path.name, "content": text})


@app.route("/api/automation/scripts/<path:name>/params")
def api_automation_script_params(name):
    """Return PowerShell param() metadata for a script file.

    Uses pwsh on the host to introspect the script. Returns [] if pwsh is not
    installed or the script has no param() block — callers degrade gracefully.
    """
    if not shutil.which("pwsh"):
        return jsonify([])
    script_path = _resolve_script_path(name)
    if script_path is None or not script_path.is_file():
        return jsonify({"error": "not found"}), 404
    ps_code = (
        "$p = (Get-Command -ErrorAction Stop '" + str(script_path) + "').Parameters.Values;"
        " $p | Select-Object Name,"
        " @{n='Type';e={$_.ParameterType.Name}},"
        " @{n='Mandatory';e={[bool]($_.Attributes | Where-Object {$_ -is [System.Management.Automation.ParameterAttribute] -and $_.Mandatory})}}, "
        " @{n='HelpMessage';e={($_.Attributes | Where-Object {$_ -is [System.Management.Automation.ParameterAttribute]}).HelpMessage}},"
        " @{n='Default';e={if($_.DefaultValue -ne $null){[string]$_.DefaultValue}else{$null}}}"
        " | Where-Object { $_.Name -notin @('Verbose','Debug','ErrorAction','WarningAction','InformationAction','ProgressAction','ErrorVariable','WarningVariable','InformationVariable','OutVariable','OutBuffer','PipelineVariable','WhatIf','Confirm') }"
        " | ConvertTo-Json -Depth 3"
    )
    try:
        result = subprocess.run(
            ["pwsh", "-NonInteractive", "-Command", ps_code],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return jsonify([])
        raw = json.loads(result.stdout)
        if isinstance(raw, dict):
            raw = [raw]
        params = [
            {
                "name": p.get("Name"),
                "type": p.get("Type", "String"),
                "mandatory": bool(p.get("Mandatory")),
                "default": p.get("Default"),
                "help": p.get("HelpMessage") or None,
            }
            for p in raw
        ]
        return jsonify(params)
    except Exception:
        return jsonify([])


@app.route("/api/clutches")
def api_clutches():
    return jsonify(_scan_clutch_inventory())


def _resolve_clutch_path(name: str):
    """Resolve a clutch basename under clutches/; None if invalid or missing."""
    from pathlib import Path

    safe = Path(name).name
    if not safe or safe != name or not safe.endswith(".yaml"):
        return None
    path = (config.data_dir() / "clutches" / safe).resolve()
    root = (config.data_dir() / "clutches").resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


@app.route("/api/clutches/<path:name>/content")
def api_clutch_content(name):
    """Return read-only YAML text of a Cached Clutch file."""
    clutch_path = _resolve_clutch_path(name)
    if clutch_path is None or not clutch_path.is_file():
        return jsonify({"error": "not found"}), 404
    try:
        size = clutch_path.stat().st_size
    except OSError:
        return jsonify({"error": "not found"}), 404
    if size > _SCRIPT_CONTENT_MAX_BYTES:
        return jsonify({"error": "file too large", "max_bytes": _SCRIPT_CONTENT_MAX_BYTES}), 413
    try:
        text = clutch_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return jsonify({"error": "unreadable"}), 500
    return jsonify({"name": clutch_path.name, "content": text})


@app.route("/api/clutch/<filename>")
def api_clutch_detail(filename):
    from pathlib import Path as _Path

    try:
        c = _load_clutch(filename)
    except FileNotFoundError:
        return jsonify({"error": "not found"}), 404
    except Exception as exc:
        try:
            raw = clutch_lib.load_raw(config.data_dir() / "clutches" / _Path(filename).name)
            return jsonify({**raw, "validation_error": str(exc)})
        except Exception:
            return jsonify({"error": str(exc)}), 400
    return jsonify(
        {
            "name": c.name,
            "description": c.description,
            "vms": [
                {
                    "name": v.name,
                    "os": v.os,
                    "vcpus": v.vcpus,
                    "ram_gb": v.ram_gb,
                    "disk_gb": v.disk_gb,
                    "os_media": v.os_media,
                    "virtio_drivers": v.virtio_drivers or "",
                    "os_config": v.os_config or "",
                    "admin_username": v.admin_username or "",
                    "automations": [
                        s.name
                        if not s.reboot_after and not s.parameters
                        else {
                            "name": s.name,
                            **({"reboot_after": True} if s.reboot_after else {}),
                            **({"parameters": s.parameters} if s.parameters else {}),
                        }
                        for s in v.automations
                    ],
                    "depends_on": v.depends_on,
                }
                for v in c.vms
            ],
        }
    )


@app.route("/clutch/<filename>/delete", methods=["POST"])
def clutch_delete(filename):
    from pathlib import Path

    safe = Path(filename).name
    path = config.data_dir() / "clutches" / safe
    path.unlink(missing_ok=True)
    alerts_lib.resolve_alerts_by_prefix(f"{_CLUTCH_ALERT_PREFIX} '{safe}'")
    return redirect(url_for("clutches"))


@app.route("/api/nests/<nest>/vms")
def api_nest_vms(nest: str):
    """Return the enriched VM inventory for a nest: provider data + metadata + DB records."""
    nest_row = nests_lib.get_nest(nest)
    if nest_row is None:
        return jsonify({"error": f"Unknown Nest id: {nest}"}), 404

    try:
        provider = _provider(nest)
    except (NoNestSelectedError, UnsupportedProviderError) as exc:
        return jsonify({"error": str(exc)}), 501

    show_pw = config.show_passwords()

    vms = provider.list_vms()
    result = []
    for vm in vms:
        name = vm["name"]
        record: dict = {
            "name": name,
            "status": vm["status"],
            "hatch_status": None,
            "ip": None,
            "clutch_file": None,
            "session_id": None,
            "started_at": None,
            "admin_username": None,
            "admin_password": None,
        }

        try:
            record["ip"] = provider.get_vm_ip(name)
        except Exception:
            pass

        try:
            tag = provider.get_vm_session_tag(name)
        except Exception:
            tag = None

        if tag:
            session = hatch_lib.get_session(tag["session_id"])
            if session is not None and session.get("nest") != nest:
                record["scripts"] = []
                result.append(record)
                continue
            record["session_id"] = tag["session_id"]
            record["clutch_file"] = tag["clutch_file"]
            db_row = hatch_lib.get_vm_record(tag["session_id"], name)
            if db_row:
                record["hatch_status"] = db_row.get("status")
                record["started_at"] = db_row.get("started_at")
                record["admin_username"] = db_row.get("admin_username")
                if show_pw:
                    record["admin_password"] = db_row.get("admin_password")
            scripts = hatch_lib.get_vm_scripts(tag["session_id"], name)
            last_events = hatch_lib.get_last_script_event_messages(tag["session_id"], name)
            for script in scripts:
                script["last_event"] = last_events.get(script["script_name"])
            record["scripts"] = scripts
        else:
            record["scripts"] = []

        result.append(record)

    return jsonify(result)


@app.route("/api/sessions")
def api_sessions():
    return jsonify(hatch_lib.list_sessions())


@app.route("/api/sessions/<session_id>/dismiss", methods=["POST"])
def api_dismiss_session(session_id):
    hatch_lib.archive_session(session_id)
    return jsonify({"ok": True})


@app.route("/api/sessions/<session_id>/vms/<vm_name>/retry", methods=["POST"])
def api_retry_vm(session_id, vm_name):
    """Retry provisioning for a failed VM — re-runs only failed/skipped scripts."""
    db_record = hatch_lib.get_vm_record(session_id, vm_name)
    if db_record is None:
        return jsonify({"error": "VM not found"}), 404
    if db_record["status"] != "failed":
        return jsonify({"error": "VM is not in a failed state"}), 409

    hatch_lib.reset_scripts_for_retry(session_id, vm_name)
    hatch_lib.set_vm_status(session_id, vm_name, "provisioning")
    hatch_lib.add_event(session_id, vm_name, "hatchery", "INFO", "Retry initiated")

    session = hatch_lib.get_session(session_id)
    nest_id = (session or {}).get("nest") or nests_lib.default_nest_id()
    try:
        if not nest_id:
            raise NoNestSelectedError()
        provider = _provider(nest_id)
    except (NoNestSelectedError, UnknownNestError, UnsupportedProviderError) as exc:
        return jsonify({"error": str(exc)}), 501

    try:
        ip = provider.get_vm_ip(vm_name)
    except Exception:
        ip = None

    if ip and _check_winrm(ip):
        _spawn_provision_thread(
            session_id,
            vm_name,
            ip,
            db_record.get("admin_username") or "",
            db_record.get("admin_password") or "",
        )
        return jsonify({"ok": True, "queued": True})

    return jsonify(
        {"ok": True, "queued": False, "message": "VM unreachable - will retry on next sync"}
    )


@app.route("/api/alerts")
def api_alerts():
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        limit = 10
    limit = max(1, min(limit, 500))
    return jsonify(
        {
            "items": alerts_lib.list_recent(limit),
            "active_alert_count": alerts_lib.count_active_alerts(),
        }
    )


@app.route("/api/plane-status")
def api_plane_status():
    """Footer Hatchery + Nests status: registry and alerts, not page URL (#277)."""
    from lib import plane_status as plane_status_lib

    return jsonify(plane_status_lib.footer_status())


@app.route("/api/dashboard-summary")
def api_dashboard_summary():
    """Dashboard Nest, VM, and Clutch rollups (#329 / #331). Dashboard-only."""
    from lib import dashboard_summary as dashboard_summary_lib

    return jsonify(dashboard_summary_lib.dashboard_summary())


@app.route("/api/sessions/<session_id>/vms/<vm_name>/events")
def api_vm_events(session_id: str, vm_name: str):
    events = hatch_lib.get_events(session_id, vm_name)
    return jsonify({"events": events})


@app.route("/api/config")
def api_config():
    tz = config.display_timezone()
    resolved = _host_timezone() if tz == "local" else "UTC"
    return jsonify({"display_timezone": tz, "resolved_timezone": resolved})


if __name__ == "__main__":  # pragma: no cover
    app.run(debug=True, host="0.0.0.0", port=5000)
