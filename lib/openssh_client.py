"""Shared OpenSSH client argv helpers for Nest and Guest transport planes.

Does not choose Nest vs Guest credentials or BatchMode policy - callers pass those.
Never stores private key bytes; only path references (ADR-0029 / nest-transport).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

KnownHostsPolicy = Literal["default", "accept-new", "skip"]


class OpenSshClientError(RuntimeError):
    """Raised when the host OpenSSH client cannot run a command."""


def require_ssh() -> str:
    """Return path to ``ssh`` on PATH, or raise."""
    path = shutil.which("ssh")
    if path is None:
        raise OpenSshClientError("OpenSSH client (`ssh`) not found on the Hatchery host PATH")
    return path


def require_scp() -> str:
    """Return path to ``scp`` on PATH, or raise."""
    path = shutil.which("scp")
    if path is None:
        raise OpenSshClientError("OpenSSH client (`scp`) not found on the Hatchery host PATH")
    return path


def build_ssh_argv(
    *,
    host: str,
    user: str | None,
    port: int,
    remote_command: str,
    identity_file: str | None = None,
    use_agent: bool = True,
    known_hosts: KnownHostsPolicy = "default",
    connect_timeout_seconds: int = 10,
    batch_mode: bool = True,
) -> list[str]:
    """Build an ``ssh`` argv. Does not run the process."""
    require_ssh()
    argv: list[str] = ["ssh"]
    if batch_mode:
        argv.extend(["-o", "BatchMode=yes"])
    argv.extend(
        [
            "-o",
            f"ConnectTimeout={connect_timeout_seconds}",
            "-p",
            str(port),
        ]
    )
    if identity_file:
        argv.extend(["-i", identity_file])
    if not use_agent:
        argv.extend(["-o", "IdentityAgent=none"])
    if known_hosts == "accept-new":
        argv.extend(["-o", "StrictHostKeyChecking=accept-new"])
    elif known_hosts == "skip":
        argv.extend(["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"])
    target = f"{user}@{host}" if user else host
    argv.append(target)
    argv.append(remote_command)
    return argv


def build_scp_argv(
    *,
    host: str,
    user: str | None,
    port: int,
    local_path: str,
    remote_path: str,
    identity_file: str | None = None,
    use_agent: bool = True,
    known_hosts: KnownHostsPolicy = "default",
    connect_timeout_seconds: int = 10,
    batch_mode: bool = True,
) -> list[str]:
    """Build an ``scp`` argv to copy a local file to the remote host."""
    require_scp()
    argv: list[str] = ["scp", "-P", str(port)]
    if batch_mode:
        argv.extend(["-o", "BatchMode=yes"])
    argv.extend(["-o", f"ConnectTimeout={connect_timeout_seconds}"])
    if identity_file:
        argv.extend(["-i", identity_file])
    if not use_agent:
        argv.extend(["-o", "IdentityAgent=none"])
    if known_hosts == "accept-new":
        argv.extend(["-o", "StrictHostKeyChecking=accept-new"])
    elif known_hosts == "skip":
        argv.extend(["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"])
    target_host = f"{user}@{host}" if user else host
    argv.append(local_path)
    argv.append(f"{target_host}:{remote_path}")
    return argv


def _write_askpass_script(password: str) -> Path:
    """Write a short-lived ASKPASS helper that prints ``password`` to stdout."""
    fd, name = tempfile.mkstemp(prefix="hatchery-askpass-", suffix=".py")
    path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env python3\n")
            fh.write("import sys\n")
            fh.write(f"sys.stdout.write({password!r})\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def run_openssh(
    argv: list[str],
    *,
    timeout: float,
    password: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an OpenSSH client argv; optional password via sshpass or SSH_ASKPASS.

    When ``password`` is set, prefer ``sshpass -e`` when on PATH; otherwise use a
    temporary ``SSH_ASKPASS`` helper (Controller password SSH until guest key
    identity lands - #519). Nest transport should pass ``password=None`` and use
    BatchMode + key/agent.
    """
    env = os.environ.copy()
    run_argv = list(argv)
    askpass_path: Path | None = None
    if password:
        sshpass = shutil.which("sshpass")
        if sshpass is not None:
            env["SSHPASS"] = password
            run_argv = [sshpass, "-e", *argv]
        else:
            askpass_path = _write_askpass_script(password)
            env["SSH_ASKPASS"] = str(askpass_path)
            env["SSH_ASKPASS_REQUIRE"] = "force"
            # OpenSSH skips ASKPASS without a display-ish hint on some hosts.
            env.setdefault("DISPLAY", "hatchery-askpass")
            # Detach from controlling tty so ssh will not prompt interactively.
            env["SSH_ASKPASS_REQUIRE"] = "force"
    try:
        return subprocess.run(
            run_argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise OpenSshClientError(f"OpenSSH timed out after {timeout}s") from exc
    except OSError as exc:
        raise OpenSshClientError(f"OpenSSH failed to start: {exc}") from exc
    finally:
        if askpass_path is not None:
            askpass_path.unlink(missing_ok=True)
