"""Guest transport: SSH primary / WinRM fallback (#497). Mocked; no live guest."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lib import guest_transport as gt
from lib.guest_transport import GuestEndpoint, SshGuestTransport, WinrmGuestTransport


class TestGuestEndpoint:
    def test_requires_host_and_user(self):
        with pytest.raises(ValueError, match="host"):
            GuestEndpoint(host="", username="a", password="p")
        with pytest.raises(ValueError, match="username"):
            GuestEndpoint(host="10.0.0.1", username="", password="p")


class TestResolveGuestTransport:
    def test_prefers_ssh_when_probe_ok(self):
        ssh = MagicMock(spec=SshGuestTransport)
        ssh.kind = "ssh"
        ssh.test_connection.return_value = True
        with (
            patch("lib.guest_transport.check_ssh", return_value=True),
            patch("lib.guest_transport.SshGuestTransport", return_value=ssh),
        ):
            t = gt.resolve_guest_transport("10.0.0.1", "admin", "pw")
        assert t is ssh

    def test_falls_back_to_winrm_with_callback(self):
        ssh = MagicMock(spec=SshGuestTransport)
        ssh.kind = "ssh"
        ssh.test_connection.return_value = False
        winrm = MagicMock(spec=WinrmGuestTransport)
        winrm.kind = "winrm"
        winrm.test_connection.return_value = True
        reasons: list[str] = []
        with (
            patch("lib.guest_transport.check_ssh", return_value=True),
            patch("lib.guest_transport.check_winrm", return_value=True),
            patch("lib.guest_transport.SshGuestTransport", return_value=ssh),
            patch("lib.guest_transport.WinrmGuestTransport", return_value=winrm),
        ):
            t = gt.resolve_guest_transport(
                "10.0.0.1",
                "admin",
                "pw",
                on_fallback=reasons.append,
            )
        assert t is winrm
        assert reasons
        assert "WinRM" in reasons[0]

    def test_raises_when_neither_available(self):
        with (
            patch("lib.guest_transport.check_ssh", return_value=False),
            patch("lib.guest_transport.check_winrm", return_value=False),
        ):
            with pytest.raises(gt.GuestTransportError, match="No guest remoting"):
                gt.resolve_guest_transport("10.0.0.1", "admin", "pw")


class TestSshGuestTransport:
    def test_run_ps_uses_encoded_command(self):
        endpoint = GuestEndpoint(host="10.0.0.1", username="admin", password="secret")
        transport = SshGuestTransport(endpoint)
        mock_result = MagicMock(returncode=0, stdout="ok\n", stderr="")
        with (
            patch("lib.openssh_client.shutil.which", return_value="/usr/bin/ssh"),
            patch("lib.openssh_client.subprocess.run", return_value=mock_result) as run,
        ):
            code, out = transport.run_ps("Write-Output ok", timeout=30)
        assert code == 0
        assert "ok" in out
        argv = run.call_args.args[0]
        # sshpass -e prefix when password set and sshpass present; or plain ssh + ASKPASS.
        joined = " ".join(argv)
        assert "EncodedCommand" in joined
        assert "BatchMode=yes" not in joined

    def test_put_file_uses_scp(self, tmp_path):
        local = tmp_path / "payload.bin"
        local.write_bytes(b"abc")
        endpoint = GuestEndpoint(host="10.0.0.1", username="admin", password="secret")
        transport = SshGuestTransport(endpoint)
        mock_result = MagicMock(returncode=0, stdout="", stderr="")

        def which(name):
            if name in {"ssh", "scp", "sshpass"}:
                return f"/usr/bin/{name}"
            return None

        with (
            patch("lib.openssh_client.shutil.which", side_effect=which),
            patch("lib.openssh_client.subprocess.run", return_value=mock_result) as run,
            patch.object(transport, "_run_remote", return_value=(0, "")),
        ):
            transport.put_file(local, r"C:\Program Files\Hatchery\temp\payload.bin")
        scp_calls = [c for c in run.call_args_list if "scp" in " ".join(c.args[0])]
        assert scp_calls
        assert str(local) in scp_calls[0].args[0]


class TestWinrmGuestTransport:
    def test_run_ps_strips_and_returns(self):
        endpoint = GuestEndpoint(host="10.0.0.1", username="admin", password="secret")
        transport = WinrmGuestTransport(endpoint)
        result = MagicMock(status_code=0, std_out=b"hello\n", std_err=b"")
        session = MagicMock()
        session.run_ps.return_value = result
        with patch.object(transport, "_session", return_value=session):
            code, out = transport.run_ps("Write-Output hello")
        assert code == 0
        assert "hello" in out


class TestGetGuestTransport:
    def test_explicit_kinds(self):
        ssh = gt.get_guest_transport("10.0.0.1", "a", "p", kind="ssh")
        winrm = gt.get_guest_transport("10.0.0.1", "a", "p", kind="winrm")
        assert isinstance(ssh, SshGuestTransport)
        assert isinstance(winrm, WinrmGuestTransport)

    def test_resolve_none_kind(self):
        winrm = MagicMock(spec=WinrmGuestTransport)
        winrm.kind = "winrm"
        with patch("lib.guest_transport.resolve_guest_transport", return_value=winrm) as resolve:
            t = gt.get_guest_transport("10.0.0.1", "a", "p", kind=None)
        assert t is winrm
        resolve.assert_called_once()


class TestSshLargeScript:
    def test_run_ps_stages_large_script(self, tmp_path):
        endpoint = GuestEndpoint(host="10.0.0.1", username="admin", password="secret")
        transport = SshGuestTransport(endpoint)
        # Force EncodedCommand path to be skipped.
        big = "Write-Output " + ("x" * 9000)
        calls: list[str] = []

        def fake_put(local_path, remote_path, *, timeout=600):
            calls.append(f"put:{remote_path}")
            assert Path(local_path).read_text(encoding="utf-8") == big

        def fake_run(remote, *, timeout):
            calls.append(remote)
            return 0, "done"

        with (
            patch.object(transport, "put_file", side_effect=fake_put),
            patch.object(transport, "_run_remote", side_effect=fake_run),
        ):
            code, out = transport.run_ps(big, timeout=60)
        assert code == 0
        assert out == "done"
        assert any(c.startswith("put:") for c in calls)
        assert any("-File" in c for c in calls)
