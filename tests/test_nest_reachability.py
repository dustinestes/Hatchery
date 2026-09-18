"""Tests for Nest reachability (#263)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from lib import config as cfg
from lib import db
from lib import nest_reachability as nr
from lib.nest_transport import NestConnectionConfig, NestHealthCheckResult, NestSshConfig


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

    def test_endpoint_failure_before_transport(self):
        nest = {
            "id": "r1",
            "name": "R",
            "location": "remote",
            "transport": "ssh",
            "provider_type": "libvirt",
            "host": "127.0.0.1",
            "port": 1,
        }
        with patch(
            "lib.nest_reachability.probe_tcp_endpoint",
            return_value=NestHealthCheckResult(
                ok=False,
                detail="endpoint not reachable — timed out",
                failure_class="endpoint",
            ),
        ):
            result = nr.probe_nest(nest)
        assert result.ok is False
        assert result.failure_class == "endpoint"
        assert "endpoint not reachable" in result.detail

    def test_transport_failure_after_endpoint_ok(self):
        nest = {
            "id": "r1",
            "name": "R",
            "location": "remote",
            "transport": "ssh",
            "provider_type": "libvirt",
            "host": "h",
            "port": 22,
        }

        class _T:
            def test_connection(self):
                return NestHealthCheckResult(
                    ok=False, detail="Permission denied", failure_class="transport"
                )

        with (
            patch(
                "lib.nest_reachability.probe_tcp_endpoint",
                return_value=NestHealthCheckResult(ok=True, detail="TCP open"),
            ),
            patch("lib.nest_reachability.get_nest_transport", return_value=_T()),
            patch(
                "lib.nests.to_connection_config",
                return_value=NestConnectionConfig(
                    location="remote",
                    transport="ssh",
                    ssh=NestSshConfig(host="h", port=22),
                ),
            ),
        ):
            result = nr.probe_nest(nest)
        assert result.ok is False
        assert result.failure_class == "transport"
        assert "Nest transport not accessible" in result.detail


class TestSnapshotAndAlerts:
    def test_record_and_summary(self):
        nest = {"id": "r1", "name": "Lab", "location": "remote"}
        nr.record_probe(
            nest,
            NestHealthCheckResult(
                ok=False,
                detail="endpoint not reachable — down",
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
                detail="endpoint reachable; Nest transport not accessible — auth",
                failure_class="transport",
            ),
        )
        assert alerts_lib.count_active_alerts() == 1
        nr.sync_alert_for_probe(nest, NestHealthCheckResult(ok=True, detail="ok"))
        assert alerts_lib.count_active_alerts() == 0

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
