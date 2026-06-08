import os
import subprocess

from flask import Flask, jsonify, redirect, render_template, request, url_for

from lib import config
from lib import db
from lib import clutch as clutch_lib
from lib import notifications as notif_lib
from lib import requirements as req_lib
from lib.clutch import VMConfig, GuestOS
from lib.providers.libvirt import LibvirtProvider

app = Flask(__name__, template_folder="templates/ui")
app.secret_key = os.environ.get("HATCHERY_SECRET_KEY", "dev-secret-change-in-production")

_REQ_WARNING_PREFIX = "Missing requirement:"


def _sync_requirements() -> None:
    """Re-evaluate host requirements and sync warning notifications."""
    notif_lib.resolve_by_message_prefix(_REQ_WARNING_PREFIX)
    for req in req_lib.missing(req_lib.check_all()):
        notif_lib.record(
            "warning",
            f"{_REQ_WARNING_PREFIX} '{req.name}' is not installed — {req.required_for}",
        )


config.load()
config.init_data_dir()
db.init_db(config.data_dir() / "hatchery.db")
_sync_requirements()


@app.context_processor
def inject_nest_status():
    warning_count = notif_lib.count_unresolved_warnings()
    return {
        "nest_has_warnings": warning_count > 0,
        "nest_warning_count": warning_count,
    }


def _provider() -> LibvirtProvider:
    data = config.data_dir()
    return LibvirtProvider(
        media_dir=data / "media",
        automation_dir=data / "automation",
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
    automation_files = _scan_dir("automation")
    return render_template(
        "automation.html", active_pane="automation", automation_files=automation_files
    )


@app.route("/settings")
def settings():
    cfg = config.get()
    return render_template("settings.html", active_pane="settings", cfg=cfg)


@app.route("/notifications")
def notifications_pane():
    items = notif_lib.list_recent(500)
    return render_template("notifications.html", active_pane="notifications", items=items)


# ── VM creation ───────────────────────────────────────────────────────────────


def _render_create_form(form_values=None, form_error=None):
    return render_template(
        "create.html",
        active_pane="dashboard",
        form_values=form_values,
        form_error=form_error,
        os_types=[e.value for e in GuestOS],
        media_files=_scan_dir("media"),
        automation_files=_scan_dir("automation"),
        clutch_files=_scan_dir("clutches", [".yaml"]),
    )


@app.route("/create", methods=["GET"])
def create():
    return _render_create_form()


@app.route("/create", methods=["POST"])
def create_post():
    action = request.form.get("action", "hatch")
    try:
        vm = _vm_config_from_form(request.form)
    except ValueError as exc:
        return _render_create_form(form_values=request.form, form_error=str(exc))

    # ── Export actions ────────────────────────────────────────────────────────
    if action in ("export_clutch", "export_and_hatch"):
        export_mode = request.form.get("export_mode", "new")
        try:
            if export_mode == "new":
                filename = request.form.get("clutch_filename", "").strip()
                if not filename:
                    raise ValueError("Clutch filename is required when creating a new file.")
                clutch_name = request.form.get("clutch_name", filename).strip() or filename
                new_clutch = clutch_lib.Clutch(name=clutch_name, vms=[vm])
                clutch_lib.export(new_clutch, filename, config.data_dir() / "clutches")
                notif_lib.record("activity", f"Clutch '{filename}.yaml' created.")
            else:
                target = request.form.get("clutch_append_target", "").strip()
                if not target:
                    raise ValueError("Select an existing Clutch file to append to.")
                clutch_lib.append_vm(vm, config.data_dir() / "clutches" / target)
                notif_lib.record("activity", f"VM '{vm.name}' appended to '{target}'.")
        except (ValueError, FileExistsError, FileNotFoundError) as exc:
            return _render_create_form(form_values=request.form, form_error=str(exc))

    # ── Hatch action ──────────────────────────────────────────────────────────
    if action in ("hatch", "export_and_hatch"):
        try:
            _provider().create_vm(vm)
            notif_lib.record("activity", f"VM '{vm.name}' is hatching.")
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            return _render_create_form(form_values=request.form, form_error=str(exc))

    if action == "export_clutch":
        return redirect(url_for("clutches"))
    return redirect(url_for("dashboard"))


def _vm_config_from_form(form) -> VMConfig:
    """Parse and validate VMConfig from a form submission."""
    automations = form.getlist("automations")
    depends_raw = form.get("depends_on", "").strip()
    depends_on = [d.strip() for d in depends_raw.split(",") if d.strip()]

    try:
        return VMConfig(
            name=form.get("name", "").strip(),
            os=form.get("os", ""),
            vcpus=int(form.get("vcpus", 0)),
            ram_gb=int(form.get("ram_gb", 0)),
            disk_gb=int(form.get("disk_gb", 0)),
            os_media=form.get("os_media", "").strip(),
            virtio_drivers=form.get("virtio_drivers") or None,
            os_config=form.get("os_config") or None,
            automations=automations,
            depends_on=depends_on,
        )
    except Exception as exc:
        raise ValueError(f"Invalid form data: {exc}") from exc


# ── API ───────────────────────────────────────────────────────────────────────


@app.route("/api/media")
def api_media():
    return jsonify(_scan_dir("media"))


@app.route("/api/automation")
def api_automation():
    return jsonify(_scan_dir("automation"))


@app.route("/api/clutches")
def api_clutches():
    return jsonify(_scan_dir("clutches", [".yaml"]))


@app.route("/api/notifications")
def api_notifications():
    return jsonify(
        {
            "items": notif_lib.list_recent(10),
            "unresolved_warning_count": notif_lib.count_unresolved_warnings(),
        }
    )


@app.route("/api/notifications/<int:notification_id>/dismiss", methods=["POST"])
def api_dismiss_notification(notification_id):
    notif_lib.dismiss(notification_id)
    return jsonify({"ok": True})


if __name__ == "__main__":  # pragma: no cover
    app.run(debug=True, host="0.0.0.0", port=5000)
