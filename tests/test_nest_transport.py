"""Tests for Nest SSH transport (#218) — mocked ``ssh``; no live remote."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lib import nest_transport as nt


class TestNestKnownHosts:
    def test_nest_known_hosts_path_under_data_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        path = nt.nest_known_hosts_path()
        assert path == tmp_path / "remoting" / "known_hosts" / "nest"
        assert path.is_file()

    def test_remove_nest_known_host_calls_ssh_keygen(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        kh = nt.nest_known_hosts_path()
        kh.write_text("lab-nest ssh-ed25519 AAAA\n", encoding="utf-8")
        calls: list[list[str]] = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))
            return MagicMock(returncode=0)

        with (
            patch("lib.nest_transport.shutil.which", return_value="/usr/bin/ssh-keygen"),
            patch("lib.nest_transport.subprocess.run", side_effect=fake_run),
        ):
            nt.remove_nest_known_host("lab-nest")
        assert calls
        assert calls[0][0] == "/usr/bin/ssh-keygen"
        assert "-R" in calls[0]
        assert "lab-nest" in calls[0]
        assert str(kh) in calls[0]

    def test_remove_nest_known_host_noop_without_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        with patch("lib.nest_transport.subprocess.run") as run:
            nt.remove_nest_known_host(None)
            nt.remove_nest_known_host("  ")
        run.assert_not_called()

    def test_nest_and_guest_known_hosts_files_isolated(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        from lib import guest_transport as gt

        nest_path = nt.nest_known_hosts_path()
        guest_path = gt.guest_known_hosts_path()
        assert nest_path != guest_path
        assert nest_path.name == "nest"
        assert guest_path.name == "guest"
        nest_path.write_text("nest-only\n", encoding="utf-8")
        guest_path.write_text("guest-only\n", encoding="utf-8")
        assert nest_path.read_text(encoding="utf-8") == "nest-only\n"
        assert guest_path.read_text(encoding="utf-8") == "guest-only\n"


class TestNestSshConfig:
    def test_requires_host(self):
        with pytest.raises(ValueError, match="host"):
            nt.NestSshConfig(host="")

    def test_rejects_bad_port(self):
        with pytest.raises(ValueError, match="port"):
            nt.NestSshConfig(host="nest.example", port=0)


class TestNestConnectionConfig:
    def test_remote_ssh_requires_ssh_config(self):
        with pytest.raises(ValueError, match="NestSshConfig"):
            nt.NestConnectionConfig(location="remote", transport="ssh", ssh=None)

    def test_remote_winrm_requires_winrm_config(self):
        with pytest.raises(ValueError, match="NestWinrmConfig"):
            nt.NestConnectionConfig(location="remote", transport="winrm", winrm=None)

    def test_local_needs_no_ssh(self):
        cfg = nt.NestConnectionConfig(location="local")
        assert nt.get_nest_transport(cfg) is None


class TestBuildSshArgv:
    def test_basic_argv(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        with patch("lib.openssh_client.shutil.which", return_value="/usr/bin/ssh"):
            argv = nt.build_ssh_argv(
                nt.NestSshConfig(host="nest.lab", user="ops", port=2222),
                "echo ok",
            )
        assert argv[0] == "ssh"
        assert "-p" in argv and "2222" in argv
        assert "ops@nest.lab" in argv
        assert argv[-1] == "echo ok"
        assert "BatchMode=yes" in " ".join(argv)

    def test_identity_file_and_no_agent(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        with patch("lib.openssh_client.shutil.which", return_value="/usr/bin/ssh"):
            argv = nt.build_ssh_argv(
                nt.NestSshConfig(
                    host="n",
                    identity_file="/home/me/.ssh/nest_ed25519",
                    use_agent=False,
                    known_hosts="accept-new",
                ),
                "true",
            )
        assert "-i" in argv
        assert "/home/me/.ssh/nest_ed25519" in argv
        assert "IdentityAgent=none" in " ".join(argv)
        assert "accept-new" in " ".join(argv)

    def test_hatchery_known_hosts_and_alias(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        with patch("lib.openssh_client.shutil.which", return_value="/usr/bin/ssh"):
            argv = nt.build_ssh_argv(
                nt.NestSshConfig(
                    host="10.0.0.5",
                    known_hosts="accept-new",
                    host_key_alias="lab-nest",
                ),
                "true",
            )
        joined = " ".join(argv)
        assert f"UserKnownHostsFile={tmp_path / 'remoting' / 'known_hosts' / 'nest'}" in joined
        assert "GlobalKnownHostsFile=/dev/null" in joined
        assert "HostKeyAlias=lab-nest" in joined
        assert "accept-new" in joined

    def test_default_policy_uses_hatchery_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        with patch("lib.openssh_client.shutil.which", return_value="/usr/bin/ssh"):
            argv = nt.build_ssh_argv(
                nt.NestSshConfig(host="n", host_key_alias="n1"),
                "true",
            )
        joined = " ".join(argv)
        assert f"UserKnownHostsFile={tmp_path / 'remoting' / 'known_hosts' / 'nest'}" in joined
        assert "HostKeyAlias=n1" in joined
        assert "StrictHostKeyChecking=accept-new" not in joined
        assert "StrictHostKeyChecking=no" not in joined

    def test_missing_ssh_client(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        with patch("lib.openssh_client.shutil.which", return_value=None):
            with pytest.raises(nt.NestTransportError, match="OpenSSH client"):
                nt.build_ssh_argv(nt.NestSshConfig(host="n"), "true")


class TestSshNestTransport:
    def _cfg(self) -> nt.NestSshConfig:
        return nt.NestSshConfig(host="nest.lab", user="hatch", host_key_alias="nest-lab")

    def test_run_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        mock_result = MagicMock(returncode=0, stdout="hello\n", stderr="")
        with (
            patch("lib.openssh_client.shutil.which", return_value="/usr/bin/ssh"),
            patch("lib.openssh_client.subprocess.run", return_value=mock_result) as run,
        ):
            out = nt.SshNestTransport(self._cfg()).run("uname -a")
        assert out == "hello\n"
        run.assert_called_once()
        assert run.call_args.args[0][-1] == "uname -a"

    def test_run_nonzero_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        mock_result = MagicMock(returncode=255, stdout="", stderr="Permission denied")
        with (
            patch("lib.openssh_client.shutil.which", return_value="/usr/bin/ssh"),
            patch("lib.openssh_client.subprocess.run", return_value=mock_result),
        ):
            with pytest.raises(nt.NestTransportError, match="Permission denied"):
                nt.SshNestTransport(self._cfg()).run("true")

    def test_test_connection_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        mock_result = MagicMock(returncode=0, stdout="hatchery-nest-ok\n", stderr="")
        with (
            patch("lib.openssh_client.shutil.which", return_value="/usr/bin/ssh"),
            patch("lib.openssh_client.subprocess.run", return_value=mock_result),
        ):
            result = nt.SshNestTransport(self._cfg()).test_connection()
        assert result.ok is True
        assert result.detail == "Nest transport OK"

    def test_test_connection_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        mock_result = MagicMock(returncode=255, stdout="", stderr="Connection refused")
        with (
            patch("lib.openssh_client.shutil.which", return_value="/usr/bin/ssh"),
            patch("lib.openssh_client.subprocess.run", return_value=mock_result),
        ):
            result = nt.SshNestTransport(self._cfg()).test_connection()
        assert result.ok is False
        assert "Connection refused" in result.detail

    def test_known_hosts_skip(self):
        with patch("lib.openssh_client.shutil.which", return_value="/usr/bin/ssh"):
            argv = nt.build_ssh_argv(
                nt.NestSshConfig(host="n", known_hosts="skip"),
                "true",
            )
        joined = " ".join(argv)
        assert "StrictHostKeyChecking=no" in joined
        assert "UserKnownHostsFile=/dev/null" in joined
        assert "remoting/known_hosts/nest" not in joined

    def test_run_timeout(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        with (
            patch("lib.openssh_client.shutil.which", return_value="/usr/bin/ssh"),
            patch(
                "lib.openssh_client.subprocess.run",
                side_effect=__import__("subprocess").TimeoutExpired(cmd="ssh", timeout=1),
            ),
        ):
            with pytest.raises(nt.NestTransportError, match="timed out"):
                nt.SshNestTransport(self._cfg()).run("true")

    def test_run_oserror(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        with (
            patch("lib.openssh_client.shutil.which", return_value="/usr/bin/ssh"),
            patch("lib.openssh_client.subprocess.run", side_effect=OSError("boom")),
        ):
            with pytest.raises(nt.NestTransportError, match="failed to start"):
                nt.SshNestTransport(self._cfg()).run("true")

    def test_test_connection_unexpected_output(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path)
        mock_result = MagicMock(returncode=0, stdout="nope\n", stderr="")
        with (
            patch("lib.openssh_client.shutil.which", return_value="/usr/bin/ssh"),
            patch("lib.openssh_client.subprocess.run", return_value=mock_result),
        ):
            result = nt.SshNestTransport(self._cfg()).test_connection()
        assert result.ok is False
        assert "unexpected" in result.detail

    def test_get_nest_transport_ssh(self):
        conn = nt.NestConnectionConfig(
            location="remote",
            transport="ssh",
            ssh=self._cfg(),
        )
        transport = nt.get_nest_transport(conn)
        assert isinstance(transport, nt.SshNestTransport)


class TestWinrmNestTransport:
    def _cfg(self) -> nt.NestWinrmConfig:
        return nt.NestWinrmConfig(
            host="win-nest",
            username="Administrator",
            password="secret",
        )

    def test_run_success(self):
        mock_session = MagicMock()
        mock_session.run_ps.return_value = MagicMock(status_code=0, std_out=b"ok\n", std_err=b"")
        mock_winrm = MagicMock()
        mock_winrm.Session.return_value = mock_session
        with patch.dict("sys.modules", {"winrm": mock_winrm}):
            out = nt.WinrmNestTransport(self._cfg()).run("Write-Output ok")
        assert out == "ok\n"
        mock_winrm.Session.assert_called_once()
        assert mock_winrm.Session.call_args.args[0] == "http://win-nest:5985/wsman"

    def test_run_nonzero_raises(self):
        mock_session = MagicMock()
        mock_session.run_ps.return_value = MagicMock(status_code=1, std_out=b"", std_err=b"boom")
        mock_winrm = MagicMock()
        mock_winrm.Session.return_value = mock_session
        with patch.dict("sys.modules", {"winrm": mock_winrm}):
            with pytest.raises(nt.NestTransportError, match="boom"):
                nt.WinrmNestTransport(self._cfg()).run("bad")

    def test_test_connection_ok(self):
        mock_session = MagicMock()
        mock_session.run_ps.return_value = MagicMock(
            status_code=0, std_out=b"hatchery-nest-ok\n", std_err=b""
        )
        mock_winrm = MagicMock()
        mock_winrm.Session.return_value = mock_session
        with patch.dict("sys.modules", {"winrm": mock_winrm}):
            result = nt.WinrmNestTransport(self._cfg()).test_connection()
        assert result.ok is True

    def test_test_connection_failure(self):
        mock_session = MagicMock()
        mock_session.run_ps.side_effect = RuntimeError("refused")
        mock_winrm = MagicMock()
        mock_winrm.Session.return_value = mock_session
        with patch.dict("sys.modules", {"winrm": mock_winrm}):
            result = nt.WinrmNestTransport(self._cfg()).test_connection()
        assert result.ok is False

    def test_get_nest_transport_winrm(self):
        conn = nt.NestConnectionConfig(
            location="remote",
            transport="winrm",
            winrm=self._cfg(),
        )
        transport = nt.get_nest_transport(conn)
        assert isinstance(transport, nt.WinrmNestTransport)
