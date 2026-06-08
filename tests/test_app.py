import pytest
from unittest.mock import MagicMock, patch

import app as app_module
import lib.clutch as clutch_lib
import lib.config as cfg
import lib.db as db_module
import lib.notifications as notif_lib
from app import app as flask_app
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


VALID_FORM = {
    "name": "test-vm",
    "os": "win11",
    "vcpus": "2",
    "ram_gb": "4",
    "disk_gb": "40",
    "os_media": "win11.iso",
    "action": "hatch",
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


class TestHatchRoute:
    def test_hatch_get_returns_200(self, client):
        assert client.get("/hatch").status_code == 200

    def test_hatch_get_contains_form(self, client):
        html = client.get("/hatch").data.decode()
        assert "hatch-form" in html

    def test_hatch_get_shows_os_types(self, client):
        html = client.get("/hatch").data.decode()
        assert "win11" in html

    def test_hatch_action_calls_provider(self, client):
        with patch("app._provider") as mock_prov:
            mock_prov.return_value.create_vm = MagicMock()
            resp = client.post("/hatch", data=VALID_FORM)
        assert resp.status_code == 302
        mock_prov.return_value.create_vm.assert_called_once()

    def test_hatch_redirects_to_dashboard(self, client):
        with patch("app._provider") as mock_prov:
            mock_prov.return_value.create_vm = MagicMock()
            resp = client.post("/hatch", data=VALID_FORM, follow_redirects=False)
        assert resp.headers["Location"].endswith("/")

    def test_hatch_with_invalid_vcpus_rerenders_form(self, client):
        bad = {**VALID_FORM, "vcpus": "0"}
        resp = client.post("/hatch", data=bad)
        assert resp.status_code == 200
        assert "hatch-form" in resp.data.decode()

    def test_hatch_with_invalid_vcpus_shows_error(self, client):
        bad = {**VALID_FORM, "vcpus": "0"}
        html = client.post("/hatch", data=bad).data.decode()
        assert "alert" in html

    def test_form_values_preserved_on_validation_error(self, client):
        bad = {**VALID_FORM, "vcpus": "0", "name": "my-preserved-vm"}
        html = client.post("/hatch", data=bad).data.decode()
        assert "my-preserved-vm" in html

    def test_provider_error_rerenders_form(self, client):
        with patch("app._provider") as mock_prov:
            mock_prov.return_value.create_vm.side_effect = FileNotFoundError("no egg")
            resp = client.post("/hatch", data=VALID_FORM)
        assert resp.status_code == 200
        assert "hatch-form" in resp.data.decode()

    def test_permission_error_rerenders_form_and_records_warning(self, client):
        err_msg = (
            "The hypervisor (libvirt-qemu) cannot access: win11.iso\n"
            "Run: chmod o+x '/home/user'\n"
            "See Getting Started — Media Access for the recommended setup."
        )
        with patch("app._provider") as mock_prov:
            mock_prov.return_value.create_vm.side_effect = PermissionError(err_msg)
            resp = client.post("/hatch", data=VALID_FORM)
        assert resp.status_code == 200
        assert "hatch-form" in resp.data.decode()
        warnings = [n for n in notif_lib.list_recent() if n["tier"] == "warning"]
        assert any("libvirt-qemu" in w["message"] for w in warnings)


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
        with patch("app.clutch_lib.export", side_effect=RuntimeError("disk full")):
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
        with patch("app.clutch_lib.save", side_effect=RuntimeError("I/O error")):
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

    def test_post_hatches_all_vms_and_redirects(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path, name="my-lab", vm_name="dc01")
        with patch("app._provider") as mock_prov:
            mock_prov.return_value.create_vm = MagicMock()
            resp = client.post(
                "/hatch-clutch", data={"clutch_file": "my-lab.yaml"}, follow_redirects=False
            )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/")
        mock_prov.return_value.create_vm.assert_called_once()

    def test_post_provider_error_rerenders_form(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        with patch("app._provider") as mock_prov:
            mock_prov.return_value.create_vm.side_effect = FileNotFoundError("no egg")
            resp = client.post("/hatch-clutch", data={"clutch_file": "my-lab.yaml"})
        assert resp.status_code == 200
        assert "alert" in resp.data.decode()

    def test_post_permission_error_records_warning(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        with patch("app._provider") as mock_prov:
            mock_prov.return_value.create_vm.side_effect = PermissionError(
                "cannot access: win11.iso"
            )
            client.post("/hatch-clutch", data={"clutch_file": "my-lab.yaml"})
        warnings = [n for n in notif_lib.list_recent() if n["tier"] == "warning"]
        assert any("cannot access" in w["message"] for w in warnings)


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
        assert vm["os_media"] == "win11.iso"

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
        assert provider.media_dir == tmp_path / "media"
        assert provider.automation_dir == tmp_path / "automation"


class TestScanDir:
    def test_returns_empty_when_subdir_missing(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        resp = client.get("/api/media")
        assert resp.get_json() == []

    def test_returns_files_in_dir(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        media = tmp_path / "media"
        media.mkdir()
        (media / "win11.iso").touch()
        (media / "win10.iso").touch()
        result = client.get("/api/media").get_json()
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
    def test_dot_green_when_no_warnings(self, client):
        with patch("lib.notifications.count_unresolved_warnings", return_value=0):
            html = client.get("/").data.decode()
        assert "nest-status-dot--green" in html

    def test_dot_red_when_has_warnings(self, client):
        with patch("lib.notifications.count_unresolved_warnings", return_value=2):
            html = client.get("/").data.decode()
        assert "nest-status-dot--red" in html

    def test_status_present_on_all_panes(self, client):
        with patch("lib.notifications.count_unresolved_warnings", return_value=0):
            for path in [
                "/",
                "/nests",
                "/clutches",
                "/automation",
                "/settings",
                "/hatch",
                "/hatch-clutch",
                "/build",
                "/notifications",
                # /edit redirects without ?clutch= — skip it here
            ]:
                html = client.get(path).data.decode()
                assert "nest-status" in html, f"Expected nest status on {path}"

    def test_tooltip_all_ok_when_no_warnings(self, client):
        with patch("lib.notifications.count_unresolved_warnings", return_value=0):
            html = client.get("/").data.decode()
        assert "All systems operational" in html

    def test_tooltip_shows_warning_count(self, client):
        with patch("lib.notifications.count_unresolved_warnings", return_value=3):
            html = client.get("/").data.decode()
        assert "3 unresolved warning" in html


class TestRequirementsSync:
    def test_records_warning_for_missing_tool(self):
        with patch(
            "lib.requirements.check_all",
            return_value=[Requirement("virsh", "libvirt-clients", "VM lifecycle", False)],
        ):
            app_module._sync_requirements()
        warnings = [n for n in notif_lib.list_recent() if n["tier"] == "warning"]
        assert any("virsh" in w["message"] for w in warnings)

    def test_no_warnings_when_all_tools_present(self):
        with patch(
            "lib.requirements.check_all",
            return_value=[Requirement("virsh", "libvirt-clients", "ops", True)],
        ):
            app_module._sync_requirements()
        assert notif_lib.count_unresolved_warnings() == 0

    def test_resolves_stale_warning_when_tool_now_present(self):
        notif_lib.record("warning", "Missing requirement: 'virsh' is not installed — VM lifecycle")
        assert notif_lib.count_unresolved_warnings() == 1
        with patch(
            "lib.requirements.check_all",
            return_value=[Requirement("virsh", "libvirt-clients", "VM lifecycle", True)],
        ):
            app_module._sync_requirements()
        assert notif_lib.count_unresolved_warnings() == 0


class TestNotificationsRoute:
    def test_returns_200(self, client):
        assert client.get("/notifications").status_code == 200

    def test_shows_recorded_item(self, client):
        notif_lib.record("activity", "test activity message")
        html = client.get("/notifications").data.decode()
        assert "test activity message" in html

    def test_shows_empty_state_when_no_items(self, client):
        html = client.get("/notifications").data.decode()
        assert "No notifications yet" in html

    def test_shows_tier_badge(self, client):
        notif_lib.record("warning", "a warning notification")
        html = client.get("/notifications").data.decode()
        assert "notif-tier-badge--warning" in html


class TestNotificationsAPI:
    def test_returns_200(self, client):
        assert client.get("/api/notifications").status_code == 200

    def test_response_is_json(self, client):
        resp = client.get("/api/notifications")
        assert resp.content_type == "application/json"

    def test_has_items_key(self, client):
        data = client.get("/api/notifications").get_json()
        assert "items" in data

    def test_has_unresolved_warning_count_key(self, client):
        data = client.get("/api/notifications").get_json()
        assert "unresolved_warning_count" in data

    def test_items_contains_recorded_notification(self, client):
        notif_lib.record("activity", "api test message")
        data = client.get("/api/notifications").get_json()
        assert any(item["message"] == "api test message" for item in data["items"])

    def test_warning_count_reflects_unresolved(self, client):
        notif_lib.record("warning", "Missing requirement: some tool")
        data = client.get("/api/notifications").get_json()
        assert data["unresolved_warning_count"] >= 1

    def test_dismiss_returns_ok(self, client):
        nid = notif_lib.record("activity", "to be dismissed")
        resp = client.post(f"/api/notifications/{nid}/dismiss")
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}

    def test_dismiss_marks_notification_dismissed(self, client):
        nid = notif_lib.record("activity", "dismiss me")
        client.post(f"/api/notifications/{nid}/dismiss")
        row = next(r for r in notif_lib.list_recent() if r["id"] == nid)
        assert row["dismissed"] == 1


class TestAPIRoutes:
    def test_api_media_returns_json(self, client):
        resp = client.get("/api/media")
        assert resp.status_code == 200
        assert resp.content_type == "application/json"

    def test_api_media_is_list(self, client):
        resp = client.get("/api/media")
        assert isinstance(resp.get_json(), list)

    def test_api_automation_returns_json(self, client):
        resp = client.get("/api/automation")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_api_clutches_returns_json(self, client):
        resp = client.get("/api/clutches")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)
