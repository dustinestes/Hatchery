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
        sandbox.mkdir()
        args = cli.build_parser().parse_args(["nest", "--data-dir", str(sandbox), "list"])
        rc = nest_cmd.run(args)
        assert rc == 0
        assert "No Nests registered" in capsys.readouterr().out
        assert not (sandbox / "hatchery.db").exists()
        assert not (sandbox / "clutches").exists()

    def test_inspect_missing_data_dir_does_not_create(self, isolated_config, tmp_path, capsys):
        missing = tmp_path / "does-not-exist"
        for cmd in (
            ["clutch", "--data-dir", str(missing), "list"],
            ["nest", "--data-dir", str(missing), "list"],
            ["vm", "--data-dir", str(missing), "list"],
        ):
            args = cli.build_parser().parse_args(cmd)
            if cmd[0] == "clutch":
                rc = clutch_cmd.run(args)
            elif cmd[0] == "nest":
                rc = nest_cmd.run(args)
            else:
                rc = vm_cmd.run(args)
            assert rc == 1
            err = capsys.readouterr().err
            assert "does not exist" in err
            assert not missing.exists()

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
        sandbox.mkdir()
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

    def test_clutch_list_empty_dir_no_create(self, isolated_config, tmp_path, capsys):
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        args = cli.build_parser().parse_args(["clutch", "--data-dir", str(sandbox), "list"])
        assert clutch_cmd.run(args) == 0
        assert "No Clutch files" in capsys.readouterr().out
        assert not (sandbox / "hatchery.db").exists()
        assert not (sandbox / "clutches").exists()

    def test_vm_list_no_nest(self, isolated_config, tmp_path, capsys):
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        args = cli.build_parser().parse_args(["vm", "--data-dir", str(sandbox), "list"])
        rc = vm_cmd.run(args)
        assert rc == 1
        assert "No Nests registered" in capsys.readouterr().err
        assert not (sandbox / "hatchery.db").exists()

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

    def _seed_local_nest(self, sandbox: Path) -> None:
        from lib.cli import bootstrap

        bootstrap.apply_data_dir(str(sandbox))
        bootstrap.init_controller_runtime()
        nests_lib.ensure_local_nest()

    def test_vm_start_stop_destroy(self, isolated_config, tmp_path, capsys):
        sandbox = tmp_path / "sandbox"
        self._seed_local_nest(sandbox)
        fake = MagicMock()
        for cmd, method in (
            ("start", "start_vm"),
            ("stop", "stop_vm"),
            ("force-stop", "force_stop_vm"),
            ("pause", "pause_vm"),
            ("resume", "resume_vm"),
            ("destroy", "destroy_vm"),
        ):
            args = cli.build_parser().parse_args(
                ["vm", "--data-dir", str(sandbox), cmd, "--nest", "local", "dc01"]
            )
            with patch("lib.providers.factory.get_provider", return_value=fake):
                assert vm_cmd.run(args) == 0
            getattr(fake, method).assert_called_with("dc01")
        out = capsys.readouterr().out
        assert "Started" in out
        assert "Paused" in out
        assert "Resumed" in out
        assert "Destroyed" in out

    def test_vm_snap_take_list_apply_delete(self, isolated_config, tmp_path, capsys):
        sandbox = tmp_path / "sandbox"
        self._seed_local_nest(sandbox)
        fake = MagicMock()
        fake.list_snapshots.return_value = ["smoke"]
        parser = cli.build_parser()
        with patch("lib.providers.factory.get_provider", return_value=fake):
            assert (
                vm_cmd.run(
                    parser.parse_args(
                        [
                            "vm",
                            "--data-dir",
                            str(sandbox),
                            "snap",
                            "take",
                            "--nest",
                            "local",
                            "dc01",
                            "--label",
                            "smoke",
                        ]
                    )
                )
                == 0
            )
            assert (
                vm_cmd.run(
                    parser.parse_args(
                        [
                            "vm",
                            "--data-dir",
                            str(sandbox),
                            "snap",
                            "list",
                            "--nest",
                            "local",
                            "dc01",
                        ]
                    )
                )
                == 0
            )
            assert (
                vm_cmd.run(
                    parser.parse_args(
                        [
                            "vm",
                            "--data-dir",
                            str(sandbox),
                            "snap",
                            "apply",
                            "--nest",
                            "local",
                            "dc01",
                            "smoke",
                        ]
                    )
                )
                == 0
            )
            assert (
                vm_cmd.run(
                    parser.parse_args(
                        [
                            "vm",
                            "--data-dir",
                            str(sandbox),
                            "snap",
                            "delete",
                            "--nest",
                            "local",
                            "dc01",
                            "smoke",
                        ]
                    )
                )
                == 0
            )
        fake.create_snapshot.assert_called_with("dc01", "smoke")
        fake.revert_snapshot.assert_called_with("dc01", "smoke")
        fake.delete_snapshot.assert_called_with("dc01", "smoke")
        assert "smoke" in capsys.readouterr().out

    def test_vm_health_reachable(self, isolated_config, tmp_path, capsys):
        sandbox = tmp_path / "sandbox"
        self._seed_local_nest(sandbox)
        fake = MagicMock()
        args = cli.build_parser().parse_args(
            ["vm", "--data-dir", str(sandbox), "health", "--nest", "local", "dc01"]
        )
        with (
            patch("lib.providers.factory.get_provider", return_value=fake),
            patch(
                "lib.guest_health.guest_health",
                return_value={"ip": "10.0.0.2", "winrm": True, "reachable": True},
            ),
        ):
            assert vm_cmd.run(args) == 0
        assert "10.0.0.2" in capsys.readouterr().out

    def test_vm_health_unreachable(self, isolated_config, tmp_path):
        sandbox = tmp_path / "sandbox"
        self._seed_local_nest(sandbox)
        fake = MagicMock()
        args = cli.build_parser().parse_args(
            ["vm", "--data-dir", str(sandbox), "health", "--nest", "local", "dc01"]
        )
        with (
            patch("lib.providers.factory.get_provider", return_value=fake),
            patch(
                "lib.guest_health.guest_health",
                return_value={"ip": None, "winrm": False, "reachable": False},
            ),
        ):
            assert vm_cmd.run(args) == 1

    def test_hatch_parse_and_dispatch(self, isolated_config, tmp_path):
        args = cli.build_parser().parse_args(
            [
                "hatch",
                "--data-dir",
                str(tmp_path / "sandbox"),
                "--clutch",
                "lab.yaml",
                "--password",
                "dc01=s3cret",
                "--no-wait",
            ]
        )
        assert args.command == "hatch"
        assert args.clutch == "lab.yaml"
        with patch("lib.cli.hatch.run", return_value=0) as run:
            assert (
                cli.main(
                    [
                        "hatch",
                        "--clutch",
                        "lab.yaml",
                        "--password",
                        "dc01=x",
                    ]
                )
                == 0
            )
        run.assert_called_once()

    def test_hatch_missing_password(self, isolated_config, tmp_path, capsys):
        import lib.cli.hatch as hatch_cmd
        from lib import clutch as clutch_lib
        from lib.clutch import Clutch, VMConfig

        sandbox = tmp_path / "sandbox"
        self._seed_local_nest(sandbox)
        clutches = sandbox / "clutches"
        clutches.mkdir(parents=True, exist_ok=True)
        clutch = Clutch(
            name="Lab",
            vms=[
                VMConfig(
                    name="dc01",
                    os="win11",
                    vcpus=2,
                    ram_gb=4,
                    disk_gb=40,
                    os_media="win.iso",
                    admin_username="Administrator",
                )
            ],
        )
        clutch_lib.save(clutch, clutches / "lab.yaml")
        args = cli.build_parser().parse_args(
            ["hatch", "--data-dir", str(sandbox), "--clutch", "lab.yaml", "--nest", "local"]
        )
        with patch("lib.providers.factory.get_provider", return_value=MagicMock()):
            rc = hatch_cmd.run(args)
        assert rc == 1
        assert "Password required" in capsys.readouterr().err

    def test_hatch_runs_create_and_poll(self, isolated_config, tmp_path, capsys):
        import lib.cli.hatch as hatch_cmd
        from lib import clutch as clutch_lib
        from lib.clutch import Clutch, VMConfig

        sandbox = tmp_path / "sandbox"
        self._seed_local_nest(sandbox)
        clutches = sandbox / "clutches"
        clutches.mkdir(parents=True, exist_ok=True)
        clutch = Clutch(
            name="Lab",
            vms=[
                VMConfig(
                    name="dc01",
                    os="win11",
                    vcpus=2,
                    ram_gb=4,
                    disk_gb=40,
                    os_media="win.iso",
                )
            ],
        )
        clutch_lib.save(clutch, clutches / "lab.yaml")
        args = cli.build_parser().parse_args(
            [
                "hatch",
                "--data-dir",
                str(sandbox),
                "--clutch",
                "lab.yaml",
                "--nest",
                "local",
                "--no-wait",
            ]
        )
        preflight = MagicMock()
        preflight.ok = True
        with (
            patch("lib.providers.factory.get_provider", return_value=MagicMock()),
            patch("lib.nest_cache.preflight_clutch", return_value=preflight),
            patch(
                "lib.hatch_lifecycle.create_and_start_hatch",
                return_value="sess-1",
            ) as create,
        ):
            rc = hatch_cmd.run(args)
        assert rc == 0
        create.assert_called_once()
        assert create.call_args.kwargs["background"] is False
        assert "sess-1" in capsys.readouterr().out

    def test_session_list_and_show(self, isolated_config, tmp_path, capsys):
        import lib.cli.session as session_cmd
        import lib.hatch as hatch_lib

        sandbox = tmp_path / "sandbox"
        self._seed_local_nest(sandbox)
        sid = hatch_lib.create_session("lab.yaml", "Lab", nest="local")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.set_vm_status(sid, "dc01", "hatching")
        hatch_lib.add_event(sid, "dc01", "hatchery", "INFO", "Creating VM")

        list_args = cli.build_parser().parse_args(
            ["session", "--data-dir", str(sandbox), "list", "--nest", "local"]
        )
        assert session_cmd.run(list_args) == 0
        out = capsys.readouterr().out
        assert sid[:8] in out
        assert "lab.yaml" in out
        assert "in_progress" in out

        show_args = cli.build_parser().parse_args(
            ["session", "--data-dir", str(sandbox), "show", sid]
        )
        assert session_cmd.run(show_args) == 0
        show_out = capsys.readouterr().out
        assert "dc01: hatching" in show_out
        assert "Creating VM" in show_out

    def test_session_show_missing(self, isolated_config, tmp_path, capsys):
        import lib.cli.session as session_cmd

        sandbox = tmp_path / "sandbox"
        self._seed_local_nest(sandbox)
        args = cli.build_parser().parse_args(
            ["session", "--data-dir", str(sandbox), "show", "no-such-session"]
        )
        assert session_cmd.run(args) == 1
        assert "not found" in capsys.readouterr().err.lower()

    def test_main_dispatches_session(self):
        with patch("lib.cli.session.run", return_value=0) as run:
            assert cli.main(["session", "list"]) == 0
        run.assert_called_once()

    def test_session_retry_queued(self, isolated_config, tmp_path, capsys):
        import lib.cli.session as session_cmd
        import lib.hatch as hatch_lib

        sandbox = tmp_path / "sandbox"
        self._seed_local_nest(sandbox)
        sid = hatch_lib.create_session("lab.yaml", "Lab", nest="local")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.set_vm_status(sid, "dc01", "failed", error="boom")
        args = cli.build_parser().parse_args(
            ["session", "--data-dir", str(sandbox), "retry", sid, "dc01"]
        )
        with patch(
            "lib.hatch_lifecycle.retry_failed_vm",
            return_value={"queued": True, "message": None},
        ) as retry:
            assert session_cmd.run(args) == 0
        retry.assert_called_once_with(sid, "dc01")
        assert "queued" in capsys.readouterr().out.lower()

    def test_session_retry_not_failed(self, isolated_config, tmp_path, capsys):
        import lib.cli.session as session_cmd
        from lib.hatch_lifecycle import RetryError

        sandbox = tmp_path / "sandbox"
        self._seed_local_nest(sandbox)
        args = cli.build_parser().parse_args(
            ["session", "--data-dir", str(sandbox), "retry", "sid", "dc01"]
        )
        with patch(
            "lib.hatch_lifecycle.retry_failed_vm",
            side_effect=RetryError("VM is not in a failed state", code="not_failed"),
        ):
            assert session_cmd.run(args) == 1
        assert "failed state" in capsys.readouterr().err


class TestJsonOutput:
    """Global ``--json`` on inspect/list/show (#423)."""

    def _seed(self, sandbox: Path) -> None:
        from lib.cli import bootstrap

        bootstrap.apply_data_dir(str(sandbox))
        bootstrap.init_controller_runtime()
        nests_lib.ensure_local_nest()

    def test_nest_list_json(self, isolated_config, tmp_path, capsys):
        import json

        sandbox = tmp_path / "sandbox"
        self._seed(sandbox)
        args = cli.build_parser().parse_args(["--json", "nest", "--data-dir", str(sandbox), "list"])
        assert nest_cmd.run(args) == 0
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload, list)
        assert payload[0]["id"] == "local"
        assert payload[0]["provider_type"] == "libvirt"

    def test_clutch_show_json(self, isolated_config, tmp_path, capsys):
        import json

        sandbox = tmp_path / "sandbox"
        self._seed(sandbox)
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
        args = cli.build_parser().parse_args(
            ["--json", "clutch", "--data-dir", str(sandbox), "show", "lab.yaml"]
        )
        assert clutch_cmd.run(args) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["name"] == "Lab"
        assert payload["file"] == "lab.yaml"
        assert payload["vms"][0]["name"] == "dc01"

    def test_session_list_json(self, isolated_config, tmp_path, capsys):
        import json
        import lib.cli.session as session_cmd
        import lib.hatch as hatch_lib

        sandbox = tmp_path / "sandbox"
        self._seed(sandbox)
        sid = hatch_lib.create_session("lab.yaml", "Lab", nest="local")
        args = cli.build_parser().parse_args(
            ["--json", "session", "--data-dir", str(sandbox), "list", "--nest", "local"]
        )
        assert session_cmd.run(args) == 0
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload, list)
        assert payload[0]["id"] == sid
        assert payload[0]["clutch_file"] == "lab.yaml"


class TestMediaAndScriptsList:
    def _seed(self, sandbox: Path) -> None:
        from lib.cli import bootstrap

        bootstrap.apply_data_dir(str(sandbox))
        bootstrap.init_controller_runtime()

    def test_media_list_and_type_filter(self, isolated_config, tmp_path, capsys):
        import lib.cli.media as media_cmd

        sandbox = tmp_path / "sandbox"
        self._seed(sandbox)
        iso_dir = cfg.data_dir() / "media" / "iso"
        virtio_dir = cfg.data_dir() / "media" / "virtio"
        iso_dir.mkdir(parents=True, exist_ok=True)
        virtio_dir.mkdir(parents=True, exist_ok=True)
        (iso_dir / "win11.iso").write_bytes(b"iso")
        (virtio_dir / "virtio.iso").write_bytes(b"virtio")

        args = cli.build_parser().parse_args(["media", "--data-dir", str(sandbox), "list"])
        assert media_cmd.run(args) == 0
        out = capsys.readouterr().out
        assert "win11.iso" in out
        assert "virtio.iso" in out

        args = cli.build_parser().parse_args(
            ["media", "--data-dir", str(sandbox), "list", "--type", "iso"]
        )
        assert media_cmd.run(args) == 0
        out = capsys.readouterr().out
        assert "win11.iso" in out
        assert "virtio.iso" not in out

    def test_scripts_list(self, isolated_config, tmp_path, capsys):
        import lib.cli.scripts as scripts_cmd

        sandbox = tmp_path / "sandbox"
        self._seed(sandbox)
        scripts = cfg.data_dir() / "automation" / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "setup.ps1").write_text("# setup\n")

        args = cli.build_parser().parse_args(["scripts", "--data-dir", str(sandbox), "list"])
        assert scripts_cmd.run(args) == 0
        out = capsys.readouterr().out
        assert "setup.ps1" in out
        assert "PowerShell" in out

    def test_media_list_json(self, isolated_config, tmp_path, capsys):
        import json
        import lib.cli.media as media_cmd

        sandbox = tmp_path / "sandbox"
        self._seed(sandbox)
        iso_dir = cfg.data_dir() / "media" / "iso"
        iso_dir.mkdir(parents=True, exist_ok=True)
        (iso_dir / "win11.iso").write_bytes(b"iso")
        args = cli.build_parser().parse_args(
            ["--json", "media", "--data-dir", str(sandbox), "list", "--type", "iso"]
        )
        assert media_cmd.run(args) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["media"][0]["name"] == "win11.iso"
        assert payload["media"][0]["type"] == "iso"

    def test_main_dispatches_media_and_scripts(self):
        with patch("lib.cli.media.run", return_value=0) as run:
            assert cli.main(["media", "list"]) == 0
        run.assert_called_once()
        with patch("lib.cli.scripts.run", return_value=0) as run:
            assert cli.main(["scripts", "list"]) == 0
        run.assert_called_once()
