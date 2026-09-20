import threading
import io
import pytest
from unittest.mock import MagicMock, patch

import hatchery as app_module
import lib.clutch as clutch_lib
import lib.config as cfg
import lib.db as db_module
import lib.alerts as alerts_lib
import lib.hatch as hatch_lib
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

    def test_automation_redirects_to_scripts(self, client):
        resp = client.get("/automation")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/automation/scripts")

    def test_automation_scripts_returns_200(self, client):
        assert client.get("/automation/scripts").status_code == 200

    def test_media_redirects_to_iso(self, client):
        resp = client.get("/media")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/media/iso")

    def test_media_iso_returns_200(self, client):
        assert client.get("/media/iso").status_code == 200

    def test_media_virtio_returns_200(self, client):
        assert client.get("/media/virtio").status_code == 200

    def test_settings_redirects_to_general(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/settings/general")

    def test_settings_general_returns_200(self, client):
        assert client.get("/settings/general").status_code == 200

    def test_settings_security_returns_200(self, client):
        assert client.get("/settings/security").status_code == 200

    def test_settings_display_returns_200(self, client):
        assert client.get("/settings/display").status_code == 200

    def test_settings_unknown_section_404(self, client):
        assert client.get("/settings/database").status_code == 404

    def test_notifications_redirects_to_alerts(self, client):
        resp = client.get("/notifications")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/notifications/alerts")

    def test_alerts_returns_200(self, client):
        assert client.get("/notifications/alerts").status_code == 200

    def test_events_returns_200(self, client):
        assert client.get("/notifications/events").status_code == 200


class TestActivePane:
    def test_dashboard_marks_active(self, client):
        html = client.get("/").data.decode()
        assert 'class="sidebar-item active"' in html or "sidebar-item active" in html

    def test_nests_marks_active(self, client):
        html = client.get("/nests").data.decode()
        assert "active" in html

    def test_settings_marks_group_and_general_child(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "library_enabled", lambda: False)
        html = client.get("/settings/general").data.decode()
        assert "sidebar-item--group active open" in html
        assert html.count("sidebar-subitem active") == 1
        assert 'href="/settings/general"' in html
        assert 'href="/settings/security"' in html
        assert 'href="/settings/display"' in html
        assert 'href="/settings/library"' not in html

    def test_settings_library_nav_when_enabled(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "library_enabled", lambda: True)
        html = client.get("/settings/general").data.decode()
        assert 'href="/settings/library"' in html
        assert ">Library</span>" in html or 'sidebar-label">Library' in html

    def test_settings_nests_nav_always_present(self, client):
        html = client.get("/settings/general").data.decode()
        assert 'href="/settings/nests"' in html

    def test_nests_pane_lists_local_nest(self, client):
        html = client.get("/nests").data.decode()
        assert 'data-nest="local"' in html
        assert "Local" in html

    def test_settings_security_marks_group_and_child(self, client):
        html = client.get("/settings/security").data.decode()
        assert "sidebar-item--group active open" in html
        assert html.count("sidebar-subitem active") == 1
        assert "Security" in html

    def test_alerts_marks_notifications_group_and_child(self, client):
        html = client.get("/notifications/alerts").data.decode()
        assert "sidebar-item--group" in html
        assert "sidebar-item--group active open" in html
        assert "sidebar-subitem active" in html or 'class="sidebar-subitem active"' in html
        assert 'href="/notifications/alerts"' in html
        assert 'href="/notifications/events"' in html

    def test_events_marks_notifications_group_and_child(self, client):
        html = client.get("/notifications/events").data.decode()
        assert "sidebar-item--group active open" in html
        assert "Events" in html
        # Alerts child should not be the active subitem when on Events
        assert html.count("sidebar-subitem active") == 1

    def test_topbar_bell_and_tray_labeled_alerts(self, client):
        html = client.get("/").data.decode()
        assert 'aria-label="Alerts"' in html
        assert 'title="Alerts"' in html
        assert "<span>Alerts</span>" in html
        # Umbrella taxonomy stays on the sidebar group only
        assert ">Notifications</span>" in html or 'sidebar-label">Notifications' in html

    def test_topbar_hatch_and_clutch_ctas(self, client):
        html = client.get("/").data.decode()
        assert ">Hatch</a>" in html
        assert ">+ Clutch</a>" in html
        assert "+ Hatch" not in html
        assert "+ Build" not in html
        assert 'href="/hatch-clutch"' in html
        assert 'href="/build"' in html


class TestPageTitles:
    def test_dashboard_title(self, client):
        html = client.get("/").data.decode()
        assert "Dashboard" in html
        assert "Dashboard content coming soon" not in html
        assert 'id="dashboard-sections"' in html
        assert 'id="dashboard-section-hatchery-title"' in html
        assert 'id="dashboard-section-connections-title"' in html
        assert 'id="dashboard-section-observability-title"' in html
        assert 'id="dash-tile-nests"' in html
        assert 'id="dash-tile-clutches"' in html
        assert 'id="dash-tile-vms"' in html
        assert 'id="dash-tile-library"' in html
        assert 'id="dash-tile-health"' in html
        assert 'id="dash-tile-alerts"' in html
        assert 'id="dash-tile-validators"' in html
        assert "hatchery.onStatusTick" in html
        assert "nest-panel" not in html
        assert 'id="dashboard-empty-nests"' in html
        # Linear hierarchy within Hatchery section: Nests, Clutches, VMs
        nests_at = html.find('id="dash-tile-nests"')
        clutches_at = html.find('id="dash-tile-clutches"')
        vms_at = html.find('id="dash-tile-vms"')
        assert nests_at < clutches_at < vms_at
        # Observability: Health, Alerts, Validators
        health_at = html.find('id="dash-tile-health"')
        alerts_at = html.find('id="dash-tile-alerts"')
        validators_at = html.find('id="dash-tile-validators"')
        assert health_at < alerts_at < validators_at
        assert 'id="dashboard-tiles"' not in html

    def test_nests_title(self, client):
        html = client.get("/nests").data.decode()
        assert "Nests" in html

    def test_clutches_title(self, client):
        html = client.get("/clutches").data.decode()
        assert "Clutches" in html
        assert "scripts-layout" in html
        assert 'id="clutches-nav"' in html
        assert 'id="clutches-library-status-btn"' in html
        assert 'aria-label="Copy"' in html
        assert "hatchery.onStatusTick" in html
        assert "inventory-nav-drift-icon" in html
        assert 'aria-label="Filter Cached Clutches"' in html
        assert 'id="clutches-filter-q"' in html
        assert 'id="clutches-filter-language"' in html
        assert 'id="clutches-filter-state"' in html
        assert 'id="clutches-meta-language"' in html
        assert 'id="clutches-body"' in html
        assert 'id="clutches-copy-path-item">Path</button>' in html
        assert 'id="clutches-copy-content-item"' in html
        assert "applyClutchFilters" in html
        assert "populateLanguageFilter" in html
        assert "loadClutchContent" in html

    def test_automation_scripts_title(self, client):
        html = client.get("/automation/scripts").data.decode()
        assert "Scripts" in html
        assert "Select a script to inspect" in html
        assert 'class="stub"' in html
        assert "sidebar-item--group" in html
        assert "sidebar-item--group active open" in html
        assert 'href="/automation/scripts"' in html

    def test_automation_scripts_marks_group_and_child(self, client):
        html = client.get("/automation/scripts").data.decode()
        assert "sidebar-item--group active open" in html
        assert html.count("sidebar-subitem active") == 1
        assert "Scripts" in html

    def test_automation_scripts_library_tabs_when_enabled(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "library_enabled", lambda: True)
        html = client.get("/automation/scripts").data.decode()
        assert 'id="scripts-tab-cache"' in html
        assert 'id="scripts-tab-library"' in html
        assert "inventory-tab--disabled" not in html
        assert 'id="scripts-library-browser"' in html
        assert "Browse library…" in html
        assert "bindLibraryBrowser" in html

    def test_automation_scripts_cached_tab_when_library_disabled(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "library_enabled", lambda: False)
        html = client.get("/automation/scripts").data.decode()
        assert 'id="scripts-tab-cache"' in html
        assert 'id="scripts-tab-library"' in html
        assert "inventory-tab--disabled" in html
        assert "Browse library…" not in html
        assert 'id="scripts-library-browser"' not in html

    def test_media_iso_library_tabs_when_enabled(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "library_enabled", lambda: True)
        html = client.get("/media/iso").data.decode()
        assert 'id="media-tab-cache"' in html
        assert 'id="media-tab-library"' in html
        assert "inventory-tab--disabled" not in html
        assert 'id="media-library-browser"' in html
        assert "Browse library…" in html
        assert "library-import-backdrop" not in html

    def test_media_iso_cached_tab_when_library_disabled(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "library_enabled", lambda: False)
        html = client.get("/media/iso").data.decode()
        assert 'id="media-tab-cache"' in html
        assert 'id="media-tab-library"' in html
        assert "inventory-tab--disabled" in html
        assert 'id="media-library-browser"' not in html

    def test_clutches_library_tabs_when_enabled(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "library_enabled", lambda: True)
        html = client.get("/clutches").data.decode()
        assert 'id="clutches-tab-cache"' in html
        assert 'id="clutches-tab-library"' in html
        assert "inventory-tab--disabled" not in html
        assert 'id="clutches-library-browser"' in html
        assert "Browse library…" in html
        assert "library-import-backdrop" not in html

    def test_clutches_cached_tab_when_library_disabled(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "library_enabled", lambda: False)
        html = client.get("/clutches").data.decode()
        assert 'id="clutches-tab-cache"' in html
        assert 'id="clutches-tab-library"' in html
        assert "inventory-tab--disabled" in html
        assert 'id="clutches-library-browser"' not in html

    def test_media_iso_title_and_nav(self, client):
        html = client.get("/media/iso").data.decode()
        assert "ISO" in html
        assert "Select an ISO to inspect" in html
        assert 'class="stub"' in html
        assert "sidebar-item--group active open" in html
        assert 'href="/media/iso"' in html
        assert 'href="/media/virtio"' in html

    def test_media_virtio_marks_group_and_child(self, client):
        html = client.get("/media/virtio").data.decode()
        assert "sidebar-item--group active open" in html
        assert html.count("sidebar-subitem active") == 1
        assert "VirtIO" in html
        assert "Select a VirtIO file to inspect" in html

    def test_settings_general_title(self, client):
        html = client.get("/settings/general").data.decode()
        assert "General" in html
        assert "Settings" in html

    def test_settings_security_title(self, client):
        html = client.get("/settings/security").data.decode()
        assert "Security" in html

    def test_settings_display_title(self, client):
        html = client.get("/settings/display").data.decode()
        assert "Display" in html

    def test_notifications_title(self, client):
        html = client.get("/notifications/alerts").data.decode()
        assert "Alerts" in html

    def test_events_title(self, client):
        html = client.get("/notifications/events").data.decode()
        assert "Events" in html

    def test_validators_title(self, client):
        html = client.get("/notifications/validators").data.decode()
        assert "Validators" in html

    def test_notifications_panes_use_list_shell(self, client):
        for path in (
            "/notifications/alerts",
            "/notifications/events",
            "/notifications/validators",
        ):
            html = client.get(path).data.decode()
            assert 'class="list-shell"' in html
            assert "list-shell-body" in html
            assert "notif-filters" in html

    def test_events_uses_vm_filter_not_side_nav(self, client):
        html = client.get("/notifications/events").data.decode()
        assert 'id="events-filter-vm"' in html
        assert "events-nav" not in html
        assert 'id="events-table"' in html


class TestDashboardShell:
    """Dashboard at-a-glance shell (#328): SSR empty states from plane status."""

    _BASE = {
        "hatchery_ok": True,
        "hatchery_title": "Hatchery Controller OK",
        "hatchery_dot": "green",
        "hatchery_issue_count": 0,
        "nests_ok": True,
        "nests_title": "No Nests registered",
        "nests_dot": "muted",
        "nest_total": 0,
        "nest_reachable": 0,
        "nest_unreachable": 0,
        "nest_unchecked": 0,
        "nest_last_validated_at": None,
        "nest_alert_count": 0,
        "library_enabled": False,
        "libraries_visible": False,
        "libraries_ok": True,
        "libraries_title": "Library disabled",
        "libraries_dot": "muted",
        "library_connection_total": 0,
        "library_connection_registered": 0,
        "library_connection_disabled": 0,
        "library_alert_count": 0,
        "library_drift_alert_count": 0,
    }

    def test_empty_nests_banner_visible_when_none(self, client):
        with patch("lib.plane_status.footer_status", return_value=self._BASE):
            html = client.get("/").data.decode()
        assert 'id="dashboard-empty-nests"' in html
        assert 'id="dashboard-empty-nests" class="empty-state" role="status" hidden' not in html
        assert "Add a Nest in Settings" in html

    def test_empty_nests_banner_hidden_when_registered(self, client):
        status = {
            **self._BASE,
            "nest_total": 1,
            "nests_title": "All 1 Nest(s) OK",
            "nests_dot": "green",
        }
        with patch("lib.plane_status.footer_status", return_value=status):
            html = client.get("/").data.decode()
        assert 'id="dashboard-empty-nests" class="empty-state" role="status" hidden' in html

    def test_library_disabled_copy_and_settings_cta(self, client):
        with patch("lib.plane_status.footer_status", return_value=self._BASE):
            html = client.get("/").data.decode()
        assert "Library is disabled" in html
        assert 'id="dash-library-body"' in html
        assert "renderLibrary" in html
        assert 'href="/settings/general"' in html
        assert "Open Settings" in html

    def test_library_enabled_loading_and_library_cta(self, client):
        status = {
            **self._BASE,
            "library_enabled": True,
            "libraries_visible": True,
            "libraries_title": "No Library connections",
        }
        with patch("lib.plane_status.footer_status", return_value=status):
            html = client.get("/").data.decode()
        assert "Loading Library status" in html
        assert 'href="/settings/library"' in html
        assert "Open Settings" in html
        assert "Open Library Settings" not in html


class TestDashboardSummaryApi:
    def test_dashboard_summary_returns_nests_vms_and_clutches(self, client, monkeypatch):
        monkeypatch.setattr(
            "lib.dashboard_summary.dashboard_summary",
            lambda: {
                "nests": {
                    "total": 1,
                    "reachable": 1,
                    "unreachable": 0,
                    "unchecked": 0,
                    "alert_count": 0,
                    "last_validated_at": "2026-09-20T12:00:00Z",
                },
                "vms": {
                    "total": 2,
                    "by_power": {"running": 1, "shut_off": 1, "paused": 0, "other": 0},
                    "by_hatch": {
                        "pending": 0,
                        "hatching": 0,
                        "provisioning": 0,
                        "fledged": 1,
                        "failed": 0,
                        "culled": 0,
                        "none": 1,
                    },
                    "nests_unavailable": 0,
                },
                "clutches": {
                    "file_count": 1,
                    "session_total": 1,
                    "by_status": {
                        "in_progress": 1,
                        "completed": 0,
                        "failed": 0,
                        "degraded": 0,
                        "unknown": 0,
                    },
                    "nests_used": [{"id": "local", "name": "Local"}],
                    "unique_clutch_files": 1,
                },
            },
        )
        resp = client.get("/api/dashboard-summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["nests"]["total"] == 1
        assert data["vms"]["total"] == 2
        assert data["vms"]["by_power"]["running"] == 1
        assert data["clutches"]["file_count"] == 1
        assert data["clutches"]["session_total"] == 1

    def test_dashboard_scripts_fetch_summary(self, client):
        html = client.get("/").data.decode()
        assert "/api/dashboard-summary" in html
        assert "renderNests" in html
        assert "renderVms" in html
        assert "renderClutches" in html
        assert "renderHealth" in html
        assert "renderAlerts" in html
        assert "renderValidators" in html
        assert "dash-nests-body" in html
        assert "dash-vms-body" in html
        assert "dash-clutches-body" in html
        assert "dash-health-body" in html
        assert "dash-alerts-body" in html
        assert "dash-validators-body" in html
        assert "fetchDashboardSummary" in html
        assert "payload.alerts" in html
        assert "Controller and Nest health rollup" not in html
        assert "Open alert counts by tier" not in html
        assert "Enabled or off, last run status" not in html


class TestSettingsRoute:
    def test_get_shows_current_data_dir(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": str(tmp_path), "bg_interval": 60})
        html = client.get("/settings/general").data.decode()
        assert str(tmp_path) in html

    def test_get_shows_config_file_path(self, client):
        html = client.get("/settings/general").data.decode()
        assert str(cfg.CONFIG_FILE) in html

    def test_post_valid_saves_and_redirects(self, client, tmp_path, monkeypatch):
        saved = {}
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": "/old/path", "bg_interval": 60})
        monkeypatch.setattr(cfg, "save", lambda c: saved.update(c))
        monkeypatch.setattr(cfg, "init_data_dir", lambda: None)
        monkeypatch.setattr(cfg, "bind_db", lambda: None)
        monkeypatch.setattr(db_module, "init_db", lambda path: None)
        resp = client.post(
            "/settings/general", data={"data_dir": str(tmp_path), "bg_interval": "60"}
        )
        assert resp.status_code == 302
        assert "/settings/general" in resp.headers["Location"]
        assert "saved=1" in resp.headers["Location"]
        assert saved["data_dir"] == str(tmp_path)

    def test_post_empty_path_shows_error(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": "/old/path", "bg_interval": 60})
        resp = client.post("/settings/general", data={"data_dir": "", "bg_interval": "60"})
        assert resp.status_code == 200
        assert "required" in resp.data.decode().lower()

    def test_post_expands_tilde(self, client, monkeypatch):
        saved = {}
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": "/old", "bg_interval": 60})
        monkeypatch.setattr(cfg, "save", lambda c: saved.update(c))
        monkeypatch.setattr(cfg, "init_data_dir", lambda: None)
        monkeypatch.setattr(cfg, "bind_db", lambda: None)
        monkeypatch.setattr(db_module, "init_db", lambda path: None)
        client.post("/settings/general", data={"data_dir": "~/hatchery/data", "bg_interval": "60"})
        assert not saved["data_dir"].startswith("~")

    def test_get_saved_param_shows_success_banner(self, client):
        html = client.get("/settings/general?saved=1").data.decode()
        assert "saved" in html.lower()

    def test_post_calls_init_data_dir(self, client, tmp_path, monkeypatch):
        called = []
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": "/old", "bg_interval": 60})
        monkeypatch.setattr(cfg, "save", lambda c: None)
        monkeypatch.setattr(cfg, "init_data_dir", lambda: called.append(True))
        monkeypatch.setattr(cfg, "bind_db", lambda: None)
        monkeypatch.setattr(db_module, "init_db", lambda path: None)
        client.post("/settings/general", data={"data_dir": str(tmp_path), "bg_interval": "60"})
        assert called

    def test_get_shows_current_bg_interval(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": "/some/path", "bg_interval": 120})
        html = client.get("/settings/general").data.decode()
        assert "120" in html

    def test_post_saves_bg_interval(self, client, tmp_path, monkeypatch):
        saved = {}
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": str(tmp_path), "bg_interval": 60})
        monkeypatch.setattr(cfg, "save", lambda c: saved.update(c))
        monkeypatch.setattr(cfg, "init_data_dir", lambda: None)
        monkeypatch.setattr(cfg, "bind_db", lambda: None)
        monkeypatch.setattr(db_module, "init_db", lambda path: None)
        client.post("/settings/general", data={"data_dir": str(tmp_path), "bg_interval": "120"})
        assert saved["bg_interval"] == 120

    def test_post_bg_interval_below_minimum_shows_error(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": "/old", "bg_interval": 60})
        resp = client.post("/settings/general", data={"data_dir": "/some/path", "bg_interval": "5"})
        assert resp.status_code == 200
        assert "10" in resp.data.decode()

    def test_get_shows_validators_section(self, client):
        html = client.get("/settings/general").data.decode()
        assert "Validators" in html
        assert "Controller requirements" in html
        assert "validators_run_retention" in html

    def test_post_saves_validator_interval(self, client, tmp_path, monkeypatch):
        saved = {}
        monkeypatch.setattr(
            cfg,
            "get",
            lambda: {
                "data_dir": str(tmp_path),
                "bg_interval": 60,
                "validators": {},
                "validators_run_retention": 50,
            },
        )
        monkeypatch.setattr(cfg, "save", lambda c: saved.update(c))
        monkeypatch.setattr(cfg, "init_data_dir", lambda: None)
        monkeypatch.setattr(cfg, "bind_db", lambda: None)
        monkeypatch.setattr(db_module, "init_db", lambda path: None)
        client.post(
            "/settings/general",
            data={
                "data_dir": str(tmp_path),
                "bg_interval": "60",
                "validators_run_retention": "25",
                "validator_id": "clutch_files",
                "validator_enabled_clutch_files": "on",
                "validator_interval_clutch_files": "180",
            },
        )
        assert saved["validators_run_retention"] == 25
        assert saved["validators"]["clutch_files"]["interval_seconds"] == 180
        assert saved["validators"]["clutch_files"]["enabled"] is True

    def test_general_post_preserves_security_keys(self, client, tmp_path, monkeypatch):
        saved = {}
        monkeypatch.setattr(
            cfg,
            "get",
            lambda: {
                "data_dir": "/old",
                "bg_interval": 60,
                "show_passwords": True,
                "display_timezone": "local",
            },
        )
        monkeypatch.setattr(cfg, "save", lambda c: saved.update(c))
        monkeypatch.setattr(cfg, "init_data_dir", lambda: None)
        monkeypatch.setattr(cfg, "bind_db", lambda: None)
        monkeypatch.setattr(db_module, "init_db", lambda path: None)
        client.post("/settings/general", data={"data_dir": str(tmp_path), "bg_interval": "90"})
        assert saved["show_passwords"] is True
        assert saved["display_timezone"] == "local"

    def test_display_post_saves_timezone(self, client, tmp_path, monkeypatch):
        saved = {}
        monkeypatch.setattr(
            cfg,
            "get",
            lambda: {"data_dir": str(tmp_path), "bg_interval": 60, "display_timezone": "UTC"},
        )
        monkeypatch.setattr(cfg, "save", lambda c: saved.update(c))
        resp = client.post("/settings/display", data={"display_timezone": "local"})
        assert resp.status_code == 302
        assert "/settings/display" in resp.headers["Location"]
        assert saved["display_timezone"] == "local"
        assert saved["data_dir"] == str(tmp_path)


class TestNestSettings:
    def test_nests_settings_returns_200(self, client):
        resp = client.get("/settings/nests")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Connections" in html
        assert 'name="nest_id"' in html
        assert "Test Nest connection" in html

    def test_nests_post_adds_remote(self, client):
        import lib.nests as nests_lib

        resp = client.post(
            "/settings/nests",
            data={
                "nest_id": ["local", "lab1"],
                "nest_name": ["Local", "Lab"],
                "nest_provider_type": ["libvirt", "hyperv"],
                "nest_location": ["local", "remote"],
                "nest_transport": ["ssh", "ssh"],
                "nest_host": ["", "nest.example"],
                "nest_port": ["", "22"],
                "nest_ssh_user": ["", "ops"],
                "nest_identity_file": ["", "~/.ssh/id"],
                "nest_cert_path": ["", ""],
                "nest_identity_expires_at": ["", "2026-12-01"],
                "nest_known_hosts": ["default", "default"],
                "nest_winrm_user": ["", ""],
                "nest_credential_ref": ["", ""],
            },
        )
        assert resp.status_code == 302
        assert "/settings/nests" in resp.headers["Location"]
        assert nests_lib.get_nest("lab1")["host"] == "nest.example"
        assert nests_lib.get_nest("lab1")["identity_file"] == "~/.ssh/id"
        assert nests_lib.get_nest("lab1")["identity_expires_at"].startswith("2026-12-01")

    def test_api_test_local_nest(self, client):
        with patch("lib.requirements.check_nest", return_value=[]):
            resp = client.post(
                "/api/nests/test-connection",
                json={"nest_id": "local"},
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_api_nest_vms_unknown_404(self, client):
        resp = client.get("/api/nests/no-such-nest/vms")
        assert resp.status_code == 404
        assert "Unknown Nest" in resp.get_json()["error"]

    def test_api_nest_vms_remote_501(self, client):
        import lib.nests as nests_lib

        nests_lib.replace_nests(
            [
                nests_lib.get_nest("local"),
                {
                    "id": "remote1",
                    "name": "Remote",
                    "provider_type": "libvirt",
                    "location": "remote",
                    "host": "r.example",
                },
            ]
        )
        resp = client.get("/api/nests/remote1/vms")
        assert resp.status_code == 501
        assert "remote1" in resp.get_json()["error"]


class TestLibrarySettingsGate:
    def test_library_redirects_when_disabled(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "library_enabled", lambda: False)
        resp = client.get("/settings/library")
        assert resp.status_code == 302
        assert "/settings/general" in resp.headers["Location"]
        assert "library_required=1" in resp.headers["Location"]

    def test_library_required_shows_hint_on_general(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "library_enabled", lambda: False)
        html = client.get("/settings/general?library_required=1").data.decode()
        assert "Enable" in html
        assert "Library" in html

    def test_library_returns_200_when_enabled(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "library_enabled", lambda: True)
        monkeypatch.setattr(
            cfg,
            "get",
            lambda: {
                "data_dir": "/data",
                "bg_interval": 60,
                "library_enabled": True,
                "library_connections": [],
                "library_script_bindings": [],
                "library_clutch_bindings": [],
                "library_media_bindings": [],
            },
        )
        resp = client.get("/settings/library")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "No connections yet" in html
        assert "Add connection" in html
        assert "Script bindings" in html
        assert "Clutch bindings" in html
        assert "Media bindings" in html
        assert "library-save-conn-btn" in html
        assert "library-save-bind-btn" in html
        assert html.count('class="action-bar"') == 0
        assert "sidebar-item--group active open" in html
        assert html.count("sidebar-subitem active") == 1

    def test_library_post_saves_connection_and_binding(self, client, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        (share / "a.ps1").write_text("# hi\n", encoding="utf-8")
        saved = {}
        monkeypatch.setattr(cfg, "library_enabled", lambda: True)
        monkeypatch.setattr(
            cfg,
            "get",
            lambda: {
                "data_dir": str(tmp_path),
                "bg_interval": 60,
                "library_enabled": True,
                "library_connections": [],
                "library_script_bindings": [],
                "library_clutch_bindings": [],
                "library_media_bindings": [],
            },
        )
        monkeypatch.setattr(cfg, "save", lambda c: saved.update(c))
        resp = client.post(
            "/settings/library",
            data={
                "library_conn_id": "abc123def456",
                "library_conn_label": "Ops share",
                "library_conn_type": "path",
                "library_conn_provider": "",
                "library_conn_base_uri": str(share),
                "library_conn_token": "",
                "library_conn_expires_at": "",
                "library_conn_kinds": "scripts,clutches,media",
                "library_conn_enabled": "1",
                "library_script_bind_id": "bind001",
                "library_script_bind_connection_id": "abc123def456",
                "library_script_bind_filter": "*.ps1",
                "library_script_bind_enabled": "1",
                "library_clutch_bind_id": "cbind001",
                "library_clutch_bind_connection_id": "abc123def456",
                "library_clutch_bind_filter": "*.yaml",
                "library_clutch_bind_enabled": "1",
                "library_media_bind_id": "mbind001",
                "library_media_bind_connection_id": "abc123def456",
                "library_media_bind_filter": "*.iso",
                "library_media_bind_target": "iso",
                "library_media_bind_enabled": "1",
            },
        )
        assert resp.status_code == 302
        assert saved["library_connections"][0]["label"] == "Ops share"
        assert saved["library_connections"][0]["expires_at"] is None
        assert saved["library_connections"][0]["enabled"] is True
        assert saved["library_script_bindings"][0]["filter"] == "*.ps1"
        assert saved["library_script_bindings"][0]["enabled"] is True
        assert saved["library_clutch_bindings"][0]["filter"] == "*.yaml"
        assert saved["library_media_bindings"][0]["target"] == "iso"

    def test_library_api_upsert_and_delete_connection(self, client, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        state = {
            "data_dir": str(tmp_path),
            "bg_interval": 60,
            "library_enabled": True,
            "library_connections": [],
            "library_script_bindings": [],
            "library_clutch_bindings": [],
            "library_media_bindings": [],
        }
        monkeypatch.setattr(cfg, "library_enabled", lambda: True)
        monkeypatch.setattr(cfg, "get", lambda: state)
        monkeypatch.setattr(cfg, "library_connections", lambda: list(state["library_connections"]))
        monkeypatch.setattr(
            cfg, "library_script_bindings", lambda: list(state["library_script_bindings"])
        )
        monkeypatch.setattr(
            cfg, "library_clutch_bindings", lambda: list(state["library_clutch_bindings"])
        )
        monkeypatch.setattr(
            cfg, "library_media_bindings", lambda: list(state["library_media_bindings"])
        )
        monkeypatch.setattr(cfg, "save", lambda c: state.update(c))

        conn = {
            "id": "cpath1",
            "label": "Share",
            "type": "path",
            "base_uri": str(share),
            "token": "",
            "expires_at": "",
            "kinds": ["scripts"],
            "enabled": True,
        }
        put = client.put("/api/library/connections", json={"connection": conn})
        assert put.status_code == 200
        assert put.get_json()["ok"] is True
        assert len(state["library_connections"]) == 1

        state["library_script_bindings"] = [
            {
                "id": "b1",
                "connection_id": "cpath1",
                "filter": "*",
                "domain": "scripts",
                "enabled": True,
            }
        ]
        deleted = client.delete("/api/library/connections/cpath1")
        assert deleted.status_code == 200
        body = deleted.get_json()
        assert body["ok"] is True
        assert body["bindings_removed"] == 1
        assert state["library_connections"] == []
        assert state["library_script_bindings"] == []

    def test_library_api_delete_git_connection_removes_cache(self, client, tmp_path, monkeypatch):
        state = {
            "data_dir": str(tmp_path),
            "bg_interval": 60,
            "library_enabled": True,
            "library_connections": [
                {
                    "id": "g1",
                    "label": "Ops git",
                    "type": "git",
                    "base_uri": "https://example.com/org/repo.git",
                    "token": "",
                    "expires_at": None,
                    "kinds": ["scripts"],
                    "enabled": True,
                }
            ],
            "library_script_bindings": [],
            "library_clutch_bindings": [],
            "library_media_bindings": [],
        }
        monkeypatch.setattr(cfg, "library_enabled", lambda: True)
        monkeypatch.setattr(cfg, "get", lambda: state)
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        monkeypatch.setattr(cfg, "library_connections", lambda: list(state["library_connections"]))
        monkeypatch.setattr(
            cfg, "library_script_bindings", lambda: list(state["library_script_bindings"])
        )
        monkeypatch.setattr(
            cfg, "library_clutch_bindings", lambda: list(state["library_clutch_bindings"])
        )
        monkeypatch.setattr(
            cfg, "library_media_bindings", lambda: list(state["library_media_bindings"])
        )
        monkeypatch.setattr(cfg, "save", lambda c: state.update(c))

        cache = tmp_path / "library" / "git" / "g1"
        cache.mkdir(parents=True)
        (cache / "marker.txt").write_text("x", encoding="utf-8")

        kept = client.delete(
            "/api/library/connections/g1",
            json={"delete_git_cache": False},
        )
        assert kept.status_code == 200
        assert kept.get_json()["git_cache_deleted"] is False
        assert cache.is_dir()
        assert state["library_connections"] == []

        state["library_connections"] = [
            {
                "id": "g1",
                "label": "Ops git",
                "type": "git",
                "base_uri": "https://example.com/org/repo.git",
                "token": "",
                "expires_at": None,
                "kinds": ["scripts"],
                "enabled": True,
            }
        ]
        deleted = client.delete(
            "/api/library/connections/g1",
            json={"delete_git_cache": True},
        )
        assert deleted.status_code == 200
        body = deleted.get_json()
        assert body["ok"] is True
        assert body["git_cache_deleted"] is True
        assert not cache.exists()
        assert state["library_connections"] == []

    def test_library_api_delete_path_ignores_git_cache_flag(self, client, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        state = {
            "data_dir": str(tmp_path),
            "bg_interval": 60,
            "library_enabled": True,
            "library_connections": [
                {
                    "id": "cpath1",
                    "label": "Share",
                    "type": "path",
                    "base_uri": str(share),
                    "token": "",
                    "expires_at": None,
                    "kinds": ["scripts"],
                    "enabled": True,
                }
            ],
            "library_script_bindings": [],
            "library_clutch_bindings": [],
            "library_media_bindings": [],
        }
        monkeypatch.setattr(cfg, "library_enabled", lambda: True)
        monkeypatch.setattr(cfg, "get", lambda: state)
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        monkeypatch.setattr(cfg, "library_connections", lambda: list(state["library_connections"]))
        monkeypatch.setattr(
            cfg, "library_script_bindings", lambda: list(state["library_script_bindings"])
        )
        monkeypatch.setattr(
            cfg, "library_clutch_bindings", lambda: list(state["library_clutch_bindings"])
        )
        monkeypatch.setattr(
            cfg, "library_media_bindings", lambda: list(state["library_media_bindings"])
        )
        monkeypatch.setattr(cfg, "save", lambda c: state.update(c))

        stray = tmp_path / "library" / "git" / "cpath1"
        stray.mkdir(parents=True)
        (stray / "x").write_text("1", encoding="utf-8")

        deleted = client.delete(
            "/api/library/connections/cpath1",
            json={"delete_git_cache": True},
        )
        assert deleted.status_code == 200
        assert deleted.get_json()["git_cache_deleted"] is False
        assert stray.is_dir()

    def test_library_api_upsert_binding(self, client, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        state = {
            "data_dir": str(tmp_path),
            "bg_interval": 60,
            "library_enabled": True,
            "library_connections": [
                {
                    "id": "c1",
                    "label": "Share",
                    "type": "path",
                    "base_uri": str(share),
                    "token": "",
                    "expires_at": None,
                    "kinds": ["scripts"],
                    "enabled": True,
                }
            ],
            "library_script_bindings": [],
            "library_clutch_bindings": [],
            "library_media_bindings": [],
        }
        monkeypatch.setattr(cfg, "library_enabled", lambda: True)
        monkeypatch.setattr(cfg, "get", lambda: state)
        monkeypatch.setattr(cfg, "library_connections", lambda: list(state["library_connections"]))
        monkeypatch.setattr(cfg, "save", lambda c: state.update(c))

        put = client.put(
            "/api/library/bindings/scripts",
            json={
                "binding": {
                    "id": "b1",
                    "connection_id": "c1",
                    "filter": "*.ps1",
                    "enabled": True,
                }
            },
        )
        assert put.status_code == 200
        assert put.get_json()["ok"] is True
        assert state["library_script_bindings"][0]["filter"] == "*.ps1"

        deleted = client.delete("/api/library/bindings/scripts/b1")
        assert deleted.status_code == 200
        assert state["library_script_bindings"] == []

    def test_library_api_test_and_pull(self, client, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        (share / "tool.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        data = tmp_path / "data"
        (data / "automation" / "scripts").mkdir(parents=True)
        conn = {
            "id": "cpath1",
            "label": "Share",
            "type": "path",
            "base_uri": str(share),
            "token": "",
            "expires_at": None,
            "kinds": ["scripts"],
        }
        monkeypatch.setattr(cfg, "library_enabled", lambda: True)
        monkeypatch.setattr(cfg, "library_connections", lambda: [conn])
        monkeypatch.setattr(
            cfg,
            "library_script_bindings",
            lambda: [{"id": "b1", "connection_id": "cpath1", "filter": "*", "domain": "scripts"}],
        )
        monkeypatch.setattr(cfg, "data_dir", lambda: data)

        test_resp = client.post(
            "/api/library/test-connection",
            json={"connection_id": "cpath1"},
        )
        assert test_resp.status_code == 200
        assert test_resp.get_json()["ok"] is True

        catalog = client.get("/api/library/scripts")
        assert catalog.status_code == 200
        items = catalog.get_json()["items"]
        assert any(i["name"] == "tool.sh" for i in items)
        tool = next(i for i in items if i["name"] == "tool.sh")
        assert tool.get("cached") is False

        pull = client.post(
            "/api/library/scripts/pull",
            json={"connection_id": "cpath1", "relative_path": "tool.sh"},
        )
        assert pull.status_code == 200
        assert pull.get_json()["imported"] == ["tool.sh"]
        assert (data / "automation" / "scripts" / "tool.sh").is_file()

        catalog2 = client.get("/api/library/scripts")
        tool2 = next(i for i in catalog2.get_json()["items"] if i["name"] == "tool.sh")
        assert tool2.get("cached") is True

    def test_library_api_forbidden_when_disabled(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "library_enabled", lambda: False)
        resp = client.get("/api/library/scripts")
        assert resp.status_code == 403

    def test_catalog_ignores_unrelated_connections(self, client, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        (share / "tool.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        script_conn = {
            "id": "cpath1",
            "label": "Share",
            "type": "path",
            "base_uri": str(share),
            "token": "",
            "expires_at": None,
            "kinds": ["scripts"],
        }
        # Media-only row that would fail strict Settings validation if incomplete —
        # must not break Scripts catalog.
        media_conn = {
            "id": "artifactory",
            "label": "Artifactory",
            "type": "https",
            "base_uri": "https://example.invalid/artifactory",
            "token": "secret",
            "expires_at": "",
            "kinds": ["media"],
        }
        monkeypatch.setattr(cfg, "library_enabled", lambda: True)
        monkeypatch.setattr(cfg, "library_connections", lambda: [media_conn, script_conn])
        monkeypatch.setattr(
            cfg,
            "library_script_bindings",
            lambda: [
                {
                    "id": "b1",
                    "connection_id": "cpath1",
                    "filter": "*",
                    "domain": "scripts",
                }
            ],
        )
        catalog = client.get("/api/library/scripts")
        assert catalog.status_code == 200
        items = catalog.get_json()["items"]
        assert any(i["name"] == "tool.sh" for i in items)
        assert all(i.get("connection_id") == "cpath1" for i in items)

    def test_library_media_catalog_and_pull(self, client, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        (share / "win11.iso").write_bytes(b"iso")
        data = tmp_path / "data"
        (data / "media" / "iso").mkdir(parents=True)
        conn = {
            "id": "m1",
            "label": "ISOs",
            "type": "path",
            "base_uri": str(share),
            "token": "",
            "expires_at": None,
            "kinds": ["media"],
        }
        monkeypatch.setattr(cfg, "library_enabled", lambda: True)
        monkeypatch.setattr(cfg, "library_connections", lambda: [conn])
        monkeypatch.setattr(
            cfg,
            "library_media_bindings",
            lambda: [
                {
                    "id": "b1",
                    "connection_id": "m1",
                    "filter": "*",
                    "domain": "media",
                    "target": "iso",
                }
            ],
        )
        monkeypatch.setattr(cfg, "data_dir", lambda: data)

        catalog = client.get("/api/library/media?target=iso")
        assert catalog.status_code == 200
        items = catalog.get_json()["items"]
        hit = next(i for i in items if i["name"] == "win11.iso")
        assert hit.get("cached") is False

        pull = client.post(
            "/api/library/media/pull",
            json={
                "connection_id": "m1",
                "relative_path": "win11.iso",
                "target": "iso",
            },
        )
        assert pull.status_code == 200
        assert (data / "media" / "iso" / "win11.iso").is_file()

        catalog2 = client.get("/api/library/media?target=iso")
        hit2 = next(i for i in catalog2.get_json()["items"] if i["name"] == "win11.iso")
        assert hit2.get("cached") is True

    def test_nest_cache_preflight_api_ok_and_missing(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path, name="lab")
        ok = client.post(
            "/api/nest-cache/preflight",
            json={"clutch_file": "lab.yaml"},
        )
        assert ok.status_code == 200
        assert ok.get_json()["ok"] is True

        (tmp_path / "media" / "iso" / "win11.iso").unlink()
        missing = client.post(
            "/api/nest-cache/preflight",
            json={"clutch_file": "lab.yaml"},
        )
        assert missing.status_code == 200
        body = missing.get_json()
        assert body["ok"] is False
        assert "Nest cache missing" in body["error"]

    def test_nest_cache_ensure_remote_returns_501(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path, name="lab")
        resp = client.post(
            "/api/nest-cache/ensure",
            json={"clutch_file": "lab.yaml", "location": "remote", "host": "nest.example"},
        )
        assert resp.status_code == 501
        assert "not available yet" in resp.get_json()["error"]

    def test_library_clutch_catalog_and_pull(self, client, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        (share / "lab.yaml").write_text("name: lab\n", encoding="utf-8")
        data = tmp_path / "data"
        (data / "clutches").mkdir(parents=True)
        conn = {
            "id": "c1",
            "label": "Clutches",
            "type": "path",
            "base_uri": str(share),
            "token": "",
            "expires_at": None,
            "kinds": ["clutches"],
        }
        monkeypatch.setattr(cfg, "library_enabled", lambda: True)
        monkeypatch.setattr(cfg, "library_connections", lambda: [conn])
        monkeypatch.setattr(
            cfg,
            "library_clutch_bindings",
            lambda: [
                {
                    "id": "b1",
                    "connection_id": "c1",
                    "filter": "*",
                    "domain": "clutches",
                }
            ],
        )
        monkeypatch.setattr(cfg, "data_dir", lambda: data)

        catalog = client.get("/api/library/clutches")
        assert catalog.status_code == 200
        assert any(i["name"] == "lab.yaml" for i in catalog.get_json()["items"])

        pull = client.post(
            "/api/library/clutches/pull",
            json={
                "connection_id": "c1",
                "relative_path": "lab.yaml",
            },
        )
        assert pull.status_code == 200
        assert (data / "clutches" / "lab.yaml").is_file()

    def test_general_post_saves_library_enabled(self, client, tmp_path, monkeypatch):
        saved = {}
        monkeypatch.setattr(
            cfg,
            "get",
            lambda: {"data_dir": str(tmp_path), "bg_interval": 60, "library_enabled": False},
        )
        monkeypatch.setattr(cfg, "save", lambda c: saved.update(c))
        monkeypatch.setattr(cfg, "init_data_dir", lambda: None)
        monkeypatch.setattr(cfg, "bind_db", lambda: None)
        monkeypatch.setattr(db_module, "init_db", lambda path: None)
        client.post(
            "/settings/general",
            data={
                "data_dir": str(tmp_path),
                "bg_interval": "60",
                "library_enabled": "on",
            },
        )
        assert saved["library_enabled"] is True

    def test_general_post_clears_library_enabled_when_unchecked(
        self, client, tmp_path, monkeypatch
    ):
        saved = {}
        monkeypatch.setattr(
            cfg,
            "get",
            lambda: {"data_dir": str(tmp_path), "bg_interval": 60, "library_enabled": True},
        )
        monkeypatch.setattr(cfg, "save", lambda c: saved.update(c))
        monkeypatch.setattr(cfg, "init_data_dir", lambda: None)
        monkeypatch.setattr(cfg, "bind_db", lambda: None)
        monkeypatch.setattr(db_module, "init_db", lambda path: None)
        client.post(
            "/settings/general",
            data={"data_dir": str(tmp_path), "bg_interval": "60"},
        )
        assert saved["library_enabled"] is False

    def test_general_shows_library_toggle(self, client):
        html = client.get("/settings/general").data.decode()
        assert 'name="library_enabled"' in html
        assert "Enable Library" in html

    def test_general_shows_settings_export_import_controls(self, client):
        html = client.get("/settings/general").data.decode()
        assert 'id="settings-export-btn"' in html
        assert ">Export<" in html
        assert 'id="settings-import-btn"' in html
        assert ">Import<" in html
        assert 'id="settings-import-backdrop"' in html
        assert 'id="settings-import-confirm"' in html
        assert "/api/settings/export" in html
        assert "Profile" not in html

    def test_settings_export_download(self, client, monkeypatch):
        monkeypatch.setattr(
            cfg,
            "get",
            lambda: {
                "data_dir": "/data",
                "bg_interval": 45,
                "show_passwords": False,
                "display_timezone": "UTC",
                "library_enabled": True,
                "library_connections": [],
                "library_script_bindings": [],
                "library_clutch_bindings": [],
                "library_media_bindings": [],
                "nest_key_alert_tiers": [{"days_before": 30, "alerts_per_day": 1}],
                "nest_ssh_identities": [],
            },
        )
        resp = client.get("/api/settings/export")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        body = resp.data.decode()
        assert "version: 1" in body
        assert "bg_interval: 45" in body
        assert "library_enabled: true" in body

    def test_settings_import_replace(self, client, tmp_path, monkeypatch):
        state = {
            "data_dir": str(tmp_path),
            "bg_interval": 60,
            "show_passwords": False,
            "display_timezone": "UTC",
            "library_enabled": True,
            "library_connections": [
                {
                    "id": "old",
                    "label": "Old",
                    "type": "path",
                    "base_uri": "/old",
                    "token": "",
                    "expires_at": None,
                    "kinds": ["scripts"],
                }
            ],
            "library_script_bindings": [],
            "library_clutch_bindings": [],
            "library_media_bindings": [],
            "nest_key_alert_tiers": [
                {"days_before": 30, "alerts_per_day": 1},
                {"days_before": 7, "alerts_per_day": 2},
            ],
            "nest_ssh_identities": [],
        }
        monkeypatch.setattr(cfg, "get", lambda: state)
        monkeypatch.setattr(cfg, "save", lambda c: state.update(c))

        yaml_body = "version: 1\nsettings:\n  bg_interval: 99\n  library_enabled: true\n"
        resp = client.post(
            "/api/settings/import",
            json={"yaml": yaml_body},
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert state["bg_interval"] == 99
        assert state["library_enabled"] is True
        assert state["library_connections"] == []
        assert state["data_dir"] == str(tmp_path)


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
        assert [s.name for s in c.vms[0].automations] == ["setup.ps1", "configure.ps1"]

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
        alerts_lib.record_alert("Invalid Clutch file: 'my-lab.yaml' — some validation error")
        assert alerts_lib.count_active_alerts() == 1
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
        assert alerts_lib.count_active_alerts() == 0


def _make_clutch(tmp_path, name="my-lab", vm_name="dc01"):
    clutches_dir = tmp_path / "clutches"
    clutches_dir.mkdir(exist_ok=True)
    iso_dir = tmp_path / "media" / "iso"
    iso_dir.mkdir(parents=True, exist_ok=True)
    (iso_dir / "win11.iso").write_bytes(b"test-iso")
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
        iso_dir = tmp_path / "media" / "iso"
        iso_dir.mkdir(parents=True)
        (iso_dir / "win11.iso").write_bytes(b"x")
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

    def test_post_missing_nest_cache_media_rerenders_form(self, client, tmp_path, monkeypatch):
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
        )
        c = Clutch(name="my-lab", vms=[vm])
        clutch_lib.export(c, "my-lab", clutches_dir)
        with patch("hatchery._run_hatch_session") as mock_run:
            resp = client.post("/hatch-clutch", data={"clutch_file": "my-lab.yaml"})
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Nest cache missing" in html
        assert "media/iso/win11.iso" in html
        mock_run.assert_not_called()

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

    @pytest.fixture(autouse=True)
    def no_side_effects(self):
        with patch("hatchery.time.sleep"), patch("hatchery._send_boot_key"):
            yield

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

        def fake_create_vm(vm_cfg, admin_password=None, storage_path=None):
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
        alerts = [n for n in alerts_lib.list_recent() if n["tier"] == "alert"]
        assert any("cannot access" in a["message"] for a in alerts)

    def test_records_hatch_event_on_success(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_session(tmp_path)
        vm = VMConfig(name="dc01", os="win11", vcpus=2, ram_gb=4, disk_gb=60, os_media="win11.iso")
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.create_vm = MagicMock()
            app_module._run_hatch_session(sid, [vm], {"dc01": None}, "lab.yaml")
        events = hatch_lib.get_events(sid, "dc01")
        assert any("created successfully" in e["message"].lower() for e in events)

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

        def fake_create(vm_cfg, admin_password=None, storage_path=None):
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

    def test_boot_key_started_in_background_thread(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_session(tmp_path)
        vm = VMConfig(name="dc01", os="win11", vcpus=2, ram_gb=4, disk_gb=60, os_media="win11.iso")
        with (
            patch("hatchery._provider") as mock_prov,
            patch("hatchery.threading.Thread") as mock_thread_cls,
        ):
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            mock_prov.return_value.create_vm = MagicMock()
            app_module._run_hatch_session(sid, [vm], {"dc01": None}, "lab.yaml")
        boot_calls = [
            c
            for c in mock_thread_cls.call_args_list
            if c.kwargs.get("target") is app_module._send_boot_key
        ]
        assert len(boot_calls) == 1
        assert boot_calls[0].kwargs["args"] == (mock_prov.return_value, "dc01")
        mock_thread.start.assert_called_once()

    def test_boot_key_thread_started_before_create_vm(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_session(tmp_path)
        vm = VMConfig(name="dc01", os="win11", vcpus=2, ram_gb=4, disk_gb=60, os_media="win11.iso")
        call_order = []
        with (
            patch("hatchery._provider") as mock_prov,
            patch("hatchery.threading.Thread") as mock_thread_cls,
        ):
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            mock_thread.start.side_effect = lambda: call_order.append("thread_start")
            mock_prov.return_value.create_vm.side_effect = lambda *a, **kw: call_order.append(
                "create_vm"
            )
            app_module._run_hatch_session(sid, [vm], {"dc01": None}, "lab.yaml")
        assert call_order.index("thread_start") < call_order.index("create_vm")

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


class TestSendBootKey:
    @pytest.fixture(autouse=True)
    def no_sleep(self):
        with patch("hatchery.time.sleep"):
            yield

    def test_polls_until_vm_running(self):
        provider = MagicMock()
        provider.get_status.side_effect = ["shut off", "shut off", "running"]
        app_module._send_boot_key(provider, "myvm")
        assert provider.get_status.call_count == 3

    def test_sends_burst_of_keypresses(self):
        provider = MagicMock()
        provider.get_status.return_value = "running"
        app_module._send_boot_key(provider, "myvm")
        assert provider.send_key.call_count == app_module._BOOT_KEY_BURST_ATTEMPTS

    def test_all_keypresses_are_enter(self):
        provider = MagicMock()
        provider.get_status.return_value = "running"
        app_module._send_boot_key(provider, "myvm")
        for call in provider.send_key.call_args_list:
            assert call == call.__class__(provider, "myvm", "KEY_ENTER") or call.args == (
                "myvm",
                "KEY_ENTER",
            )

    def test_continues_burst_on_send_key_failure(self):
        provider = MagicMock()
        provider.get_status.return_value = "running"
        provider.send_key.side_effect = RuntimeError("virsh failed")
        app_module._send_boot_key(provider, "myvm")
        assert provider.send_key.call_count == app_module._BOOT_KEY_BURST_ATTEMPTS

    def test_settles_after_running_before_burst(self):
        provider = MagicMock()
        provider.get_status.return_value = "running"
        with patch("hatchery.time.sleep") as mock_sleep:
            app_module._send_boot_key(provider, "myvm")
        assert mock_sleep.call_args_list[0].args == (app_module._BOOT_KEY_SETTLE_SECONDS,)

    def test_handles_get_status_exception(self):
        provider = MagicMock()
        provider.get_status.side_effect = [RuntimeError("virsh error"), "running"]
        app_module._send_boot_key(provider, "myvm")
        assert provider.get_status.call_count == 2

    def test_gives_up_polling_after_max_attempts(self):
        provider = MagicMock()
        provider.get_status.return_value = "shut off"
        app_module._send_boot_key(provider, "myvm")
        assert provider.get_status.call_count == app_module._BOOT_KEY_POLL_ATTEMPTS
        assert provider.send_key.call_count == app_module._BOOT_KEY_BURST_ATTEMPTS

    def test_still_sends_keys_if_vm_never_reached_running(self):
        provider = MagicMock()
        provider.get_status.return_value = "shut off"
        app_module._send_boot_key(provider, "myvm")
        assert provider.send_key.call_count == app_module._BOOT_KEY_BURST_ATTEMPTS


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
                with patch("hatchery.provision_lib.check_setup_complete", return_value=True):
                    with patch("hatchery.provision_lib.read_setup_log", return_value=""):
                        with patch("hatchery.provision_lib.delete_setup_log"):
                            with patch("hatchery.provision_lib.delete_setup_flag"):
                                app_module._sync_hatch_status()
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert next(v["status"] for v in s["vms"] if v["vm_name"] == "dc01") == "fledged"

    def test_imports_setup_log_events_before_fledging(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_hatching(tmp_path)
        setup_log = (
            "[HATCH:INFO][setup][2026-07-20T12:00:00+00:00] Hatchery first boot setup started\n"
            "[HATCH:INFO][step-1][2026-07-20T12:00:05+00:00] Step 1 succeeded: Set network profile"
        )
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = "dc01"
            mock_prov.return_value.get_vm_ip.return_value = "192.168.122.40"
            with patch("hatchery._check_winrm", return_value=True):
                with patch("hatchery.provision_lib.check_setup_complete", return_value=True):
                    with patch(
                        "hatchery.provision_lib.read_setup_log", return_value=setup_log
                    ) as mock_read:
                        with patch("hatchery.provision_lib.delete_setup_log") as mock_del_log:
                            with patch("hatchery.provision_lib.delete_setup_flag"):
                                app_module._sync_hatch_status()
        mock_read.assert_called_once_with("192.168.122.40", "", "")
        mock_del_log.assert_called_once_with("192.168.122.40", "", "")
        events = hatch_lib.get_events(sid, "dc01")
        setup_events = [e for e in events if e.get("script_name") == "hatchery-setup.ps1"]
        assert len(setup_events) == 2
        assert setup_events[0]["component"] == "setup"
        assert setup_events[0]["received_at"] == "2026-07-20T12:00:00+00:00"
        assert setup_events[1]["message"] == "Step 1 succeeded: Set network profile"

    def test_records_hatch_event_when_fledged(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_hatching(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = "dc01"
            mock_prov.return_value.get_vm_ip.return_value = "192.168.122.40"
            with patch("hatchery._check_winrm", return_value=True):
                with patch("hatchery.provision_lib.check_setup_complete", return_value=True):
                    with patch("hatchery.provision_lib.read_setup_log", return_value=""):
                        with patch("hatchery.provision_lib.delete_setup_log"):
                            with patch("hatchery.provision_lib.delete_setup_flag"):
                                app_module._sync_hatch_status()
        events = hatch_lib.get_events(sid, "dc01")
        assert any("no automation scripts" in e["message"].lower() for e in events)

    def test_no_change_when_setup_flag_not_present(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_hatching(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = "dc01"
            mock_prov.return_value.get_vm_ip.return_value = "192.168.122.40"
            with patch("hatchery._check_winrm", return_value=True):
                with patch("hatchery.provision_lib.check_setup_complete", return_value=False):
                    app_module._sync_hatch_status()
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert next(v["status"] for v in s["vms"] if v["vm_name"] == "dc01") == "hatching"

    def test_deletes_setup_flag_on_handoff(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        self._setup_hatching(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = "dc01"
            mock_prov.return_value.get_vm_ip.return_value = "192.168.122.40"
            with patch("hatchery._check_winrm", return_value=True):
                with patch("hatchery.provision_lib.check_setup_complete", return_value=True):
                    with patch("hatchery.provision_lib.read_setup_log", return_value=""):
                        with patch("hatchery.provision_lib.delete_setup_log"):
                            with patch("hatchery.provision_lib.delete_setup_flag") as mock_del:
                                app_module._sync_hatch_status()
        mock_del.assert_called_once_with("192.168.122.40", "", "")

    def test_starts_vm_when_shut_off_during_hatching(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        self._setup_hatching(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = "dc01"
            mock_prov.return_value.get_status.return_value = "shut off"
            app_module._sync_hatch_status()
        mock_prov.return_value.start_vm.assert_called_once_with("dc01")

    def test_does_not_check_winrm_when_shut_off(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        self._setup_hatching(tmp_path)
        with patch("hatchery._provider") as mock_prov, patch("hatchery._check_winrm") as mock_winrm:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = "dc01"
            mock_prov.return_value.get_status.return_value = "shut off"
            app_module._sync_hatch_status()
        mock_winrm.assert_not_called()

    def test_start_failure_does_not_mark_failed(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup_hatching(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = "dc01"
            mock_prov.return_value.get_status.return_value = "shut off"
            mock_prov.return_value.start_vm.side_effect = RuntimeError("virsh failed")
            app_module._sync_hatch_status()
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert next(v["status"] for v in s["vms"] if v["vm_name"] == "dc01") == "hatching"

    def test_does_not_start_fledged_vm_when_shut_off(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.set_vm_status(sid, "dc01", "fledged")
        hatch_lib.set_vm_uuid(sid, "dc01", self._UUID)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = "dc01"
            mock_prov.return_value.get_status.return_value = "shut off"
            app_module._sync_hatch_status()
        mock_prov.return_value.start_vm.assert_not_called()

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
        # Two VMs — ws01 stays hatching so the session is not auto-archived,
        # letting us assert that dc01's status was set to culled.
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm(sid, "ws01")
        hatch_lib.set_vm_status(sid, "dc01", "hatching")
        hatch_lib.set_vm_uuid(sid, "dc01", self._UUID)
        hatch_lib.set_vm_status(sid, "ws01", "hatching")
        ws_uuid = "bbbbccdd-1234-5678-abcd-000000000002"
        hatch_lib.set_vm_uuid(sid, "ws01", ws_uuid)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.side_effect = lambda uuid: (
                None if uuid == self._UUID else "ws01"
            )
            mock_prov.return_value.get_status.return_value = "running"
            mock_prov.return_value.get_vm_ip.return_value = None
            app_module._sync_hatch_status()
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert next(v["status"] for v in s["vms"] if v["vm_name"] == "dc01") == "culled"

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
        # Two VMs — ws01 stays hatching (→ in_progress) so the session is not
        # auto-archived, letting us assert that dc01's status was set to culled.
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm(sid, "ws01")
        hatch_lib.set_vm_status(sid, "dc01", "fledged")
        hatch_lib.set_vm_uuid(sid, "dc01", self._UUID)
        ws_uuid = "bbbbccdd-1234-5678-abcd-000000000002"
        hatch_lib.set_vm_status(sid, "ws01", "hatching")
        hatch_lib.set_vm_uuid(sid, "ws01", ws_uuid)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.side_effect = lambda uuid: (
                None if uuid == self._UUID else "ws01"
            )
            mock_prov.return_value.get_status.return_value = "running"
            mock_prov.return_value.get_vm_ip.return_value = None
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

    def test_auto_archives_session_when_last_vm_culled(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        self._setup_hatching(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_name_by_uuid.return_value = None
            app_module._sync_hatch_status()
        assert hatch_lib.list_sessions() == []

    def test_does_not_archive_when_other_vms_still_hatching(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm(sid, "ws01")
        hatch_lib.set_vm_status(sid, "dc01", "hatching")
        hatch_lib.set_vm_uuid(sid, "dc01", self._UUID)
        hatch_lib.set_vm_status(sid, "ws01", "hatching")
        hatch_lib.set_vm_uuid(sid, "ws01", "bbbbccdd-1234-5678-abcd-000000000002")
        with patch("hatchery._provider") as mock_prov:
            # dc01 is culled, ws01 is still running
            mock_prov.return_value.get_vm_name_by_uuid.side_effect = lambda uuid: (
                None if uuid == self._UUID else "ws01"
            )
            mock_prov.return_value.get_status.return_value = "running"
            mock_prov.return_value.get_vm_ip.return_value = None
            app_module._sync_hatch_status()
        assert len(hatch_lib.list_sessions()) == 1


class TestApiDismissSession:
    def test_dismiss_archives_session(self, client, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        resp = client.post(f"/api/sessions/{sid}/dismiss")
        assert resp.status_code == 200
        assert hatch_lib.list_sessions() == []

    def test_dismiss_returns_ok(self, client, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        resp = client.post(f"/api/sessions/{sid}/dismiss")
        assert resp.get_json() == {"ok": True}

    def test_dismiss_nonexistent_session_is_silent(self, client):
        resp = client.post("/api/sessions/does-not-exist/dismiss")
        assert resp.status_code == 200


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

    def test_automation_reboot_after_included_in_response(self, client, tmp_path, monkeypatch):
        from lib.clutch import AutomationScript
        import lib.clutch as clutch_lib

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
            automations=[AutomationScript(name="setup.ps1", reboot_after=True)],
        )
        c = Clutch(name="my-lab", vms=[vm])
        clutch_lib.export(c, "my-lab", clutches_dir)
        data = client.get("/api/clutch/my-lab.yaml").get_json()
        entry = data["vms"][0]["automations"][0]
        assert isinstance(entry, dict)
        assert entry["name"] == "setup.ps1"
        assert entry["reboot_after"] is True

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
        alerts_lib.record_alert("Invalid Clutch file: 'my-lab.yaml' — some error")
        assert alerts_lib.count_active_alerts() == 1
        client.post("/clutch/my-lab.yaml/delete")
        assert alerts_lib.count_active_alerts() == 0

    def test_clutches_page_uses_modal_not_confirm(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        html = client.get("/clutches").data.decode()
        assert "delete-modal-backdrop" in html
        assert 'id="clutches-delete-btn"' in html
        assert "confirm(" not in html


class TestProvider:
    def test_returns_libvirt_provider(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        provider = app_module._provider()
        assert isinstance(provider, LibvirtProvider)
        assert provider.iso_dir == tmp_path / "media" / "iso"
        assert provider.virtio_dir == tmp_path / "media" / "virtio"
        assert provider.automation_dir == tmp_path / "automation" / "os_config"

    def test_provider_honors_nest_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        import lib.nests as nests_lib

        nests_lib.ensure_local_nest()
        provider = app_module._provider("local")
        assert isinstance(provider, LibvirtProvider)

    def test_hatch_form_shows_nest_select(self, client):
        html = client.get("/hatch-clutch").data.decode()
        assert 'name="nest"' in html
        assert 'id="hatch-nest-select"' in html

    def test_hatch_rejects_unknown_nest(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        resp = client.post(
            "/hatch-clutch",
            data={"clutch_file": "my-lab.yaml", "nest": "no-such-nest"},
        )
        assert resp.status_code == 200
        assert "Unknown Nest" in resp.data.decode()

    def test_hatch_rejects_remote_nest(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        import lib.nests as nests_lib

        _make_clutch(tmp_path)
        nests_lib.replace_nests(
            [
                nests_lib.get_nest("local"),
                {
                    "id": "remote1",
                    "name": "Remote",
                    "provider_type": "libvirt",
                    "location": "remote",
                    "host": "r.example",
                },
            ]
        )
        resp = client.post(
            "/hatch-clutch",
            data={"clutch_file": "my-lab.yaml", "nest": "remote1"},
        )
        assert resp.status_code == 200
        assert "not available" in resp.data.decode()


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
        names = [i["name"] if isinstance(i, dict) else i for i in result]
        assert "win10.iso" in names
        assert "win11.iso" in names
        assert all(isinstance(i, dict) and "drift_state" in i for i in result)

    def test_filters_by_extension(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        clutches = tmp_path / "clutches"
        clutches.mkdir()
        (clutches / "lab.yaml").touch()
        (clutches / "notes.txt").touch()
        result = client.get("/api/clutches").get_json()
        names = [i["name"] if isinstance(i, dict) else i for i in result]
        assert "lab.yaml" in names
        assert "notes.txt" not in names
        assert all(isinstance(i, dict) and "drift_state" in i for i in result)
        lab = next(i for i in result if i["name"] == "lab.yaml")
        assert lab["language"] == "YAML"

    def test_api_clutch_content_returns_text(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        clutches = tmp_path / "clutches"
        clutches.mkdir()
        (clutches / "lab.yaml").write_text("name: Lab\nvms: []\n")
        resp = client.get("/api/clutches/lab.yaml/content")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "lab.yaml"
        assert "name: Lab" in data["content"]


class TestPlaneStatus:
    _LIBRARIES_OFF = {
        "library_enabled": False,
        "libraries_visible": False,
        "libraries_ok": True,
        "libraries_title": "Library disabled",
        "libraries_dot": "muted",
        "library_connection_total": 0,
        "library_connection_registered": 0,
        "library_connection_disabled": 0,
        "library_alert_count": 0,
        "library_drift_alert_count": 0,
    }

    def test_footer_shows_hatchery_and_nests(self, client):
        with patch(
            "lib.plane_status.footer_status",
            return_value={
                "hatchery_ok": True,
                "hatchery_title": "Hatchery Controller OK",
                "hatchery_dot": "green",
                "hatchery_issue_count": 0,
                "nests_ok": True,
                "nests_title": "All 1 Nest(s) OK",
                "nests_dot": "green",
                "nest_total": 1,
                "nest_unreachable": 0,
                "nest_alert_count": 0,
                **self._LIBRARIES_OFF,
            },
        ):
            html = client.get("/").data.decode()
        assert "Hatchery</span>" in html
        assert "Nests</span>" in html
        assert "footer-hatchery" in html
        assert "footer-nests" in html
        assert "footer-libraries" in html
        assert "nest-status-dot--green" in html

    def test_hatchery_red_when_controller_issues(self, client):
        with patch(
            "lib.plane_status.footer_status",
            return_value={
                "hatchery_ok": False,
                "hatchery_title": "Hatchery: 1 Controller issue(s) — see Alerts",
                "hatchery_dot": "red",
                "hatchery_issue_count": 1,
                "nests_ok": True,
                "nests_title": "All 1 Nest(s) OK",
                "nests_dot": "green",
                "nest_total": 1,
                "nest_unreachable": 0,
                "nest_alert_count": 0,
                **self._LIBRARIES_OFF,
            },
        ):
            html = client.get("/").data.decode()
        assert "Hatchery: 1 Controller issue(s)" in html
        assert "nest-status-dot--red" in html

    def test_nests_muted_when_none_registered(self, client):
        with patch(
            "lib.plane_status.footer_status",
            return_value={
                "hatchery_ok": True,
                "hatchery_title": "Hatchery Controller OK",
                "hatchery_dot": "green",
                "hatchery_issue_count": 0,
                "nests_ok": True,
                "nests_title": "No Nests registered",
                "nests_dot": "muted",
                "nest_total": 0,
                "nest_unreachable": 0,
                "nest_alert_count": 0,
                **self._LIBRARIES_OFF,
            },
        ):
            html = client.get("/").data.decode()
        assert "No Nests registered" in html
        assert "nest-status-dot--muted" in html

    def test_nests_red_when_unreachable(self, client):
        with patch(
            "lib.plane_status.footer_status",
            return_value={
                "hatchery_ok": True,
                "hatchery_title": "Hatchery Controller OK",
                "hatchery_dot": "green",
                "hatchery_issue_count": 0,
                "nests_ok": False,
                "nests_title": "Nests: 1 of 2 unreachable — see Alerts",
                "nests_dot": "red",
                "nest_total": 2,
                "nest_unreachable": 1,
                "nest_alert_count": 0,
                **self._LIBRARIES_OFF,
            },
        ):
            html = client.get("/").data.decode()
        assert "1 of 2 unreachable" in html
        assert "nest-status-dot--red" in html

    def test_libraries_chip_visible_when_enabled(self, client):
        with patch(
            "lib.plane_status.footer_status",
            return_value={
                "hatchery_ok": True,
                "hatchery_title": "Hatchery Controller OK",
                "hatchery_dot": "green",
                "hatchery_issue_count": 0,
                "nests_ok": True,
                "nests_title": "All 1 Nest(s) OK",
                "nests_dot": "green",
                "nest_total": 1,
                "nest_unreachable": 0,
                "nest_alert_count": 0,
                "library_enabled": True,
                "libraries_visible": True,
                "libraries_ok": True,
                "libraries_title": "No Library connections",
                "libraries_dot": "muted",
                "library_connection_total": 0,
                "library_alert_count": 0,
            },
        ):
            html = client.get("/").data.decode()
        assert "Libraries</span>" in html
        assert "No Library connections" in html
        open_tag = html.split('id="footer-libraries"', 1)[1].split(">", 1)[0]
        assert "hidden" not in open_tag

    def test_libraries_chip_hidden_when_disabled(self, client):
        with patch(
            "lib.plane_status.footer_status",
            return_value={
                "hatchery_ok": True,
                "hatchery_title": "Hatchery Controller OK",
                "hatchery_dot": "green",
                "hatchery_issue_count": 0,
                "nests_ok": True,
                "nests_title": "All 1 Nest(s) OK",
                "nests_dot": "green",
                "nest_total": 1,
                "nest_unreachable": 0,
                "nest_alert_count": 0,
                **self._LIBRARIES_OFF,
            },
        ):
            html = client.get("/").data.decode()
        open_tag = html.split('id="footer-libraries"', 1)[1].split(">", 1)[0]
        assert "hidden" in open_tag

    def test_api_plane_status(self, client):
        resp = client.get("/api/plane-status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "hatchery_dot" in data
        assert "nests_dot" in data
        assert "libraries_visible" in data
        assert "libraries_dot" in data
        assert data["hatchery_dot"] in ("green", "red")
        assert data["nests_dot"] in ("green", "red", "muted")
        assert data["libraries_dot"] in ("green", "red", "muted")
        assert isinstance(data["libraries_visible"], bool)

    def test_status_present_on_all_panes(self, client):
        for path in [
            "/",
            "/nests",
            "/clutches",
            "/automation/scripts",
            "/settings/general",
            "/settings/security",
            "/settings/display",
            "/hatch-clutch",
            "/build",
            "/notifications/alerts",
            "/notifications/events",
        ]:
            html = client.get(path).data.decode()
            assert "nest-status" in html, f"Expected nest status on {path}"
            assert "Hatchery" in html
            assert "Nests" in html
            assert "footer-hatchery" in html
            assert "footer-nests" in html
            assert "footer-libraries" in html
            # Libraries chip is in the DOM but hidden when Library is off.
            assert 'id="footer-libraries"' in html


class TestRequirementsSync:
    def test_records_alert_for_missing_controller_tool(self):
        with patch(
            "lib.requirements.check_controller",
            return_value=[
                Requirement(
                    "ssh",
                    "openssh-client",
                    "Nest transport client for Remote Nests",
                    False,
                    role="controller",
                    install_hint="sudo apt install openssh-client",
                )
            ],
        ):
            app_module._sync_requirements()
        alerts = [n for n in alerts_lib.list_recent() if n["tier"] == "alert"]
        assert any(
            "ssh" in a["message"] and "Controller requirement:" in a["message"] for a in alerts
        )

    def test_no_alerts_when_all_tools_present(self):
        with patch(
            "lib.requirements.check_controller",
            return_value=[
                Requirement("ssh", "openssh-client", "ops", True, role="controller"),
            ],
        ):
            app_module._sync_requirements()
        assert alerts_lib.count_active_alerts() == 0

    def test_resolves_legacy_nest_tool_alerts(self):
        alerts_lib.record_alert("Missing requirement: 'virsh' is not installed — VM lifecycle")
        assert alerts_lib.count_active_alerts() == 1
        with patch("lib.requirements.check_controller", return_value=[]):
            app_module._sync_requirements()
        assert alerts_lib.count_active_alerts() == 0

    def test_resolves_stale_alert_when_tool_now_present(self):
        alerts_lib.record_alert(
            "Controller requirement: 'ssh' is not installed — Nest transport client for Remote Nests"
        )
        assert alerts_lib.count_active_alerts() == 1
        with patch(
            "lib.requirements.check_controller",
            return_value=[
                Requirement(
                    "ssh",
                    "openssh-client",
                    "Nest transport client for Remote Nests",
                    True,
                    role="controller",
                )
            ],
        ):
            app_module._sync_requirements()
        assert alerts_lib.count_active_alerts() == 0

    def test_does_not_duplicate_alert_on_repeated_calls(self):
        missing = [
            Requirement(
                "ssh",
                "openssh-client",
                "Nest transport client for Remote Nests",
                False,
                role="controller",
                install_hint="sudo apt install openssh-client",
            )
        ]
        with patch("lib.requirements.check_controller", return_value=missing):
            app_module._sync_requirements()
            app_module._sync_requirements()
            app_module._sync_requirements()
        warnings = [
            n for n in alerts_lib.list_recent() if n["tier"] == "alert" and n["resolved"] == 0
        ]
        assert len(warnings) == 1

    def test_optional_pwsh_does_not_alert(self):
        with patch(
            "lib.requirements.check_controller",
            return_value=[
                Requirement(
                    "pwsh", "powershell", "scripts", False, optional=True, role="controller"
                ),
            ],
        ):
            app_module._sync_requirements()
        assert alerts_lib.count_active_alerts() == 0


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
        alerts = [
            n for n in alerts_lib.list_recent() if n["tier"] == "alert" and n["resolved"] == 0
        ]
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
        alerts = [
            n for n in alerts_lib.list_recent() if n["tier"] == "alert" and n["resolved"] == 0
        ]
        msg = next(a["message"] for a in alerts if "bad.yaml" in a["message"])
        assert "Circular dependency" in msg
        assert msg.count("bad.yaml") == 1
        assert "Value error" not in msg

    def test_no_alert_for_valid_clutch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        _make_clutch(tmp_path)
        app_module._sync_clutches()
        assert alerts_lib.count_active_alerts() == 0

    def test_resolves_stale_alert_when_clutch_fixed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        alerts_lib.record_alert("Invalid Clutch file: 'my-lab.yaml' — some old error")
        assert alerts_lib.count_active_alerts() == 1
        _make_clutch(tmp_path)
        app_module._sync_clutches()
        assert alerts_lib.count_active_alerts() == 0

    def test_does_not_duplicate_alert_on_repeated_calls(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        clutches_dir = tmp_path / "clutches"
        clutches_dir.mkdir()
        (clutches_dir / "bad.yaml").write_text("not: valid: clutch: [")
        app_module._sync_clutches()
        app_module._sync_clutches()
        app_module._sync_clutches()
        active = [
            n for n in alerts_lib.list_recent() if n["tier"] == "alert" and n["resolved"] == 0
        ]
        assert len(active) == 1

    def test_noop_when_clutches_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        app_module._sync_clutches()
        assert alerts_lib.count_active_alerts() == 0


class TestAlertsRoute:
    def test_parent_redirects_to_alerts(self, client):
        resp = client.get("/notifications")
        assert resp.status_code == 302
        assert "/notifications/alerts" in resp.headers["Location"]

    def test_alerts_returns_200(self, client):
        assert client.get("/notifications/alerts").status_code == 200

    def test_shows_recorded_alert(self, client):
        alerts_lib.record_alert("test alert message")
        html = client.get("/notifications/alerts").data.decode()
        assert "test alert message" in html

    def test_shows_empty_state_when_no_items(self, client):
        html = client.get("/notifications/alerts").data.decode()
        assert "No alerts yet" in html
        assert 'id="alert-empty"' in html

    def test_shows_active_status(self, client):
        alerts_lib.record_alert("an environment alert")
        html = client.get("/notifications/alerts").data.decode()
        assert "notif-status-badge--active" in html

    def test_subscribes_to_status_tick(self, client):
        html = client.get("/notifications/alerts").data.decode()
        assert "alert-tbody" in html
        assert "hatchery.onStatusTick" in html
        assert html.index("app.js") < html.index("hatchery.onStatusTick")


class TestValidatorsPane:
    def test_pane_renders(self, client):
        html = client.get("/notifications/validators").data.decode()
        assert "Validators" in html
        assert "validator-runs-tbody" in html
        assert "hatchery.onStatusTick" in html
        assert "validator-filter-id" in html
        assert "validator-filter-status" in html
        assert "validator-filter-tier" in html
        # Pane script must load after app.js via scripts block (not content).
        assert html.index("app.js") < html.index("hatchery.onStatusTick")

    def test_api_lists_runs(self, client):
        from lib.validators.runs import record_run

        record_run(
            validator_id="clutch_files",
            status="ok",
            message="ok",
            trigger="manual",
        )
        data = client.get("/api/validators/runs").get_json()
        assert "runs" in data
        assert any(r["validator_id"] == "clutch_files" for r in data["runs"])

    def test_api_filters_status_and_tier(self, client):
        from lib.validators.runs import record_run

        record_run(
            validator_id="clutch_files",
            status="findings",
            message="has findings",
            tier="warning",
            findings_count=1,
            trigger="manual",
        )
        data = client.get("/api/validators/runs?status=findings&tier=warning").get_json()
        assert len(data["runs"]) == 1
        assert data["runs"][0]["status"] == "findings"


class TestEventsRoute:
    def test_returns_200(self, client):
        assert client.get("/notifications/events").status_code == 200

    def test_shows_events_layout(self, client):
        html = client.get("/notifications/events").data.decode()
        assert 'class="list-shell"' in html
        assert 'id="events-filter-vm"' in html
        assert 'id="events-table"' in html
        assert "events-nav" not in html
        assert "Events content coming soon" not in html


class TestApiVmEvents:
    def test_returns_events_for_vm(self, client):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_event(sid, "dc01", "hatchery", "INFO", "Creating VM")
        hatch_lib.add_event(
            sid,
            "dc01",
            "script",
            "WARN",
            "Almost done",
            script_name="setup.ps1",
            component="Timezone",
        )
        resp = client.get(f"/api/sessions/{sid}/vms/dc01/events")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "events" in data
        assert len(data["events"]) == 2
        assert data["events"][0]["message"] == "Creating VM"
        assert data["events"][0]["context"] == "hatchery"
        assert data["events"][1]["level"] == "WARN"
        assert data["events"][1]["script_name"] == "setup.ps1"
        assert data["events"][1]["component"] == "Timezone"

    def test_returns_empty_list_when_no_events(self, client):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        data = client.get(f"/api/sessions/{sid}/vms/dc01/events").get_json()
        assert data == {"events": []}


class TestBackgroundThread:
    def test_loop_calls_hatch_sync_on_timeout(self):
        stop = MagicMock()
        stop.wait.side_effect = [False, True]
        with patch.object(app_module, "_sync_hatch_status") as mock_hatch:
            app_module._background_loop(stop)
        mock_hatch.assert_called_once()

    def test_loop_calls_hatch_sync_multiple_ticks(self):
        stop = MagicMock()
        stop.wait.side_effect = [False, False, False, True]
        with patch.object(app_module, "_sync_hatch_status") as mock_hatch:
            app_module._background_loop(stop)
        assert mock_hatch.call_count == 3

    def test_loop_exits_without_sync_when_stopped_immediately(self):
        stop = MagicMock()
        stop.wait.return_value = True
        with patch.object(app_module, "_sync_hatch_status") as mock_hatch:
            app_module._background_loop(stop)
        mock_hatch.assert_not_called()

    def test_start_background_thread_spawns_daemon_thread(self):
        with patch("threading.Thread") as mock_thread_cls:
            mock_t = MagicMock()
            mock_thread_cls.return_value = mock_t
            stop = app_module._start_background_thread()
        assert mock_thread_cls.call_args.kwargs.get("daemon") is True
        mock_t.start.assert_called_once()
        assert isinstance(stop, threading.Event)


class TestApiImport:
    def test_import_clutch_yaml(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        data = {"files": (io.BytesIO(b"name: lab\nvms: []\n"), "lab.yaml")}
        resp = client.post(
            "/api/import/clutches",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["imported"] == ["lab.yaml"]
        assert (tmp_path / "clutches" / "lab.yaml").is_file()
        html = client.get("/clutches").data.decode()
        assert "lab.yaml" in html
        assert 'id="clutch-import-btn"' in html

    def test_import_conflict_returns_error(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        iso_dir = tmp_path / "media" / "iso"
        iso_dir.mkdir(parents=True)
        (iso_dir / "win.iso").write_bytes(b"old")
        resp = client.post(
            "/api/import/media/iso",
            data={"files": (io.BytesIO(b"new"), "win.iso")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["imported"] == []
        assert body["errors"][0]["reason"] == "already exists (refuse overwrite)"
        assert (iso_dir / "win.iso").read_bytes() == b"old"

    def test_media_and_scripts_pages_have_import(self, client):
        assert 'id="media-import-btn"' in client.get("/media/iso").data.decode()
        assert 'id="media-import-btn"' in client.get("/media/virtio").data.decode()
        assert 'id="scripts-import-btn"' in client.get("/automation/scripts").data.decode()

    def test_import_requires_files(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        resp = client.post("/api/import/automation/scripts", data={})
        assert resp.status_code == 400


class TestApiInventoryDelete:
    def test_delete_media_iso(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        iso_dir = tmp_path / "media" / "iso"
        iso_dir.mkdir(parents=True)
        (iso_dir / "win.iso").write_bytes(b"iso")
        resp = client.post("/api/media/iso/win.iso/delete")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert not (iso_dir / "win.iso").exists()

    def test_delete_media_virtio(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        virtio_dir = tmp_path / "media" / "virtio"
        virtio_dir.mkdir(parents=True)
        (virtio_dir / "virtio.iso").write_bytes(b"v")
        resp = client.post("/api/media/virtio/virtio.iso/delete")
        assert resp.status_code == 200
        assert not (virtio_dir / "virtio.iso").exists()

    def test_delete_script(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        scripts = tmp_path / "automation" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "setup.ps1").write_text("Write-Host hi\n")
        resp = client.post("/api/automation/scripts/setup.ps1/delete")
        assert resp.status_code == 200
        assert not (scripts / "setup.ps1").exists()

    def test_delete_missing_returns_404(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "media" / "iso").mkdir(parents=True)
        assert client.post("/api/media/iso/missing.iso/delete").status_code == 404

    def test_delete_rejects_path_traversal(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        outside = tmp_path / "secret.txt"
        outside.write_text("nope")
        (tmp_path / "automation" / "scripts").mkdir(parents=True)
        resp = client.post("/api/automation/scripts/../secret.txt/delete")
        assert resp.status_code == 404
        assert outside.exists()

    def test_inventory_pages_have_delete_controls(self, client):
        iso_html = client.get("/media/iso").data.decode()
        assert 'id="media-delete-btn"' in iso_html
        assert 'id="delete-modal-backdrop"' in iso_html
        scripts_html = client.get("/automation/scripts").data.decode()
        assert 'id="scripts-delete-btn"' in scripts_html
        assert 'id="delete-modal-backdrop"' in scripts_html


class TestAlertsAPI:
    def test_returns_200(self, client):
        assert client.get("/api/alerts").status_code == 200

    def test_response_is_json(self, client):
        resp = client.get("/api/alerts")
        assert resp.content_type == "application/json"

    def test_has_items_key(self, client):
        data = client.get("/api/alerts").get_json()
        assert "items" in data

    def test_has_active_alert_count_key(self, client):
        data = client.get("/api/alerts").get_json()
        assert "active_alert_count" in data

    def test_items_contains_recorded_alert(self, client):
        alerts_lib.record_alert("api test message")
        data = client.get("/api/alerts").get_json()
        assert any(item["message"] == "api test message" for item in data["items"])

    def test_alert_count_reflects_active(self, client):
        alerts_lib.record_alert("Missing requirement: some tool")
        data = client.get("/api/alerts").get_json()
        assert data["active_alert_count"] >= 1

    def test_limit_query_caps_items(self, client):
        for i in range(5):
            alerts_lib.record_alert(f"limit-test-{i}")
        data = client.get("/api/alerts?limit=2").get_json()
        assert len(data["items"]) == 2
        data500 = client.get("/api/alerts?limit=500").get_json()
        assert len(data500["items"]) >= 5


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

    def test_api_script_params_returns_empty_when_pwsh_missing(self, client, tmp_path, monkeypatch):
        from unittest.mock import patch

        scripts_dir = tmp_path / "automation" / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "setup.ps1").write_text("param($Env) Write-Host $Env")
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        with patch("shutil.which", return_value=None):
            resp = client.get("/api/automation/scripts/setup.ps1/params")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_api_script_params_returns_404_when_file_missing(self, client, tmp_path, monkeypatch):
        from unittest.mock import patch

        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        with patch("shutil.which", return_value="/usr/bin/pwsh"):
            resp = client.get("/api/automation/scripts/nonexistent.ps1/params")
        assert resp.status_code == 404

    def test_api_script_params_rejects_path_traversal(self, client, tmp_path, monkeypatch):
        from unittest.mock import patch

        (tmp_path / "automation" / "scripts").mkdir(parents=True)
        (tmp_path / "secret.ps1").write_text("Write-Host leaked")
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        with patch("shutil.which", return_value="/usr/bin/pwsh"):
            resp = client.get("/api/automation/scripts/../secret.ps1/params")
        assert resp.status_code == 404

    def test_api_clutches_returns_json(self, client):
        resp = client.get("/api/clutches")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)


class TestAutomationScriptsPane:
    def test_page_lists_scripts_and_metadata(self, client, tmp_path, monkeypatch):
        scripts = tmp_path / "automation" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "setup.ps1").write_text("Write-Host hi")
        (scripts / "bootstrap.sh").write_text("#!/bin/sh\necho hi")
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)

        html = client.get("/automation/scripts").data.decode()
        assert "setup.ps1" in html
        assert "bootstrap.sh" in html
        assert "PowerShell" in html
        assert "Shell" in html
        assert "automation/scripts/setup.ps1" in html
        assert "scripts-layout" in html
        assert 'aria-label="Filter Cached scripts"' in html
        assert 'id="scripts-filter-q"' in html
        assert 'id="scripts-filter-language"' in html
        assert 'id="scripts-filter-state"' in html
        assert "scripts-nav-filtered-empty" in html
        assert 'aria-label="Copy"' in html
        assert 'id="scripts-copy-path-item">Path</button>' in html
        assert 'id="scripts-copy-content-item"' in html
        assert ">Contents</button>" in html
        assert "scripts-nav-drift-icon" in html
        assert "hatchery.onStatusTick" in html
        assert "applyScriptFilters" in html

    def test_page_shows_used_by_from_clutch_string_and_object(self, client, tmp_path, monkeypatch):
        scripts = tmp_path / "automation" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "setup.ps1").write_text("Write-Host hi")
        (scripts / "configure.ps1").write_text("Write-Host cfg")
        clutches = tmp_path / "clutches"
        clutches.mkdir(parents=True)
        clutch = Clutch(
            name="Lab",
            vms=[
                VMConfig(
                    name="dc01",
                    os="win11",
                    vcpus=2,
                    ram_gb=4,
                    disk_gb=60,
                    os_media="win11.iso",
                    automations=["setup.ps1", {"name": "configure.ps1", "reboot_after": True}],
                )
            ],
        )
        clutch_lib.save(clutch, clutches / "lab.yaml")
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)

        html = client.get("/automation/scripts").data.decode()
        assert '"setup.ps1"' in html or "setup.ps1" in html
        # used_by embedded as JSON for the client
        assert "lab.yaml" in html
        assert "dc01" in html

    def test_empty_state_when_no_scripts(self, client, tmp_path, monkeypatch):
        (tmp_path / "automation" / "scripts").mkdir(parents=True)
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        html = client.get("/automation/scripts").data.decode()
        assert "No scripts found" in html
        assert "automation/scripts/" in html

    def test_content_api_returns_script_text(self, client, tmp_path, monkeypatch):
        scripts = tmp_path / "automation" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "setup.ps1").write_text("Write-Host hello")
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)

        resp = client.get("/api/automation/scripts/setup.ps1/content")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "setup.ps1"
        assert data["content"] == "Write-Host hello"

    def test_content_api_404_when_missing(self, client, tmp_path, monkeypatch):
        (tmp_path / "automation" / "scripts").mkdir(parents=True)
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        resp = client.get("/api/automation/scripts/missing.ps1/content")
        assert resp.status_code == 404

    def test_content_api_rejects_path_traversal(self, client, tmp_path, monkeypatch):
        (tmp_path / "automation" / "scripts").mkdir(parents=True)
        (tmp_path / "outside.ps1").write_text("secret")
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        resp = client.get("/api/automation/scripts/../outside.ps1/content")
        assert resp.status_code == 404

    def test_content_api_rejects_oversized_file(self, client, tmp_path, monkeypatch):
        scripts = tmp_path / "automation" / "scripts"
        scripts.mkdir(parents=True)
        big = scripts / "huge.ps1"
        big.write_bytes(b"x" * (app_module._SCRIPT_CONTENT_MAX_BYTES + 1))
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        resp = client.get("/api/automation/scripts/huge.ps1/content")
        assert resp.status_code == 413

    def test_script_used_by_helper_maps_references(self, tmp_path, monkeypatch):
        scripts = tmp_path / "automation" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "setup.ps1").write_text("x")
        clutches = tmp_path / "clutches"
        clutches.mkdir(parents=True)
        clutch_lib.save(
            Clutch(
                name="Lab",
                vms=[
                    VMConfig(
                        name="web01",
                        os="win11",
                        vcpus=2,
                        ram_gb=4,
                        disk_gb=40,
                        os_media="win.iso",
                        automations=["setup.ps1"],
                    )
                ],
            ),
            clutches / "lab.yaml",
        )
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        usage = app_module._script_used_by()
        assert usage["setup.ps1"] == [{"clutch": "lab.yaml", "clutch_name": "Lab", "vm": "web01"}]


class TestMediaPanes:
    def test_iso_page_lists_files(self, client, tmp_path, monkeypatch):
        iso_dir = tmp_path / "media" / "iso"
        iso_dir.mkdir(parents=True)
        (iso_dir / "win11.iso").write_bytes(b"iso-bytes")
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)

        html = client.get("/media/iso").data.decode()
        assert "win11.iso" in html
        assert "media/iso/win11.iso" in html
        assert "media-layout" in html
        assert 'aria-label="Copy"' in html
        assert 'id="media-copy-path-item">Path</button>' in html
        assert "media-copy-content-item" not in html
        assert "media-nav-drift-icon" in html
        assert 'id="media-library-status-btn"' in html
        assert 'aria-label="Filter Cached ISO"' in html or "Filter Cached" in html
        assert 'id="media-filter-q"' in html
        assert 'id="media-filter-state"' in html
        assert "hatchery.onStatusTick" in html
        assert "refreshDriftInventory" in html
        assert "applyMediaFilters" in html

    def test_virtio_empty_state(self, client, tmp_path, monkeypatch):
        (tmp_path / "media" / "virtio").mkdir(parents=True)
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        html = client.get("/media/virtio").data.decode()
        assert "No files found" in html
        assert "media/virtio/" in html

    def test_iso_used_by_embedded(self, client, tmp_path, monkeypatch):
        iso_dir = tmp_path / "media" / "iso"
        iso_dir.mkdir(parents=True)
        (iso_dir / "win11.iso").write_bytes(b"x")
        clutches = tmp_path / "clutches"
        clutches.mkdir(parents=True)
        clutch_lib.save(
            Clutch(
                name="Lab",
                vms=[
                    VMConfig(
                        name="dc01",
                        os="win11",
                        vcpus=2,
                        ram_gb=4,
                        disk_gb=60,
                        os_media="win11.iso",
                    )
                ],
            ),
            clutches / "lab.yaml",
        )
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        html = client.get("/media/iso").data.decode()
        assert "lab.yaml" in html
        assert "dc01" in html

    def test_inspect_api_returns_probe(self, client, tmp_path, monkeypatch):
        iso_dir = tmp_path / "media" / "iso"
        iso_dir.mkdir(parents=True)
        (iso_dir / "win11.iso").write_bytes(b"not-a-real-iso")
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)

        with patch(
            "lib.media_inspect.probe_iso",
            return_value={
                "available": True,
                "volume_id": "TEST_VOL",
                "publisher": "MICROSOFT CORPORATION",
                "app_id": "CDIMAGE 2.56",
                "created_at": "2025-09-16 00:00:00",
                "boot": "BIOS, UEFI",
                "backend": "pycdlib",
                "error": None,
            },
        ):
            resp = client.get("/api/media/iso/win11.iso/inspect")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "win11.iso"
        assert data["probe"]["volume_id"] == "TEST_VOL"
        assert data["probe"]["boot"] == "BIOS, UEFI"
        assert data["probe"]["backend"] == "pycdlib"
        assert data["size_bytes"] == len(b"not-a-real-iso")

    def test_inspect_api_404_and_traversal(self, client, tmp_path, monkeypatch):
        (tmp_path / "media" / "iso").mkdir(parents=True)
        (tmp_path / "outside.iso").write_bytes(b"secret")
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        assert client.get("/api/media/iso/missing.iso/inspect").status_code == 404
        assert client.get("/api/media/iso/../outside.iso/inspect").status_code == 404

    def test_virtio_inspect_api(self, client, tmp_path, monkeypatch):
        virtio = tmp_path / "media" / "virtio"
        virtio.mkdir(parents=True)
        (virtio / "virtio-win.iso").write_bytes(b"virtio")
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        with patch(
            "lib.media_inspect.probe_iso",
            return_value={
                "available": False,
                "volume_id": None,
                "publisher": None,
                "app_id": None,
                "created_at": None,
                "boot": None,
                "backend": None,
                "error": "not a valid ISO",
            },
        ):
            resp = client.get("/api/media/virtio/virtio-win.iso/inspect")
        assert resp.status_code == 200
        assert resp.get_json()["probe"]["error"] == "not a valid ISO"


# ── settings show_passwords ───────────────────────────────────────────────────


class TestSettingsShowPasswords:
    def test_post_saves_show_passwords_true_when_checked(self, client, tmp_path, monkeypatch):
        saved = {}
        monkeypatch.setattr(cfg, "get", lambda: {"data_dir": str(tmp_path), "bg_interval": 60})
        monkeypatch.setattr(cfg, "save", lambda c: saved.update(c))
        client.post(
            "/settings/security",
            data={"show_passwords": "on", "nest_ssh_identities": "[]"},
        )
        assert saved["show_passwords"] is True
        assert saved["data_dir"] == str(tmp_path)

    def test_post_saves_show_passwords_false_when_unchecked(self, client, tmp_path, monkeypatch):
        saved = {}
        monkeypatch.setattr(
            cfg,
            "get",
            lambda: {"data_dir": str(tmp_path), "bg_interval": 60, "show_passwords": True},
        )
        monkeypatch.setattr(cfg, "save", lambda c: saved.update(c))
        client.post("/settings/security", data={"nest_ssh_identities": "[]"})
        assert saved["show_passwords"] is False

    def test_get_shows_show_passwords_checkbox(self, client):
        html = client.get("/settings/security").data.decode()
        assert "show_passwords" in html

    def test_get_checkbox_checked_when_setting_true(self, client, monkeypatch):
        monkeypatch.setattr(
            cfg,
            "get",
            lambda: {"data_dir": "/some/path", "bg_interval": 60, "show_passwords": True},
        )
        html = client.get("/settings/security").data.decode()
        assert 'name="show_passwords"' in html
        assert "checked" in html


# ── api_nest_vms ──────────────────────────────────────────────────────────────


class TestApiNestVms:
    def _mock_provider(self, vms=None, ip=None, tag=None):
        mock = MagicMock()
        mock.list_vms.return_value = vms or []
        mock.get_vm_ip.return_value = ip
        mock.get_vm_session_tag.return_value = tag
        return mock

    def test_returns_200_with_empty_list(self, client):
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value = self._mock_provider()
            resp = client.get("/api/nests/local/vms")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_returns_vm_name_and_status(self, client):
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value = self._mock_provider(
                vms=[{"name": "dc01", "status": "running"}]
            )
            resp = client.get("/api/nests/local/vms")
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["name"] == "dc01"
        assert data[0]["status"] == "running"

    def test_includes_ip_when_available(self, client):
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value = self._mock_provider(
                vms=[{"name": "dc01", "status": "running"}],
                ip="192.168.122.10",
            )
            resp = client.get("/api/nests/local/vms")
        data = resp.get_json()
        assert data[0]["ip"] == "192.168.122.10"

    def test_ip_is_none_when_unavailable(self, client):
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value = self._mock_provider(
                vms=[{"name": "dc01", "status": "shut off"}], ip=None
            )
            resp = client.get("/api/nests/local/vms")
        data = resp.get_json()
        assert data[0]["ip"] is None

    def test_includes_session_and_clutch_from_tag(self, client):
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value = self._mock_provider(
                vms=[{"name": "dc01", "status": "running"}],
                tag={"session_id": "abc-123", "clutch_file": "lab.yaml"},
            )
            resp = client.get("/api/nests/local/vms")
        data = resp.get_json()
        assert data[0]["session_id"] == "abc-123"
        assert data[0]["clutch_file"] == "lab.yaml"

    def test_session_and_clutch_null_when_untagged(self, client):
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value = self._mock_provider(
                vms=[{"name": "dc01", "status": "running"}], tag=None
            )
            resp = client.get("/api/nests/local/vms")
        data = resp.get_json()
        assert data[0]["session_id"] is None
        assert data[0]["clutch_file"] is None

    def test_includes_hatch_status_when_tagged(self, client):
        import lib.hatch as hatch_lib

        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.set_vm_status(sid, "dc01", "provisioning")

        with patch("hatchery._provider") as mock_prov:
            prov = self._mock_provider(
                vms=[{"name": "dc01", "status": "running"}],
                tag={"session_id": sid, "clutch_file": "lab.yaml"},
            )
            mock_prov.return_value = prov
            resp = client.get("/api/nests/local/vms")
        data = resp.get_json()
        assert data[0]["hatch_status"] == "provisioning"

    def test_hatch_status_null_when_untagged(self, client):
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value = self._mock_provider(
                vms=[{"name": "dc01", "status": "running"}], tag=None
            )
            resp = client.get("/api/nests/local/vms")
        data = resp.get_json()
        assert data[0]["hatch_status"] is None

    def test_includes_db_credentials_when_tagged(self, client):
        import lib.hatch as hatch_lib

        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01", admin_username="alice", admin_password="s3cr3t")

        with patch("hatchery._provider") as mock_prov:
            prov = self._mock_provider(
                vms=[{"name": "dc01", "status": "running"}],
                tag={"session_id": sid, "clutch_file": "lab.yaml"},
            )
            mock_prov.return_value = prov
            with patch.object(cfg, "show_passwords", return_value=True):
                resp = client.get("/api/nests/local/vms")
        data = resp.get_json()
        assert data[0]["admin_username"] == "alice"
        assert data[0]["admin_password"] == "s3cr3t"

    def test_password_hidden_when_show_passwords_false(self, client):
        import lib.hatch as hatch_lib

        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01", admin_username="alice", admin_password="s3cr3t")

        with patch("hatchery._provider") as mock_prov:
            prov = self._mock_provider(
                vms=[{"name": "dc01", "status": "running"}],
                tag={"session_id": sid, "clutch_file": "lab.yaml"},
            )
            mock_prov.return_value = prov
            with patch.object(cfg, "show_passwords", return_value=False):
                resp = client.get("/api/nests/local/vms")
        data = resp.get_json()
        assert data[0]["admin_username"] == "alice"
        assert data[0]["admin_password"] is None

    def test_ip_exception_does_not_crash(self, client):
        with patch("hatchery._provider") as mock_prov:
            prov = self._mock_provider(vms=[{"name": "dc01", "status": "running"}])
            prov.get_vm_ip.side_effect = Exception("network error")
            mock_prov.return_value = prov
            resp = client.get("/api/nests/local/vms")
        assert resp.status_code == 200
        assert resp.get_json()[0]["ip"] is None

    def test_tag_exception_does_not_crash(self, client):
        with patch("hatchery._provider") as mock_prov:
            prov = self._mock_provider(vms=[{"name": "dc01", "status": "running"}])
            prov.get_vm_session_tag.side_effect = Exception("metadata error")
            mock_prov.return_value = prov
            resp = client.get("/api/nests/local/vms")
        assert resp.status_code == 200
        assert resp.get_json()[0]["session_id"] is None

    def test_scripts_included_when_tagged(self, client):
        import lib.hatch as hatch_lib

        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")

        class _S:
            def __init__(self, name):
                self.name = name
                self.reboot_after = False

        hatch_lib.add_vm_scripts(sid, "dc01", [_S("setup.ps1")])

        with patch("hatchery._provider") as mock_prov:
            prov = self._mock_provider(
                vms=[{"name": "dc01", "status": "running"}],
                tag={"session_id": sid, "clutch_file": "lab.yaml"},
            )
            mock_prov.return_value = prov
            resp = client.get("/api/nests/local/vms")
        data = resp.get_json()
        assert data[0]["scripts"][0]["script_name"] == "setup.ps1"

    def test_scripts_empty_when_untagged(self, client):
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value = self._mock_provider(
                vms=[{"name": "dc01", "status": "running"}], tag=None
            )
            resp = client.get("/api/nests/local/vms")
        assert resp.get_json()[0]["scripts"] == []

    def test_scripts_include_last_event_from_hatch_events(self, client):
        import lib.hatch as hatch_lib

        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")

        class _S:
            def __init__(self, name):
                self.name = name
                self.reboot_after = False

        hatch_lib.add_vm_scripts(sid, "dc01", [_S("setup.ps1")])
        hatch_lib.set_script_status(sid, "dc01", 0, "succeeded", exit_code=0, output="raw line\n")
        hatch_lib.add_event(
            sid, "dc01", "script", "INFO", "Setting timezone", script_name="setup.ps1"
        )
        hatch_lib.add_event(
            sid, "dc01", "script", "INFO", "Rename complete", script_name="setup.ps1"
        )

        with patch("hatchery._provider") as mock_prov:
            prov = self._mock_provider(
                vms=[{"name": "dc01", "status": "running"}],
                tag={"session_id": sid, "clutch_file": "lab.yaml"},
            )
            mock_prov.return_value = prov
            resp = client.get("/api/nests/local/vms")
        script = resp.get_json()[0]["scripts"][0]
        assert script["last_event"] == "Rename complete"

    def test_last_event_null_when_no_script_events(self, client):
        import lib.hatch as hatch_lib

        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")

        class _S:
            def __init__(self, name):
                self.name = name
                self.reboot_after = False

        hatch_lib.add_vm_scripts(sid, "dc01", [_S("setup.ps1")])
        hatch_lib.add_event(sid, "dc01", "hatchery", "INFO", "lifecycle only")

        with patch("hatchery._provider") as mock_prov:
            prov = self._mock_provider(
                vms=[{"name": "dc01", "status": "running"}],
                tag={"session_id": sid, "clutch_file": "lab.yaml"},
            )
            mock_prov.return_value = prov
            resp = client.get("/api/nests/local/vms")
        assert resp.get_json()[0]["scripts"][0]["last_event"] is None


# ── api_retry_vm ──────────────────────────────────────────────────────────────


class TestApiRetryVm:
    def _setup_failed_vm(self, tmp_path):
        import lib.hatch as hatch_lib

        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01", admin_username="admin", admin_password="pass")

        class _S:
            def __init__(self, name):
                self.name = name
                self.reboot_after = False

        hatch_lib.add_vm_scripts(sid, "dc01", [_S("setup.ps1")])
        hatch_lib.set_vm_status(sid, "dc01", "failed")
        return sid

    def test_returns_404_for_unknown_vm(self, client):
        resp = client.post("/api/sessions/no-such/vms/dc01/retry")
        assert resp.status_code == 404

    def test_returns_409_when_vm_not_failed(self, client):
        import lib.hatch as hatch_lib

        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        resp = client.post(f"/api/sessions/{sid}/vms/dc01/retry")
        assert resp.status_code == 409

    def test_resets_scripts_and_sets_provisioning(self, client, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib

        sid = self._setup_failed_vm(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_ip.return_value = None
            resp = client.post(f"/api/sessions/{sid}/vms/dc01/retry")
        assert resp.status_code == 200
        rec = hatch_lib.get_vm_record(sid, "dc01")
        assert rec["status"] == "provisioning"
        scripts = hatch_lib.get_vm_scripts(sid, "dc01")
        assert scripts[0]["status"] == "pending"

    def test_spawns_thread_when_winrm_reachable(self, client, tmp_path):
        sid = self._setup_failed_vm(tmp_path)
        spawned = []
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_ip.return_value = "192.168.1.10"
            with patch("hatchery._check_winrm", return_value=True):
                with patch(
                    "hatchery._spawn_provision_thread",
                    side_effect=lambda *a, **kw: spawned.append(a),
                ):
                    resp = client.post(f"/api/sessions/{sid}/vms/dc01/retry")
        assert resp.status_code == 200
        assert resp.get_json()["queued"] is True
        assert len(spawned) == 1

    def test_queued_false_when_vm_unreachable(self, client, tmp_path):
        sid = self._setup_failed_vm(tmp_path)
        with patch("hatchery._provider") as mock_prov:
            mock_prov.return_value.get_vm_ip.return_value = None
            resp = client.post(f"/api/sessions/{sid}/vms/dc01/retry")
        assert resp.get_json()["queued"] is False


# ── _provision_vm_thread ──────────────────────────────────────────────────────


class TestProvisionVmThread:
    def _setup(self, tmp_path):
        import lib.hatch as hatch_lib

        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01", admin_username="admin", admin_password="pass")
        return sid

    def _script(self, tmp_path, name="setup.ps1"):
        (tmp_path / "automation" / "scripts").mkdir(parents=True, exist_ok=True)
        p = tmp_path / "automation" / "scripts" / name
        p.write_text("echo hi")
        return name

    def test_sets_fledged_on_all_success(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib
        import lib.config as cfg
        import hatchery as app_module

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup(tmp_path)
        script_name = self._script(tmp_path)

        class _S:
            name = script_name
            reboot_after = False

        hatch_lib.add_vm_scripts(sid, "dc01", [_S()])
        hatch_lib.set_vm_status(sid, "dc01", "provisioning")

        with patch("hatchery.provision_lib.run_script", return_value=(0, "ok")):
            with patch("hatchery._provider"):
                app_module._provision_vm_thread(sid, "dc01", "192.168.1.1", "admin", "pass")

        assert hatch_lib.get_vm_record(sid, "dc01")["status"] == "fledged"
        assert hatch_lib.get_vm_scripts(sid, "dc01")[0]["status"] == "succeeded"

    def test_sets_failed_on_nonzero_exit(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib
        import lib.config as cfg
        import hatchery as app_module

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup(tmp_path)
        script_name = self._script(tmp_path)

        class _S:
            name = script_name
            reboot_after = False

        hatch_lib.add_vm_scripts(sid, "dc01", [_S()])
        hatch_lib.set_vm_status(sid, "dc01", "provisioning")

        with patch("hatchery.provision_lib.run_script", return_value=(1, "error")):
            with patch("hatchery._provider"):
                app_module._provision_vm_thread(sid, "dc01", "192.168.1.1", "admin", "pass")

        assert hatch_lib.get_vm_record(sid, "dc01")["status"] == "failed"
        assert hatch_lib.get_vm_scripts(sid, "dc01")[0]["status"] == "failed"

    def test_skips_remaining_scripts_on_failure(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib
        import lib.config as cfg
        import hatchery as app_module

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup(tmp_path)
        self._script(tmp_path, "a.ps1")
        self._script(tmp_path, "b.ps1")

        class _A:
            name = "a.ps1"
            reboot_after = False

        class _B:
            name = "b.ps1"
            reboot_after = False

        hatch_lib.add_vm_scripts(sid, "dc01", [_A(), _B()])
        hatch_lib.set_vm_status(sid, "dc01", "provisioning")

        with patch("hatchery.provision_lib.run_script", return_value=(1, "fail")):
            with patch("hatchery._provider"):
                app_module._provision_vm_thread(sid, "dc01", "192.168.1.1", "admin", "pass")

        scripts = hatch_lib.get_vm_scripts(sid, "dc01")
        assert scripts[0]["status"] == "failed"
        assert scripts[1]["status"] == "skipped"

    def test_skips_already_succeeded_scripts(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib
        import lib.config as cfg
        import hatchery as app_module

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup(tmp_path)
        self._script(tmp_path, "a.ps1")
        self._script(tmp_path, "b.ps1")

        class _A:
            name = "a.ps1"
            reboot_after = False

        class _B:
            name = "b.ps1"
            reboot_after = False

        hatch_lib.add_vm_scripts(sid, "dc01", [_A(), _B()])
        hatch_lib.set_script_status(sid, "dc01", 0, "succeeded", exit_code=0, output="")
        hatch_lib.set_vm_status(sid, "dc01", "provisioning")

        call_count = []
        with patch(
            "hatchery.provision_lib.run_script",
            side_effect=lambda *a, **kw: call_count.append(1) or (0, "ok"),
        ):
            with patch("hatchery._provider"):
                app_module._provision_vm_thread(sid, "dc01", "192.168.1.1", "admin", "pass")

        assert len(call_count) == 1  # only b.ps1 ran
        assert hatch_lib.get_vm_record(sid, "dc01")["status"] == "fledged"

    def test_sets_failed_on_run_script_exception(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib
        import lib.config as cfg
        import hatchery as app_module

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup(tmp_path)
        script_name = self._script(tmp_path)

        class _S:
            name = script_name
            reboot_after = False

        hatch_lib.add_vm_scripts(sid, "dc01", [_S()])
        hatch_lib.set_vm_status(sid, "dc01", "provisioning")

        with patch("hatchery.provision_lib.run_script", side_effect=ConnectionError("refused")):
            with patch("hatchery._provider"):
                app_module._provision_vm_thread(sid, "dc01", "192.168.1.1", "admin", "pass")

        assert hatch_lib.get_vm_record(sid, "dc01")["status"] == "failed"
        assert hatch_lib.get_vm_scripts(sid, "dc01")[0]["exit_code"] == -1

    def test_reboot_after_calls_restart_guest_and_waits_for_winrm(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib
        import lib.config as cfg
        import hatchery as app_module

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup(tmp_path)
        script_name = self._script(tmp_path)

        class _S:
            name = script_name
            reboot_after = True

        hatch_lib.add_vm_scripts(sid, "dc01", [_S()])
        hatch_lib.set_vm_status(sid, "dc01", "provisioning")

        with patch("hatchery.provision_lib.run_script", return_value=(0, "ok")):
            with patch("hatchery.provision_lib.restart_guest") as mock_restart:
                with patch("hatchery._check_winrm", return_value=True):
                    with patch("hatchery.time.sleep"):
                        app_module._provision_vm_thread(sid, "dc01", "192.168.1.1", "admin", "pass")

        mock_restart.assert_called_once_with("192.168.1.1", "admin", "pass")
        assert hatch_lib.get_vm_record(sid, "dc01")["status"] == "fledged"

    def test_removes_from_provisioning_set_on_completion(self, tmp_path, monkeypatch):
        import lib.hatch as hatch_lib
        import lib.config as cfg
        import hatchery as app_module

        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        sid = self._setup(tmp_path)
        hatch_lib.set_vm_status(sid, "dc01", "provisioning")
        app_module._provisioning.add((sid, "dc01"))

        with patch("hatchery.provision_lib.run_script", return_value=(0, "ok")):
            with patch("hatchery._provider"):
                app_module._provision_vm_thread(sid, "dc01", "192.168.1.1", "admin", "pass")

        assert (sid, "dc01") not in app_module._provisioning
