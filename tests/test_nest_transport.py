"""Tests for Nest SSH transport (#218) — mocked ``ssh``; no live remote."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lib import nest_transport as nt


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

    def test_remote_winrm_not_implemented(self):
        with pytest.raises(nt.NestTransportError, match="#220"):
            nt.NestConnectionConfig(location="remote", transport="winrm")

    def test_local_needs_no_ssh(self):
        cfg = nt.NestConnectionConfig(location="local")
        assert nt.get_nest_transport(cfg) is None


class TestBuildSshArgv:
    def test_basic_argv(self):
        with patch("lib.nest_transport.shutil.which", return_value="/usr/bin/ssh"):
            argv = nt.build_ssh_argv(
                nt.NestSshConfig(host="nest.lab", user="ops", port=2222),
                "echo ok",
            )
        assert argv[0] == "ssh"
        assert "-p" in argv and "2222" in argv
        assert "ops@nest.lab" in argv
        assert argv[-1] == "echo ok"
        assert "BatchMode=yes" in " ".join(argv)

    def test_identity_file_and_no_agent(self):
        with patch("lib.nest_transport.shutil.which", return_value="/usr/bin/ssh"):
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

    def test_missing_ssh_client(self):
        with patch("lib.nest_transport.shutil.which", return_value=None):
            with pytest.raises(nt.NestTransportError, match="OpenSSH client"):
                nt.build_ssh_argv(nt.NestSshConfig(host="n"), "true")


class TestSshNestTransport:
    def _cfg(self) -> nt.NestSshConfig:
        return nt.NestSshConfig(host="nest.lab", user="hatch")

    def test_run_success(self):
        mock_result = MagicMock(returncode=0, stdout="hello\n", stderr="")
        with (
            patch("lib.nest_transport.shutil.which", return_value="/usr/bin/ssh"),
            patch("lib.nest_transport.subprocess.run", return_value=mock_result) as run,
        ):
            out = nt.SshNestTransport(self._cfg()).run("uname -a")
        assert out == "hello\n"
        run.assert_called_once()
        assert run.call_args.args[0][-1] == "uname -a"

    def test_run_nonzero_raises(self):
        mock_result = MagicMock(returncode=255, stdout="", stderr="Permission denied")
        with (
            patch("lib.nest_transport.shutil.which", return_value="/usr/bin/ssh"),
            patch("lib.nest_transport.subprocess.run", return_value=mock_result),
        ):
            with pytest.raises(nt.NestTransportError, match="Permission denied"):
                nt.SshNestTransport(self._cfg()).run("true")

    def test_test_connection_ok(self):
        mock_result = MagicMock(returncode=0, stdout="hatchery-nest-ok\n", stderr="")
        with (
            patch("lib.nest_transport.shutil.which", return_value="/usr/bin/ssh"),
            patch("lib.nest_transport.subprocess.run", return_value=mock_result),
        ):
            result = nt.SshNestTransport(self._cfg()).test_connection()
        assert result.ok is True
        assert result.detail == "reachable"

    def test_test_connection_failure(self):
        mock_result = MagicMock(returncode=255, stdout="", stderr="Connection refused")
        with (
            patch("lib.nest_transport.shutil.which", return_value="/usr/bin/ssh"),
            patch("lib.nest_transport.subprocess.run", return_value=mock_result),
        ):
            result = nt.SshNestTransport(self._cfg()).test_connection()
        assert result.ok is False
        assert "Connection refused" in result.detail

    def test_known_hosts_skip(self):
        with patch("lib.nest_transport.shutil.which", return_value="/usr/bin/ssh"):
            argv = nt.build_ssh_argv(
                nt.NestSshConfig(host="n", known_hosts="skip"),
                "true",
            )
        joined = " ".join(argv)
        assert "StrictHostKeyChecking=no" in joined
        assert "UserKnownHostsFile=/dev/null" in joined

    def test_run_timeout(self):
        with (
            patch("lib.nest_transport.shutil.which", return_value="/usr/bin/ssh"),
            patch(
                "lib.nest_transport.subprocess.run",
                side_effect=__import__("subprocess").TimeoutExpired(cmd="ssh", timeout=1),
            ),
        ):
            with pytest.raises(nt.NestTransportError, match="timed out"):
                nt.SshNestTransport(self._cfg()).run("true")

    def test_run_oserror(self):
        with (
            patch("lib.nest_transport.shutil.which", return_value="/usr/bin/ssh"),
            patch("lib.nest_transport.subprocess.run", side_effect=OSError("boom")),
        ):
            with pytest.raises(nt.NestTransportError, match="failed to start"):
                nt.SshNestTransport(self._cfg()).run("true")

    def test_test_connection_unexpected_output(self):
        mock_result = MagicMock(returncode=0, stdout="nope\n", stderr="")
        with (
            patch("lib.nest_transport.shutil.which", return_value="/usr/bin/ssh"),
            patch("lib.nest_transport.subprocess.run", return_value=mock_result),
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
