"""Guest transport - Controller remoting to a guest VM (not a Nest host).

SSH is primary; WinRM is the Windows fallback (ADR-0029 / #497). Nest transport
(`lib.nest_transport`) is a parallel plane - different target, credentials, and
identity. Shared OpenSSH **client** helpers live in ``lib.openssh_client``.

Until guest key identity (#519), SSH auth uses the hatch admin password via
sshpass or SSH_ASKPASS on the Controller.
"""

from __future__ import annotations

import base64
import logging
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Literal, Protocol

from lib.guest_health import check_ssh, check_winrm
from lib.openssh_client import (
    OpenSshClientError,
    build_scp_argv,
    build_ssh_argv,
    run_openssh,
)

log = logging.getLogger(__name__)

GuestTransportKind = Literal["ssh", "winrm"]

# WinRM uses Negotiate (NTLM) by default after Enable-PSRemoting.
_WINRM_TRANSPORT = "ntlm"

# EncodedCommand safety margin under Windows CreateProcess ~8191 limit.
_ENCODED_COMMAND_MAX = 6000


class GuestTransportError(RuntimeError):
    """Raised when guest remoting cannot connect or a remote command fails."""


@dataclass(frozen=True)
class GuestEndpoint:
    """In-memory guest remoting target (hatch admin credentials)."""

    host: str
    username: str
    password: str
    ssh_port: int = 22
    winrm_port: int = 5985
    # Path reference only (#519); never Nest identity_file by default (ADR-0029).
    identity_file: str | None = None

    def __post_init__(self) -> None:
        if not self.host or not str(self.host).strip():
            raise ValueError("Guest host is required")
        if not self.username or not str(self.username).strip():
            raise ValueError("Guest username is required")
        if self.ssh_port < 1 or self.ssh_port > 65535:
            raise ValueError(f"invalid SSH port: {self.ssh_port}")
        if self.winrm_port < 1 or self.winrm_port > 65535:
            raise ValueError(f"invalid WinRM port: {self.winrm_port}")


class GuestTransport(Protocol):
    """Shared guest remoting: PowerShell run + file put."""

    kind: GuestTransportKind

    def run_ps(self, code: str, *, timeout: int = 300) -> tuple[int, str]:
        """Run PowerShell on the guest; return (exit_code, combined output)."""

    def put_file(self, local_path: Path, remote_path: str, *, timeout: int = 600) -> None:
        """Copy a local file to a guest path."""

    def test_connection(self) -> bool:
        """Return True when a trivial authenticated probe succeeds."""


def _strip_clixml(text: str) -> str:
    from lib import provision as provision_lib

    return provision_lib._strip_clixml(text)


def _ps_encoded_command(code: str) -> str:
    return base64.b64encode(code.encode("utf-16-le")).decode("ascii")


class WinrmGuestTransport:
    """Guest remoting over WinRM (pywinrm) - Windows fallback."""

    kind: GuestTransportKind = "winrm"

    def __init__(self, endpoint: GuestEndpoint) -> None:
        self.endpoint = endpoint

    def _session(self, *, timeout: int):
        from lib import provision as provision_lib

        # Share session construction with provision._make_session (tests patch that path).
        if self.endpoint.winrm_port != 5985:
            try:
                import winrm
            except ImportError as exc:  # pragma: no cover
                raise GuestTransportError("pywinrm is required for WinRM guest transport") from exc
            return winrm.Session(
                f"http://{self.endpoint.host}:{self.endpoint.winrm_port}/wsman",
                auth=(self.endpoint.username, self.endpoint.password),
                transport=_WINRM_TRANSPORT,
                operation_timeout_sec=timeout,
                read_timeout_sec=timeout + 10,
            )
        return provision_lib._make_session(
            self.endpoint.host,
            self.endpoint.username,
            self.endpoint.password,
            timeout,
        )

    def run_ps(self, code: str, *, timeout: int = 300) -> tuple[int, str]:
        session = self._session(timeout=timeout)
        result = session.run_ps(code)
        stdout = _strip_clixml(result.std_out.decode("utf-8", errors="replace").strip())
        stderr = _strip_clixml(result.std_err.decode("utf-8", errors="replace").strip())
        body = "\n".join(filter(None, [stdout, stderr]))
        return int(result.status_code), body

    def put_file(self, local_path: Path, remote_path: str, *, timeout: int = 600) -> None:
        # Chunked WinRM stdin upload stays in software_provision for now; this
        # seam exists so callers can prefer SSH put when resolve selects SSH.
        raise GuestTransportError(
            "WinRM put_file is not implemented on GuestTransport; "
            "use software_provision staging helpers for WinRM chunked upload"
        )

    def test_connection(self) -> bool:
        try:
            code, out = self.run_ps("Write-Output hatchery-guest-ok", timeout=10)
            return code == 0 and "hatchery-guest-ok" in out
        except Exception:
            return False

    def winrm_session(self, *, timeout: int):
        """Expose the underlying pywinrm session for Software chunked upload."""
        return self._session(timeout=timeout)


class SshGuestTransport:
    """Guest remoting over OpenSSH (password or identity_file)."""

    kind: GuestTransportKind = "ssh"

    def __init__(self, endpoint: GuestEndpoint) -> None:
        self.endpoint = endpoint

    def _password(self) -> str | None:
        if self.endpoint.identity_file:
            return None
        return self.endpoint.password or None

    def _ssh_argv(self, remote_command: str, *, connect_timeout: int) -> list[str]:
        password = self._password()
        return build_ssh_argv(
            host=self.endpoint.host,
            user=self.endpoint.username,
            port=self.endpoint.ssh_port,
            remote_command=remote_command,
            identity_file=self.endpoint.identity_file,
            use_agent=bool(self.endpoint.identity_file),
            known_hosts="accept-new",
            connect_timeout_seconds=connect_timeout,
            batch_mode=password is None,
        )

    def run_ps(self, code: str, *, timeout: int = 300) -> tuple[int, str]:
        encoded = _ps_encoded_command(code)
        if len(encoded) <= _ENCODED_COMMAND_MAX:
            remote = (
                "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass "
                f"-EncodedCommand {encoded}"
            )
            return self._run_remote(remote, timeout=timeout)

        # Large scripts: stage a temp .ps1, invoke -File, then delete.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".ps1",
            delete=False,
        ) as tmp:
            tmp.write(code)
            local_ps1 = Path(tmp.name)
        remote_ps1 = r"C:\Program Files\Hatchery\temp\hatchery-run.ps1"
        try:
            self.put_file(local_ps1, remote_ps1, timeout=min(timeout, 120))
            remote = (
                "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass "
                f'-File "{remote_ps1}"'
            )
            return self._run_remote(remote, timeout=timeout)
        finally:
            local_ps1.unlink(missing_ok=True)
            try:
                self._run_remote(
                    "powershell.exe -NoProfile -NonInteractive -Command "
                    f"\"Remove-Item -LiteralPath '{remote_ps1}' -Force "
                    '-ErrorAction SilentlyContinue"',
                    timeout=30,
                )
            except Exception:
                pass

    def _run_remote(self, remote_command: str, *, timeout: int) -> tuple[int, str]:
        connect_timeout = min(30, max(5, timeout))
        try:
            argv = self._ssh_argv(remote_command, connect_timeout=connect_timeout)
            result = run_openssh(argv, timeout=float(timeout + 5), password=self._password())
        except OpenSshClientError as exc:
            raise GuestTransportError(str(exc)) from exc
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        # Prefer stdout; append stderr when present (ssh often puts errors there).
        body = "\n".join(filter(None, [_strip_clixml(out), _strip_clixml(err)]))
        return result.returncode, body

    def put_file(self, local_path: Path, remote_path: str, *, timeout: int = 600) -> None:
        local_path = Path(local_path)
        if not local_path.is_file():
            raise GuestTransportError(f"local file not found: {local_path}")
        # Ensure remote parent exists (Windows guest path semantics on any Controller OS).
        parent = str(PureWindowsPath(remote_path).parent)
        if parent and parent not in {".", "\\"}:
            mkdir_code = (
                f"$p = '{parent.replace(chr(39), chr(39) + chr(39))}'; "
                "$null = New-Item -Path $p -ItemType Directory -Force"
            )
            encoded = _ps_encoded_command(mkdir_code)
            if len(encoded) <= _ENCODED_COMMAND_MAX:
                self._run_remote(
                    "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass "
                    f"-EncodedCommand {encoded}",
                    timeout=60,
                )
        password = self._password()
        try:
            argv = build_scp_argv(
                host=self.endpoint.host,
                user=self.endpoint.username,
                port=self.endpoint.ssh_port,
                local_path=str(local_path),
                remote_path=remote_path,
                identity_file=self.endpoint.identity_file,
                use_agent=bool(self.endpoint.identity_file),
                known_hosts="accept-new",
                connect_timeout_seconds=min(30, max(5, timeout)),
                batch_mode=password is None,
            )
            result = run_openssh(argv, timeout=float(timeout), password=password)
        except OpenSshClientError as exc:
            raise GuestTransportError(str(exc)) from exc
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            raise GuestTransportError(err or f"scp exited {result.returncode}")

    def test_connection(self) -> bool:
        try:
            code, out = self.run_ps("Write-Output hatchery-guest-ok", timeout=15)
            return code == 0 and "hatchery-guest-ok" in out
        except Exception:
            return False


def resolve_guest_transport(
    host: str,
    username: str,
    password: str,
    *,
    prefer_ssh: bool = True,
    identity_file: str | None = None,
    ssh_port: int = 22,
    winrm_port: int = 5985,
    on_fallback: Callable[[str], None] | None = None,
) -> WinrmGuestTransport | SshGuestTransport:
    """Return SSH guest transport when usable; otherwise WinRM Windows fallback.

    Emits ``on_fallback(reason)`` when falling back from SSH to WinRM so hatch
    events can surface the preference clearly.
    """
    endpoint = GuestEndpoint(
        host=host,
        username=username,
        password=password,
        ssh_port=ssh_port,
        winrm_port=winrm_port,
        identity_file=identity_file,
    )

    if prefer_ssh and check_ssh(host, port=ssh_port):
        ssh = SshGuestTransport(endpoint)
        if ssh.test_connection():
            log.debug("guest transport: SSH to %s:%s", host, ssh_port)
            return ssh
        reason = f"SSH open on {host}:{ssh_port} but guest auth/probe failed; using WinRM"
        log.info("%s", reason)
        if on_fallback:
            on_fallback(reason)

    if check_winrm(host, port=winrm_port):
        winrm_t = WinrmGuestTransport(endpoint)
        if winrm_t.test_connection():
            if prefer_ssh and not check_ssh(host, port=ssh_port) and on_fallback:
                on_fallback(f"Guest SSH not reachable on {host}:{ssh_port}; using WinRM")
            log.debug("guest transport: WinRM to %s:%s", host, winrm_port)
            return winrm_t
        raise GuestTransportError(f"WinRM open on {host}:{winrm_port} but guest auth/probe failed")

    raise GuestTransportError(
        f"No guest remoting available on {host} (SSH :{ssh_port} / WinRM :{winrm_port})"
    )


def get_guest_transport(
    host: str,
    username: str,
    password: str,
    *,
    kind: GuestTransportKind | None = None,
    identity_file: str | None = None,
    ssh_port: int = 22,
    winrm_port: int = 5985,
) -> WinrmGuestTransport | SshGuestTransport:
    """Return a transport of the requested kind, or resolve preference when None."""
    if kind is None:
        return resolve_guest_transport(
            host,
            username,
            password,
            identity_file=identity_file,
            ssh_port=ssh_port,
            winrm_port=winrm_port,
        )
    endpoint = GuestEndpoint(
        host=host,
        username=username,
        password=password,
        ssh_port=ssh_port,
        winrm_port=winrm_port,
        identity_file=identity_file,
    )
    if kind == "ssh":
        return SshGuestTransport(endpoint)
    if kind == "winrm":
        return WinrmGuestTransport(endpoint)
    raise GuestTransportError(f"unsupported guest transport: {kind!r}")
