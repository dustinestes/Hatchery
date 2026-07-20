from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import winrm

# WinRM uses Negotiate (NTLM) by default after Enable-PSRemoting.
# NTLM is preferred over Basic because credentials never travel in plaintext.
# Requires LocalAccountTokenFilterPolicy=1 on the guest for non-built-in admin accounts.
_TRANSPORT = "ntlm"

# Single well-identified directory for all Hatchery-managed files on the guest.
# Created by hatchery-setup.ps1 on first boot.
HATCHERY_GUEST_DIR = r"C:\Program Files\Hatchery"

# Written as the last step of hatchery-setup.ps1.
# Hatchery polls for this file before starting automation scripts so that
# provisioning never begins while first-boot setup is still running.
# Deleted by Hatchery immediately on detection.
SETUP_COMPLETE_FLAG = rf"{HATCHERY_GUEST_DIR}\temp\hatchery-ready"


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
        [string]$Tier = 'INFO',
        [string]$Component = ''
    )
    $prefix = if ($Component) { "[HATCH:$Tier][$Component]" } else { "[HATCH:$Tier]" }
    Write-Output "$prefix $Message"
    $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $line = if ($Component) { "[HATCH:$Tier][$Component][$ts] $Message" } else { "[HATCH:$Tier][$ts] $Message" }
    try { Add-Content -Path $script:HatchLogFile -Value $line -Encoding UTF8 } catch { }
}
"""


def _build_injection(script_name: str) -> str:
    """Build the preamble injected into every script before execution.

    Sets $script:HatchLogFile to a per-script path under HATCHERY_GUEST_DIR\\logs\\,
    creates the directory if needed, then defines Write-HatchEvent.
    """
    log_file = rf"{HATCHERY_GUEST_DIR}\logs\{script_name}.log"
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

    The WinRM connection will drop before the command returns — that is expected.
    """
    session = _make_session(ip, admin_username, admin_password, timeout=30)
    try:
        session.run_ps("Restart-Computer -Force")
    except Exception:
        pass  # connection drop during restart is expected
