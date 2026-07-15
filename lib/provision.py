from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import winrm

# WinRM uses Negotiate (NTLM) by default after Enable-PSRemoting.
# NTLM is preferred over Basic because credentials never travel in plaintext.
# Requires LocalAccountTokenFilterPolicy=1 on the guest for non-built-in admin accounts.
_TRANSPORT = "ntlm"

# Written by the last FirstLogonCommand in every answer file template.
# Hatchery polls for this file before starting automation scripts so that
# provisioning never begins while FirstLogonCommands are still running.
# Deleted by Hatchery immediately on detection — no permanent guest footprint.
SETUP_COMPLETE_FLAG = r"C:\Windows\Temp\hatchery-ready"


_CLIXML_NS = "http://schemas.microsoft.com/powershell/2004/04"


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


def _build_ps_invocation(content: str, parameters: dict[str, str]) -> str:
    """Wrap script content in a scriptblock call when parameters are present.

    PowerShell's param() block works inside a scriptblock called with named args:
        & { param($Name) ... } -Name 'value'
    This lets us pass values without touching the script file.
    """
    if not parameters:
        return content
    args = " ".join(f"-{k} {_ps_quote(v)}" for k, v in parameters.items())
    return f"& {{\n{content}\n}} {args}"


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

    ps_code = _build_ps_invocation(content, params)
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
