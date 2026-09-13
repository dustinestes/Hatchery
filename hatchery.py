import atexit
import json
import os
import shutil
import socket
import subprocess
import threading
import time

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from lib import config
from lib import db
from lib import clutch as clutch_lib
from lib import hatch as hatch_lib
from lib import alerts as alerts_lib
from lib import media_inspect as media_inspect_lib
from lib import import_files as import_files_lib
from lib import provision as provision_lib
from lib import requirements as req_lib
from lib import nest_key_expiry as nest_key_expiry_lib
from lib import library as library_lib
from lib.clutch import VMConfig, GuestOS
from pydantic import ValidationError
from lib.providers.libvirt import LibvirtProvider

# Tracks (session_id, vm_name) pairs currently being provisioned so the sync
# loop does not spawn duplicate threads.
_provisioning: set[tuple[str, str]] = set()
_provisioning_lock = threading.Lock()

app = Flask(__name__, template_folder="templates/ui")
app.secret_key = os.environ.get("HATCHERY_SECRET_KEY", "dev-secret-change-in-production")

_REQ_WARNING_PREFIX = "Missing requirement:"
_CLUTCH_ALERT_PREFIX = "Invalid Clutch file:"


def _sync_requirements() -> None:
    """Re-evaluate host requirements and sync alerts."""
    for req in req_lib.check_all():
        msg = f"{_REQ_WARNING_PREFIX} '{req.name}' is not installed — {req.required_for}"
        if not req.present:
            if not alerts_lib.has_active_alert(msg):
                alerts_lib.record_alert(msg)
        else:
            alerts_lib.resolve_alerts_by_prefix(msg)


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
    """Validate all Clutch files and sync alerts for any that fail."""
    clutches_dir = config.data_dir() / "clutches"
    if not clutches_dir.exists():
        return
    for path in sorted(clutches_dir.glob("*.yaml")):
        prefix = f"{_CLUTCH_ALERT_PREFIX} '{path.name}'"
        try:
            clutch_lib.load(path)
            alerts_lib.resolve_alerts_by_prefix(prefix)
        except Exception as exc:
            msg = f"{prefix} — {_clutch_error_detail(path.name, str(exc))}"
            if not alerts_lib.has_active_alert(msg):
                alerts_lib.record_alert(msg)


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
                    f"Script failed: WinRM connection error — {exc}",
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
                    f"Script failed: {sname} — Exit Code: {exit_code}",
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
                f"Script complete: {sname} — Exit Code: {exit_code}",
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
            "All scripts succeeded — VM is fledged",
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
    sessions = hatch_lib.list_sessions()
    monitored = [
        (s["id"], v["vm_name"], v.get("libvirt_uuid"), v["status"])
        for s in sessions
        for v in s["vms"]
        if v["status"] in ("hatching", "provisioning", "fledged")
    ]
    if not monitored:
        return

    provider = _provider()

    for session_id, vm_name, libvirt_uuid, vm_status in monitored:
        if not libvirt_uuid:
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
                    f"Windows setup complete — starting provisioning "
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
                    "Windows setup complete — no automation scripts configured",
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
    """Evaluate Nest SSH identity expiry and sync Alerts (#219)."""
    identities = nest_key_expiry_lib.parse_identities(config.nest_ssh_identities())
    tiers = nest_key_expiry_lib.parse_tiers(config.nest_key_alert_tiers())
    nest_key_expiry_lib.sync_nest_key_expiry_alerts(identities, tiers)


def _background_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(config.bg_interval()):
        _sync_requirements()
        _sync_clutches()
        _sync_hatch_status()
        _sync_nest_key_expiry()


def _start_background_thread() -> threading.Event:
    stop = threading.Event()
    t = threading.Thread(target=_background_loop, args=(stop,), daemon=True)
    t.start()
    atexit.register(stop.set)
    return stop


def _provider() -> LibvirtProvider:
    data = config.data_dir()
    return LibvirtProvider(
        iso_dir=data / "media" / "iso",
        virtio_dir=data / "media" / "virtio",
        automation_dir=data / "automation" / "os_config",
    )


config.load()
config.init_data_dir()
db.init_db(config.data_dir() / "hatchery.db")
config.bind_db()
_sync_requirements()
_sync_clutches()
_sync_hatch_status()
_start_background_thread()


@app.context_processor
def inject_nest_status():
    alert_count = alerts_lib.count_active_alerts()
    return {
        "nest_has_warnings": alert_count > 0,
        "nest_warning_count": alert_count,
        "library_enabled": config.library_enabled(),
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
    return render_template("nests.html", active_pane="nests")


@app.route("/clutches")
def clutches():
    clutch_files = _scan_dir("clutches", [".yaml"])
    return render_template("clutches.html", active_pane="clutches", clutch_files=clutch_files)


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
        items=media_inspect_lib.scan_media_dir("iso"),
        used_by=media_inspect_lib.media_used_by("os_media"),
        empty_subdir="media/iso/",
        item_kind="ISO",
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
        items=media_inspect_lib.scan_media_dir("virtio"),
        used_by=media_inspect_lib.media_used_by("virtio_drivers"),
        empty_subdir="media/virtio/",
        item_kind="VirtIO file",
    )


def _host_timezone() -> str:
    """Return the host's local IANA timezone name (e.g. 'America/Chicago')."""
    from datetime import datetime

    return str(datetime.now().astimezone().tzinfo)


_SETTINGS_SECTIONS = {
    "general": (
        "General",
        "Application paths, background validation, and feature toggles.",
    ),
    "security": (
        "Security",
        "Password visibility and Nest SSH identity expiry alerts.",
    ),
    "display": (
        "Display",
        "How timestamps and related values are shown in the UI.",
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
):
    import json

    if section not in _SETTINGS_SECTIONS:
        abort(404)
    title, subtitle = _SETTINGS_SECTIONS[section]
    cfg = {**config.get(), **(cfg_overlay or {})}
    identities_json = nest_ssh_identities_json
    if identities_json is None:
        identities_json = json.dumps(cfg.get("nest_ssh_identities") or [], indent=2)
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
    import json
    from pathlib import Path

    if section not in _SETTINGS_SECTIONS:
        abort(404)
    if section == "library" and not config.library_enabled():
        return redirect(url_for("settings_section", section="general", library_required="1"))

    def _rerender(error, cfg_overlay=None, identities_json=None):
        return _settings_template(
            section,
            form_error=error,
            cfg_overlay=cfg_overlay,
            nest_ssh_identities_json=identities_json,
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
                "Background validation interval must be a whole number of seconds (minimum 10)."
            )

        new_cfg["data_dir"] = str(Path(data_dir_raw).expanduser())
        new_cfg["bg_interval"] = bg_interval
        new_cfg["library_enabled"] = "library_enabled" in request.form
        config.save(new_cfg)
        config.init_data_dir()
        db.init_db(Path(new_cfg["data_dir"]) / "hatchery.db")
        config.bind_db()
        return redirect(url_for("settings_section", section="general", saved="1"))

    if section == "security":
        days_list = request.form.getlist("nest_tier_days_before")
        alerts_list = request.form.getlist("nest_tier_alerts_per_day")
        if len(days_list) != len(alerts_list):
            return _rerender("Nest key alert tiers are incomplete — each row needs both fields.")
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

        identities_raw = request.form.get("nest_ssh_identities", "").strip() or "[]"
        try:
            identities_parsed = json.loads(identities_raw)
            if not isinstance(identities_parsed, list):
                raise ValueError("identities must be a JSON array")
            nest_key_expiry_lib.parse_identities(identities_parsed)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            return _rerender(
                f"Nest SSH identities JSON is invalid: {exc}",
                identities_json=identities_raw,
            )

        new_cfg["show_passwords"] = "show_passwords" in request.form
        new_cfg["nest_key_alert_tiers"] = tiers_parsed
        new_cfg["nest_ssh_identities"] = identities_parsed
        config.save(new_cfg)
        _sync_nest_key_expiry()
        return redirect(url_for("settings_section", section="security", saved="1"))

    if section == "library":
        conn_ids = request.form.getlist("library_conn_id")
        conn_labels = request.form.getlist("library_conn_label")
        conn_types = request.form.getlist("library_conn_type")
        conn_uris = request.form.getlist("library_conn_base_uri")
        conn_tokens = request.form.getlist("library_conn_token")
        conn_expires = request.form.getlist("library_conn_expires_at")
        conn_kinds = request.form.getlist("library_conn_kinds")
        n = len(conn_labels)
        if not (
            len(conn_ids) == n
            and len(conn_types) == n
            and len(conn_uris) == n
            and len(conn_tokens) == n
            and len(conn_expires) == n
            and len(conn_kinds) == n
        ):
            return _rerender("Library connections are incomplete — each row needs all fields.")
        raw_conns = []
        for i in range(n):
            raw_conns.append(
                {
                    "id": (conn_ids[i] or "").strip(),
                    "label": (conn_labels[i] or "").strip(),
                    "type": (conn_types[i] or "path").strip(),
                    "base_uri": (conn_uris[i] or "").strip(),
                    "token": conn_tokens[i] or "",
                    "expires_at": (conn_expires[i] or "").strip(),
                    "kinds": [
                        k.strip() for k in (conn_kinds[i] or "").split(",") if k.strip()
                    ],
                }
            )
        try:
            connections = library_lib.parse_connections(raw_conns)
        except ValueError as exc:
            return _rerender(
                f"Library connections are invalid: {exc}",
                {"library_connections": raw_conns, "library_script_bindings": []},
            )

        bind_ids = request.form.getlist("library_script_bind_id")
        bind_conn_ids = request.form.getlist("library_script_bind_connection_id")
        bind_filters = request.form.getlist("library_script_bind_filter")
        bn = len(bind_conn_ids)
        if not (len(bind_ids) == bn and len(bind_filters) == bn):
            return _rerender("Script bindings are incomplete — each row needs a connection and filter.")
        raw_binds = []
        for i in range(bn):
            raw_binds.append(
                {
                    "id": (bind_ids[i] or "").strip(),
                    "connection_id": (bind_conn_ids[i] or "").strip(),
                    "filter": (bind_filters[i] or "*").strip() or "*",
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
                },
            )

        new_cfg["library_connections"] = connections
        new_cfg["library_script_bindings"] = bindings
        config.save(new_cfg)
        return redirect(url_for("settings_section", section="library", saved="1"))

    # display
    display_timezone_raw = request.form.get("display_timezone", "UTC").strip()
    if display_timezone_raw not in ("UTC", "local"):
        display_timezone_raw = "UTC"
    new_cfg["display_timezone"] = display_timezone_raw
    config.save(new_cfg)
    return redirect(url_for("settings_section", section="display", saved="1"))


def _library_require_enabled():
    if not config.library_enabled():
        return jsonify({"error": "Library is disabled — enable it under Settings → General."}), 403
    return None


def _connection_from_request_body(data: dict, *, require_expiry: bool = True) -> dict:
    """Normalize a connection object from JSON (Settings test or pull)."""
    raw = data.get("connection")
    if isinstance(raw, dict):
        parsed = library_lib.parse_connections([raw], require_expiry=require_expiry)
        return parsed[0]
    conn_id = str(data.get("connection_id") or "").strip()
    if not conn_id:
        raise ValueError("connection or connection_id is required")
    for conn in config.library_connections():
        if conn.get("id") == conn_id:
            return library_lib.parse_connections(
                [conn], require_expiry=require_expiry
            )[0]
    raise ValueError(f"Unknown connection id: {conn_id}")


@app.route("/api/library/test-connection", methods=["POST"])
def api_library_test_connection():
    denied = _library_require_enabled()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        conn = _connection_from_request_body(data, require_expiry=False)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    result = library_lib.test_connection(conn)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route("/api/library/test-filter", methods=["POST"])
def api_library_test_filter():
    denied = _library_require_enabled()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        conn = _connection_from_request_body(data, require_expiry=False)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc), "hits": []}), 400
    filt = str(data.get("filter") or "*")
    result = library_lib.test_filter(conn, filt)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route("/api/library/scripts")
def api_library_scripts():
    denied = _library_require_enabled()
    if denied:
        return denied
    try:
        connections = library_lib.parse_connections(config.library_connections())
        bindings = library_lib.parse_script_bindings(
            config.library_script_bindings(), connections
        )
    except ValueError as exc:
        return jsonify({"error": str(exc), "items": []}), 400
    items = library_lib.catalog_scripts(connections, bindings)
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
        result = library_lib.pull_script(conn, relative_path)
    except FileExistsError as exc:
        return jsonify({"error": str(exc)}), 409
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({"imported": [result["name"]], "sha256": result["sha256"], "errors": []})


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
    provider = _provider()
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


def _render_hatch_clutch_form(clutch_files, preselected="", clutch_obj=None, form_error=None):
    return render_template(
        "hatch_clutch.html",
        active_pane="dashboard",
        clutch_files=clutch_files,
        preselected=preselected,
        clutch_obj=clutch_obj,
        form_error=form_error,
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
    if not filename:
        return _render_hatch_clutch_form(clutch_files, form_error="Select a Clutch file to hatch.")
    try:
        clutch_obj = _load_clutch(filename)
    except FileNotFoundError:
        return _render_hatch_clutch_form(
            clutch_files,
            preselected=filename,
            form_error=f"Clutch file '{filename}' not found.",
        )
    except Exception as exc:
        return _render_hatch_clutch_form(clutch_files, preselected=filename, form_error=str(exc))

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
        )

    session_id = hatch_lib.create_session(filename, clutch_obj.name)
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
    return jsonify(_scan_dir("media/iso"))


@app.route("/api/media/virtio")
def api_media_virtio():
    return jsonify(_scan_dir("media/virtio"))


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
    return jsonify(_scan_dir("automation/scripts"))


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
    return jsonify(_scan_dir("clutches", [".yaml"]))


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
    provider = _provider()
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

    provider = _provider()
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
        {"ok": True, "queued": False, "message": "VM unreachable — will retry on next sync"}
    )


@app.route("/api/alerts")
def api_alerts():
    return jsonify(
        {
            "items": alerts_lib.list_recent(10),
            "active_alert_count": alerts_lib.count_active_alerts(),
        }
    )


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
