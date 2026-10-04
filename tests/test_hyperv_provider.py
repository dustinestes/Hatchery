"""Mocked unit tests for HyperVProvider lifecycle (#213 PR A)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from lib.clutch import VMConfig
from lib.nest_transport import NestTransportError
from lib.providers.hyperv import (
    HyperVProvider,
    _JSON_MARKER,
    _extract_json,
    _local_powershell_exe,
    _map_state,
    _normalize_list,
    _ps_quote,
)


def _json_line(payload) -> str:
    return f"{_JSON_MARKER}{json.dumps(payload, separators=(',', ':'))}"


@pytest.fixture
def scripts():
    return []


@pytest.fixture
def provider(scripts):
    def runner(script: str) -> str:
        scripts.append(script)
        # Default ack for mutate scripts that end with ok marker write.
        if '{"ok":true}' in script or '"ok":true' in script:
            return _json_line({"ok": True})
        raise AssertionError(f"unexpected script without stub:\n{script}")

    return HyperVProvider("hv1", runner=runner)


class TestHelpers:
    def test_ps_quote_escapes(self):
        assert _ps_quote("a'b") == "'a''b'"

    def test_map_state(self):
        assert _map_state("Running") == "running"
        assert _map_state("Off") == "shut off"
        assert _map_state("Paused") == "paused"
        assert _map_state("Weird") == "weird"
        assert _map_state(None) == "unknown"
        assert _map_state("") == "unknown"

    def test_normalize_list_none(self):
        assert _normalize_list(None) == []

    def test_extract_json_variants(self):
        assert _extract_json(f"{_JSON_MARKER}") is None
        assert _extract_json('{"State":"Off"}') == {"State": "Off"}
        assert _extract_json('[{"Name":"a"}]') == [{"Name": "a"}]
        with pytest.raises(RuntimeError, match="no JSON"):
            _extract_json("noise only")

    def test_local_powershell_missing(self, monkeypatch):
        monkeypatch.setattr("lib.providers.hyperv.shutil.which", lambda _n: None)
        with pytest.raises(RuntimeError, match="PowerShell is required"):
            _local_powershell_exe()


class TestListAndStatus:
    def test_list_vms_empty(self, scripts):
        def runner(script: str) -> str:
            scripts.append(script)
            return _json_line([])

        p = HyperVProvider("hv1", runner=runner)
        assert p.list_vms() == []
        assert "Get-VM" in scripts[0]

    def test_list_vms_maps_states(self):
        def runner(script: str) -> str:
            return _json_line(
                [
                    {"Name": "a", "State": "Running"},
                    {"Name": "b", "State": "Off"},
                    {"Name": "c", "State": "Paused"},
                ]
            )

        p = HyperVProvider("hv1", runner=runner)
        assert p.list_vms() == [
            {"name": "a", "status": "running"},
            {"name": "b", "status": "shut off"},
            {"name": "c", "status": "paused"},
        ]

    def test_list_vms_single_object(self):
        def runner(script: str) -> str:
            return _json_line({"Name": "solo", "State": "Running"})

        p = HyperVProvider("hv1", runner=runner)
        assert p.list_vms() == [{"name": "solo", "status": "running"}]

    def test_get_status(self):
        def runner(script: str) -> str:
            assert "Get-VM -Name 'lab'" in script
            return _json_line({"State": "Running"})

        p = HyperVProvider("hv1", runner=runner)
        assert p.get_status("lab") == "running"


class TestPower:
    def test_start_stop_force_pause_resume(self, provider, scripts):
        provider.start_vm("vm1")
        provider.stop_vm("vm1")
        provider.force_stop_vm("vm1")
        provider.pause_vm("vm1")
        provider.resume_vm("vm1")
        joined = "\n".join(scripts)
        assert "Start-VM -Name 'vm1'" in joined
        assert "Stop-VM -Name 'vm1' -Force" in joined
        assert "Stop-VM -Name 'vm1' -TurnOff -Force" in joined
        assert "Suspend-VM -Name 'vm1'" in joined
        assert "Resume-VM -Name 'vm1'" in joined

    def test_destroy_removes_disks(self, provider, scripts):
        provider.destroy_vm("old")
        assert "Remove-VM -Name 'old' -Force" in scripts[0]
        assert "Remove-Item" in scripts[0]


class TestSnapshots:
    def test_create_list_revert_delete(self, scripts):
        calls = {"n": 0}

        def runner(script: str) -> str:
            scripts.append(script)
            calls["n"] += 1
            if "Get-VMSnapshot" in script:
                return _json_line(["snap-a", "snap-b"])
            return _json_line({"ok": True})

        p = HyperVProvider("hv1", runner=runner)
        p.create_snapshot("vm1", "snap-a")
        assert p.list_snapshots("vm1") == ["snap-a", "snap-b"]
        p.revert_snapshot("vm1", "snap-a")
        p.delete_snapshot("vm1", "snap-b")
        joined = "\n".join(scripts)
        assert "Checkpoint-VM -Name 'vm1' -SnapshotName 'snap-a'" in joined
        assert "Restore-VMSnapshot -Name 'snap-a' -VMName 'vm1'" in joined
        assert "Remove-VMSnapshot -VMName 'vm1' -Name 'snap-b'" in joined


class TestIdentity:
    def test_get_vm_ip(self):
        def runner(script: str) -> str:
            return _json_line({"Ip": "10.0.0.5"})

        p = HyperVProvider("hv1", runner=runner)
        assert p.get_vm_ip("vm1") == "10.0.0.5"

    def test_get_vm_ip_none(self):
        def runner(script: str) -> str:
            return _json_line({"Ip": None})

        p = HyperVProvider("hv1", runner=runner)
        assert p.get_vm_ip("vm1") is None

    def test_uuid_roundtrip(self):
        def runner(script: str) -> str:
            if "Where-Object" in script:
                return _json_line({"Name": "renamed"})
            return _json_line({"Id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"})

        p = HyperVProvider("hv1", runner=runner)
        assert p.get_vm_uuid("vm1") == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert p.get_vm_name_by_uuid("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee") == "renamed"

    def test_session_tag(self, scripts):
        def runner(script: str) -> str:
            scripts.append(script)
            if "Get-VM" in script and "Notes" in script:
                notes = 'hatchery-session:{"session_id":"s1","clutch_file":"lab.yaml"}'
                return _json_line({"Notes": notes})
            return _json_line({"ok": True})

        p = HyperVProvider("hv1", runner=runner)
        p.tag_vm_session("vm1", "s1", "lab.yaml")
        assert "Set-VM -Name 'vm1' -Notes" in scripts[0]
        assert p.get_vm_session_tag("vm1") == {
            "session_id": "s1",
            "clutch_file": "lab.yaml",
        }

    def test_session_tag_missing(self):
        def runner(script: str) -> str:
            return _json_line({"Notes": "operator note"})

        p = HyperVProvider("hv1", runner=runner)
        assert p.get_vm_session_tag("vm1") is None

    def test_set_poweroff_action(self, provider, scripts):
        provider.set_poweroff_action("vm1", "restart")
        assert "AutomaticStopAction ShutDown" in scripts[0]
        provider.set_poweroff_action("vm1", "destroy")
        assert "AutomaticStopAction TurnOff" in scripts[1]

    def test_set_poweroff_action_rejects_unknown(self, provider):
        with pytest.raises(ValueError, match="unsupported Hyper-V poweroff"):
            provider.set_poweroff_action("vm1", "suspend")


class TestDeferred:
    def test_create_vm_raises(self, provider):
        vm = VMConfig(
            name="new",
            os="windows",
            vcpus=2,
            ram_gb=4,
            disk_gb=40,
            os_media="win11.iso",
        )
        with pytest.raises(RuntimeError, match="create_vm"):
            provider.create_vm(vm)

    def test_send_key_raises(self, provider):
        with pytest.raises(RuntimeError, match="send_key"):
            provider.send_key("vm1", "KEY_ENTER")

    def test_nest_tool_specs(self):
        specs = HyperVProvider.nest_tool_specs()
        assert len(specs) == 1
        assert specs[0].name == "Get-VM"
        assert specs[0].check == "hyperv_get_vm"


class TestTransportPaths:
    def test_winrm_runs_script_directly(self):
        from lib.nest_transport import NestWinrmConfig, WinrmNestTransport

        winrm = WinrmNestTransport(NestWinrmConfig(host="n.example", username="u", password="p"))
        winrm.run = MagicMock(return_value=_json_line([]))
        p = HyperVProvider("hv1", transport=winrm)
        assert p.list_vms() == []
        cmd = winrm.run.call_args.args[0]
        assert "Get-VM" in cmd
        assert "-EncodedCommand" not in cmd

    def test_ssh_uses_encoded_command(self):
        from lib.nest_transport import NestSshConfig, SshNestTransport

        ssh = SshNestTransport(NestSshConfig(host="n.example", user="u"))
        ssh.run = MagicMock(return_value=_json_line([]))
        p = HyperVProvider("hv1", transport=ssh)
        assert p.list_vms() == []
        cmd = ssh.run.call_args.args[0]
        assert "powershell.exe" in cmd
        assert "-EncodedCommand" in cmd

    def test_transport_error_wrapped(self):
        from lib.nest_transport import NestSshConfig, SshNestTransport

        ssh = SshNestTransport(NestSshConfig(host="n.example", user="u"))
        ssh.run = MagicMock(side_effect=NestTransportError("boom"))
        p = HyperVProvider("hv1", transport=ssh)
        with pytest.raises(RuntimeError, match="boom"):
            p.list_vms()

    def test_local_run_cmd_success(self, monkeypatch):
        monkeypatch.setattr("lib.providers.hyperv._local_powershell_exe", lambda: "/bin/pwsh")
        mock_run = MagicMock(return_value=MagicMock(stdout=_json_line([])))
        monkeypatch.setattr("lib.providers.hyperv.run_cmd", mock_run)
        p = HyperVProvider("hv1")
        assert p.list_vms() == []
        argv = mock_run.call_args.args[0]
        assert argv[0] == "/bin/pwsh"
        assert "-EncodedCommand" in argv

    def test_local_run_cmd_failure(self, monkeypatch):
        import subprocess

        monkeypatch.setattr("lib.providers.hyperv._local_powershell_exe", lambda: "/bin/pwsh")

        def boom(*_a, **_k):
            raise subprocess.CalledProcessError(1, ["pwsh"], stderr="no module")

        monkeypatch.setattr("lib.providers.hyperv.run_cmd", boom)
        p = HyperVProvider("hv1")
        with pytest.raises(RuntimeError, match="no module"):
            p.list_vms()

    def test_discovery_errors_return_none(self):
        def runner(_script: str) -> str:
            raise RuntimeError("fail")

        p = HyperVProvider("hv1", runner=runner)
        assert p.get_vm_ip("vm1") is None
        assert p.get_vm_uuid("vm1") is None
        assert p.get_vm_name_by_uuid("u") is None
        assert p.get_vm_session_tag("vm1") is None
