import atexit
import os
import subprocess
import threading

from flask import Flask, jsonify, redirect, render_template, request, url_for

from lib import config
from lib import db
from lib import clutch as clutch_lib
from lib import notifications as notif_lib
from lib import requirements as req_lib
from lib.clutch import VMConfig, GuestOS
from pydantic import ValidationError
from lib.providers.libvirt import LibvirtProvider

app = Flask(__name__, template_folder="templates/ui")
app.secret_key = os.environ.get("HATCHERY_SECRET_KEY", "dev-secret-change-in-production")

_REQ_WARNING_PREFIX = "Missing requirement:"


def _sync_requirements() -> None:
    """Re-evaluate host requirements and sync alerts."""
    for req in req_lib.check_all():
        msg = f"{_REQ_WARNING_PREFIX} '{req.name}' is not installed — {req.required_for}"
        if not req.present:
            if not notif_lib.has_active_alert(msg):
                notif_lib.record_alert(msg)
        else:
            notif_lib.resolve_alerts_by_prefix(msg)


def _background_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(config.bg_interval()):
        _sync_requirements()


def _start_background_thread() -> threading.Event:
    stop = threading.Event()
    t = threading.Thread(target=_background_loop, args=(stop,), daemon=True)
    t.start()
    atexit.register(stop.set)
    return stop


config.load()
config.init_data_dir()
db.init_db(config.data_dir() / "hatchery.db")
_sync_requirements()
_start_background_thread()


@app.context_processor
def inject_nest_status():
    alert_count = notif_lib.count_active_alerts()
    return {
        "nest_has_warnings": alert_count > 0,
        "nest_warning_count": alert_count,
    }


def _provider() -> LibvirtProvider:
    data = config.data_dir()
    return LibvirtProvider(
        iso_dir=data / "media" / "iso",
        virtio_dir=data / "media" / "virtio",
        automation_dir=data / "automation" / "os_config",
    )


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
    clutch_files = _scan_dir("clutches", [".yaml"])
    return render_template("index.html", active_pane="dashboard", clutch_files=clutch_files)


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


@app.route("/settings")
def settings():
    return render_template(
        "settings.html",
        active_pane="settings",
        cfg=config.get(),
        config_file=str(config.CONFIG_FILE),
        form_error=None,
        form_saved=request.args.get("saved") == "1",
    )


@app.route("/settings", methods=["POST"])
def settings_post():
    from pathlib import Path

    data_dir_raw = request.form.get("data_dir", "").strip()
    if not data_dir_raw:
        return render_template(
            "settings.html",
            active_pane="settings",
            cfg=config.get(),
            config_file=str(config.CONFIG_FILE),
            form_error="Data directory path is required.",
            form_saved=False,
        )

    new_cfg = {**config.get(), "data_dir": str(Path(data_dir_raw).expanduser())}
    config.save(new_cfg)
    config.init_data_dir()
    return redirect(url_for("settings", saved="1"))


@app.route("/notifications")
def notifications_pane():
    items = notif_lib.list_recent(500)
    return render_template("notifications.html", active_pane="notifications", items=items)


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

    for vm in clutch_obj.vms:
        try:
            _provider().create_vm(vm, admin_password=passwords[vm.name])
            notif_lib.record_activity(f"VM '{vm.name}' is hatching.")
        except PermissionError as exc:
            notif_lib.record_alert(str(exc).splitlines()[0])
            return _render_hatch_clutch_form(
                clutch_files,
                preselected=filename,
                clutch_obj=clutch_obj,
                form_error=str(exc),
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            return _render_hatch_clutch_form(
                clutch_files,
                preselected=filename,
                clutch_obj=clutch_obj,
                form_error=str(exc),
            )

    return redirect(url_for("dashboard"))


# ── Clutch builder ───────────────────────────────────────────────────────────


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
                "automations": [a.strip() for a in auto_raw.split(",") if a.strip()],
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
        automations = [a.strip() for a in auto_raw.split(",") if a.strip()]
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

    try:
        vms = _vm_list_from_form(request.form)
        c = clutch_lib.Clutch(name=clutch_name, vms=vms)
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
    notif_lib.record_activity(f"Clutch '{saved}' created.")

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
    try:
        clutch_obj = _load_clutch(filename)
        form_name = clutch_obj.name
    except FileNotFoundError:
        return redirect(url_for("clutches"))
    except Exception as exc:
        try:
            raw = clutch_lib.load_raw(config.data_dir() / "clutches" / _Path(filename).name)
            form_name = raw["name"]
            form_error = str(exc)
        except Exception:
            return redirect(url_for("clutches"))

    current_stem = filename[:-5] if filename.endswith(".yaml") else filename
    return render_template(
        "edit.html",
        form_error=form_error,
        form_name=form_name,
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

    try:
        vms = _vm_list_from_form(request.form)
        c = clutch_lib.Clutch(name=new_name, vms=vms)
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

    notif_lib.record_activity(f"Clutch '{new_filename}' saved.")

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
                    "automations": v.automations,
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
    notif_lib.record_activity(f"Clutch '{safe}' deleted.")
    return redirect(url_for("clutches"))


@app.route("/api/notifications")
def api_notifications():
    return jsonify(
        {
            "items": notif_lib.list_recent(10),
            "active_alert_count": notif_lib.count_active_alerts(),
        }
    )


if __name__ == "__main__":  # pragma: no cover
    app.run(debug=True, host="0.0.0.0", port=5000)
