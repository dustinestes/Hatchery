from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import winrm

from lib.clutch import GuestOS
from lib.guest_health import check_winrm
from lib.guest_paths import guest_paths_for

log = logging.getLogger(__name__)

# Windows FILETIME epoch (100ns ticks since 1601-01-01 UTC) ↔ Unix epoch offset.
_FILETIME_UNIX_EPOCH = 116444736000000000

EventEmit = Callable[[str, str], None]

# WinRM uses Negotiate (NTLM) by default after Enable-PSRemoting.
# NTLM is preferred over Basic because credentials never travel in plaintext.
# Requires LocalAccountTokenFilterPolicy=1 on the guest for non-built-in admin accounts.
_TRANSPORT = "ntlm"

# Windows guest path roles (ADR-0025 / #474). Prefer guest_paths_for(GuestOS) in new code.
_WINDOWS_PATHS = guest_paths_for(GuestOS.WIN11)
HATCHERY_GUEST_DIR = _WINDOWS_PATHS.root

# Written as the last step of hatchery-setup.ps1.
# Hatchery polls for this file before starting automation scripts so that
# provisioning never begins while first-boot setup is still running.
# Deleted by Hatchery immediately on detection.
SETUP_COMPLETE_FLAG = rf"{_WINDOWS_PATHS.temp}\hatchery-ready"

# Written by hatchery-setup.ps1 during FirstLogonCommands. Imported into hatch_events
# after WinRM connects, then deleted so the guest stays clean.
SETUP_LOG_FILE = rf"{_WINDOWS_PATHS.logs}\hatchery-setup.log"


_CLIXML_NS = "http://schemas.microsoft.com/powershell/2004/04"

# Write-HatchEvent function body — injected into every script before execution.
# Writes to stdout (captured by pywinrm) and to a per-script log file under
# HATCHERY_GUEST_DIR\logs\ for local audit. $script:HatchLogFile is set by
# _build_injection() before this function is defined.
_WRITE_HATCH_EVENT_FUNC = """\
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
    try { Add-Content -Path $script:HatchLogFile -Value $line -Encoding UTF8 } catch { }
}
"""


def _build_injection(script_name: str) -> str:
    """Build the preamble injected into every script before execution.

    Sets $script:HatchLogFile to a per-script path under HATCHERY_GUEST_DIR\\logs\\,
    creates the directory if needed, then defines Write-HatchEvent.
    """
    log_file = rf"{_WINDOWS_PATHS.logs}\{script_name}.log"
    return (
        f"$script:HatchLogFile = '{log_file}'\n"
        "$null = New-Item -Path (Split-Path $script:HatchLogFile) -ItemType Directory -Force\n"
        + _WRITE_HATCH_EVENT_FUNC
    )


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
    return winrm.Session(
        f"http://{ip}:5985/wsman",
        auth=(admin_username, admin_password),
        transport=_TRANSPORT,
        operation_timeout_sec=timeout,
        read_timeout_sec=timeout + 10,
    )


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


def _build_ps_invocation(content: str, parameters: dict[str, str], inject: str = "") -> str:
    """Optionally wrap content in a scriptblock for parameter passing.

    PowerShell requires param() to be the first statement in a scriptblock.
    When wrapping, the param() block is extracted and placed first, then
    the inject preamble follows, then the rest of the script — so named
    argument binding works correctly.

    Without parameters: inject is prepended and content is sent as-is.
    With parameters: content is wrapped in & { param(...) <inject> <rest> } -Key 'val'
    """
    if not parameters:
        return inject + content
    param_block, rest = _extract_param_block(content)
    if param_block:
        inner = param_block + "\n" + inject + rest
    else:
        inner = inject + content
    args = " ".join(f"-{k} {_ps_quote(v)}" for k, v in parameters.items())
    return f"& {{\n{inner}\n}} {args}"


def run_script(
    ip: str,
    admin_username: str,
    admin_password: str,
    script_path: str | Path,
    parameters: dict[str, str] | None = None,
    timeout: int = 300,
) -> tuple[int, str]:
    """Execute a PowerShell script on a remote Windows guest via WinRM.

    Returns (exit_code, output) where output combines stdout and stderr.
    Raises an exception if the WinRM connection cannot be established.
    """
    script_path = Path(script_path)
    content = script_path.read_text(encoding="utf-8")
    params = parameters or {}

    header = (
        f"[Hatchery] endpoint : http://{ip}:5985/wsman\n"
        f"[Hatchery] transport: {_TRANSPORT}\n"
        f"[Hatchery] user     : {admin_username}\n"
        f"[Hatchery] script   : {script_path.name}\n"
        f"[Hatchery] params   : {', '.join(f'{k}={v}' for k, v in params.items()) or 'none'}\n"
        f"[Hatchery] ---\n"
    )

    inject = _build_injection(script_path.name)
    ps_code = _build_ps_invocation(content, params, inject)
    session = _make_session(ip, admin_username, admin_password, timeout)
    result = session.run_ps(ps_code)
    stdout = _strip_clixml(result.std_out.decode("utf-8", errors="replace").strip())
    stderr = _strip_clixml(result.std_err.decode("utf-8", errors="replace").strip())
    body = "\n".join(filter(None, [stdout, stderr]))
    return result.status_code, header + body


def check_setup_complete(ip: str, admin_username: str, admin_password: str) -> bool:
    """Return True if the guest's setup-complete flag file exists.

    Called after WinRM TCP is confirmed open to ensure all FirstLogonCommands
    have finished before automation scripts begin.
    """
    try:
        session = _make_session(ip, admin_username, admin_password, timeout=10)
        result = session.run_ps(f"Test-Path '{SETUP_COMPLETE_FLAG}'")
        return result.std_out.decode("utf-8", errors="replace").strip().lower() == "true"
    except Exception:
        return False


def delete_setup_flag(ip: str, admin_username: str, admin_password: str) -> None:
    """Remove the setup-complete flag file from the guest.

    Called immediately after check_setup_complete() returns True so the flag
    leaves no permanent footprint on the guest.
    """
    session = _make_session(ip, admin_username, admin_password, timeout=10)
    try:
        session.run_ps(
            f"Remove-Item -Path '{SETUP_COMPLETE_FLAG}' -Force -ErrorAction SilentlyContinue"
        )
    except Exception:
        pass  # non-fatal; flag is ephemeral


def read_setup_log(ip: str, admin_username: str, admin_password: str) -> str:
    """Return the first-boot setup log from the guest, or empty string if absent.

    Called after check_setup_complete() returns True so hatchery-setup.ps1 step
    events can be imported into hatch_events before automation scripts run.
    """
    try:
        session = _make_session(ip, admin_username, admin_password, timeout=10)
        result = session.run_ps(
            f"Get-Content -Path '{SETUP_LOG_FILE}' -Raw -ErrorAction SilentlyContinue"
        )
        text = result.std_out.decode("utf-8", errors="replace")
        return _strip_clixml(text).strip()
    except Exception:
        return ""


def delete_setup_log(ip: str, admin_username: str, admin_password: str) -> None:
    """Remove the first-boot setup log from the guest after import.

    Non-fatal if the file is already gone or WinRM fails.
    """
    session = _make_session(ip, admin_username, admin_password, timeout=10)
    try:
        session.run_ps(f"Remove-Item -Path '{SETUP_LOG_FILE}' -Force -ErrorAction SilentlyContinue")
    except Exception:
        pass  # non-fatal; log is ephemeral


def shutdown_guest(ip: str, admin_username: str, admin_password: str) -> None:
    """Issue a graceful shutdown to the guest via WinRM.

    The WinRM connection will drop before the command returns — that is expected.
    """
    session = _make_session(ip, admin_username, admin_password, timeout=30)
    try:
        session.run_ps("Stop-Computer -Force")
    except Exception:
        pass  # connection drop during shutdown is expected


def restart_guest(ip: str, admin_username: str, admin_password: str) -> None:
    """Issue a graceful restart to the guest via WinRM.

    The WinRM connection will drop before the command returns - that is expected.
    """
    session = _make_session(ip, admin_username, admin_password, timeout=30)
    try:
        session.run_ps("Restart-Computer -Force")
    except Exception:
        pass  # connection drop during restart is expected


def get_last_boot_uptime(ip: str, admin_username: str, admin_password: str) -> str:
    """Return guest ``LastBootUpTime`` as a UTC FileTime string (sortable, comparable).

    This is the guest's own boot identity - not a Controller-side guess from TCP.
    """
    session = _make_session(ip, admin_username, admin_password, timeout=30)
    result = session.run_ps(
        "(Get-CimInstance -ClassName Win32_OperatingSystem).LastBootUpTime"
        ".ToUniversalTime().ToFileTimeUtc().ToString()"
    )
    if result.status_code != 0:
        err = _strip_clixml(result.std_err.decode("utf-8", errors="replace")).strip()
        raise RuntimeError(f"failed to read LastBootUpTime: {err or result.status_code}")
    text = _strip_clixml(result.std_out.decode("utf-8", errors="replace")).strip()
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
        if not check_winrm(ip):
            continue
        try:
            current = get_last_boot_uptime(ip, admin_username, admin_password)
        except Exception as exc:
            log.debug("LastBootUpTime probe failed (guest still coming up): %s", exc)
            continue
        if current != previous_boot_id:
            return current
        log.debug(
            "WinRM up but LastBootUpTime unchanged (%s) - waiting for real reboot",
            previous_boot_id,
        )
    raise RuntimeError(
        f"guest did not report a new LastBootUpTime within {int(timeout_sec)}s "
        f"(still {previous_boot_id!r})"
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
    """Require several successful authenticated WinRM probes after reboot.

    LastBootUpTime can flip while WinRM is still dropping pipes on heavy Send
    streams (Software staging). A short stable window reduces that race.
    """

    def emit(level: str, message: str) -> None:
        if on_event:
            on_event(level, message)
        log.info("%s", message)

    emit(
        "INFO",
        f"Waiting for WinRM to stabilize after reboot ({consecutive} consecutive probes)",
    )
    deadline = time.monotonic() + timeout_sec
    ok = 0
    while time.monotonic() < deadline:
        try:
            session = _make_session(ip, admin_username, admin_password, timeout=30)
            result = session.run_ps("Write-Output ready")
            if result.status_code == 0:
                ok += 1
                if ok >= consecutive:
                    emit(
                        "INFO",
                        f"WinRM stable after reboot ({consecutive} consecutive probes)",
                    )
                    return
            else:
                if ok:
                    emit(
                        "WARN",
                        "WinRM probe returned non-zero during settle - resetting stability count",
                    )
                ok = 0
        except Exception as exc:
            if ok:
                emit(
                    "WARN",
                    f"WinRM probe failed during settle - resetting stability count: {exc}",
                )
            else:
                log.debug("post-reboot WinRM probe failed: %s", exc)
            ok = 0
        time.sleep(poll_interval_sec)
    raise RuntimeError(
        f"WinRM did not stay stable for {consecutive} probes within {int(timeout_sec)}s "
        "after guest reboot"
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

    When ``settle`` is True (default), also wait for consecutive successful WinRM
    probes so the next automation does not hit a half-ready remoting stack.

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
        wait_for_winrm_stable(ip, admin_username, admin_password, on_event=on_event)
    return after
