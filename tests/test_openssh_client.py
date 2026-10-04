"""Shared OpenSSH client helpers (#497)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lib import openssh_client as osc


def test_require_ssh_and_scp():
    with patch("lib.openssh_client.shutil.which", return_value="/usr/bin/ssh"):
        assert osc.require_ssh() == "/usr/bin/ssh"
    with patch("lib.openssh_client.shutil.which", return_value=None):
        with pytest.raises(osc.OpenSshClientError, match="ssh"):
            osc.require_ssh()
    with patch("lib.openssh_client.shutil.which", return_value="/usr/bin/scp"):
        assert osc.require_scp() == "/usr/bin/scp"
    with patch("lib.openssh_client.shutil.which", return_value=None):
        with pytest.raises(osc.OpenSshClientError, match="scp"):
            osc.require_scp()


def test_build_scp_argv_accept_new():
    with patch("lib.openssh_client.shutil.which", return_value="/usr/bin/scp"):
        argv = osc.build_scp_argv(
            host="g.lab",
            user="admin",
            port=22,
            local_path="/tmp/a.bin",
            remote_path=r"C:\temp\a.bin",
            known_hosts="accept-new",
            batch_mode=False,
        )
    assert argv[0] == "scp"
    assert "BatchMode=yes" not in " ".join(argv)
    assert "accept-new" in " ".join(argv)
    assert argv[-2] == "/tmp/a.bin"


def test_run_openssh_askpass_when_no_sshpass(tmp_path):
    mock_result = MagicMock(returncode=0, stdout="ok\n", stderr="")

    def which(name):
        if name == "ssh":
            return "/usr/bin/ssh"
        return None

    with (
        patch("lib.openssh_client.shutil.which", side_effect=which),
        patch("lib.openssh_client.subprocess.run", return_value=mock_result) as run,
    ):
        result = osc.run_openssh(
            ["ssh", "admin@10.0.0.1", "true"],
            timeout=5,
            password="secret",
        )
    assert result.returncode == 0
    env = run.call_args.kwargs["env"]
    assert env["SSH_ASKPASS_REQUIRE"] == "force"
    assert "SSH_ASKPASS" in env


def test_run_openssh_sshpass_when_available():
    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    def which(name):
        return f"/usr/bin/{name}"

    with (
        patch("lib.openssh_client.shutil.which", side_effect=which),
        patch("lib.openssh_client.subprocess.run", return_value=mock_result) as run,
    ):
        osc.run_openssh(["ssh", "h@n", "true"], timeout=5, password="pw")
    argv = run.call_args.args[0]
    assert argv[0] == "/usr/bin/sshpass"
    assert argv[1] == "-e"
    assert run.call_args.kwargs["env"]["SSHPASS"] == "pw"
