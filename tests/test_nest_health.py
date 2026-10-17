"""Nest Health gather (#538) - mocked; no live Nest."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import lib.config as config
import lib.db as db_module
from lib import nest_health as nh
from lib.nest_transport import NestHealthCheckResult


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(config, "DEFAULT_DATA_DIR", data)
    monkeypatch.setattr(config, "data_dir", lambda: data)
    monkeypatch.setattr(config, "_config", {})
    monkeypatch.setattr(config, "_pending_yaml_settings", {})
    monkeypatch.setattr(config, "_db_bound", False)
    monkeypatch.setattr(config, "_runtime_data_dir", None)
    monkeypatch.setattr(config, "_bootstrap_data_dir", None)
    db_module.init_db(data / "hatchery.db")
    config.bind_db()
    yield
    db_module._db_path = None
    config.set_runtime_data_dir(None)


class TestVolumeStorageStatus:
    def test_disconnected_without_disks(self):
        st = nh.volume_storage_status("/var/lib/libvirt/images", [])
        assert st["status"] == "Disconnected"

    def test_connected_and_warn_error(self):
        disks = [
            {
                "mount": "/",
                "path": "/",
                "total_bytes": 100 * 1024**3,
                "used_bytes": 90 * 1024**3,
                "free_bytes": 10 * 1024**3 - 1,
            }
        ]
        st = nh.volume_storage_status("/var/lib/libvirt/images", disks)
        assert st["status"] == "Error"
        disks[0]["free_bytes"] = 15 * 1024**3
        disks[0]["used_bytes"] = 85 * 1024**3
        st = nh.volume_storage_status("/home/vms", disks)
        assert st["status"] == "Warn"
        disks[0]["free_bytes"] = 50 * 1024**3
        disks[0]["used_bytes"] = 50 * 1024**3
        st = nh.volume_storage_status("/home/vms/disk", disks)
        assert st["status"] == "Connected"

    def test_windows_path_matches_drive(self):
        disks = [
            {
                "mount": "C:",
                "path": "C:\\",
                "total_bytes": 100 * 1024**3,
                "used_bytes": 40 * 1024**3,
                "free_bytes": 60 * 1024**3,
            }
        ]
        st = nh.volume_storage_status(r"C:\Hatchery\VMs", disks)
        assert st["status"] == "Connected"
        assert st["mount"] == "C:"
        assert st["free_bytes"] == 60 * 1024**3
        # Forward slashes / mixed case still match.
        st = nh.volume_storage_status("c:/Hatchery/VMs", disks)
        assert st["status"] == "Connected"

    def test_empty_path_and_unmatched(self):
        assert nh.volume_storage_status("", [{"mount": "/"}])["status"] == "Disconnected"
        assert (
            nh.volume_storage_status("/other", [{"mount": "/data", "path": "/data"}])["status"]
            == "Disconnected"
        )

    def test_connected_without_byte_stats(self):
        disks = [{"mount": "/data", "path": "/data", "free_bytes": None, "total_bytes": None}]
        st = nh.volume_storage_status("/data/vms", disks)
        assert st["status"] == "Connected"


class TestParseHelpers:
    def test_disks_from_df(self):
        stdout = (
            "Filesystem     1B-blocks        Used   Available Use% Mounted on\n"
            "/dev/sda1   100000000000  40000000000  60000000000  40% /\n"
            "tmpfs          1000000000           0  1000000000   0% /dev/shm\n"
        )
        disks = nh._disks_from_df(stdout)
        assert len(disks) == 1
        assert disks[0]["mount"] == "/"
        assert disks[0]["free_bytes"] == 60000000000

    def test_parse_meminfo_text(self):
        text = "MemTotal:       2048000 kB\nMemAvailable:   1024000 kB\n"
        mem = nh._parse_meminfo_text(text)
        assert mem is not None
        assert mem["total_bytes"] == 2048000 * 1024
        assert mem["free_bytes"] == 1024000 * 1024

    def test_disks_from_win_json(self):
        stdout = (
            '[{"DeviceID":"C:","Size":1000,"FreeSpace":400},'
            '{"DeviceID":"D:","Size":null,"FreeSpace":null}]'
        )
        disks = nh._disks_from_win_json(stdout)
        assert len(disks) == 1
        assert disks[0]["mount"] == "C:"
        assert disks[0]["total_bytes"] == 1000
        assert disks[0]["free_bytes"] == 400
        assert disks[0]["used_bytes"] == 600
        assert nh._disks_from_win_json("not-json") == []


class TestRunHealth:
    def test_gate_fail_skips_deeper(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        nest = {
            "id": "r1",
            "name": "Remote",
            "location": "remote",
            "transport": "ssh",
            "host": "nest.example",
            "provider_type": "libvirt",
        }
        fail = NestHealthCheckResult(ok=False, detail="down", failure_class="endpoint")
        with (
            patch("lib.nest_reachability.probe_nest", return_value=fail),
            patch("lib.nest_reachability.record_probe") as record,
            patch("lib.nest_reachability.sync_alert_for_probe"),
            patch("lib.requirements.check_nest") as check_nest,
        ):
            result = nh.run_health(nest, persist=True, sync_alerts=True)
        assert result["ok"] is False
        assert result["deeper_ran"] is False
        assert result["cpu"] is None
        assert result["disks"] == []
        assert result["prerequisites"] == []
        check_nest.assert_not_called()
        record.assert_called_once()
        stored = nh.get_health("r1")
        assert stored is not None
        assert stored["ok"] is False

    def test_gate_ok_runs_deeper_local(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        nest = {
            "id": "local",
            "name": "Local",
            "location": "local",
            "provider_type": "libvirt",
        }
        ok = NestHealthCheckResult(ok=True, detail="Local Nest OK")
        from lib.requirements import Requirement

        fake_req = Requirement(
            name="virsh",
            package="libvirt-clients",
            required_for="manage VMs",
            present=True,
            optional=False,
            install_hint="apt install libvirt-clients",
        )
        with (
            patch("lib.nest_reachability.probe_nest", return_value=ok),
            patch("lib.nest_reachability.record_probe"),
            patch("lib.nest_reachability.sync_alert_for_probe"),
            patch(
                "lib.nest_health._gather_resources_local",
                return_value={
                    "cpu": {"count": 4, "utilization_percent": None},
                    "memory": {
                        "total_bytes": 8 * 1024**3,
                        "used_bytes": 2 * 1024**3,
                        "free_bytes": 6 * 1024**3,
                    },
                    "disks": [
                        {
                            "mount": "/",
                            "path": "/",
                            "total_bytes": 100,
                            "used_bytes": 40,
                            "free_bytes": 60,
                            "state": "ok",
                        }
                    ],
                },
            ),
            patch("lib.requirements.check_nest", return_value=[fake_req]),
        ):
            result = nh.run_health(nest, persist=True, sync_alerts=False)
        assert result["ok"] is True
        assert result["deeper_ran"] is True
        assert result["cpu"]["count"] == 4
        assert result["memory"]["total_bytes"] == 8 * 1024**3
        assert len(result["disks"]) == 1
        assert result["prerequisites"][0]["name"] == "virsh"
        assert result["prerequisites"][0]["present"] is True

    def test_remote_ssh_resources_mocked(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        nest = {
            "id": "lab",
            "name": "Lab",
            "location": "remote",
            "transport": "ssh",
            "host": "10.0.0.2",
            "provider_type": "libvirt",
        }
        ok = NestHealthCheckResult(ok=True, detail="transport OK")
        transport = MagicMock()

        def fake_run(cmd):
            if "nproc" in cmd:
                return "8\n"
            if "meminfo" in cmd:
                return "MemTotal: 4096000 kB\nMemAvailable: 2048000 kB\n"
            if "df " in cmd:
                return (
                    "Filesystem 1B-blocks Used Available Use% Mounted on\n"
                    "/dev/vda1 200000000000 50000000000 150000000000 25% /\n"
                )
            return ""

        transport.run.side_effect = fake_run
        with (
            patch("lib.nest_reachability.probe_nest", return_value=ok),
            patch("lib.nest_reachability.record_probe"),
            patch("lib.nest_reachability.sync_alert_for_probe"),
            patch("lib.nests.to_connection_config", return_value=MagicMock()),
            patch("lib.nest_health.get_nest_transport", return_value=transport),
            patch("lib.requirements.check_nest", return_value=[]),
        ):
            result = nh.run_health(nest, persist=False, sync_alerts=False)
        assert result["deeper_ran"] is True
        assert result["cpu"]["count"] == 8
        assert result["memory"]["total_bytes"] == 4096000 * 1024
        assert result["disks"][0]["mount"] == "/"

    def test_remote_hyperv_ssh_uses_windows_resources(self, tmp_path, monkeypatch):
        """Hyper-V over SSH must not use POSIX df (empty disks on Windows Nests)."""
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        nest = {
            "id": "hv",
            "name": "HV",
            "location": "remote",
            "transport": "ssh",
            "host": "10.0.0.3",
            "provider_type": "hyperv",
            "ssh_user": "Developer",
        }
        ok = NestHealthCheckResult(ok=True, detail="transport OK")
        with (
            patch("lib.nest_reachability.probe_nest", return_value=ok),
            patch("lib.nest_reachability.record_probe"),
            patch("lib.nest_reachability.sync_alert_for_probe"),
            patch("lib.nests.to_connection_config", return_value=MagicMock()),
            patch("lib.nest_health.get_nest_transport", return_value=MagicMock()),
            patch(
                "lib.nest_health._gather_resources_windows",
                return_value={
                    "cpu": {"count": 4, "utilization_percent": None},
                    "memory": {
                        "total_bytes": 8 * 1024**3,
                        "free_bytes": 3 * 1024**3,
                        "used_bytes": 5 * 1024**3,
                    },
                    "disks": [
                        {
                            "filesystem": "C:",
                            "mount": "C:",
                            "path": "C:\\",
                            "total_bytes": 1000,
                            "used_bytes": 600,
                            "free_bytes": 400,
                            "state": "ok",
                        }
                    ],
                },
            ) as win_gather,
            patch("lib.nest_health._gather_resources_ssh") as posix_gather,
            patch("lib.requirements.check_nest", return_value=[]),
        ):
            result = nh.run_health(nest, persist=False, sync_alerts=False)
        win_gather.assert_called_once()
        posix_gather.assert_not_called()
        assert result["disks"][0]["mount"] == "C:"
        assert result["cpu"]["count"] == 4


class TestMigrateValidatorSettings:
    def test_copies_reachability_once(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        from lib import config as config_lib

        config_lib.update_settings(
            {
                "validators": {
                    "nest_reachability": {"enabled": True, "interval_seconds": 90},
                }
            }
        )
        nh.migrate_reachability_validator_settings()
        stored = config_lib.get().get("validators") or {}
        assert stored["nest_health"]["enabled"] is True
        assert stored["nest_health"]["interval_seconds"] == 90
        # Second call does not overwrite nest_health.
        config_lib.update_settings(
            {
                "validators": {
                    **stored,
                    "nest_reachability": {"enabled": False, "interval_seconds": 30},
                }
            }
        )
        nh.migrate_reachability_validator_settings()
        assert config_lib.get()["validators"]["nest_health"]["interval_seconds"] == 90


class TestRunAsValidator:
    def test_summarizes_gate_failures(self):
        nest = {
            "id": "r1",
            "name": "Lab",
            "location": "remote",
            "transport": "ssh",
            "host": "h",
            "provider_type": "libvirt",
        }
        fail = NestHealthCheckResult(ok=False, detail="down", failure_class="endpoint")
        ctx = MagicMock(nest_id=None, winrm_password=None)
        with (
            patch("lib.nests.list_nests", return_value=[nest]),
            patch("lib.nest_reachability.probe_nest", return_value=fail),
            patch("lib.nest_reachability.record_probe"),
            patch("lib.nest_reachability.sync_alert_for_probe"),
            patch("lib.nest_reachability.record_last_run"),
        ):
            summary = nh.run_as_validator(ctx, sync_alerts=True)
        assert "1 of 1" in summary
        ctx.note_finding.assert_called()


class TestResourceParsers:
    def test_disks_from_win_json(self):
        disks = nh._disks_from_win_json('[{"DeviceID":"C:","Size":1000,"FreeSpace":400}]')
        assert len(disks) == 1
        assert disks[0]["mount"] == "C:"
        assert disks[0]["free_bytes"] == 400

    def test_gather_winrm_mocked(self):
        def fake_ps(_transport, script, timeout=30):
            if "NumberOfLogicalProcessors" in script:
                return "16\n"
            if "TotalVisibleMemorySize" in script:
                return '{"total":8589934592,"free":2147483648}'
            if "Win32_LogicalDisk" in script:
                return '[{"DeviceID":"C:","Size":2000,"FreeSpace":500}]'
            return ""

        with patch("lib.nest_health._run_windows_ps", side_effect=fake_ps):
            out = nh._gather_resources_winrm(MagicMock())
        assert out["cpu"]["count"] == 16
        assert out["memory"]["total_bytes"] == 8589934592
        assert out["disks"][0]["mount"] == "C:"

    def test_prune_removed(self):
        nest = {"id": "gone", "name": "G"}
        ok = NestHealthCheckResult(ok=True, detail="ok")
        with (
            patch("lib.nest_reachability.probe_nest", return_value=ok),
            patch("lib.nest_reachability.record_probe"),
            patch("lib.nest_reachability.sync_alert_for_probe"),
            patch(
                "lib.nest_health._gather_resources_local",
                return_value={"cpu": None, "memory": None, "disks": []},
            ),
            patch("lib.requirements.check_nest", return_value=[]),
        ):
            nh.run_health(
                {**nest, "location": "local", "provider_type": "libvirt"},
                persist=True,
                sync_alerts=False,
            )
        assert nh.get_health("gone") is not None
        nh.prune_removed_nests(set())
        assert nh.get_health("gone") is None

    def test_parse_json_noise(self):
        assert nh._parse_json_object('progress\n{"a":1}') == {"a": 1}
        assert nh._parse_int_line("\n  42 \n") == 42

    def test_local_memory_darwin_mocked(self, monkeypatch):
        monkeypatch.setattr(nh.platform, "system", lambda: "Darwin")

        def fake_run(argv, **kwargs):
            cmd = argv[0] if argv else ""
            if cmd == "pagesize":
                return MagicMock(stdout="4096\n", returncode=0)
            if cmd == "vm_stat":
                return MagicMock(
                    stdout="Pages free: 100.\nPages speculative: 50.\n",
                    returncode=0,
                )
            if cmd == "sysctl":
                return MagicMock(stdout="8589934592\n", returncode=0)
            return MagicMock(stdout="", returncode=1)

        with patch("lib.nest_health.subprocess.run", side_effect=fake_run):
            mem = nh._local_memory()
        assert mem is not None
        assert mem["total_bytes"] == 8589934592

    def test_local_memory_windows_mocked(self, monkeypatch):
        monkeypatch.setattr(nh.platform, "system", lambda: "Windows")
        monkeypatch.setattr(
            nh.shutil, "which", lambda name: "/usr/bin/pwsh" if name == "pwsh" else None
        )
        with patch(
            "lib.nest_health.subprocess.run",
            return_value=MagicMock(
                stdout='{"total":4096,"free":1024}',
                returncode=0,
            ),
        ):
            mem = nh._local_memory()
        assert mem == {
            "total_bytes": 4096,
            "free_bytes": 1024,
            "used_bytes": 3072,
        }

    def test_local_disks_windows_mocked(self, monkeypatch):
        monkeypatch.setattr(nh.platform, "system", lambda: "Windows")
        monkeypatch.setattr(
            nh.shutil, "which", lambda name: "/usr/bin/pwsh" if name == "pwsh" else None
        )
        with patch(
            "lib.nest_health.subprocess.run",
            return_value=MagicMock(
                stdout='[{"DeviceID":"D:","Size":5000,"FreeSpace":1000}]',
                returncode=0,
            ),
        ):
            disks = nh._local_disks()
        assert disks[0]["mount"] == "D:"

    def test_gather_resources_remote_winrm_no_password(self):
        nest = {
            "id": "w",
            "location": "remote",
            "transport": "winrm",
            "host": "h",
            "provider_type": "hyperv",
        }
        out = nh._gather_resources(nest, winrm_password=None)
        assert out == {"cpu": None, "memory": None, "disks": []}

    def test_run_df_local_and_parse_int(self):
        with patch(
            "lib.nest_health.subprocess.run",
            return_value=MagicMock(
                stdout=(
                    "Filesystem 1B-blocks Used Available Use% Mounted on\n"
                    "/dev/sda1 100 40 60 40% /data\n"
                ),
                returncode=0,
            ),
        ):
            disks = nh._disks_from_df(nh._run_df_local())
        assert disks[0]["mount"] == "/data"
        assert nh._parse_json_value("") is None
        assert nh._parse_json_value("not-json") is None

    def test_local_cpu_and_gather_local(self, monkeypatch):
        monkeypatch.setattr(nh.os, "cpu_count", lambda: 6)
        assert nh._local_cpu() == {"count": 6, "utilization_percent": None}
        with (
            patch(
                "lib.nest_health._local_cpu", return_value={"count": 1, "utilization_percent": None}
            ),
            patch("lib.nest_health._local_memory", return_value=None),
            patch("lib.nest_health._local_disks", return_value=[]),
        ):
            assert nh._gather_resources_local()["cpu"]["count"] == 1

    def test_gather_resources_config_error(self):
        nest = {
            "id": "r",
            "location": "remote",
            "transport": "ssh",
            "host": "h",
            "provider_type": "libvirt",
        }
        with patch("lib.nests.to_connection_config", side_effect=ValueError("bad")):
            out = nh._gather_resources(nest)
        assert out["disks"] == []

    def test_ssh_gather_handles_transport_errors(self):
        transport = MagicMock()
        transport.run.side_effect = RuntimeError("boom")
        out = nh._gather_resources_ssh(transport)
        assert out == {"cpu": None, "memory": None, "disks": []}
