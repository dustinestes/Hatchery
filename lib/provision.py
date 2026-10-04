from __future__ import annotations

import contextvars
import logging
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import winrm

from lib.clutch import GuestOS
from lib.guest_health import check_ssh, check_winrm
from lib.guest_paths import guest_paths_for

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GuestTransportDefaults:
    """Thread/async-scoped defaults for guest SSH client identity (#524)."""

    identity_file: str | None = None
    ssh_port: int = 22
    winrm_port: int = 5985


_guest_transport_defaults: contextvars.ContextVar[GuestTransportDefaults] = contextvars.ContextVar(
    "guest_transport_defaults",
    default=GuestTransportDefaults(),
)


@contextmanager
def guest_transport_defaults(
    *,
    identity_file: str | None = None,
    ssh_port: int = 22,
    winrm_port: int = 5985,
) -> Iterator[None]:
    """Bind guest SSH identity/port for ``_guest_transport`` in this context."""
    token = _guest_transport_defaults.set(
        GuestTransportDefaults(
            identity_file=identity_file,
            ssh_port=ssh_port,
            winrm_port=winrm_port,
        )
    )
    try:
        yield
    finally:
        _guest_transport_defaults.reset(token)


# Windows FILETIME epoch (100ns ticks since 1601-01-01 UTC) ↔ Unix epoch offset.
_FILETIME_UNIX_EPOCH = 116444736000000000

EventEmit = Callable[[str, str], None]

# WinRM uses Negotiate (NTLM) by default after Enable-PSRemoting.
# NTLM is preferred over Basic because credentials never travel in plaintext.
# Requires LocalAccountTokenFilterPolicy=1 on the guest for non-built-in admin accounts.
_TRANSPORT = "ntlm"

# Windows guest path roles (ADR-0025 / #474). Prefer guest_paths_for(GuestOS) in new code.
_WINDOWS_PATHS = guest_paths_for(GuestOS.WINDOWS)
HATCHERY_GUEST_DIR = _WINDOWS_PATHS.root

# Written as the last step of hatchery-setup-windows.ps1.
# Hatchery polls for this file before starting automation scripts so that
# provisioning never begins while first-boot setup is still running.
# Deleted by Hatchery immediately on detection.
SETUP_COMPLETE_FLAG = rf"{_WINDOWS_PATHS.temp}\hatchery-ready"

# Written by hatchery-setup-windows.ps1 during FirstLogonCommands. Imported into hatch_events
# after WinRM connects, then deleted so the guest stays clean.
SETUP_LOG_FILE = rf"{_WINDOWS_PATHS.logs}\hatchery-setup-windows.log"


_CLIXML_NS = "http://schemas.microsoft.com/powershell/2004/04"

# Hatchery guest PowerShell module (#554 / ADR-0032). Installed once by ensure
# under HATCHERY_ROOT\modules\Hatchery; discovered via PSModulePath (WinPS + pwsh).
# Controllers do not inject this function into user script bodies.
_HATCHERY_MODULE_PSM1 = """\
function Write-HatchEvent {
    param(
        [Parameter(Mandatory)]
        [string]$Message,
        [ValidateSet('INFO', 'WARN', 'ERROR')]
        [string]$Level = 'INFO',
        [string]$Component = ''
    )
    $prefix = if ($Component) { "[HATCH:$Level][$Component]" } else { "[HATCH:$Level]" }
    Write-Output "$prefix $Message"
    $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss+00:00")
    $line = if ($Component) { "[HATCH:$Level][$Component][$ts] $Message" } else { "[HATCH:$Level][$ts] $Message" }
    $logFile = $env:HATCHERY_SCRIPT_LOG
    if (-not $logFile -and $env:HATCHERY_LOGS) {
        $logFile = Join-Path $env:HATCHERY_LOGS 'hatchery-events.log'
    }
    if ($logFile) {
        try {
            $null = New-Item -Path (Split-Path -Parent $logFile) -ItemType Directory -Force
            Add-Content -Path $logFile -Value $line -Encoding UTF8
        } catch { }
    }
}

Export-ModuleMember -Function Write-HatchEvent
"""

_HATCHERY_MODULE_PSD1 = """\
@{
    RootModule        = 'Hatchery.psm1'
    ModuleVersion     = '1.0.0'
    GUID              = 'b8e6c2a1-4f3d-4e9a-9c1b-7a2d5e6f8a90'
    Author            = 'Hatchery'
    CompanyName       = 'Hatchery'
    Copyright         = 'Copyright (c) Hatchery'
    Description       = 'Hatchery guest builtins (Write-HatchEvent and related helpers).'
    PowerShellVersion = '5.1'
    FunctionsToExport = @('Write-HatchEvent')
    CmdletsToExport   = @()
    VariablesToExport = @()
    AliasesToExport   = @()
}
"""


def hatchery_module_psm1_source() -> str:
    """PowerShell module body installed under ``HATCHERY_ROOT\\modules\\Hatchery``."""
    return _HATCHERY_MODULE_PSM1.strip() + "\n"


def hatchery_module_psd1_source() -> str:
    """PowerShell module manifest installed beside ``Hatchery.psm1``."""
    return _HATCHERY_MODULE_PSD1.strip() + "\n"


def _strip_clixml(text: str) -> str:
    """Extract plain text from CLIXML-formatted PowerShell output.

    pywinrm's run_ps() returns CLIXML (PowerShell's XML serialization format)
    prefixed with "#< CLIXML\r\n" when output goes through the PowerShell
    pipeline. This strips the header, extracts readable string content from
    <S> nodes, and discards progress/verbose/debug objects.
    Returns the input unchanged when it is not CLIXML.
    """
    stripped = text.lstrip()
    # CLIXML output is always prefixed with "#< CLIXML\r\n" by PowerShell
    if stripped.startswith("#< CLIXML"):
        nl = stripped.find("\n")
        stripped = stripped[nl + 1 :].lstrip() if nl != -1 else ""
    if not stripped.startswith("<Objs"):
        return text
    try:
        root = ET.fromstring(stripped)
        lines = []
        for node in root.iter(f"{{{_CLIXML_NS}}}S"):
            val = node.text or ""
            # Decode PowerShell _xHHHH_ unicode escapes (e.g. _x000D_ = \r)
            val = re.sub(r"_x([0-9A-Fa-f]{4})_", lambda m: chr(int(m.group(1), 16)), val)
            val = val.replace("\r\n", "\n").replace("\r", "\n").strip()
            if val:
                lines.append(val)
        return "\n".join(lines)
    except ET.ParseError:
        return text


def _make_session(ip: str, admin_username: str, admin_password: str, timeout: int) -> winrm.Session:
    """Return a pywinrm session (WinRM-only helpers / Software chunked upload)."""
    return winrm.Session(
        f"http://{ip}:5985/wsman",
        auth=(admin_username, admin_password),
        transport=_TRANSPORT,
        operation_timeout_sec=timeout,
        read_timeout_sec=timeout + 10,
    )


def _guest_transport(
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    on_fallback: Callable[[str], None] | None = None,
    identity_file: str | None = None,
    ssh_port: int | None = None,
    winrm_port: int | None = None,
):
    """Resolve SSH-primary / WinRM-fallback guest remoting (#497 / #524)."""
    from lib import guest_transport as gt

    defaults = _guest_transport_defaults.get()
    return gt.resolve_guest_transport(
        ip,
        admin_username,
        admin_password,
        on_fallback=on_fallback,
        identity_file=identity_file if identity_file is not None else defaults.identity_file,
        ssh_port=ssh_port if ssh_port is not None else defaults.ssh_port,
        winrm_port=winrm_port if winrm_port is not None else defaults.winrm_port,
    )


def guest_remoting_ready(ip: str) -> bool:
    """Cheap TCP check: guest SSH or WinRM port is open."""
    return check_ssh(ip) or check_winrm(ip)


def _ps_quote(value: str) -> str:
    """Single-quote a PowerShell string argument, escaping interior single quotes."""
    return "'" + str(value).replace("'", "''") + "'"


def _extract_param_block(content: str) -> tuple[str, str]:
    """Split content into (param_block, rest) at the boundary of the param() block.

    Tracks parenthesis depth so nested parens in default values are handled correctly.
    Returns ('', content) when no param block is found.
    """
    m = re.search(r"^[ \t]*param\s*\(", content, re.MULTILINE | re.IGNORECASE)
    if not m:
        return "", content
    start = m.start()
    paren_start = content.index("(", m.start())
    depth = 0
    pos = paren_start
    while pos < len(content):
        if content[pos] == "(":
            depth += 1
        elif content[pos] == ")":
            depth -= 1
            if depth == 0:
                end = pos + 1
                return content[start:end], content[end:]
        pos += 1
    return "", content


def _build_ps_invocation(
    content: str,
    parameters: dict[str, str],
    *,
    env_prefix: str = "",
) -> str:
    """Build the remoting payload: optional outer env, then user script + clutch params.

    User script bodies are not rewritten with Hatchery helper functions (#554).
    Process env (reserved / Clutch / job log path) is applied in an outer scope so
    ``param()`` remains the first statement inside the user scriptblock.

    Clutch parameter values are the only values bound into the user scriptblock
    (``& { param(...) <user body> } -Key 'val'``). When the script declares
    ``param()`` but the Clutch passes no values, the scriptblock still runs so
    defaults apply and outer env stays outside ``param()``.
    """
    param_block, rest = _extract_param_block(content)
    if parameters:
        inner = (param_block + "\n" + rest) if param_block else content
        args = " ".join(f"-{k} {_ps_quote(v)}" for k, v in parameters.items())
        user = f"& {{\n{inner}\n}} {args}"
    elif param_block and env_prefix:
        # Keep param() first inside the user scriptblock; env stays outside.
        user = f"& {{\n{param_block}\n{rest}\n}}"
    elif param_block:
        user = param_block + "\n" + rest
    else:
        user = content
    return env_prefix + user


def run_script(
    ip: str,
    admin_username: str,
    admin_password: str,
    script_path: str | Path,
    parameters: dict[str, str] | None = None,
    timeout: int = 300,
    environment: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Execute a PowerShell script on a remote Windows guest (SSH primary, WinRM fallback).

    ``environment`` is already-merged guest env (reserved + user; #501).
    Windows path today: PowerShell ``$env:`` assignments outside the user body.
    ``Write-HatchEvent`` comes from the guest Hatchery module (ensure / PSModulePath),
    not from rewriting the user script. POSIX export helper lives in ``lib.guest_env``
    for future Linux / macOS remoting.

    Returns (exit_code, output) where output combines stdout and stderr.
    Raises an exception if guest remoting cannot be established.
    """
    from lib import guest_env as guest_env_lib

    script_path = Path(script_path)
    content = script_path.read_text(encoding="utf-8")
    params = parameters or {}

    transport = _guest_transport(ip, admin_username, admin_password)
    defaults = _guest_transport_defaults.get()
    if transport.kind == "ssh":
        endpoint = f"ssh://{admin_username}@{ip}:{defaults.ssh_port}"
        transport_label = "ssh"
    else:
        endpoint = f"http://{ip}:{defaults.winrm_port}/wsman"
        transport_label = _TRANSPORT

    header = (
        f"[Hatchery] endpoint : {endpoint}\n"
        f"[Hatchery] transport: {transport_label}\n"
        f"[Hatchery] user     : {admin_username}\n"
        f"[Hatchery] script   : {script_path.name}\n"
        f"[Hatchery] params   : {', '.join(f'{k}={v}' for k, v in params.items()) or 'none'}\n"
        f"[Hatchery] ---\n"
    )

    job_env = dict(environment or {})
    if "HATCHERY_SCRIPT_LOG" not in job_env:
        logs = job_env.get("HATCHERY_LOGS") or _WINDOWS_PATHS.logs
        job_env["HATCHERY_SCRIPT_LOG"] = rf"{logs}\{script_path.name}.log"
    if "HATCHERY_MODULES" not in job_env:
        job_env["HATCHERY_MODULES"] = _WINDOWS_PATHS.modules
    env_prefix = guest_env_lib.powershell_job_preamble(job_env)
    ps_code = _build_ps_invocation(content, params, env_prefix=env_prefix)
    status, body = transport.run_ps(ps_code, timeout=timeout)
    return status, header + body


def check_setup_complete(ip: str, admin_username: str, admin_password: str) -> bool:
    """Return True if the guest's setup-complete flag file exists.

    Called after guest remoting TCP is open to ensure all FirstLogonCommands
    have finished before automation scripts begin. Prefers SSH (#497).
    """
    try:
        transport = _guest_transport(ip, admin_username, admin_password)
        code, out = transport.run_ps(f"Test-Path '{SETUP_COMPLETE_FLAG}'", timeout=10)
        if code != 0:
            return False
        return out.strip().splitlines()[-1].strip().lower() == "true" if out.strip() else False
    except Exception:
        return False


def delete_setup_flag(ip: str, admin_username: str, admin_password: str) -> None:
    """Remove the setup-complete flag file from the guest.

    Called immediately after check_setup_complete() returns True so the flag
    leaves no permanent footprint on the guest.
    """
    try:
        transport = _guest_transport(ip, admin_username, admin_password)
        transport.run_ps(
            f"Remove-Item -Path '{SETUP_COMPLETE_FLAG}' -Force -ErrorAction SilentlyContinue",
            timeout=10,
        )
    except Exception:
        pass  # non-fatal; flag is ephemeral


def read_setup_log(ip: str, admin_username: str, admin_password: str) -> str:
    """Return the first-boot setup log from the guest, or empty string if absent.

    Called after check_setup_complete() returns True so hatchery-setup-windows.ps1 step
    events can be imported into hatch_events before automation scripts run.
    """
    try:
        transport = _guest_transport(ip, admin_username, admin_password)
        _code, text = transport.run_ps(
            f"Get-Content -Path '{SETUP_LOG_FILE}' -Raw -ErrorAction SilentlyContinue",
            timeout=10,
        )
        return _strip_clixml(text).strip()
    except Exception:
        return ""


def delete_setup_log(ip: str, admin_username: str, admin_password: str) -> None:
    """Remove the first-boot setup log from the guest after import.

    Non-fatal if the file is already gone or remoting fails.
    """
    try:
        transport = _guest_transport(ip, admin_username, admin_password)
        transport.run_ps(
            f"Remove-Item -Path '{SETUP_LOG_FILE}' -Force -ErrorAction SilentlyContinue",
            timeout=10,
        )
    except Exception:
        pass  # non-fatal; log is ephemeral


def shutdown_guest(ip: str, admin_username: str, admin_password: str) -> None:
    """Issue a graceful shutdown to the guest via guest remoting.

    The connection will drop before the command returns - that is expected.
    """
    try:
        transport = _guest_transport(ip, admin_username, admin_password)
        transport.run_ps("Stop-Computer -Force", timeout=30)
    except Exception:
        pass  # connection drop during shutdown is expected


def restart_guest(ip: str, admin_username: str, admin_password: str) -> None:
    """Issue a graceful restart to the guest via guest remoting.

    The connection will drop before the command returns - that is expected.
    """
    try:
        transport = _guest_transport(ip, admin_username, admin_password)
        transport.run_ps("Restart-Computer -Force", timeout=30)
    except Exception:
        pass  # connection drop during restart is expected


def get_last_boot_uptime(ip: str, admin_username: str, admin_password: str) -> str:
    """Return guest ``LastBootUpTime`` as a UTC FileTime string (sortable, comparable).

    This is the guest's own boot identity - not a Controller-side guess from TCP.
    """
    transport = _guest_transport(ip, admin_username, admin_password)
    code, text = transport.run_ps(
        "(Get-CimInstance -ClassName Win32_OperatingSystem).LastBootUpTime"
        ".ToUniversalTime().ToFileTimeUtc().ToString()",
        timeout=30,
    )
    if code != 0:
        raise RuntimeError(f"failed to read LastBootUpTime: {text or code}")
    # First line only; ignore CLIXML noise leftovers.
    token = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if not token.isdigit():
        raise RuntimeError(f"unexpected LastBootUpTime value from guest: {text!r}")
    return token


def filetime_to_utc(filetime: str | int) -> datetime:
    """Convert a Windows UTC FILETIME (100ns ticks since 1601) to an aware UTC datetime."""
    ft = int(filetime)
    return datetime.fromtimestamp((ft - _FILETIME_UNIX_EPOCH) / 10_000_000, tz=timezone.utc)


def format_guest_reboot_confirmed(filetime: str) -> str:
    """Event copy: UTC ISO matching hatch event timestamps, plus raw FileTime ticks."""
    iso = filetime_to_utc(filetime).isoformat(timespec="seconds")
    return f"Guest reboot confirmed: {iso} (LastBootUpTime={filetime})"


def wait_for_boot_uptime_change(
    ip: str,
    admin_username: str,
    admin_password: str,
    previous_boot_id: str,
    *,
    poll_interval_sec: float = 5.0,
    timeout_sec: float = 600.0,
) -> str:
    """Block until the guest reports a ``LastBootUpTime`` different from ``previous_boot_id``.

    TCP WinRM may come back (or never drop) before the reboot finishes; only a new
    boot identity means the guest has actually restarted. Raises on timeout.
    """
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        time.sleep(poll_interval_sec)
        if not guest_remoting_ready(ip):
            continue
        try:
            current = get_last_boot_uptime(ip, admin_username, admin_password)
        except Exception as exc:
            log.debug("LastBootUpTime probe failed (guest still coming up): %s", exc)
            continue
        if current != previous_boot_id:
            return current
        log.debug(
            "Guest remoting up but LastBootUpTime unchanged (%s) - waiting for real reboot",
            previous_boot_id,
        )
    raise RuntimeError(
        f"guest did not report a new LastBootUpTime within {int(timeout_sec)}s "
        f"(still {previous_boot_id!r})"
    )


def wait_for_guest_stable(
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    consecutive: int = 3,
    poll_interval_sec: float = 5.0,
    timeout_sec: float = 180.0,
    on_event: EventEmit | None = None,
) -> None:
    """Require several successful authenticated guest remoting probes after reboot.

    LastBootUpTime can flip while remoting is still dropping pipes on heavy Send
    streams (Software staging). A short stable window reduces that race.
    """

    def emit(level: str, message: str) -> None:
        if on_event:
            on_event(level, message)
        log.info("%s", message)

    emit(
        "INFO",
        f"Waiting for guest remoting to stabilize after reboot ({consecutive} consecutive probes)",
    )
    deadline = time.monotonic() + timeout_sec
    ok = 0
    while time.monotonic() < deadline:
        try:
            transport = _guest_transport(ip, admin_username, admin_password)
            code, _out = transport.run_ps("Write-Output ready", timeout=30)
            if code == 0:
                ok += 1
                if ok >= consecutive:
                    emit(
                        "INFO",
                        f"Guest remoting stable after reboot "
                        f"({consecutive} consecutive probes via {transport.kind})",
                    )
                    return
            else:
                if ok:
                    emit(
                        "WARN",
                        "Guest remoting probe returned non-zero during settle - "
                        "resetting stability count",
                    )
                ok = 0
        except Exception as exc:
            if ok:
                emit(
                    "WARN",
                    f"Guest remoting probe failed during settle - resetting stability count: {exc}",
                )
            else:
                log.debug("post-reboot guest remoting probe failed: %s", exc)
            ok = 0
        time.sleep(poll_interval_sec)
    raise RuntimeError(
        f"Guest remoting did not stay stable for {consecutive} probes within "
        f"{int(timeout_sec)}s after guest reboot"
    )


def wait_for_winrm_stable(
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    consecutive: int = 3,
    poll_interval_sec: float = 5.0,
    timeout_sec: float = 180.0,
    on_event: EventEmit | None = None,
) -> None:
    """Compatibility alias for ``wait_for_guest_stable`` (SSH primary / WinRM fallback)."""
    wait_for_guest_stable(
        ip,
        admin_username,
        admin_password,
        consecutive=consecutive,
        poll_interval_sec=poll_interval_sec,
        timeout_sec=timeout_sec,
        on_event=on_event,
    )


def reboot_guest_and_wait(
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    poll_interval_sec: float = 5.0,
    timeout_sec: float = 600.0,
    settle: bool = True,
    on_event: EventEmit | None = None,
) -> str:
    """Capture ``LastBootUpTime``, restart the guest, wait until boot identity changes.

    When ``settle`` is True (default), also wait for consecutive successful guest
    remoting probes so the next automation does not hit a half-ready stack.

    Emits operator-visible events via ``on_event(level, message)`` when provided:
    reboot confirmed, then settle wait / stable (and settle WARN resets).

    Returns the post-reboot ``LastBootUpTime`` FileTime string.
    """

    def emit(level: str, message: str) -> None:
        if on_event:
            on_event(level, message)

    before = get_last_boot_uptime(ip, admin_username, admin_password)
    restart_guest(ip, admin_username, admin_password)
    after = wait_for_boot_uptime_change(
        ip,
        admin_username,
        admin_password,
        before,
        poll_interval_sec=poll_interval_sec,
        timeout_sec=timeout_sec,
    )
    emit("INFO", format_guest_reboot_confirmed(after))
    if settle:
        wait_for_guest_stable(ip, admin_username, admin_password, on_event=on_event)
    return after
