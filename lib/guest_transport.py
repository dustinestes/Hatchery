"""Guest transport - Controller remoting to a guest VM (not a Nest host).

SSH is primary; WinRM is the Windows fallback (ADR-0029 / #497). Nest transport
(`lib.nest_transport`) is a parallel plane - different target, credentials, and
identity. Shared OpenSSH **client** helpers live in ``lib.openssh_client``.

Guest SSH keys come from Clutch ``remoting.ssh.authorize`` (#524 / ADR-0030):
inject pubkeys, verify BatchMode + identity path, then disable password SSH.
Until authorize completes (or when WinRM fallback is used), hatch may still use
the admin password via sshpass or SSH_ASKPASS on the Controller.
"""

from __future__ import annotations

import base64
import logging
import shutil
import subprocess
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

# Large ``run_ps`` bodies are staged here (not Hatchery temp - that dir is
# created by ensure itself; #591).
_REMOTE_RUN_PS1 = r"C:\Windows\Temp\hatchery-run.ps1"

# Relative to Controller data_dir (ADR-0037 / #593).
_GUEST_KNOWN_HOSTS_REL = Path("remoting") / "known_hosts" / "guest"


class GuestTransportError(RuntimeError):
    """Raised when guest remoting cannot connect or a remote command fails."""


def _ps_single_quote(value: str) -> str:
    """PowerShell single-quoted string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def guest_known_hosts_path() -> Path:
    """Return ``{data_dir}/remoting/known_hosts/guest``, creating parents/file."""
    from lib import config as config_lib

    path = config_lib.data_dir() / _GUEST_KNOWN_HOSTS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    return path


def remove_guest_known_host(vm_id: str | None) -> None:
    """Best-effort remove ``HostKeyAlias`` entry for ``vm_id`` from guest trust (#593)."""
    alias = (vm_id or "").strip()
    if not alias:
        return
    path = guest_known_hosts_path()
    if not path.is_file() or path.stat().st_size == 0:
        return
    ssh_keygen = shutil.which("ssh-keygen")
    if ssh_keygen is None:
        log.debug("ssh-keygen not on PATH; skip guest known_hosts prune for %s", alias)
        return
    try:
        subprocess.run(
            [ssh_keygen, "-R", alias, "-f", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.debug("guest known_hosts prune failed for %s: %s", alias, exc)
        return
    # ssh-keygen leaves a .old backup beside the file; drop it quietly.
    old = path.with_name(path.name + ".old")
    try:
        old.unlink(missing_ok=True)
    except OSError:
        pass


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
    # Pre-minted VM UUID for HostKeyAlias (ADR-0036 / #593).
    vm_id: str | None = None

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
        encoded = _ps_encoded_command(code)
        if len(encoded) <= _ENCODED_COMMAND_MAX:
            session = self._session(timeout=timeout)
            result = session.run_ps(code)
            stdout = _strip_clixml(result.std_out.decode("utf-8", errors="replace").strip())
            stderr = _strip_clixml(result.std_err.decode("utf-8", errors="replace").strip())
            body = "\n".join(filter(None, [stdout, stderr]))
            return int(result.status_code), body

        # Large scripts: stage under Windows Temp, invoke as script (#591).
        # pywinrm's session.run_ps always EncodedCommand-encodes the body.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".ps1",
            delete=False,
        ) as tmp:
            tmp.write(code)
            local_ps1 = Path(tmp.name)
        remote_ps1 = _REMOTE_RUN_PS1
        try:
            self.put_file(local_ps1, remote_ps1, timeout=min(timeout, 120))
            session = self._session(timeout=timeout)
            wrapper = (
                f"$ErrorActionPreference = 'Stop'\n"
                f"& {_ps_single_quote(remote_ps1)}\n"
                f"exit $(if ($null -ne $LASTEXITCODE) {{ $LASTEXITCODE }} else {{ 0 }})\n"
            )
            result = session.run_ps(wrapper)
            stdout = _strip_clixml(result.std_out.decode("utf-8", errors="replace").strip())
            stderr = _strip_clixml(result.std_err.decode("utf-8", errors="replace").strip())
            body = "\n".join(filter(None, [stdout, stderr]))
            return int(result.status_code), body
        finally:
            local_ps1.unlink(missing_ok=True)
            try:
                session = self._session(timeout=30)
                session.run_ps(
                    "Remove-Item -LiteralPath "
                    f"{_ps_single_quote(remote_ps1)} -Force -ErrorAction SilentlyContinue"
                )
            except Exception:
                pass

    def put_file(self, local_path: Path, remote_path: str, *, timeout: int = 600) -> None:
        """Chunked WinRM stdin upload (same path as Software staging; #591)."""
        from lib import software_provision as soft_prov

        soft_prov._upload_file(
            self.endpoint.host,
            self.endpoint.username,
            self.endpoint.password,
            Path(local_path),
            remote_path,
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

    def _ssh_trust_kwargs(self) -> dict:
        """Hatchery-owned guest known_hosts + HostKeyAlias when vm_id is set (#593)."""
        alias = (self.endpoint.vm_id or "").strip() or None
        return {
            "known_hosts": "accept-new",
            "user_known_hosts_file": str(guest_known_hosts_path()),
            "host_key_alias": alias,
        }

    def _ssh_argv(self, remote_command: str, *, connect_timeout: int) -> list[str]:
        password = self._password()
        # When an identity file is set, disable the agent so BatchMode verify
        # cannot offer a different agent key than the authorize identity.
        return build_ssh_argv(
            host=self.endpoint.host,
            user=self.endpoint.username,
            port=self.endpoint.ssh_port,
            remote_command=remote_command,
            identity_file=self.endpoint.identity_file,
            use_agent=False if self.endpoint.identity_file else True,
            connect_timeout_seconds=connect_timeout,
            batch_mode=password is None,
            **self._ssh_trust_kwargs(),
        )

    def run_ps(self, code: str, *, timeout: int = 300) -> tuple[int, str]:
        encoded = _ps_encoded_command(code)
        if len(encoded) <= _ENCODED_COMMAND_MAX:
            remote = (
                "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass "
                f"-EncodedCommand {encoded}"
            )
            return self._run_remote(remote, timeout=timeout)

        # Large scripts: stage under Windows Temp, invoke -File, then delete (#591).
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".ps1",
            delete=False,
        ) as tmp:
            tmp.write(code)
            local_ps1 = Path(tmp.name)
        remote_ps1 = _REMOTE_RUN_PS1
        try:
            self.put_file(local_ps1, remote_ps1, timeout=min(timeout, 120))
            # Path has no spaces; keep -File argv free of nested quotes for sshd/cmd.
            remote = (
                "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass "
                f"-File {remote_ps1}"
            )
            return self._run_remote(remote, timeout=timeout)
        finally:
            local_ps1.unlink(missing_ok=True)
            try:
                self._run_remote(
                    "powershell.exe -NoProfile -NonInteractive -Command "
                    f"Remove-Item -LiteralPath {_ps_single_quote(remote_ps1)} "
                    "-Force -ErrorAction SilentlyContinue",
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
                use_agent=False if self.endpoint.identity_file else True,
                connect_timeout_seconds=min(30, max(5, timeout)),
                batch_mode=password is None,
                **self._ssh_trust_kwargs(),
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
    vm_id: str | None = None,
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
        vm_id=vm_id,
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
    vm_id: str | None = None,
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
            vm_id=vm_id,
        )
    endpoint = GuestEndpoint(
        host=host,
        username=username,
        password=password,
        ssh_port=ssh_port,
        winrm_port=winrm_port,
        identity_file=identity_file,
        vm_id=vm_id,
    )
    if kind == "ssh":
        return SshGuestTransport(endpoint)
    if kind == "winrm":
        return WinrmGuestTransport(endpoint)
    raise GuestTransportError(f"unsupported guest transport: {kind!r}")
