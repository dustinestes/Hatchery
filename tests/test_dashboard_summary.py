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
            {"id": "a", "name": "A", "provider_type": "libvirt"},
            {"id": "b", "name": "B", "provider_type": "utm"},
            {"id": "c", "name": "C", "provider_type": "hyperv"},
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
        assert fields["nest_by_provider"] == {"libvirt": 1, "utm": 1, "hyperv": 1}

    def test_by_provider_defaults_libvirt(self):
        fields = dash.nest_tile_fields(
            [{"id": "x", "name": "X"}],
            snap_nests={},
        )
        assert fields["nest_by_provider"]["libvirt"] == 1
        assert fields["nest_by_provider"]["utm"] == 0
        assert fields["nest_by_provider"]["hyperv"] == 0


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


class TestClutchSummary:
    def test_empty(self):
        summary = dash.clutch_summary()
        assert summary["file_count"] == 0
        assert summary["session_total"] == 0
        assert summary["nests_used"] == []
        assert summary["unique_clutch_files"] == 0

    def test_counts_files_and_sessions(self, tmp_path, monkeypatch):
        from lib import hatch as hatch_lib

        clutch_dir = tmp_path / "clutches"
        clutch_dir.mkdir()
        (clutch_dir / "lab.yaml").write_text("vms: []\n", encoding="utf-8")
        (clutch_dir / "ignore.txt").write_text("x", encoding="utf-8")

        nests_lib.ensure_local_nest()
        sid = hatch_lib.create_session("lab.yaml", "Lab", nest="local")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.set_vm_status(sid, "dc01", "fledged")

        summary = dash.clutch_summary()
        assert summary["file_count"] == 1
        assert summary["session_total"] == 1
        assert summary["by_status"]["completed"] == 1
        assert summary["unique_clutch_files"] == 1
        assert summary["nests_used"] == [{"id": "local", "name": "Local"}]


class TestLibrarySummary:
    def test_empty_linked(self):
        summary = dash.library_summary()
        assert summary["linked"] == {"scripts": 0, "clutches": 0, "media": 0}
        assert summary["by_drift"] == {
            "in_sync": 0,
            "out_of_sync": 0,
            "unknown": 0,
            "orphan": 0,
        }

    def test_counts_provenance_by_domain(self):
        from lib import library_provenance as prov

        prov.upsert_on_pull(
            domain="scripts",
            cache_name="a.ps1",
            connection_id="c1",
            relative_path="a.ps1",
            source_type="path",
            cache_sha256="a" * 64,
        )
        prov.upsert_on_pull(
            domain="scripts",
            cache_name="b.ps1",
            connection_id="c1",
            relative_path="b.ps1",
            source_type="path",
            cache_sha256="b" * 64,
        )
        prov.upsert_on_pull(
            domain="clutches",
            cache_name="lab.yaml",
            connection_id="c1",
            relative_path="lab.yaml",
            source_type="path",
            cache_sha256="c" * 64,
        )
        prov.upsert_on_pull(
            domain="media",
            cache_name="win.iso",
            connection_id="c1",
            relative_path="win.iso",
            source_type="path",
            cache_sha256="d" * 64,
            media_target="iso",
        )
        prov.set_drift_state(
            "scripts",
            "b.ps1",
            drift_state="out_of_sync",
        )
        summary = dash.library_summary()
        assert summary["linked"] == {"scripts": 2, "clutches": 1, "media": 1}
        assert summary["by_drift"]["in_sync"] == 3
        assert summary["by_drift"]["out_of_sync"] == 1


class TestValidatorsSummary:
    def test_enabled_and_latest_runs(self):
        from lib.validators import builtins as builtins_mod
        from lib.validators.registry import clear_registry
        from lib.validators.runs import record_run
        from lib.validators.settings import save_validator_configs

        clear_registry()
        builtins_mod.register_builtins()
        save_validator_configs(
            {
                "controller_requirements": {"enabled": True, "interval_seconds": 60},
                "clutch_files": {"enabled": False, "interval_seconds": 60},
            }
        )
        record_run(
            validator_id="controller_requirements",
            status="ok",
            message="ok",
            finished_at="2026-09-20T16:00:00Z",
        )
        record_run(
            validator_id="nest_reachability",
            status="findings",
            message="down",
            findings_count=2,
            finished_at="2026-09-20T16:30:00Z",
        )

        summary = dash.validators_summary()
        assert summary["total"] >= 2
        assert summary["enabled"] >= 1
        assert summary["disabled"] >= 1
        assert summary["by_status"]["ok"] >= 1
        assert summary["by_status"]["findings"] >= 1
        assert summary["by_scope"]["controller"] >= 1
        assert summary["by_scope"]["nest"] >= 1
        assert summary["degraded"] >= 1
        assert summary["findings_total"] >= 2
        assert summary["last_run_at"] == "2026-09-20T16:30:00Z"

    def test_all_disabled(self):
        from lib.validators import builtins as builtins_mod
        from lib.validators.registry import all_validators, clear_registry
        from lib.validators.settings import save_validator_configs

        clear_registry()
        builtins_mod.register_builtins()
        save_validator_configs(
            {v.id: {"enabled": False, "interval_seconds": 60} for v in all_validators()}
        )
        summary = dash.validators_summary()
        assert summary["total"] > 0
        assert summary["enabled"] == 0
        assert summary["disabled"] == summary["total"]
        assert summary["never_run"] == 0


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


class TestTileValidationStamps:
    def test_vms_placeholder_omits_alerts_and_validators(self):
        stamps = dash.tile_validation_stamps()
        assert stamps["vms"] == {
            "has_validator": False,
            "at": None,
            "label": "not implemented",
        }
        assert "alerts" not in stamps
        assert "validators" not in stamps

    def test_nests_and_library_from_runs(self):
        from lib.validators.runs import record_run

        record_run(
            validator_id="nest_reachability",
            status="ok",
            message="ok",
            finished_at="2026-09-20T12:00:00Z",
        )
        record_run(
            validator_id="library_connections",
            status="ok",
            message="ok",
            finished_at="2026-09-20T13:00:00Z",
        )
        record_run(
            validator_id="clutch_files",
            status="ok",
            message="ok",
            finished_at="2026-09-20T11:00:00Z",
        )
        stamps = dash.tile_validation_stamps()
        assert stamps["nests"]["has_validator"] is True
        assert stamps["nests"]["at"] == "2026-09-20T12:00:00Z"
        assert stamps["library"]["has_validator"] is True
        assert stamps["library"]["at"] == "2026-09-20T13:00:00Z"
        assert stamps["clutches"]["at"] == "2026-09-20T11:00:00Z"

    def test_dashboard_summary_includes_validated(self):
        summary = dash.dashboard_summary()
        assert "validated" in summary
        assert set(summary["validated"]) == {"nests", "clutches", "vms", "library"}
