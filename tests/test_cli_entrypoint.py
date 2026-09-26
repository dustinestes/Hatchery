"""Subprocess smoke for the ``hatchery`` console script (#432).

In-process coverage lives in ``tests/test_cli.py``. These tests exercise the
installed entrypoint (``[project.scripts] hatchery = lib.cli:main``) so packaging
and global-flag wiring stay honest in CI.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import lib.config as cfg
import lib.db as db_module
import lib.nests as nests_lib


def _hatchery_argv() -> list[str]:
    """Return argv prefix for the console script, or fail if it is missing."""
    exe = shutil.which("hatchery")
    if exe:
        return [exe]
    pytest.fail(
        "hatchery console script not on PATH; run via `uv run pytest` after `uv sync` "
        f"(python={sys.executable})"
    )


def _run_hatchery(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_hatchery_argv(), *args],
        capture_output=True,
        text=True,
        check=check,
    )


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """Mirror ``test_cli`` isolation so seeding a sandbox does not leak into other tests."""
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(cfg, "DEFAULT_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(
        cfg,
        "_DEFAULTS",
        {
            "data_dir": str(tmp_path / "data"),
            "bg_interval": 60,
            "validators": {},
            "validators_run_retention": 50,
            "nest_reachability_status": {},
            "show_passwords": False,
            "display_timezone": "UTC",
            "library_enabled": False,
            "library_connections": [],
            "library_script_bindings": [],
            "library_clutch_bindings": [],
            "library_media_bindings": [],
            "nest_key_alert_tiers": [],
            "nest_ssh_identities": [],
        },
    )
    monkeypatch.setattr(cfg, "_config", {})
    monkeypatch.setattr(cfg, "_pending_yaml_settings", {})
    monkeypatch.setattr(cfg, "_db_bound", False)
    monkeypatch.setattr(cfg, "_runtime_data_dir", None)
    monkeypatch.setattr(cfg, "_runtime_nest_local", False)
    monkeypatch.setattr(cfg, "_bootstrap_data_dir", None)
    db_module.init_db(tmp_path / "hatchery.db")
    yield tmp_path
    db_module._db_path = None
    cfg.set_runtime_data_dir(None)
    cfg.set_runtime_nest_local(False)


class TestCliEntrypointSmoke:
    def test_help_lists_json_and_core_commands(self):
        result = _run_hatchery("--help")
        assert result.returncode == 0, result.stderr
        out = result.stdout
        assert "--json" in out
        for name in (
            "serve",
            "nest",
            "clutch",
            "vm",
            "hatch",
            "session",
            "media",
            "scripts",
            "settings",
        ):
            assert name in out

    def test_json_nest_list_via_console_script(self, isolated_config, tmp_path):
        from lib.cli import bootstrap

        sandbox = tmp_path / "sandbox"
        bootstrap.apply_data_dir(str(sandbox))
        bootstrap.init_controller_runtime(create=True)
        nests_lib.ensure_local_nest()
        assert (Path(sandbox) / "hatchery.db").is_file()

        result = _run_hatchery(
            "--json",
            "nest",
            "--data-dir",
            str(sandbox),
            "list",
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert isinstance(payload, list)
        assert payload[0]["id"] == "local"
        assert payload[0]["provider_type"] == "libvirt"
