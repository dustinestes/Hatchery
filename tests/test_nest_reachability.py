"""Tests for Nest reachability (#263)."""

from __future__ import annotations


import pytest

from lib import config as cfg
from lib import db
from lib import nest_reachability as nr
from lib.nest_types import NestHealthCheckResult


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.yaml")
    db.init_db(tmp_path / "hatchery.db")
    cfg.load()
    cfg.bind_db()
    yield


class TestProbeNest:
    def test_local_always_ok(self):
        result = nr.probe_nest({"id": "local", "location": "local", "name": "Local"})
        assert result.ok is True

    def test_remote_rejected(self):
        nest = {
            "id": "r1",
            "name": "R",
            "location": "remote",
            "transport": "ssh",
            "provider_type": "libvirt",
            "host": "h",
            "port": 22,
        }
        result = nr.probe_nest(nest)
        assert result.ok is False
        assert result.failure_class == "config"
        assert "#620" in result.detail


class TestSnapshotAndAlerts:
    def test_record_and_summary(self):
        nest = {"id": "r1", "name": "Lab", "location": "remote"}
        nr.record_probe(
            nest,
            NestHealthCheckResult(
                ok=False,
                detail="endpoint not reachable - down",
                failure_class="endpoint",
            ),
        )
        snap = nr.get_snapshot()
        assert snap["nests"]["r1"]["ok"] is False
        assert snap["nests"]["r1"]["failure_class"] == "endpoint"
        assert snap["remote_down"] == 1
        assert snap["remotes_ok"] is False

    def test_sync_alert_open_and_clear(self):
        from lib import alerts as alerts_lib

        nest = {"id": "r1", "name": "Lab", "location": "remote"}
        nr.sync_alert_for_probe(
            nest,
            NestHealthCheckResult(
                ok=False,
                detail="endpoint reachable; Nest transport not accessible - auth",
                failure_class="transport",
            ),
        )
        assert alerts_lib.count_active_alerts() == 1
        nr.sync_alert_for_probe(nest, NestHealthCheckResult(ok=True, detail="ok"))
        assert alerts_lib.count_active_alerts() == 0

    def test_sync_alert_collapses_duplicates_by_nest_id(self):
        """Rename / detail churn must not leave multiple active reachability Alerts."""
        from lib import alerts as alerts_lib

        alerts_lib.record_alert("Nest reachability: 'UTM Box' (r1): endpoint not reachable - a")
        alerts_lib.record_alert("Nest reachability: 'Lab' (r1): endpoint not reachable - b")
        nest = {"id": "r1", "name": "Lab", "location": "remote"}
        nr.sync_alert_for_probe(
            nest,
            NestHealthCheckResult(
                ok=False,
                detail="endpoint not reachable - still down",
                failure_class="endpoint",
            ),
        )
        active = [
            a
            for a in alerts_lib.list_recent()
            if not a["resolved"] and "Nest reachability:" in a["message"]
        ]
        assert len(active) == 1
        assert "(r1)" in active[0]["message"]

    def test_sync_alert_does_not_reopen_when_one_active(self):
        from lib import alerts as alerts_lib

        nest = {"id": "r1", "name": "Lab", "location": "remote"}
        nr.sync_alert_for_probe(
            nest,
            NestHealthCheckResult(ok=False, detail="down-1", failure_class="endpoint"),
        )
        nr.sync_alert_for_probe(
            nest,
            NestHealthCheckResult(ok=False, detail="down-2-different", failure_class="endpoint"),
        )
        assert alerts_lib.count_active_alerts() == 1

    def test_label_uses_failure_class(self):
        nest = {"id": "r1", "name": "Lab", "location": "remote"}
        nr.record_probe(
            nest,
            NestHealthCheckResult(ok=False, detail="x", failure_class="endpoint"),
        )
        assert nr.nest_reachability_label("r1") == "Endpoint not reachable"

    def test_prune_removed_nests_updates_snapshot(self):
        from lib import nests as nests_lib

        nest = {"id": "r1", "name": "Lab", "location": "remote"}
        nr.record_probe(
            nest,
            NestHealthCheckResult(ok=False, detail="x", failure_class="endpoint"),
        )
        assert nr.get_snapshot()["remote_down"] == 1
        nr.prune_removed_nests({nests_lib.LOCAL_NEST_ID})
        snap = nr.get_snapshot()
        assert "r1" not in (snap.get("nests") or {})
        assert snap["remote_down"] == 0
        assert snap["remotes_ok"] is True


class TestCapabilityGate:
    def test_local_always_reachable(self):
        assert nr.is_reachable_for_capability({"id": "local", "location": "local"}) is True

    def test_remote_requires_ok_snapshot(self):
        nest = {"id": "r1", "name": "Lab", "location": "remote"}
        assert nr.is_reachable_for_capability(nest) is False
        nr.record_probe(
            nest,
            NestHealthCheckResult(ok=False, detail="down", failure_class="endpoint"),
        )
        assert nr.is_reachable_for_capability(nest) is False
        nr.record_probe(nest, NestHealthCheckResult(ok=True, detail="OK"))
        assert nr.is_reachable_for_capability(nest) is True


class TestProbeTcpEndpoint:
    def test_empty_host_and_bad_port(self):
        assert nr.probe_tcp_endpoint("", 22).failure_class == "config"
        assert nr.probe_tcp_endpoint("h", "x").failure_class == "config"

    def test_open_timeout_and_oserror(self):
        from unittest.mock import MagicMock, patch

        with patch("lib.nest_reachability.socket.create_connection", return_value=MagicMock()):
            assert nr.probe_tcp_endpoint("h", 22).ok is True
        with patch("lib.nest_reachability.socket.create_connection", side_effect=TimeoutError):
            res = nr.probe_tcp_endpoint("h", 22)
        assert res.failure_class == "endpoint"
        assert "timed out" in res.detail
        with patch("lib.nest_reachability.socket.create_connection", side_effect=OSError("nope")):
            res = nr.probe_tcp_endpoint("h", 22)
        assert res.failure_class == "endpoint"
        assert "nope" in res.detail


class TestReachabilityLabels:
    def test_labels_by_failure_class(self):
        nest = {"id": "r1", "name": "Lab", "location": "remote"}
        assert nr.nest_reachability_label("r1") == "Reachability not checked yet"
        for fc, label in (
            ("transport", "Transport not accessible"),
            ("config", "Cannot probe"),
            (None, "Unreachable"),
        ):
            nr.record_probe(nest, NestHealthCheckResult(ok=False, detail="x", failure_class=fc))
            assert nr.nest_reachability_label("r1") == label
        nr.record_probe(nest, NestHealthCheckResult(ok=True, detail="ok"))
        assert nr.nest_reachability_label("r1") == "Reachable"
