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
        v = get_validator("library_connections")
        assert v is not None
        assert getattr(v, "stub", False) is True

    def test_nest_reachability_active(self):
        v = get_validator("nest_reachability")
        assert v is not None
        assert getattr(v, "stub", False) is False


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
        assert result["tier"] == "info"
        assert result["findings_count"] == 0
        assert list_runs(validator_id="clutch_files")

    def test_run_validator_records_findings_tier(self):
        from unittest.mock import patch

        from lib.requirements import Requirement

        with patch(
            "lib.requirements.check_controller",
            return_value=[
                Requirement(
                    "ssh",
                    "openssh-client",
                    "Nest transport",
                    False,
                    role="controller",
                )
            ],
        ):
            result = run_validator("controller_requirements", trigger="manual")
        assert result["status"] == "findings"
        assert result["tier"] == "alert"
        assert result["findings_count"] >= 1
        rows = list_runs(validator_id="controller_requirements", status="findings")
        assert rows
        assert rows[0]["findings_count"] >= 1


class TestListRunsFilters:
    def test_filter_by_status_and_tier(self):
        record_run(
            validator_id="clutch_files",
            status="findings",
            message="bad",
            tier="alert",
            findings_count=2,
            trigger="manual",
        )
        record_run(
            validator_id="clutch_files",
            status="ok",
            message="good",
            tier="info",
            trigger="manual",
        )
        assert len(list_runs(status="findings")) == 1
        assert len(list_runs(tier="alert")) == 1
        assert list_runs(status="findings", tier="alert")[0]["message"] == "bad"


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
            "lib.requirements.check_controller",
            return_value=[
                Requirement(
                    "ssh",
                    "openssh-client",
                    "Nest transport",
                    False,
                    role="controller",
                    install_hint="sudo apt install openssh-client",
                )
            ],
        ):
            ctx = ValidatorContext(trigger="manual")
            get_validator("controller_requirements").run(ctx)
        from lib import alerts as alerts_lib

        assert any(
            "ssh" in a["message"] and "Controller requirement:" in a["message"]
            for a in alerts_lib.list_recent()
            if not a["resolved"]
        )


class TestNestCapability:
    def test_not_stub(self):
        v = get_validator("nest_capability")
        assert v is not None
        assert getattr(v, "stub", False) is False

    def test_run_alerts_missing_local_tools(self, monkeypatch):
        from unittest.mock import patch

        from lib.requirements import Requirement

        nest = {"id": "local", "name": "Local", "location": "local", "provider_type": "libvirt"}
        with (
            patch("lib.nests.list_nests", return_value=[nest]),
            patch(
                "lib.requirements.check_nest",
                return_value=[
                    Requirement("virsh", "libvirt-clients", "ops", False, role="nest"),
                ],
            ),
        ):
            ctx = ValidatorContext(trigger="manual")
            get_validator("nest_capability").run(ctx)
        from lib import alerts as alerts_lib

        assert any(
            "Nest capability:" in a["message"] and "virsh" in a["message"]
            for a in alerts_lib.list_recent()
            if not a["resolved"]
        )

    def test_skips_unreachable_remote_and_clears_capability_alerts(self):
        """Unreachable Remotes must not invent missing-tool Alerts (#286)."""
        from unittest.mock import patch

        from lib import alerts as alerts_lib
        from lib.nest_transport import NestHealthCheckResult
        from lib import nest_reachability as nr

        nest = {
            "id": "r1",
            "name": "Lab",
            "location": "remote",
            "provider_type": "libvirt",
            "transport": "ssh",
            "host": "nest.example",
        }
        nr.record_probe(
            nest,
            NestHealthCheckResult(
                ok=False,
                detail="endpoint not reachable — down",
                failure_class="endpoint",
            ),
        )
        alerts_lib.record_alert(
            "Nest capability: 'Lab' (r1): 'virsh' is not available — VM lifecycle"
        )
        with (
            patch("lib.nests.list_nests", return_value=[nest]),
            patch("lib.requirements.check_nest") as check_nest,
        ):
            summary = get_validator("nest_capability").run(ValidatorContext(trigger="manual"))
        check_nest.assert_not_called()
        assert "skipped" in summary.lower()
        assert "unreachable" in summary.lower()
        active_cap = [
            a
            for a in alerts_lib.list_recent()
            if not a["resolved"] and "Nest capability:" in a["message"]
        ]
        assert active_cap == []

    def test_checks_reachable_remote(self):
        from unittest.mock import patch

        from lib import nest_reachability as nr
        from lib.nest_transport import NestHealthCheckResult
        from lib.requirements import Requirement

        nest = {
            "id": "r1",
            "name": "Lab",
            "location": "remote",
            "provider_type": "libvirt",
            "transport": "ssh",
            "host": "nest.example",
        }
        nr.record_probe(nest, NestHealthCheckResult(ok=True, detail="OK"))
        with (
            patch("lib.nests.list_nests", return_value=[nest]),
            patch(
                "lib.requirements.check_nest",
                return_value=[
                    Requirement("virsh", "libvirt-clients", "ops", False, role="nest"),
                ],
            ) as check_nest,
        ):
            summary = get_validator("nest_capability").run(ValidatorContext(trigger="manual"))
        check_nest.assert_called_once()
        assert "missing" in summary.lower()
        from lib import alerts as alerts_lib

        assert any(
            "Nest capability:" in a["message"] and "virsh" in a["message"]
            for a in alerts_lib.list_recent()
            if not a["resolved"]
        )


class TestNestReachability:
    def test_run_alerts_unreachable_remote(self):
        from unittest.mock import patch

        from lib.nest_transport import NestHealthCheckResult

        nest = {
            "id": "r1",
            "name": "Lab",
            "location": "remote",
            "provider_type": "libvirt",
            "transport": "ssh",
            "host": "nest.example",
        }
        with (
            patch("lib.nests.list_nests", return_value=[nest]),
            patch("lib.nests.ensure_local_nest", return_value=None),
            patch(
                "lib.nest_reachability.probe_nest",
                return_value=NestHealthCheckResult(
                    ok=False,
                    detail="endpoint not reachable — Connection refused",
                    failure_class="endpoint",
                ),
            ),
        ):
            ctx = ValidatorContext(trigger="manual")
            summary = get_validator("nest_reachability").run(ctx)
        from lib import alerts as alerts_lib

        assert "unreachable" in summary.lower()
        assert any(
            "Nest reachability:" in a["message"] and "endpoint not reachable" in a["message"]
            for a in alerts_lib.list_recent()
            if not a["resolved"]
        )

    def test_run_resolves_when_reachable(self):
        from unittest.mock import patch

        from lib import alerts as alerts_lib
        from lib.nest_transport import NestHealthCheckResult

        nest = {
            "id": "r1",
            "name": "Lab",
            "location": "remote",
            "provider_type": "libvirt",
            "transport": "ssh",
            "host": "nest.example",
        }
        alerts_lib.record_alert("Nest reachability: 'Lab' (r1): Connection refused")
        with (
            patch("lib.nests.list_nests", return_value=[nest]),
            patch("lib.nests.ensure_local_nest", return_value=None),
            patch(
                "lib.nest_reachability.probe_nest",
                return_value=NestHealthCheckResult(ok=True, detail="OK"),
            ),
        ):
            get_validator("nest_reachability").run(ValidatorContext(trigger="manual"))
        assert alerts_lib.count_active_alerts() == 0
