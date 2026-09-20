"""Tests for Hatchery Controller CLI (#22 / ADR-0013)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import lib.cli as cli
import lib.cli.serve as serve_cmd
import lib.config as cfg
import lib.db as db_module


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
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


class TestBuildParser:
    def test_serve_defaults(self):
        parser = cli.build_parser()
        args = parser.parse_args(["serve"])
        assert args.command == "serve"
        assert args.host == "0.0.0.0"
        assert args.port == 5000
        assert args.data_dir is None
        assert args.nest_local is False

    def test_serve_flags(self):
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "serve",
                "--data-dir",
                "/tmp/sandbox",
                "--nest-local",
                "--host",
                "127.0.0.1",
                "--port",
                "8080",
            ]
        )
        assert args.data_dir == "/tmp/sandbox"
        assert args.nest_local is True
        assert args.host == "127.0.0.1"
        assert args.port == 8080

    def test_requires_command(self):
        parser = cli.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


class TestMainAndServe:
    def test_main_dispatches_serve(self):
        with patch("lib.cli.serve.run", return_value=0) as run:
            rc = cli.main(["serve", "--port", "9"])
        assert rc == 0
        run.assert_called_once()
        assert run.call_args[0][0].port == 9

    def test_serve_sets_override_and_runs_gunicorn(self, isolated_config, tmp_path):
        sandbox = tmp_path / "sandbox"
        args = cli.build_parser().parse_args(
            ["serve", "--data-dir", str(sandbox), "--host", "127.0.0.1", "--port", "9"]
        )
        fake_app = MagicMock()
        hatchery_mod = MagicMock(app=fake_app)
        with (
            patch.dict("sys.modules", {"hatchery": hatchery_mod}),
            patch("lib.cli.serve._run_with_gunicorn") as run_guni,
        ):
            rc = serve_cmd.run(args)

        assert rc == 0
        assert Path(cfg.runtime_data_dir()) == sandbox.resolve()
        run_guni.assert_called_once()
        called_app, called_opts = run_guni.call_args[0]
        assert called_app is fake_app
        assert called_opts["bind"] == "127.0.0.1:9"
        assert called_opts["workers"] == 1

    def test_serve_sets_nest_local_flag(self, isolated_config, tmp_path):
        args = cli.build_parser().parse_args(
            ["serve", "--data-dir", str(tmp_path / "sandbox"), "--nest-local"]
        )
        fake_app = MagicMock()
        hatchery_mod = MagicMock(app=fake_app)
        with (
            patch.dict("sys.modules", {"hatchery": hatchery_mod}),
            patch("lib.cli.serve._run_with_gunicorn"),
        ):
            rc = serve_cmd.run(args)
        assert rc == 0
        assert cfg.runtime_nest_local() is True
        assert cfg.nest_local_enabled() is True
