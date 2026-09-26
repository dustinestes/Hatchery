"""Portable Nest-tool subprocess helpers."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from lib.run_cmd import format_process_error, run_cmd


def test_format_prefers_stderr_over_argv_repr():
    exc = subprocess.CalledProcessError(
        1,
        ["virsh", "suspend", "test26"],
        stderr="error: Failed to suspend domain test26\n",
    )
    msg = format_process_error(exc)
    assert "Failed to suspend domain test26" in msg
    assert "['virsh'" not in msg


def test_format_falls_back_to_stdout():
    exc = subprocess.CalledProcessError(
        1,
        ["pwsh", "-Command", "Stop-VM"],
        output="Stop-VM : The operation failed because disk is missing.\n",
        stderr="",
    )
    assert "disk is missing" in format_process_error(exc)


def test_format_bytes_streams():
    exc = subprocess.CalledProcessError(
        1,
        ["utmctl", "start", "x"],
        stderr=b"error: image not found\n",
    )
    assert format_process_error(exc) == "error: image not found"


def test_format_empty_streams_uses_exit_summary():
    exc = subprocess.CalledProcessError(1, ["tool", "arg with space"])
    msg = format_process_error(exc)
    assert "exit 1" in msg
    assert "tool" in msg


def test_run_cmd_raises_with_captured_stderr():
    fake = MagicMock(returncode=1, stdout="", stderr="error: no such disk\n")
    with patch("lib.run_cmd.subprocess.run", return_value=fake):
        with pytest.raises(subprocess.CalledProcessError) as exc:
            run_cmd(["anyctl", "pause", "vm"], echo_failure=False)
    assert format_process_error(exc.value) == "error: no such disk"


def test_run_cmd_echoes_failure_to_stderr(capsys):
    fake = MagicMock(returncode=1, stdout="", stderr="error: disk image missing\n")
    with patch("lib.run_cmd.subprocess.run", return_value=fake):
        with pytest.raises(subprocess.CalledProcessError):
            run_cmd(["virsh", "suspend", "test26"])
    err = capsys.readouterr().err
    assert "disk image missing" in err
    assert "Nest tool failed" in err
