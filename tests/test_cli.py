"""Tests for Hatchery Controller CLI (#22 / #23 / ADR-0013)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import lib.cli as cli
import lib.cli.clutch as clutch_cmd
import lib.cli.nest as nest_cmd
import lib.cli.serve as serve_cmd
import lib.cli.vm as vm_cmd
import lib.config as cfg
import lib.db as db_module
import lib.nests as nests_lib


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

    def test_nest_list_parse(self):
        args = cli.build_parser().parse_args(["nest", "--data-dir", "/tmp/x", "list"])
        assert args.command == "nest"
        assert args.nest_command == "list"
        assert args.data_dir == "/tmp/x"

    def test_vm_list_nest_flag(self):
        args = cli.build_parser().parse_args(["vm", "list", "--nest", "local"])
        assert args.command == "vm"
        assert args.vm_command == "list"
        assert args.nest == "local"

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

    def test_main_dispatches_nest(self):
        with patch("lib.cli.nest.run", return_value=0) as run:
            rc = cli.main(["nest", "list"])
        assert rc == 0
        run.assert_called_once()

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


class TestOperatorInspect:
    def test_nest_list_empty(self, isolated_config, tmp_path, capsys):
        sandbox = tmp_path / "sandbox"
        args = cli.build_parser().parse_args(["nest", "--data-dir", str(sandbox), "list"])
        rc = nest_cmd.run(args)
        assert rc == 0
        assert "No Nests registered" in capsys.readouterr().out

    def test_nest_list_shows_local(self, isolated_config, tmp_path, capsys):
        sandbox = tmp_path / "sandbox"
        args = cli.build_parser().parse_args(["nest", "--data-dir", str(sandbox), "list"])
        # Bootstrap then seed Local in that data dir.
        from lib.cli import bootstrap

        bootstrap.apply_data_dir(str(sandbox))
        bootstrap.init_controller_runtime()
        nests_lib.ensure_local_nest()
        rc = nest_cmd.run(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "local" in out
        assert "Local" in out

    def test_nest_test_unknown(self, isolated_config, tmp_path, capsys):
        sandbox = tmp_path / "sandbox"
        args = cli.build_parser().parse_args(
            ["nest", "--data-dir", str(sandbox), "test", "missing"]
        )
        rc = nest_cmd.run(args)
        assert rc == 1
        assert "Unknown Nest" in capsys.readouterr().err

    def test_nest_test_ok(self, isolated_config, tmp_path, capsys):
        sandbox = tmp_path / "sandbox"
        from lib.cli import bootstrap

        bootstrap.apply_data_dir(str(sandbox))
        bootstrap.init_controller_runtime()
        nests_lib.ensure_local_nest()
        args = cli.build_parser().parse_args(["nest", "--data-dir", str(sandbox), "test", "local"])
        with patch(
            "lib.nests.test_connection",
            return_value={"ok": True, "message": "Local Nest OK"},
        ):
            rc = nest_cmd.run(args)
        assert rc == 0
        assert "Local Nest OK" in capsys.readouterr().out

    def test_clutch_list_and_show(self, isolated_config, tmp_path, capsys):
        sandbox = tmp_path / "sandbox"
        from lib.cli import bootstrap

        bootstrap.apply_data_dir(str(sandbox))
        bootstrap.init_controller_runtime()
        clutches = cfg.data_dir() / "clutches"
        clutches.mkdir(parents=True, exist_ok=True)
        (clutches / "lab.yaml").write_text(
            "name: Lab\n"
            "description: Demo\n"
            "vms:\n"
            "  - name: dc01\n"
            "    os: win11\n"
            "    vcpus: 2\n"
            "    ram_gb: 4\n"
            "    disk_gb: 60\n"
            "    os_media: win11.iso\n"
        )
        list_args = cli.build_parser().parse_args(["clutch", "--data-dir", str(sandbox), "list"])
        assert clutch_cmd.run(list_args) == 0
        assert "lab.yaml" in capsys.readouterr().out

        show_args = cli.build_parser().parse_args(
            ["clutch", "--data-dir", str(sandbox), "show", "lab.yaml"]
        )
        assert clutch_cmd.run(show_args) == 0
        out = capsys.readouterr().out
        assert "name: Lab" in out
        assert "dc01" in out

    def test_vm_list_no_nest(self, isolated_config, tmp_path, capsys):
        sandbox = tmp_path / "sandbox"
        args = cli.build_parser().parse_args(["vm", "--data-dir", str(sandbox), "list"])
        rc = vm_cmd.run(args)
        assert rc == 1
        assert "No Nests registered" in capsys.readouterr().err

    def test_vm_list_mocked_provider(self, isolated_config, tmp_path, capsys):
        sandbox = tmp_path / "sandbox"
        from lib.cli import bootstrap

        bootstrap.apply_data_dir(str(sandbox))
        bootstrap.init_controller_runtime()
        nests_lib.ensure_local_nest()
        fake = MagicMock()
        fake.list_vms.return_value = [{"name": "dc01", "status": "running"}]
        args = cli.build_parser().parse_args(
            ["vm", "--data-dir", str(sandbox), "list", "--nest", "local"]
        )
        with patch("lib.providers.factory.get_provider", return_value=fake):
            rc = vm_cmd.run(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "dc01" in out
        assert "running" in out

    def test_vm_list_remote_unsupported(self, isolated_config, tmp_path, capsys):
        sandbox = tmp_path / "sandbox"
        from lib.cli import bootstrap
        from lib.providers.factory import UnsupportedProviderError

        bootstrap.apply_data_dir(str(sandbox))
        bootstrap.init_controller_runtime()
        nests_lib.replace_nests(
            [
                {
                    "id": "remote1",
                    "name": "Remote",
                    "provider_type": "libvirt",
                    "location": "remote",
                    "host": "r.example",
                }
            ]
        )
        args = cli.build_parser().parse_args(
            ["vm", "--data-dir", str(sandbox), "list", "--nest", "remote1"]
        )
        with patch(
            "lib.providers.factory.get_provider",
            side_effect=UnsupportedProviderError("Remote Nest 'remote1' not available"),
        ):
            rc = vm_cmd.run(args)
        assert rc == 1
        assert "not available" in capsys.readouterr().err.lower()
