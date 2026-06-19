import threading
import pytest
from unittest.mock import MagicMock, patch

import hatchery as app_module
import lib.clutch as clutch_lib
import lib.config as cfg
import lib.db as db_module
import lib.notifications as notif_lib
from hatchery import app as flask_app
from lib.clutch import VMConfig, Clutch
from lib.providers.libvirt import LibvirtProvider
from lib.requirements import Requirement


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def isolate_db(tmp_path):
    db_module.init_db(tmp_path / "hatchery.db")
    yield
    db_module._db_path = None


VALID_BUILD_FORM = {
    "clutch_filename": "test-lab",
    "vm_name[]": "dc01",
    "vm_os[]": "win11",
    "vm_vcpus[]": "2",
    "vm_ram_gb[]": "4",
    "vm_disk_gb[]": "60",
    "vm_os_media[]": "win11.iso",
    "vm_depends_on[]": "",
}


class TestRoutes:
    def test_dashboard_returns_200(self, client):
        assert client.get("/").status_code == 200

    def test_nests_returns_200(self, client):
        assert client.get("/nests").status_code == 200

    def test_clutches_returns_200(self, client):
        assert client.get("/clutches").status_code == 200

    def test_automation_returns_200(self, client):
        assert client.get("/automation").status_code == 200

    def test_settings_returns_200(self, client):
        assert client.get("/settings").status_code == 200

    def test_notifications_returns_200(self, client):
        assert client.get("/notifications").status_code == 200


class TestActivePane:
    def test_dashboard_marks_active(self, client):
        html = client.get("/").data.decode()
        assert 'class="sidebar-item active"' in html or "sidebar-item active" in html

    def test_nests_marks_active(self, client):
        html = client.get("/nests").data.decode()
        assert "active" in html

    def test_settings_marks_active(self, client):
        html = client.get("/settings").data.decode()
        assert "active" in html


class TestPageTitles:
    def test_dashboard_title(self, client):
        html = client.get("/").data.decode()
        assert "Dashboard" in html

    def test_nests_title(self, client):
        html = client.get("/nests").data.decode()
        assert "Nests" in html

    def test_clutches_title(self, client):
        html = client.get("/clutches").data.decode()
        assert "Clutches" in html

    def test_automation_title(self, client):
        html = client.get("/automation").data.decode()
        assert "Automation" in html

    def test_settings_title(self, client):
        html = client.get("/settings").data.decode()
        assert "Settings" in html

    def test_notifications_title(self, client):
        html = client.get("/notifications").data.decode()
        assert "Notifications" in html


class TestSettingsRoute:
    def test_get_shows_current_data_dir(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": str(tmp_path), "bg_interval": 60})
        html = client.get("/settings").data.decode()
        assert str(tmp_path) in html

    def test_get_shows_config_file_path(self, client):
        html = client.get("/settings").data.decode()
        assert str(cfg.CONFIG_FILE) in html

    def test_post_valid_saves_and_redirects(self, client, tmp_path, monkeypatch):
        saved = {}
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": "/old/path", "bg_interval": 60})
        monkeypatch.setattr(cfg, "save", lambda c: saved.update(c))
        monkeypatch.setattr(cfg, "init_data_dir", lambda: None)
        resp = client.post("/settings", data={"data_dir": str(tmp_path), "bg_interval": "60"})
        assert resp.status_code == 302
        assert "saved=1" in resp.headers["Location"]
        assert saved["data_dir"] == str(tmp_path)

    def test_post_empty_path_shows_error(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": "/old/path", "bg_interval": 60})
        resp = client.post("/settings", data={"data_dir": "", "bg_interval": "60"})
        assert resp.status_code == 200
        assert "required" in resp.data.decode().lower()

    def test_post_expands_tilde(self, client, monkeypatch):
        saved = {}
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": "/old", "bg_interval": 60})
        monkeypatch.setattr(cfg, "save", lambda c: saved.update(c))
        monkeypatch.setattr(cfg, "init_data_dir", lambda: None)
        client.post("/settings", data={"data_dir": "~/hatchery/data", "bg_interval": "60"})
        assert not saved["data_dir"].startswith("~")

    def test_get_saved_param_shows_success_banner(self, client):
        html = client.get("/settings?saved=1").data.decode()
        assert "saved" in html.lower()

    def test_post_calls_init_data_dir(self, client, tmp_path, monkeypatch):
        called = []
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": "/old", "bg_interval": 60})
        monkeypatch.setattr(cfg, "save", lambda c: None)
        monkeypatch.setattr(cfg, "init_data_dir", lambda: called.append(True))
        client.post("/settings", data={"data_dir": str(tmp_path), "bg_interval": "60"})
        assert called

    def test_get_shows_current_bg_interval(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": "/some/path", "bg_interval": 120})
        html = client.get("/settings").data.decode()
        assert "120" in html

    def test_post_saves_bg_interval(self, client, tmp_path, monkeypatch):
        saved = {}
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": str(tmp_path), "bg_interval": 60})
        monkeypatch.setattr(cfg, "save", lambda c: saved.update(c))
        monkeypatch.setattr(cfg, "init_data_dir", lambda: None)
        client.post("/settings", data={"data_dir": str(tmp_path), "bg_interval": "120"})
        assert saved["bg_interval"] == 120

    def test_post_bg_interval_below_minimum_shows_error(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": "/old", "bg_interval": 60})
        resp = client.post("/settings", data={"data_dir": "/some/path", "bg_interval": "5"})
        assert resp.status_code == 200
        assert "10" in resp.data.decode()

    def test_post_bg_interval_non_numeric_shows_error(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": "/old", "bg_interval": 60})
        resp = client.post("/settings", data={"data_dir": "/some/path", "bg_interval": "abc"})
        assert resp.status_code == 200
        assert "interval" in resp.data.decode().lower()


class TestBuildRoute:
    def test_build_get_returns_200(self, client):
        assert client.get("/build").status_code == 200

    def test_build_get_contains_build_form(self, client):
        html = client.get("/build").data.decode()
        assert "build-form" in html

    def test_build_post_no_filename_rerenders_form(self, client):
        resp = client.post("/build", data={"clutch_filename": ""})
        assert resp.status_code == 200
        assert "alert" in resp.data.decode()

    def test_build_post_no_vms_rerenders_form(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        resp = client.post("/build", data={"clutch_filename": "new-lab"})
        assert resp.status_code == 200
        assert "alert" in resp.data.decode()

    def test_build_post_saves_and_redirects(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        form = {
            "clutch_name": "Test Lab",
            "clutch_filename": "test-lab",
            "vm_name[]": "dc01",
            "vm_os[]": "win11",
            "vm_vcpus[]": "2",
            "vm_ram_gb[]": "4",
            "vm_disk_gb[]": "60",
            "vm_os_media[]": "win11.iso",
            "vm_depends_on[]": "",
        }
        resp = client.post("/build", data=form, follow_redirects=False)
        assert resp.status_code == 302
        assert (tmp_path / "clutches" / "test-lab.yaml").exists()

    def test_build_post_duplicate_filename_rerenders_form(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path, name="my-lab")
        form = {
            "clutch_filename": "my-lab",
            "vm_name[]": "dc01",
            "vm_os[]": "win11",
            "vm_vcpus[]": "2",
            "vm_ram_gb[]": "4",
            "vm_disk_gb[]": "60",
            "vm_os_media[]": "win11.iso",
            "vm_depends_on[]": "",
        }
        resp = client.post("/build", data=form)
        assert resp.status_code == 200
        assert "alert" in resp.data.decode()

    def test_build_post_unexpected_export_error_rerenders_form(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        form = {
            "clutch_filename": "test-lab",
            "vm_name[]": "dc01",
            "vm_os[]": "win11",
            "vm_vcpus[]": "2",
            "vm_ram_gb[]": "4",
            "vm_disk_gb[]": "60",
            "vm_os_media[]": "win11.iso",
            "vm_depends_on[]": "",
        }
        with patch("hatchery.clutch_lib.export", side_effect=RuntimeError("disk full")):
            resp = client.post("/build", data=form)
        assert resp.status_code == 200
        assert "alert" in resp.data.decode()

    def test_build_post_circular_dep_shows_clean_error(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        form = {
            "clutch_name": "Cycle Lab",
            "clutch_filename": "cycle-lab",
            "vm_name[]": ["dc01", "client01"],
            "vm_os[]": ["win11", "win11"],
            "vm_vcpus[]": ["2", "2"],
            "vm_ram_gb[]": ["4", "4"],
            "vm_disk_gb[]": ["60", "60"],
            "vm_os_media[]": ["win11.iso", "win11.iso"],
            "vm_depends_on[]": ["client01", "dc01"],
        }
        resp = client.post("/build", data=form)
        body = resp.data.decode()
        assert resp.status_code == 200
        assert "Circular dependency detected" in body
        assert "Value error," not in body
        assert "pydantic" not in body.lower()
        assert not (tmp_path / "clutches" / "cycle-lab.yaml").exists()

    def test_build_post_validation_error_preserves_form_state(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        form = {
            "clutch_name": "My Lab",
            "clutch_filename": "my-lab",
            "vm_name[]": ["dc01", "client01"],
            "vm_os[]": ["win11", "win11"],
            "vm_vcpus[]": ["2", "2"],
            "vm_ram_gb[]": ["4", "4"],
            "vm_disk_gb[]": ["60", "60"],
            "vm_os_media[]": ["win11.iso", "win11.iso"],
            "vm_depends_on[]": ["client01", "dc01"],
        }
        resp = client.post("/build", data=form)
        body = resp.data.decode()
        assert resp.status_code == 200
        assert 'value="My Lab"' in body
        assert 'value="my-lab"' in body
        assert "dc01" in body
        assert "client01" in body

    def test_build_post_saves_automations_in_clutch(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        form = {**VALID_BUILD_FORM, "vm_automations[]": "setup.ps1,configure.ps1"}
        client.post("/build", data=form)
        c = clutch_lib.load(tmp_path / "clutches" / "test-lab.yaml")
        assert c.vms[0].automations == ["setup.ps1", "configure.ps1"]

    def test_build_post_admin_username_saved_to_clutch(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        form = {
            **VALID_BUILD_FORM,
            "vm_admin_username[]": "alice",
        }
        resp = client.post("/build", data=form, follow_redirects=False)
        assert resp.status_code == 302
        saved = clutch_lib.load(tmp_path / "clutches" / "test-lab.yaml")
        assert saved.vms[0].admin_username == "alice"

    def test_build_post_save_and_hatch_saves_clutch_and_redirects_to_hatch_clutch(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        form = {**VALID_BUILD_FORM, "action": "save_and_hatch"}
        resp = client.post("/build", data=form, follow_redirects=False)
        assert resp.status_code == 302
        assert "hatch-clutch" in resp.headers["Location"]
        assert "test-lab.yaml" in resp.headers["Location"]
        assert (tmp_path / "clutches" / "test-lab.yaml").exists()


class TestEditRoute:
    def test_get_no_clutch_redirects_to_clutches(self, client):
        resp = client.get("/edit", follow_redirects=False)
        assert resp.status_code == 302
        assert "/clutches" in resp.headers["Location"]

    def test_get_missing_file_redirects_to_clutches(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        resp = client.get("/edit?clutch=ghost.yaml", follow_redirects=False)
        assert resp.status_code == 302

    def test_get_valid_clutch_returns_200(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        assert client.get("/edit?clutch=my-lab.yaml").status_code == 200

    def test_get_shows_edit_form(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        html = client.get("/edit?clutch=my-lab.yaml").data.decode()
        assert "edit-form" in html

    def test_post_saves_in_place(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        form = {
            "existing_filename": "my-lab.yaml",
            "clutch_name": "Updated Lab",
            "clutch_filename": "my-lab",
            "vm_name[]": "dc01",
            "vm_os[]": "win11",
            "vm_vcpus[]": "2",
            "vm_ram_gb[]": "4",
            "vm_disk_gb[]": "60",
            "vm_os_media[]": "win11.iso",
            "vm_depends_on[]": "",
        }
        resp = client.post("/edit", data=form, follow_redirects=False)
        assert resp.status_code == 302
        assert "my-lab.yaml" in resp.headers["Location"]

    def test_post_rename_creates_new_file(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        form = {
            "existing_filename": "my-lab.yaml",
            "clutch_name": "Renamed Lab",
            "clutch_filename": "renamed-lab",
            "vm_name[]": "dc01",
            "vm_os[]": "win11",
            "vm_vcpus[]": "2",
            "vm_ram_gb[]": "4",
            "vm_disk_gb[]": "60",
            "vm_os_media[]": "win11.iso",
            "vm_depends_on[]": "",
        }
        resp = client.post("/edit", data=form, follow_redirects=False)
        assert resp.status_code == 302
        assert (tmp_path / "clutches" / "renamed-lab.yaml").exists()
        assert not (tmp_path / "clutches" / "my-lab.yaml").exists()

    def test_post_rename_conflict_rerenders_form(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path, name="my-lab")
        _make_clutch(tmp_path, name="other-lab", vm_name="ws01")
        form = {
            "existing_filename": "my-lab.yaml",
            "clutch_name": "Other",
            "clutch_filename": "other-lab",
            "vm_name[]": "dc01",
            "vm_os[]": "win11",
            "vm_vcpus[]": "2",
            "vm_ram_gb[]": "4",
            "vm_disk_gb[]": "60",
            "vm_os_media[]": "win11.iso",
            "vm_depends_on[]": "",
        }
        resp = client.post("/edit", data=form)
        assert resp.status_code == 200
        assert "alert" in resp.data.decode()

    def test_post_rename_conflict_preserves_form_values(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path, name="my-lab")
        _make_clutch(tmp_path, name="other-lab", vm_name="ws01")
        form = {
            "existing_filename": "my-lab.yaml",
            "clutch_name": "Attempted Name",
            "clutch_filename": "other-lab",
            "vm_name[]": "dc01",
            "vm_os[]": "win11",
            "vm_vcpus[]": "2",
            "vm_ram_gb[]": "4",
            "vm_disk_gb[]": "60",
            "vm_os_media[]": "win11.iso",
            "vm_depends_on[]": "",
        }
        html = client.post("/edit", data=form).data.decode()
        assert "Attempted Name" in html
        assert 'value="other-lab"' in html

    def test_post_empty_clutch_name_defaults_to_filename_stem(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        form = {
            "existing_filename": "my-lab.yaml",
            "clutch_name": "",
            "clutch_filename": "my-lab",
            "vm_name[]": "dc01",
            "vm_os[]": "win11",
            "vm_vcpus[]": "2",
            "vm_ram_gb[]": "4",
            "vm_disk_gb[]": "60",
            "vm_os_media[]": "win11.iso",
            "vm_depends_on[]": "",
        }
        resp = client.post("/edit", data=form, follow_redirects=False)
        assert resp.status_code == 302

    def test_post_no_vms_rerenders_form(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        resp = client.post(
            "/edit",
            data={"existing_filename": "my-lab.yaml", "clutch_filename": "my-lab"},
        )
        assert resp.status_code == 200
        assert "alert" in resp.data.decode()

    def test_post_circular_dep_shows_clean_error(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        form = {
            "existing_filename": "my-lab.yaml",
            "clutch_name": "My Lab",
            "clutch_filename": "my-lab",
            "vm_name[]": ["dc01", "client01"],
            "vm_os[]": ["win11", "win11"],
            "vm_vcpus[]": ["2", "2"],
            "vm_ram_gb[]": ["4", "4"],
            "vm_disk_gb[]": ["60", "60"],
            "vm_os_media[]": ["win11.iso", "win11.iso"],
            "vm_depends_on[]": ["client01", "dc01"],
        }
        resp = client.post("/edit", data=form)
        body = resp.data.decode()
        assert resp.status_code == 200
        assert "Circular dependency detected" in body
        assert "Value error," not in body
        assert "pydantic" not in body.lower()

    def test_post_unexpected_save_error_rerenders_form(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        form = {
            "existing_filename": "my-lab.yaml",
            "clutch_name": "My Lab",
            "clutch_filename": "my-lab",
            "vm_name[]": "dc01",
            "vm_os[]": "win11",
            "vm_vcpus[]": "2",
            "vm_ram_gb[]": "4",
            "vm_disk_gb[]": "60",
            "vm_os_media[]": "win11.iso",
            "vm_depends_on[]": "",
        }
        with patch("hatchery.clutch_lib.save", side_effect=RuntimeError("I/O error")):
            resp = client.post("/edit", data=form)
        assert resp.status_code == 200
        assert "alert" in resp.data.decode()

    def test_post_no_existing_filename_redirects(self, client):
        resp = client.post("/edit", data={"existing_filename": ""}, follow_redirects=False)
        assert resp.status_code == 302

    def test_post_no_filename_rerenders_form(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        resp = client.post(
            "/edit", data={"existing_filename": "my-lab.yaml", "clutch_filename": ""}
        )
        assert resp.status_code == 200
        assert "alert" in resp.data.decode()

    def test_post_save_and_hatch_redirects_to_hatch_clutch(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        form = {
            "action": "save_and_hatch",
            "existing_filename": "my-lab.yaml",
            "clutch_name": "My Lab",
            "clutch_filename": "my-lab",
            "vm_name[]": "dc01",
            "vm_os[]": "win11",
            "vm_vcpus[]": "2",
            "vm_ram_gb[]": "4",
            "vm_disk_gb[]": "60",
            "vm_os_media[]": "win11.iso",
            "vm_depends_on[]": "",
        }
        resp = client.post("/edit", data=form, follow_redirects=False)
        assert resp.status_code == 302
        assert "hatch-clutch" in resp.headers["Location"]
        assert "my-lab.yaml" in resp.headers["Location"]

    def test_get_circular_dependency_renders_form_with_error(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        clutches_dir = tmp_path / "clutches"
        clutches_dir.mkdir()
        (clutches_dir / "cycle.yaml").write_text(
            "name: cycle-lab\nvms:\n"
            "  - {name: vm-a, os: win11, vcpus: 2, ram_gb: 4, disk_gb: 40,"
            " os_media: win11.iso, depends_on: [vm-b]}\n"
            "  - {name: vm-b, os: win11, vcpus: 2, ram_gb: 4, disk_gb: 40,"
            " os_media: win11.iso, depends_on: [vm-a]}\n"
        )
        resp = client.get("/edit?clutch=cycle.yaml")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "edit-form" in html
        assert "Circular dependency" in html

    def test_post_save_resolves_active_alert_for_file(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        notif_lib.record_alert("Invalid Clutch file: 'my-lab.yaml' — some validation error")
        assert notif_lib.count_active_alerts() == 1
        form = {
            "existing_filename": "my-lab.yaml",
            "clutch_name": "My Lab",
            "clutch_filename": "my-lab",
            "vm_name[]": "dc01",
            "vm_os[]": "win11",
            "vm_vcpus[]": "2",
            "vm_ram_gb[]": "4",
            "vm_disk_gb[]": "60",
            "vm_os_media[]": "win11.iso",
            "vm_depends_on[]": "",
        }
        client.post("/edit", data=form)
        assert notif_lib.count_active_alerts() == 0


def _make_clutch(tmp_path, name="my-lab", vm_name="dc01"):
    clutches_dir = tmp_path / "clutches"
    clutches_dir.mkdir(exist_ok=True)
    vm = VMConfig(name=vm_name, os="win11", vcpus=2, ram_gb=4, disk_gb=60, os_media="win11.iso")
    c = Clutch(name=name, vms=[vm])
    clutch_lib.export(c, name, clutches_dir)
    return clutches_dir / f"{name}.yaml"


class TestHatchClutchRoute:
    def test_get_returns_200(self, client):
        assert client.get("/hatch-clutch").status_code == 200

    def test_get_contains_form(self, client):
        html = client.get("/hatch-clutch").data.decode()
        assert "hatch-clutch-form" in html

    def test_get_preselects_clutch_from_query_param(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path, name="my-lab")
        html = client.get("/hatch-clutch?clutch=my-lab.yaml").data.decode()
        assert "dc01" in html

    def test_get_summary_shows_resource_pills(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path, name="my-lab")
        html = client.get("/hatch-clutch?clutch=my-lab.yaml").data.decode()
        assert "2 vCPU" in html
        assert "4 GB RAM" in html
        assert "60 GB disk" in html

    def test_get_invalid_clutch_shows_error(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        (tmp_path / "clutches" / "bad.yaml").write_text("not: valid: clutch: yaml: [")
        html = client.get("/hatch-clutch?clutch=bad.yaml").data.decode()
        assert "alert" in html

    def test_post_no_file_rerenders_form(self, client):
        resp = client.post("/hatch-clutch", data={"clutch_file": ""})
        assert resp.status_code == 200
        assert "alert" in resp.data.decode()

    def test_post_file_not_found_rerenders_form(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        resp = client.post("/hatch-clutch", data={"clutch_file": "missing.yaml"})
        assert resp.status_code == 200
        assert "alert" in resp.data.decode()

    def test_post_invalid_clutch_rerenders_form(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        (tmp_path / "clutches" / "bad.yaml").write_text("not: valid: clutch: yaml: [")
        resp = client.post("/hatch-clutch", data={"clutch_file": "bad.yaml"})
        assert resp.status_code == 200
        assert "alert" in resp.data.decode()

    def test_post_missing_password_rerenders_form(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        clutches_dir = tmp_path / "clutches"
        clutches_dir.mkdir()
        vm = VMConfig(
            name="dc01",
            os="win11",
            vcpus=2,
            ram_gb=4,
            disk_gb=60,
            os_media="win11.iso",
            admin_username="alice",
        )
        c = Clutch(name="my-lab", vms=[vm])
        clutch_lib.export(c, "my-lab", clutches_dir)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.create_vm = MagicMock()
            resp = client.post("/hatch-clutch", data={"clutch_file": "my-lab.yaml"})
        assert resp.status_code == 200
        assert "Password required" in resp.data.decode()
        mock_prov.return_value.create_vm.assert_not_called()

    def test_post_creates_session_and_redirects_to_nests(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path, name="my-lab", vm_name="dc01")
        with patch("hatchery._run_hatch_session"):
            resp = client.post(
                "/hatch-clutch", data={"clutch_file": "my-lab.yaml"}, follow_redirects=False
            )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/nests")

    def test_post_creates_session_with_vms_pending(self, client, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path, name="my-lab", vm_name="dc01")
        with patch("hatchery._run_hatch_session"):
            client.post(
                "/hatch-clutch", data={"clutch_file": "my-lab.yaml"}, follow_redirects=False
            )
        sessions = hatch_lib.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["clutch_file"] == "my-lab.yaml"
        assert sessions[0]["vms"][0]["vm_name"] == "dc01"
        assert sessions[0]["vms"][0]["status"] == "pending"

    def test_post_redirects_even_when_provider_would_fail(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        with patch("hatchery._run_hatch_session"):
            resp = client.post(
                "/hatch-clutch", data={"clutch_file": "my-lab.yaml"}, follow_redirects=False
            )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/nests")


class TestRunHatchSession:
    """Tests for the _run_hatch_session background orchestration function."""

    def _setup_session(self, tmp_path, vm_name="dc01"):
        import lib.hatch as hatch_lib

        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, vm_name)
        return sid

    def _get_vm(self, sid, vm_name="dc01"):
        import lib.hatch as hatch_lib

        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        return next(v for v in s["vms"] if v["vm_name"] == vm_name)

    def test_calls_create_vm_for_each_vm(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_session(tmp_path)
        vm = VMConfig(name="dc01", os="win11", vcpus=2, ram_gb=4, disk_gb=60, os_media="win11.iso")
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.create_vm = MagicMock()
            app_module._run_hatch_session(sid, [vm], {"dc01": None}, "lab.yaml")
        mock_prov.return_value.create_vm.assert_called_once()

    def test_passes_password_to_create_vm(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_session(tmp_path)
        vm = VMConfig(
            name="dc01",
            os="win11",
            vcpus=2,
            ram_gb=4,
            disk_gb=60,
            os_media="win11.iso",
            admin_username="alice",
        )
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.create_vm = MagicMock()
            app_module._run_hatch_session(sid, [vm], {"dc01": "s3cr3t"}, "lab.yaml")
        _, kwargs = mock_prov.return_value.create_vm.call_args
        assert kwargs.get("admin_password") == "s3cr3t"

    def test_marks_vm_hatching_before_create(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        import lib.hatch as hatch_lib

        sid = self._setup_session(tmp_path)
        vm = VMConfig(name="dc01", os="win11", vcpus=2, ram_gb=4, disk_gb=60, os_media="win11.iso")
        observed = []

        def fake_create_vm(vm_cfg, admin_password=None):
            sessions = hatch_lib.list_sessions()
            s = next(s for s in sessions if s["id"] == sid)
            observed.append(next(v["status"] for v in s["vms"] if v["vm_name"] == "dc01"))

        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.create_vm.side_effect = fake_create_vm
            app_module._run_hatch_session(sid, [vm], {"dc01": None}, "lab.yaml")
        assert observed == ["hatching"]

    def test_marks_vm_failed_on_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_session(tmp_path)
        vm = VMConfig(name="dc01", os="win11", vcpus=2, ram_gb=4, disk_gb=60, os_media="win11.iso")
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.create_vm.side_effect = FileNotFoundError("no egg")
            app_module._run_hatch_session(sid, [vm], {"dc01": None}, "lab.yaml")
        assert self._get_vm(sid)["status"] == "failed"
        assert "no egg" in self._get_vm(sid)["error"]

    def test_permission_error_records_alert(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_session(tmp_path)
        vm = VMConfig(name="dc01", os="win11", vcpus=2, ram_gb=4, disk_gb=60, os_media="win11.iso")
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.create_vm.side_effect = PermissionError(
                "cannot access: win11.iso"
            )
            app_module._run_hatch_session(sid, [vm], {"dc01": None}, "lab.yaml")
        alerts = [n for n in notif_lib.list_recent() if n["tier"] == "alert"]
        assert any("cannot access" in a["message"] for a in alerts)

    def test_records_activity_on_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_session(tmp_path)
        vm = VMConfig(name="dc01", os="win11", vcpus=2, ram_gb=4, disk_gb=60, os_media="win11.iso")
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.create_vm = MagicMock()
            app_module._run_hatch_session(sid, [vm], {"dc01": None}, "lab.yaml")
        activity = [n for n in notif_lib.list_recent() if n["tier"] == "activity"]
        assert any("dc01" in a["message"] for a in activity)

    def test_continues_after_one_vm_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        import lib.hatch as hatch_lib

        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm(sid, "ws01")
        vms = [
            VMConfig(name="dc01", os="win11", vcpus=2, ram_gb=4, disk_gb=60, os_media="win11.iso"),
            VMConfig(name="ws01", os="win11", vcpus=2, ram_gb=4, disk_gb=60, os_media="win11.iso"),
        ]
        call_count = 0

        def fake_create(vm_cfg, admin_password=None):
            nonlocal call_count
            call_count += 1
            if vm_cfg.name == "dc01":
                raise FileNotFoundError("dc01 failed")

        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.create_vm.side_effect = fake_create
            app_module._run_hatch_session(sid, vms, {"dc01": None, "ws01": None}, "lab.yaml")

        assert call_count == 2
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        statuses = {v["vm_name"]: v["status"] for v in s["vms"]}
        assert statuses["dc01"] == "failed"
        assert statuses["ws01"] == "hatching"

    def test_tags_vm_session_metadata_on_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_session(tmp_path)
        vm = VMConfig(name="dc01", os="win11", vcpus=2, ram_gb=4, disk_gb=60, os_media="win11.iso")
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.create_vm = MagicMock()
            mock_prov.return_value.tag_vm_session = MagicMock()
            app_module._run_hatch_session(sid, [vm], {"dc01": None}, "lab.yaml")
        mock_prov.return_value.tag_vm_session.assert_called_once_with("dc01", sid, "lab.yaml")

    def test_tag_failure_does_not_block_hatching(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_session(tmp_path)
        vm = VMConfig(name="dc01", os="win11", vcpus=2, ram_gb=4, disk_gb=60, os_media="win11.iso")
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.create_vm = MagicMock()
            mock_prov.return_value.tag_vm_session.side_effect = RuntimeError("virsh failed")
            app_module._run_hatch_session(sid, [vm], {"dc01": None}, "lab.yaml")
        assert self._get_vm(sid)["status"] == "hatching"

    def test_stores_uuid_after_create(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_session(tmp_path)
        vm = VMConfig(name="dc01", os="win11", vcpus=2, ram_gb=4, disk_gb=60, os_media="win11.iso")
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.create_vm = MagicMock()
            mock_prov.return_value.get_vm_uuid.return_value = "test-uuid-1234"
            app_module._run_hatch_session(sid, [vm], {"dc01": None}, "lab.yaml")
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        vm_row = next(v for v in s["vms"] if v["vm_name"] == "dc01")
        assert vm_row["libvirt_uuid"] == "test-uuid-1234"

    def test_uuid_failure_does_not_block_hatching(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_session(tmp_path)
        vm = VMConfig(name="dc01", os="win11", vcpus=2, ram_gb=4, disk_gb=60, os_media="win11.iso")
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.create_vm = MagicMock()
            mock_prov.return_value.get_vm_uuid.side_effect = RuntimeError("virsh failed")
            app_module._run_hatch_session(sid, [vm], {"dc01": None}, "lab.yaml")
        assert self._get_vm(sid)["status"] == "hatching"


class TestCheckWinrm:
    def test_returns_true_when_connection_succeeds(self, monkeypatch):
        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        with patch("socket.create_connection", return_value=mock_sock):
            assert app_module._check_winrm("192.168.1.1") is True

    def test_returns_false_on_connection_refused(self):
        with patch("socket.create_connection", side_effect=OSError("refused")):
            assert app_module._check_winrm("192.168.1.1") is False

    def test_returns_false_on_timeout(self):
        with patch("socket.create_connection", side_effect=TimeoutError()):
            assert app_module._check_winrm("192.168.1.1") is False

    def test_uses_port_5985_by_default(self):
        with patch("socket.create_connection", side_effect=OSError) as mock_conn:
            app_module._check_winrm("10.0.0.1")
        assert mock_conn.call_args[0][0] == ("10.0.0.1", 5985)

    def test_custom_port(self):
        with patch("socket.create_connection", side_effect=OSError) as mock_conn:
            app_module._check_winrm("10.0.0.1", port=5986)
        assert mock_conn.call_args[0][0] == ("10.0.0.1", 5986)


class TestSyncHatchStatus:
    _UUID = "aabbccdd-1234-5678-abcd-000000000001"

    def _setup_hatching(self, tmp_path, with_uuid=True):
        import lib.hatch as hatch_lib

        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.set_vm_status(sid, "dc01", "hatching")
        if with_uuid:
            hatch_lib.set_vm_uuid(sid, "dc01", self._UUID)
        return sid

    def test_marks_fledged_when_winrm_responds(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_hatching(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = "dc01"
            mock_prov.return_value.get_vm_ip.return_value = "192.168.122.40"
            with patch("hatchery._check_winrm", return_value=True):
                app_module._sync_hatch_status()
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert next(v["status"] for v in s["vms"] if v["vm_name"] == "dc01") == "fledged"

    def test_records_activity_when_fledged(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        self._setup_hatching(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = "dc01"
            mock_prov.return_value.get_vm_ip.return_value = "192.168.122.40"
            with patch("hatchery._check_winrm", return_value=True):
                app_module._sync_hatch_status()
        activity = [n for n in notif_lib.list_recent() if n["tier"] == "activity"]
        assert any("fledged" in a["message"] for a in activity)

    def test_no_change_when_no_ip_yet(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_hatching(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = "dc01"
            mock_prov.return_value.get_vm_ip.return_value = None
            app_module._sync_hatch_status()
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert next(v["status"] for v in s["vms"] if v["vm_name"] == "dc01") == "hatching"

    def test_no_change_when_winrm_not_responding(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_hatching(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = "dc01"
            mock_prov.return_value.get_vm_ip.return_value = "192.168.122.40"
            with patch("hatchery._check_winrm", return_value=False):
                app_module._sync_hatch_status()
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert next(v["status"] for v in s["vms"] if v["vm_name"] == "dc01") == "hatching"

    def test_marks_culled_when_uuid_not_found_on_host(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_hatching(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = None
            app_module._sync_hatch_status()
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert next(v["status"] for v in s["vms"] if v["vm_name"] == "dc01") == "culled"

    def test_records_activity_when_culled(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        self._setup_hatching(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = None
            app_module._sync_hatch_status()
        activity = [n for n in notif_lib.list_recent() if n["tier"] == "activity"]
        assert any("removed" in a["message"] for a in activity)

    def test_skips_vm_when_no_uuid_stored(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_hatching(tmp_path, with_uuid=False)
        with patch("hatchery._provider") as mock_prov:
            app_module._sync_hatch_status()
        mock_prov.return_value.get_vm_name_by_uuid.assert_not_called()
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert next(v["status"] for v in s["vms"] if v["vm_name"] == "dc01") == "hatching"

    def test_skips_when_no_monitored_vms(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        with patch("hatchery._provider") as mock_prov:
            app_module._sync_hatch_status()
        mock_prov.assert_not_called()

    def test_marks_culled_when_fledged_vm_gone(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.set_vm_status(sid, "dc01", "fledged")
        hatch_lib.set_vm_uuid(sid, "dc01", self._UUID)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = None
            app_module._sync_hatch_status()
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert next(v["status"] for v in s["vms"] if v["vm_name"] == "dc01") == "culled"

    def test_fledged_vm_not_rechecked_for_winrm(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.set_vm_status(sid, "dc01", "fledged")
        hatch_lib.set_vm_uuid(sid, "dc01", self._UUID)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = "dc01"
            app_module._sync_hatch_status()
        mock_prov.return_value.get_vm_ip.assert_not_called()

    def test_updates_name_when_vm_renamed(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_hatching(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = "dc01-renamed"
            mock_prov.return_value.get_vm_ip.return_value = None
            app_module._sync_hatch_status()
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        names = [v["vm_name"] for v in s["vms"]]
        assert "dc01-renamed" in names
        assert "dc01" not in names

    def test_records_activity_when_renamed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        self._setup_hatching(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = "dc01-renamed"
            mock_prov.return_value.get_vm_ip.return_value = None
            app_module._sync_hatch_status()
        activity = [n for n in notif_lib.list_recent() if n["tier"] == "activity"]
        assert any("renamed" in a["message"] for a in activity)


class TestApiSessions:
    def test_returns_empty_list_initially(self, client):
        data = client.get("/api/sessions").get_json()
        assert data == []

    def test_returns_200(self, client):
        assert client.get("/api/sessions").status_code == 200

    def test_returns_sessions_after_hatch(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path, name="my-lab")
        with patch("hatchery._run_hatch_session"):
            client.post("/hatch-clutch", data={"clutch_file": "my-lab.yaml"})
        data = client.get("/api/sessions").get_json()
        assert len(data) == 1
        assert data[0]["clutch_file"] == "my-lab.yaml"

    def test_session_includes_vms(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path, name="my-lab", vm_name="dc01")
        with patch("hatchery._run_hatch_session"):
            client.post("/hatch-clutch", data={"clutch_file": "my-lab.yaml"})
        data = client.get("/api/sessions").get_json()
        assert data[0]["vms"][0]["vm_name"] == "dc01"

    def test_session_includes_status(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        with patch("hatchery._run_hatch_session"):
            client.post("/hatch-clutch", data={"clutch_file": "my-lab.yaml"})
        data = client.get("/api/sessions").get_json()
        assert "status" in data[0]


class TestAPIClutchDetail:
    def test_returns_json(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        resp = client.get("/api/clutch/my-lab.yaml")
        assert resp.status_code == 200
        assert resp.content_type == "application/json"

    def test_returns_vm_list(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path, vm_name="dc01")
        data = client.get("/api/clutch/my-lab.yaml").get_json()
        assert any(v["name"] == "dc01" for v in data["vms"])

    def test_vm_includes_all_fields(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        data = client.get("/api/clutch/my-lab.yaml").get_json()
        vm = data["vms"][0]
        assert "os_media" in vm
        assert "vcpus" in vm
        assert "ram_gb" in vm
        assert "disk_gb" in vm
        assert "virtio_drivers" in vm
        assert "os_config" in vm
        assert "admin_username" in vm
        assert vm["os_media"] == "win11.iso"

    def test_vm_includes_admin_username(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        clutches_dir = tmp_path / "clutches"
        clutches_dir.mkdir()
        vm = VMConfig(
            name="dc01",
            os="win11",
            vcpus=2,
            ram_gb=4,
            disk_gb=60,
            os_media="win11.iso",
            admin_username="alice",
        )
        c = Clutch(name="my-lab", vms=[vm])
        import lib.clutch as clutch_lib

        clutch_lib.export(c, "my-lab", clutches_dir)
        data = client.get("/api/clutch/my-lab.yaml").get_json()
        assert data["vms"][0]["admin_username"] == "alice"

    def test_not_found_returns_404(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        resp = client.get("/api/clutch/ghost.yaml")
        assert resp.status_code == 404

    def test_path_traversal_is_stripped(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        resp = client.get("/api/clutch/..%2Fsome-file.yaml")
        assert resp.status_code == 404

    def test_invalid_clutch_returns_400(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        (tmp_path / "clutches" / "bad.yaml").write_text("not: valid: clutch: yaml: [")
        resp = client.get("/api/clutch/bad.yaml")
        assert resp.status_code == 400

    def test_circular_dependency_returns_200_with_vms(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        clutches_dir = tmp_path / "clutches"
        clutches_dir.mkdir()
        (clutches_dir / "cycle.yaml").write_text(
            "name: cycle-lab\nvms:\n"
            "  - {name: vm-a, os: win11, vcpus: 2, ram_gb: 4, disk_gb: 40,"
            " os_media: win11.iso, depends_on: [vm-b]}\n"
            "  - {name: vm-b, os: win11, vcpus: 2, ram_gb: 4, disk_gb: 40,"
            " os_media: win11.iso, depends_on: [vm-a]}\n"
        )
        resp = client.get("/api/clutch/cycle.yaml")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["vms"]) == 2
        assert "validation_error" in data
        assert "Circular dependency" in data["validation_error"]


class TestDeleteClutch:
    def test_delete_existing_file(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        path = _make_clutch(tmp_path)
        resp = client.post("/clutch/my-lab.yaml/delete", follow_redirects=False)
        assert resp.status_code == 302
        assert not path.exists()

    def test_delete_redirects_to_clutches(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        resp = client.post("/clutch/my-lab.yaml/delete", follow_redirects=False)
        assert "/clutches" in resp.headers["Location"]

    def test_delete_nonexistent_file_still_redirects(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        resp = client.post("/clutch/ghost.yaml/delete", follow_redirects=False)
        assert resp.status_code == 302

    def test_delete_path_traversal_blocked(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        # Flask routing decodes %2F as a path separator, so it never reaches the route
        resp = client.post("/clutch/..%2Fmy-lab.yaml/delete", follow_redirects=False)
        assert resp.status_code == 404
        assert (tmp_path / "clutches" / "my-lab.yaml").exists()

    def test_delete_resolves_active_alert_for_file(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        notif_lib.record_alert("Invalid Clutch file: 'my-lab.yaml' — some error")
        assert notif_lib.count_active_alerts() == 1
        client.post("/clutch/my-lab.yaml/delete")
        assert notif_lib.count_active_alerts() == 0

    def test_clutches_page_uses_modal_not_confirm(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        html = client.get("/clutches").data.decode()
        assert "delete-modal-backdrop" in html
        assert "delete-clutch-btn" in html
        assert "confirm(" not in html


class TestProvider:
    def test_returns_libvirt_provider(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        provider = app_module._provider()
        assert isinstance(provider, LibvirtProvider)
        assert provider.iso_dir == tmp_path / "media" / "iso"
        assert provider.virtio_dir == tmp_path / "media" / "virtio"
        assert provider.automation_dir == tmp_path / "automation" / "os_config"


class TestScanDir:
    def test_returns_empty_when_subdir_missing(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        resp = client.get("/api/media/iso")
        assert resp.get_json() == []

    def test_returns_files_in_dir(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        iso = tmp_path / "media" / "iso"
        iso.mkdir(parents=True)
        (iso / "win11.iso").touch()
        (iso / "win10.iso").touch()
        result = client.get("/api/media/iso").get_json()
        assert "win10.iso" in result
        assert "win11.iso" in result

    def test_filters_by_extension(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        clutches = tmp_path / "clutches"
        clutches.mkdir()
        (clutches / "lab.yaml").touch()
        (clutches / "notes.txt").touch()
        result = client.get("/api/clutches").get_json()
        assert "lab.yaml" in result
        assert "notes.txt" not in result


class TestNestStatus:
    def test_dot_green_when_no_alerts(self, client):
        with patch("lib.notifications.count_active_alerts", return_value=0):
            html = client.get("/").data.decode()
        assert "nest-status-dot--green" in html

    def test_dot_red_when_has_alerts(self, client):
        with patch("lib.notifications.count_active_alerts", return_value=2):
            html = client.get("/").data.decode()
        assert "nest-status-dot--red" in html

    def test_status_present_on_all_panes(self, client):
        with patch("lib.notifications.count_active_alerts", return_value=0):
            for path in [
                "/",
                "/nests",
                "/clutches",
                "/automation",
                "/settings",
                "/hatch-clutch",
                "/build",
                "/notifications",
                # /edit redirects without ?clutch= — skip it here
            ]:
                html = client.get(path).data.decode()
                assert "nest-status" in html, f"Expected nest status on {path}"

    def test_tooltip_all_ok_when_no_alerts(self, client):
        with patch("lib.notifications.count_active_alerts", return_value=0):
            html = client.get("/").data.decode()
        assert "All systems operational" in html

    def test_tooltip_shows_alert_count(self, client):
        with patch("lib.notifications.count_active_alerts", return_value=3):
            html = client.get("/").data.decode()
        assert "3 active alert" in html


class TestRequirementsSync:
    def test_records_alert_for_missing_tool(self):
        with patch(
            "lib.requirements.check_all",
            return_value=[Requirement("virsh", "libvirt-clients", "VM lifecycle", False)],
        ):
            app_module._sync_requirements()
        alerts = [n for n in notif_lib.list_recent() if n["tier"] == "alert"]
        assert any("virsh" in a["message"] for a in alerts)

    def test_no_alerts_when_all_tools_present(self):
        with patch(
            "lib.requirements.check_all",
            return_value=[Requirement("virsh", "libvirt-clients", "ops", True)],
        ):
            app_module._sync_requirements()
        assert notif_lib.count_active_alerts() == 0

    def test_resolves_stale_alert_when_tool_now_present(self):
        notif_lib.record_alert("Missing requirement: 'virsh' is not installed — VM lifecycle")
        assert notif_lib.count_active_alerts() == 1
        with patch(
            "lib.requirements.check_all",
            return_value=[Requirement("virsh", "libvirt-clients", "VM lifecycle", True)],
        ):
            app_module._sync_requirements()
        assert notif_lib.count_active_alerts() == 0

    def test_does_not_duplicate_alert_on_repeated_calls(self):
        missing = [Requirement("virsh", "libvirt-clients", "VM lifecycle", False)]
        with patch("lib.requirements.check_all", return_value=missing):
            app_module._sync_requirements()
            app_module._sync_requirements()
            app_module._sync_requirements()
        warnings = [
            n for n in notif_lib.list_recent() if n["tier"] == "alert" and n["resolved"] == 0
        ]
        assert len(warnings) == 1


class TestClutchesSync:
    def test_records_alert_for_invalid_clutch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        clutches_dir = tmp_path / "clutches"
        clutches_dir.mkdir()
        (clutches_dir / "bad.yaml").write_text(
            "name: cycle\nvms:\n"
            "  - {name: vm-a, os: win11, vcpus: 2, ram_gb: 4, disk_gb: 40,"
            " os_media: win11.iso, depends_on: [vm-b]}\n"
            "  - {name: vm-b, os: win11, vcpus: 2, ram_gb: 4, disk_gb: 40,"
            " os_media: win11.iso, depends_on: [vm-a]}\n"
        )
        app_module._sync_clutches()
        alerts = [n for n in notif_lib.list_recent() if n["tier"] == "alert" and n["resolved"] == 0]
        assert any("bad.yaml" in a["message"] for a in alerts)

    def test_alert_message_strips_redundant_file_context(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        clutches_dir = tmp_path / "clutches"
        clutches_dir.mkdir()
        (clutches_dir / "bad.yaml").write_text(
            "name: cycle\nvms:\n"
            "  - {name: vm-a, os: win11, vcpus: 2, ram_gb: 4, disk_gb: 40,"
            " os_media: win11.iso, depends_on: [vm-b]}\n"
            "  - {name: vm-b, os: win11, vcpus: 2, ram_gb: 4, disk_gb: 40,"
            " os_media: win11.iso, depends_on: [vm-a]}\n"
        )
        app_module._sync_clutches()
        alerts = [n for n in notif_lib.list_recent() if n["tier"] == "alert" and n["resolved"] == 0]
        msg = next(a["message"] for a in alerts if "bad.yaml" in a["message"])
        assert "Circular dependency" in msg
        assert msg.count("bad.yaml") == 1
        assert "Value error" not in msg

    def test_no_alert_for_valid_clutch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        app_module._sync_clutches()
        assert notif_lib.count_active_alerts() == 0

    def test_resolves_stale_alert_when_clutch_fixed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        notif_lib.record_alert("Invalid Clutch file: 'my-lab.yaml' — some old error")
        assert notif_lib.count_active_alerts() == 1
        _make_clutch(tmp_path)
        app_module._sync_clutches()
        assert notif_lib.count_active_alerts() == 0

    def test_does_not_duplicate_alert_on_repeated_calls(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        clutches_dir = tmp_path / "clutches"
        clutches_dir.mkdir()
        (clutches_dir / "bad.yaml").write_text("not: valid: clutch: [")
        app_module._sync_clutches()
        app_module._sync_clutches()
        app_module._sync_clutches()
        active = [n for n in notif_lib.list_recent() if n["tier"] == "alert" and n["resolved"] == 0]
        assert len(active) == 1

    def test_noop_when_clutches_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        app_module._sync_clutches()
        assert notif_lib.count_active_alerts() == 0


class TestNotificationsRoute:
    def test_returns_200(self, client):
        assert client.get("/notifications").status_code == 200

    def test_shows_recorded_item(self, client):
        notif_lib.record_activity("test activity message")
        html = client.get("/notifications").data.decode()
        assert "test activity message" in html

    def test_shows_empty_state_when_no_items(self, client):
        html = client.get("/notifications").data.decode()
        assert "No notifications yet" in html

    def test_shows_alert_tier_badge(self, client):
        notif_lib.record_alert("an environment alert")
        html = client.get("/notifications").data.decode()
        assert "notif-tier-badge--alert" in html


class TestBackgroundThread:
    def test_loop_calls_sync_on_timeout(self):
        stop = MagicMock()
        stop.wait.side_effect = [False, True]
        with (
            patch.object(app_module, "_sync_requirements") as mock_req,
            patch.object(app_module, "_sync_clutches") as mock_clutch,
            patch.object(app_module, "_sync_hatch_status") as mock_hatch,
        ):
            app_module._background_loop(stop)
        mock_req.assert_called_once()
        mock_clutch.assert_called_once()
        mock_hatch.assert_called_once()

    def test_loop_calls_sync_multiple_ticks(self):
        stop = MagicMock()
        stop.wait.side_effect = [False, False, False, True]
        with (
            patch.object(app_module, "_sync_requirements") as mock_req,
            patch.object(app_module, "_sync_clutches") as mock_clutch,
            patch.object(app_module, "_sync_hatch_status") as mock_hatch,
        ):
            app_module._background_loop(stop)
        assert mock_req.call_count == 3
        assert mock_clutch.call_count == 3
        assert mock_hatch.call_count == 3

    def test_loop_exits_without_sync_when_stopped_immediately(self):
        stop = MagicMock()
        stop.wait.return_value = True
        with (
            patch.object(app_module, "_sync_requirements") as mock_req,
            patch.object(app_module, "_sync_clutches") as mock_clutch,
            patch.object(app_module, "_sync_hatch_status") as mock_hatch,
        ):
            app_module._background_loop(stop)
        mock_req.assert_not_called()
        mock_clutch.assert_not_called()
        mock_hatch.assert_not_called()

    def test_start_background_thread_spawns_daemon_thread(self):
        with patch("threading.Thread") as mock_thread_cls:
            mock_t = MagicMock()
            mock_thread_cls.return_value = mock_t
            stop = app_module._start_background_thread()
        assert mock_thread_cls.call_args.kwargs.get("daemon") is True
        mock_t.start.assert_called_once()
        assert isinstance(stop, threading.Event)


class TestNotificationsAPI:
    def test_returns_200(self, client):
        assert client.get("/api/notifications").status_code == 200

    def test_response_is_json(self, client):
        resp = client.get("/api/notifications")
        assert resp.content_type == "application/json"

    def test_has_items_key(self, client):
        data = client.get("/api/notifications").get_json()
        assert "items" in data

    def test_has_active_alert_count_key(self, client):
        data = client.get("/api/notifications").get_json()
        assert "active_alert_count" in data

    def test_items_contains_recorded_notification(self, client):
        notif_lib.record_activity("api test message")
        data = client.get("/api/notifications").get_json()
        assert any(item["message"] == "api test message" for item in data["items"])

    def test_alert_count_reflects_active(self, client):
        notif_lib.record_alert("Missing requirement: some tool")
        data = client.get("/api/notifications").get_json()
        assert data["active_alert_count"] >= 1


class TestAPIRoutes:
    def test_api_media_iso_returns_json(self, client):
        resp = client.get("/api/media/iso")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_api_media_virtio_returns_json(self, client):
        resp = client.get("/api/media/virtio")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_api_automation_os_config_returns_json(self, client):
        resp = client.get("/api/automation/os-config")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_api_automation_scripts_returns_json(self, client):
        resp = client.get("/api/automation/scripts")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_api_clutches_returns_json(self, client):
        resp = client.get("/api/clutches")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)
