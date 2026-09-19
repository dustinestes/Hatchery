"""Footer plane status rollups (#277)."""

from __future__ import annotations

import pytest

from lib import alerts as alerts_lib
from lib import config as cfg
from lib import db
from lib import nests as nests_lib
from lib import plane_status as ps
from lib.nest_transport import NestHealthCheckResult


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.yaml")
    db.init_db(tmp_path / "hatchery.db")
    cfg.load()
    cfg.bind_db()
    yield


class TestFooterStatus:
    def test_hatchery_green_without_controller_alerts(self):
        nests_lib.ensure_local_nest()
        status = ps.footer_status()
        assert status["hatchery_dot"] == "green"
        assert status["hatchery_ok"] is True

    def test_hatchery_red_on_controller_alert(self):
        nests_lib.ensure_local_nest()
        alerts_lib.record_alert("Controller requirement: 'ssh' is not installed — x")
        status = ps.footer_status()
        assert status["hatchery_dot"] == "red"
        assert status["hatchery_issue_count"] == 1

    def test_hatchery_ignores_info_tier(self):
        nests_lib.ensure_local_nest()
        alerts_lib.record_alert("Controller requirement: noise", tier="info")
        status = ps.footer_status()
        assert status["hatchery_dot"] == "green"

    def test_nests_muted_when_registry_empty(self):
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM nests")
            conn.commit()
        finally:
            conn.close()
        status = ps.footer_status()
        assert status["nest_total"] == 0
        assert status["nests_dot"] == "muted"
        assert status["nests_title"] == "No Nests registered"

    def test_nests_red_when_unreachable(self):
        from lib import nest_reachability as nr

        nests_lib.ensure_local_nest()
        nr.record_probe(
            {"id": "local", "name": "Local", "location": "local"},
            NestHealthCheckResult(ok=False, detail="down", failure_class="endpoint"),
        )
        status = ps.footer_status()
        assert status["nests_dot"] == "red"
        assert status["nest_unreachable"] == 1

    def test_nests_red_on_nest_scoped_alert(self):
        nests_lib.ensure_local_nest()
        alerts_lib.record_alert("Nest capability: 'Local' (local): 'virsh' is not available — x")
        status = ps.footer_status()
        assert status["nests_dot"] == "red"
        assert status["nest_alert_count"] == 1

    def test_libraries_hidden_when_disabled(self):
        status = ps.footer_status()
        assert status["library_enabled"] is False
        assert status["libraries_visible"] is False

    def test_libraries_muted_when_enabled_empty(self):
        c = cfg.get()
        c["library_enabled"] = True
        c["library_connections"] = []
        cfg.save(c)
        status = ps.footer_status()
        assert status["libraries_visible"] is True
        assert status["libraries_dot"] == "muted"
        assert status["libraries_title"] == "No Library connections"

    def test_libraries_green_when_ok(self, tmp_path):
        share = tmp_path / "share"
        share.mkdir()
        c = cfg.get()
        c["library_enabled"] = True
        c["library_connections"] = [
            {
                "id": "c1",
                "label": "Share",
                "type": "path",
                "base_uri": str(share),
                "token": "",
                "expires_at": None,
                "kinds": ["scripts"],
            }
        ]
        cfg.save(c)
        status = ps.footer_status()
        assert status["libraries_dot"] == "green"
        assert status["library_connection_total"] == 1

    def test_libraries_footer_counts_only_enabled(self, tmp_path):
        share = tmp_path / "share"
        share.mkdir()
        c = cfg.get()
        c["library_enabled"] = True
        c["library_connections"] = [
            {
                "id": "c1",
                "label": "On",
                "type": "path",
                "base_uri": str(share),
                "token": "",
                "expires_at": None,
                "kinds": ["scripts"],
                "enabled": True,
            },
            {
                "id": "c2",
                "label": "Off",
                "type": "path",
                "base_uri": str(share),
                "token": "",
                "expires_at": None,
                "kinds": ["scripts"],
                "enabled": False,
            },
        ]
        cfg.save(c)
        status = ps.footer_status()
        assert status["library_connection_total"] == 1
        assert status["libraries_dot"] == "green"

    def test_libraries_muted_when_all_connections_disabled(self, tmp_path):
        share = tmp_path / "share"
        share.mkdir()
        c = cfg.get()
        c["library_enabled"] = True
        c["library_connections"] = [
            {
                "id": "c1",
                "label": "Off",
                "type": "path",
                "base_uri": str(share),
                "token": "",
                "expires_at": None,
                "kinds": ["scripts"],
                "enabled": False,
            }
        ]
        cfg.save(c)
        status = ps.footer_status()
        assert status["library_connection_total"] == 0
        assert status["libraries_dot"] == "muted"
        assert status["libraries_title"] == "No Library connections"

    def test_libraries_red_on_library_alert(self, tmp_path):
        share = tmp_path / "share"
        share.mkdir()
        c = cfg.get()
        c["library_enabled"] = True
        c["library_connections"] = [
            {
                "id": "c1",
                "label": "Share",
                "type": "path",
                "base_uri": str(share),
                "token": "",
                "expires_at": None,
                "kinds": ["scripts"],
            }
        ]
        cfg.save(c)
        alerts_lib.record_alert(
            "Library connection: 'Share' (c1) — Path does not exist: /x",
            tier="alert",
        )
        status = ps.footer_status()
        assert status["libraries_dot"] == "red"
        assert status["library_alert_count"] == 1
