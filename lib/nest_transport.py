"""Nest transport — Hatchery control plane to a Nest host (not a guest VM).

Remote Nest default is SSH with a **referenced** OpenSSH identity (path and/or
agent). Hatchery does not store private keys here (#218). Guest provisioning
stays in ``lib.provision`` (WinRM for Windows guests).

WinRM is an explicit Nest transport fallback for Windows Nests (#220) when
OpenSSH is unavailable or WinRM is preferred. Nest registry persistence of
WinRM passwords should use encrypted storage (#110) — this module only holds
session credentials in memory.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Literal, Protocol

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
class NestWinrmConfig:
    """WinRM connection settings for a remote Windows Nest (#220).

    Prefer SSH (#218) when OpenSSH is available. Username/password are session
    credentials for pywinrm; do not treat this module as a secrets store.
    """

    host: str
    username: str
    password: str
    port: int = 5985
    use_ssl: bool = False
    # pywinrm auth transport (ntlm is the common lab default; same as guest provision).
    auth_transport: str = "ntlm"
    operation_timeout_sec: int = 20

    def __post_init__(self) -> None:
        if not self.host or not str(self.host).strip():
            raise ValueError("Nest WinRM host is required")
        if not self.username or not str(self.username).strip():
            raise ValueError("Nest WinRM username is required")
        if self.port < 1 or self.port > 65535:
            raise ValueError(f"invalid WinRM port: {self.port}")
        if self.operation_timeout_sec < 1:
            raise ValueError("operation_timeout_sec must be >= 1")

    @property
    def endpoint_url(self) -> str:
        scheme = "https" if self.use_ssl else "http"
        return f"{scheme}://{self.host}:{self.port}/wsman"


@dataclass(frozen=True)
class NestConnectionConfig:
    """Nest control-plane connection — local Nests need no transport.

    ``transport`` is the per-Nest choice (``ssh`` default, ``winrm`` fallback).
    """

    location: Literal["local", "remote"] = "local"
    transport: NestTransportKind = "ssh"
    ssh: NestSshConfig | None = None
    winrm: NestWinrmConfig | None = None
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.location != "remote":
            return
        if self.transport == "ssh" and self.ssh is None:
            raise ValueError("remote SSH Nest requires NestSshConfig")
        if self.transport == "winrm" and self.winrm is None:
            raise ValueError("remote WinRM Nest requires NestWinrmConfig")


@dataclass(frozen=True)
class NestHealthCheckResult:
    """Result of a Nest connectivity check (UI: Test Nest connection).

    ``failure_class`` (when ``ok`` is False):

    - ``endpoint`` — host:port not reachable (nothing listening / filtered / wrong address)
    - ``transport`` — endpoint accepts TCP but Nest transport session failed (auth, protocol, …)
    - ``config`` — Nest row / client setup cannot run a probe (missing password, invalid fields)
    """

    ok: bool
    detail: str
    failure_class: str | None = None


class NestTransport(Protocol):
    """Shared Nest control-plane transport (SSH or WinRM)."""

    def test_connection(self) -> NestHealthCheckResult:
        """Connectivity check — UI label: Test Nest connection."""

    def run(self, remote_command: str, *, timeout: float | None = None) -> str:
        """Run a command on the Nest host; return stdout.

        SSH: remote shell command. WinRM: PowerShell script text.
        """


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
            return NestHealthCheckResult(
                ok=False,
                detail=str(exc),
                failure_class="transport",
            )
        if "hatchery-nest-ok" in out:
            return NestHealthCheckResult(ok=True, detail="Nest transport OK")
        return NestHealthCheckResult(
            ok=False,
            detail=f"unexpected response: {out.strip()!r}",
            failure_class="transport",
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


class WinrmNestTransport:
    """Run PowerShell on a remote Windows Nest over WinRM (pywinrm)."""

    def __init__(self, config: NestWinrmConfig) -> None:
        self.config = config

    def _session(self, *, timeout: float | None = None):
        try:
            import winrm
        except ImportError as exc:  # pragma: no cover
            raise NestTransportError("pywinrm is required for WinRM Nest transport") from exc

        op_timeout = int(timeout) if timeout is not None else self.config.operation_timeout_sec
        return winrm.Session(
            self.config.endpoint_url,
            auth=(self.config.username, self.config.password),
            transport=self.config.auth_transport,
            operation_timeout_sec=op_timeout,
            read_timeout_sec=op_timeout + 10,
        )

    def test_connection(self) -> NestHealthCheckResult:
        """Connectivity check — UI label: Test Nest connection."""
        try:
            out = self.run("Write-Output 'hatchery-nest-ok'")
        except NestTransportError as exc:
            return NestHealthCheckResult(
                ok=False,
                detail=str(exc),
                failure_class="transport",
            )
        if "hatchery-nest-ok" in out:
            return NestHealthCheckResult(ok=True, detail="Nest transport OK")
        return NestHealthCheckResult(
            ok=False,
            detail=f"unexpected response: {out.strip()!r}",
            failure_class="transport",
        )

    def run(self, remote_command: str, *, timeout: float | None = None) -> str:
        """Run PowerShell on the Nest host; return stdout."""
        try:
            session = self._session(timeout=timeout)
            result = session.run_ps(remote_command)
        except NestTransportError:
            raise
        except Exception as exc:
            raise NestTransportError(f"WinRM Nest command failed: {exc}") from exc

        status = getattr(result, "status_code", 1)
        if status != 0:
            err_raw = getattr(result, "std_err", b"") or b""
            err = (
                err_raw.decode("utf-8", errors="replace")
                if isinstance(err_raw, bytes)
                else str(err_raw)
            ).strip()
            raise NestTransportError(err or f"WinRM status {status}")

        out_raw = getattr(result, "std_out", b"") or b""
        if isinstance(out_raw, bytes):
            return out_raw.decode("utf-8", errors="replace")
        return str(out_raw)


def get_nest_transport(
    connection: NestConnectionConfig,
) -> SshNestTransport | WinrmNestTransport | None:
    """Return a transport for a remote Nest, or None for local."""
    if connection.location == "local":
        return None
    if connection.transport == "ssh":
        assert connection.ssh is not None
        return SshNestTransport(connection.ssh)
    if connection.transport == "winrm":
        assert connection.winrm is not None
        return WinrmNestTransport(connection.winrm)
    raise NestTransportError(f"unsupported Nest transport: {connection.transport!r}")
