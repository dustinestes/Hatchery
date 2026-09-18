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
