"""Tests for Dashboard Nest + VM rollups (#329)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import lib.dashboard_summary as dash
import lib.nest_reachability as nr
import lib.nests as nests_lib
import lib.plane_status as ps
from lib import config as cfg
from lib import db
from lib.nest_transport import NestHealthCheckResult


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.yaml")
    db.init_db(tmp_path / "hatchery.db")
    cfg.load()
    cfg.bind_db()
    yield


class TestNestTileFields:
    def test_empty_registry(self):
        fields = dash.nest_tile_fields([], snap_nests={})
        assert fields["nest_total"] == 0
        assert fields["nest_reachable"] == 0
        assert fields["nest_unreachable"] == 0
        assert fields["nest_unchecked"] == 0

    def test_counts_reachable_unreachable_unchecked(self):
        nests = [
            {"id": "a", "name": "A"},
            {"id": "b", "name": "B"},
            {"id": "c", "name": "C"},
        ]
        snap = {
            "a": {"ok": True, "checked_at": "2026-09-20T12:00:00Z"},
            "b": {"ok": False, "checked_at": "2026-09-20T11:00:00Z"},
        }
        fields = dash.nest_tile_fields(nests, snap_nests=snap)
        assert fields["nest_total"] == 3
        assert fields["nest_reachable"] == 1
        assert fields["nest_unreachable"] == 1
        assert fields["nest_unchecked"] == 1
        assert fields["nest_last_validated_at"] == "2026-09-20T12:00:00Z"


class TestVmSummary:
    def test_empty_registry(self, monkeypatch):
        monkeypatch.setattr(nests_lib, "list_nests", lambda: [])
        summary = dash.vm_summary()
        assert summary["total"] == 0
        assert summary["nests_unavailable"] == 0
        assert summary["by_power"]["running"] == 0

    def test_aggregates_power_and_hatch(self, monkeypatch):
        monkeypatch.setattr(
            nests_lib,
            "list_nests",
            lambda: [
                {
                    "id": "local",
                    "name": "Local",
                    "provider_type": "libvirt",
                    "location": "local",
                }
            ],
        )
        provider = MagicMock()
        provider.list_vms.return_value = [
            {"name": "dc01", "status": "running"},
            {"name": "ws01", "status": "shut off"},
            {"name": "ws02", "status": "paused"},
        ]
        provider.get_vm_session_tag.side_effect = [
            {"session_id": "s1", "clutch_file": "lab.yaml"},
            None,
            {"session_id": "s1", "clutch_file": "lab.yaml"},
        ]

        def get_vm_record(sid, name):
            if name == "dc01":
                return {"status": "fledged"}
            if name == "ws02":
                return {"status": "failed"}
            return None

        monkeypatch.setattr(dash, "get_provider", lambda nid: provider)
        monkeypatch.setattr("lib.hatch.get_vm_record", get_vm_record)

        summary = dash.vm_summary()
        assert summary["total"] == 3
        assert summary["by_power"]["running"] == 1
        assert summary["by_power"]["shut_off"] == 1
        assert summary["by_power"]["paused"] == 1
        assert summary["by_hatch"]["fledged"] == 1
        assert summary["by_hatch"]["failed"] == 1
        assert summary["by_hatch"]["none"] == 1
        assert summary["nests_unavailable"] == 0


class TestFooterStatusNestFields:
    def test_includes_nest_tile_fields(self):
        nests_lib.ensure_local_nest()
        nr.record_probe(
            nests_lib.get_nest("local"),
            NestHealthCheckResult(ok=True, detail="OK", failure_class=None),
            checked_at="2026-09-20T15:00:00Z",
        )
        status = ps.footer_status()
        assert status["nest_total"] >= 1
        assert "nest_reachable" in status
        assert "nest_unchecked" in status
        assert status["nest_last_validated_at"] == "2026-09-20T15:00:00Z"
