"""Nest transport — Hatchery control plane to a Nest host (not a guest VM).

Remote Nest default is SSH with a **referenced** OpenSSH identity (path and/or
agent). Hatchery does not store private keys here (#218). Guest provisioning
stays in ``lib.provision`` (WinRM for Windows guests).

WinRM Nest transport is a supported fallback (#220) but is not implemented in
this module yet — use ``transport=\"winrm\"`` only after that work lands.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Literal

NestTransportKind = Literal["ssh", "winrm"]
KnownHostsPolicy = Literal["default", "accept-new", "skip"]


class NestTransportError(RuntimeError):
    """Raised when a Nest host cannot be reached or a remote command fails."""


@dataclass(frozen=True)
class NestSshConfig:
    """SSH connection settings for a remote Nest (key reference only)."""

    host: str
    user: str | None = None
    port: int = 22
    # Path to an existing private key on the Hatchery host — never copied into the DB as key bytes.
    identity_file: str | None = None
    use_agent: bool = True
    known_hosts: KnownHostsPolicy = "default"
    connect_timeout_seconds: int = 10

    def __post_init__(self) -> None:
        if not self.host or not str(self.host).strip():
            raise ValueError("Nest SSH host is required")
        if self.port < 1 or self.port > 65535:
            raise ValueError(f"invalid SSH port: {self.port}")
        if self.connect_timeout_seconds < 1:
            raise ValueError("connect_timeout_seconds must be >= 1")


@dataclass(frozen=True)
class NestConnectionConfig:
    """Nest control-plane connection — local Nests need no transport."""

    location: Literal["local", "remote"] = "local"
    transport: NestTransportKind = "ssh"
    ssh: NestSshConfig | None = None
    # WinRM fields reserved for #220 (endpoint, etc.)
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.location == "remote" and self.transport == "ssh" and self.ssh is None:
            raise ValueError("remote SSH Nest requires NestSshConfig")
        if self.location == "remote" and self.transport == "winrm":
            raise NestTransportError(
                "WinRM Nest transport is not implemented yet — see issue #220; "
                "use transport='ssh' (default) or a local Nest"
            )


@dataclass(frozen=True)
class NestHealthCheckResult:
    """Result of a Nest connectivity check (UI: Test Nest connection)."""

    ok: bool
    detail: str


def build_ssh_argv(config: NestSshConfig, remote_command: str) -> list[str]:
    """Build an ``ssh`` argv for a Nest host. Does not run the process."""
    if shutil.which("ssh") is None:
        raise NestTransportError("OpenSSH client (`ssh`) not found on the Hatchery host PATH")

    argv: list[str] = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={config.connect_timeout_seconds}",
        "-p",
        str(config.port),
    ]

    if config.identity_file:
        argv.extend(["-i", config.identity_file])
    if not config.use_agent:
        argv.extend(["-o", "IdentityAgent=none"])

    if config.known_hosts == "accept-new":
        argv.extend(["-o", "StrictHostKeyChecking=accept-new"])
    elif config.known_hosts == "skip":
        argv.extend(["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"])

    target = f"{config.user}@{config.host}" if config.user else config.host
    argv.append(target)
    argv.append(remote_command)
    return argv


class SshNestTransport:
    """Run commands on a remote Nest over SSH using the host OpenSSH client."""

    def __init__(self, config: NestSshConfig) -> None:
        self.config = config

    def test_connection(self) -> NestHealthCheckResult:
        """Connectivity check — UI label: Test Nest connection."""
        try:
            out = self.run("echo hatchery-nest-ok")
        except NestTransportError as exc:
            return NestHealthCheckResult(ok=False, detail=str(exc))
        if "hatchery-nest-ok" in out:
            return NestHealthCheckResult(ok=True, detail="reachable")
        return NestHealthCheckResult(
            ok=False,
            detail=f"unexpected response: {out.strip()!r}",
        )

    def run(self, remote_command: str, *, timeout: float | None = None) -> str:
        """Run a shell command on the Nest host; return stdout (stderr on failure)."""
        argv = build_ssh_argv(self.config, remote_command)
        wait = timeout if timeout is not None else float(self.config.connect_timeout_seconds + 5)
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=wait,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise NestTransportError(
                f"SSH timed out connecting to {self.config.host}:{self.config.port}"
            ) from exc
        except OSError as exc:
            raise NestTransportError(f"SSH failed to start: {exc}") from exc

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            raise NestTransportError(
                err or f"SSH exited {result.returncode} ({shlex.join(argv[:-1])} …)"
            )
        return result.stdout


def get_nest_transport(connection: NestConnectionConfig) -> SshNestTransport | None:
    """Return a transport for a remote Nest, or None for local.

    Raises ``NestTransportError`` for unsupported remote transports.
    """
    if connection.location == "local":
        return None
    if connection.transport == "ssh":
        assert connection.ssh is not None
        return SshNestTransport(connection.ssh)
    raise NestTransportError(
        f"unsupported Nest transport: {connection.transport!r} (see #218 / #220)"
    )
