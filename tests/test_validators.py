"""Tests for pluggable validators (#268)."""

from __future__ import annotations

import pytest

from lib import config as cfg
from lib import db
from lib.validators import builtins as builtins_mod
from lib.validators.context import ValidatorContext
from lib.validators.registry import all_validators, clear_registry, get_validator
from lib.validators.runs import latest_by_validator, list_runs, record_run
from lib.validators.scheduler import run_validator
from lib.validators.settings import (
    get_run_retention,
    list_validator_configs,
    migrate_bg_interval,
    save_validator_configs,
)


@pytest.fixture(autouse=True)
def _reset_validators(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.yaml")
    db.init_db(tmp_path / "hatchery.db")
    cfg.load()
    cfg.bind_db()
    clear_registry()
    builtins_mod.register_builtins()
    yield


class TestRegistry:
    def test_builtins_registered(self):
        ids = {v.id for v in all_validators()}
        assert "controller_requirements" in ids
        assert "clutch_files" in ids
        assert "nest_key_expiry" in ids
        assert "nest_reachability" in ids
        assert "library_connections" in ids

    def test_stubs_marked(self):
        v = get_validator("nest_capability")
        assert v is not None
        assert getattr(v, "stub", False) is True


class TestRuns:
    def test_record_and_list(self):
        record_run(validator_id="clutch_files", status="ok", message="ok", trigger="manual")
        rows = list_runs(limit=10)
        assert len(rows) == 1
        assert rows[0]["validator_id"] == "clutch_files"
        assert rows[0]["status"] == "ok"

    def test_retention_trims(self, monkeypatch):
        monkeypatch.setitem(cfg.get(), "validators_run_retention", 10)
        # save via config
        c = cfg.get()
        c["validators_run_retention"] = 10
        cfg.save(c)
        assert get_run_retention() == 10
        for i in range(15):
            record_run(
                validator_id="clutch_files",
                status="ok",
                message=f"run {i}",
                trigger="schedule",
            )
        rows = list_runs(validator_id="clutch_files", limit=100)
        assert len(rows) == 10

    def test_latest_by_validator(self):
        record_run(validator_id="clutch_files", status="ok", message="first", trigger="manual")
        record_run(validator_id="clutch_files", status="error", message="second", trigger="manual")
        latest = latest_by_validator()
        assert latest["clutch_files"]["message"] == "second"


class TestSchedulerRun:
    def test_run_validator_records_ok(self):
        result = run_validator("clutch_files", trigger="manual")
        assert result["status"] == "ok"
        assert list_runs(validator_id="clutch_files")


class TestSettings:
    def test_migrate_bg_interval_seeds(self):
        c = cfg.get()
        c["bg_interval"] = 90
        c["validators"] = {}
        cfg.save(c)
        migrate_bg_interval()
        rows = list_validator_configs()
        assert all(r["interval_seconds"] == 90 for r in rows if not r.get("stub"))

    def test_save_configs(self):
        save_validator_configs(
            {"clutch_files": {"enabled": False, "interval_seconds": 120}},
            retention=25,
        )
        rows = {r["id"]: r for r in list_validator_configs()}
        assert rows["clutch_files"]["enabled"] is False
        assert rows["clutch_files"]["interval_seconds"] == 120
        assert get_run_retention() == 25


class TestControllerRequirements:
    def test_run_creates_alerts_for_missing(self, monkeypatch):
        from unittest.mock import patch

        from lib.requirements import Requirement

        with patch(
            "lib.requirements.check_all",
            return_value=[Requirement("virsh", "libvirt-clients", "ops", False)],
        ):
            ctx = ValidatorContext(trigger="manual")
            get_validator("controller_requirements").run(ctx)
        from lib import alerts as alerts_lib

        assert any("virsh" in a["message"] for a in alerts_lib.list_recent() if not a["resolved"])
