import atexit
import json
import os
import shutil
import socket
import subprocess
import threading
import time

from flask import Flask, jsonify, redirect, render_template, request, url_for

from lib import config
from lib import db
from lib import clutch as clutch_lib
from lib import hatch as hatch_lib
from lib import alerts as alerts_lib
from lib import provision as provision_lib
from lib import requirements as req_lib
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


def _background_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(config.bg_interval()):
        _sync_requirements()
        _sync_clutches()
        _sync_hatch_status()


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
    return render_template(
        "automation.html",
        active_pane="automation",
        os_config_files=_scan_dir("automation/os_config"),
        scripts_files=_scan_dir("automation/scripts"),
    )


def _host_timezone() -> str:
    """Return the host's local IANA timezone name (e.g. 'America/Chicago')."""
    from datetime import datetime

    return str(datetime.now().astimezone().tzinfo)


@app.route("/settings")
def settings():
    return render_template(
        "settings.html",
        active_pane="settings",
        cfg=config.get(),
        config_file=str(config.CONFIG_FILE),
        host_timezone=_host_timezone(),
        form_error=None,
        form_saved=request.args.get("saved") == "1",
    )


@app.route("/settings", methods=["POST"])
def settings_post():
    from pathlib import Path

    def _rerender(error):
        return render_template(
            "settings.html",
            active_pane="settings",
            cfg=config.get(),
            config_file=str(config.CONFIG_FILE),
            host_timezone=_host_timezone(),
            form_error=error,
            form_saved=False,
        )

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

    display_timezone_raw = request.form.get("display_timezone", "UTC").strip()
    if display_timezone_raw not in ("UTC", "local"):
        display_timezone_raw = "UTC"

    new_cfg = {
        **config.get(),
        "data_dir": str(Path(data_dir_raw).expanduser()),
        "bg_interval": bg_interval,
        "show_passwords": "show_passwords" in request.form,
        "display_timezone": display_timezone_raw,
    }
    config.save(new_cfg)
    config.init_data_dir()
    return redirect(url_for("settings", saved="1"))


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


_BOOT_KEY_POLL_ATTEMPTS = 30  # poll up to 30s (1s intervals) for VM to reach running state
_BOOT_KEY_BURST_ATTEMPTS = 10  # send key 10 times (0.5s intervals) = 5s burst


def _send_boot_key(provider, name: str) -> None:
    """Wait for VM to reach running state then send KEY_ENTER repeatedly to hit the boot prompt."""
    for _ in range(_BOOT_KEY_POLL_ATTEMPTS):
        try:
            if provider.get_status(name) == "running":
                break
        except Exception:
            pass
        time.sleep(1)
    for _ in range(_BOOT_KEY_BURST_ATTEMPTS):
        try:
            provider.send_key(name, "KEY_ENTER")
        except Exception:
            break
        time.sleep(0.5)


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


@app.route("/api/media/iso")
def api_media_iso():
    return jsonify(_scan_dir("media/iso"))


@app.route("/api/media/virtio")
def api_media_virtio():
    return jsonify(_scan_dir("media/virtio"))


@app.route("/api/automation/os-config")
def api_automation_os_config():
    return jsonify(_scan_dir("automation/os_config"))


@app.route("/api/automation/scripts")
def api_automation_scripts():
    return jsonify(_scan_dir("automation/scripts"))


@app.route("/api/automation/scripts/<path:name>/params")
def api_automation_script_params(name):
    """Return PowerShell param() metadata for a script file.

    Uses pwsh on the host to introspect the script. Returns [] if pwsh is not
    installed or the script has no param() block — callers degrade gracefully.
    """
    if not shutil.which("pwsh"):
        return jsonify([])
    script_path = config.data_dir() / "automation" / "scripts" / name
    if not script_path.is_file():
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
