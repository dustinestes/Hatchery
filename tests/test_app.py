import pytest
from unittest.mock import MagicMock, patch

import lib.clutch as clutch_lib
import lib.config as cfg
from app import app as flask_app
from lib.clutch import VMConfig
from lib.providers.libvirt import LibvirtProvider
from lib.requirements import Requirement


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


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


class TestCreateRoute:
    def test_create_get_returns_200(self, client):
        assert client.get("/create").status_code == 200

    def test_create_get_contains_form(self, client):
        html = client.get("/create").data.decode()
        assert "hatch-form" in html

    def test_create_get_shows_os_types(self, client):
        html = client.get("/create").data.decode()
        assert "win11" in html

    def test_hatch_action_calls_provider(self, client):
        with patch("app._provider") as mock_prov:
            mock_prov.return_value.create_vm = MagicMock()
            resp = client.post("/create", data=VALID_FORM)
        assert resp.status_code == 302
        mock_prov.return_value.create_vm.assert_called_once()

    def test_hatch_redirects_to_dashboard(self, client):
        with patch("app._provider") as mock_prov:
            mock_prov.return_value.create_vm = MagicMock()
            resp = client.post("/create", data=VALID_FORM, follow_redirects=False)
        assert resp.headers["Location"].endswith("/")

    def test_hatch_with_invalid_vcpus_rerenders_form(self, client):
        bad = {**VALID_FORM, "vcpus": "0"}
        resp = client.post("/create", data=bad)
        assert resp.status_code == 200
        assert "hatch-form" in resp.data.decode()

    def test_hatch_with_invalid_vcpus_shows_error(self, client):
        bad = {**VALID_FORM, "vcpus": "0"}
        html = client.post("/create", data=bad).data.decode()
        assert "alert" in html

    def test_form_values_preserved_on_validation_error(self, client):
        bad = {**VALID_FORM, "vcpus": "0", "name": "my-preserved-vm"}
        html = client.post("/create", data=bad).data.decode()
        assert "my-preserved-vm" in html

    def test_export_clutch_redirects_to_clutches(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir(parents=True, exist_ok=True)
        form = {
            **VALID_FORM,
            "action": "export_clutch",
            "export_mode": "new",
            "clutch_filename": "test-export",
            "clutch_name": "",
        }
        resp = client.post("/create", data=form, follow_redirects=False)
        assert resp.status_code == 302
        assert "/clutches" in resp.headers["Location"]

    def test_export_clutch_missing_filename_rerenders_form(self, client):
        form = {
            **VALID_FORM,
            "action": "export_clutch",
            "export_mode": "new",
            "clutch_filename": "",
        }
        resp = client.post("/create", data=form)
        assert resp.status_code == 200
        assert "hatch-form" in resp.data.decode()

    def test_provider_error_rerenders_form(self, client):
        with patch("app._provider") as mock_prov:
            mock_prov.return_value.create_vm.side_effect = FileNotFoundError("no egg")
            resp = client.post("/create", data=VALID_FORM)
        assert resp.status_code == 200
        assert "hatch-form" in resp.data.decode()

    def test_export_append_blank_target_rerenders_form(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "clutches").mkdir()
        form = {
            **VALID_FORM,
            "action": "export_clutch",
            "export_mode": "append",
            "clutch_append_target": "",
        }
        resp = client.post("/create", data=form)
        assert resp.status_code == 200
        assert "hatch-form" in resp.data.decode()

    def test_filename_label_has_required_indicator(self, client):
        html = client.get("/create").data.decode()
        assert 'for="clutch_filename"' in html
        assert 'class="required"' in html

    def test_export_append_happy_path_redirects_to_clutches(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        clutches_dir = tmp_path / "clutches"
        clutches_dir.mkdir()
        existing_vm = VMConfig(
            name="existing-vm", os="win10", vcpus=1, ram_gb=2, disk_gb=20, os_media="win10.iso"
        )
        clutch_lib.export(
            clutch_lib.Clutch(name="my-lab", vms=[existing_vm]), "my-lab", clutches_dir
        )
        form = {
            **VALID_FORM,
            "action": "export_clutch",
            "export_mode": "append",
            "clutch_append_target": "my-lab.yaml",
        }
        resp = client.post("/create", data=form, follow_redirects=False)
        assert resp.status_code == 302
        assert "/clutches" in resp.headers["Location"]


class TestProvider:
    def test_returns_libvirt_provider(self, tmp_path, monkeypatch):
        import app as app_module

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


class TestRequirementsWarning:
    def test_no_banner_when_all_present(self, client):
        with patch(
            "lib.requirements.check_all",
            return_value=[Requirement("virsh", "libvirt-clients", "ops", True)],
        ):
            html = client.get("/").data.decode()
        assert "req-warning" not in html

    def test_banner_shown_when_tools_missing(self, client):
        with patch(
            "lib.requirements.check_all",
            return_value=[Requirement("virsh", "libvirt-clients", "VM lifecycle", False)],
        ):
            html = client.get("/").data.decode()
        assert "req-warning" in html
        assert "libvirt-clients" in html

    def test_apt_command_shown_in_banner(self, client):
        with patch(
            "lib.requirements.check_all",
            return_value=[Requirement("virsh", "libvirt-clients", "VM lifecycle", False)],
        ):
            html = client.get("/").data.decode()
        assert "sudo apt install libvirt-clients" in html

    def test_banner_appears_on_all_panes(self, client):
        missing = [Requirement("virsh", "libvirt-clients", "VM lifecycle", False)]
        with patch("lib.requirements.check_all", return_value=missing):
            for path in ["/", "/nests", "/clutches", "/automation", "/settings", "/create"]:
                html = client.get(path).data.decode()
                assert "req-warning" in html, f"Expected warning banner on {path}"


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
