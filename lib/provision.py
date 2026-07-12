from __future__ import annotations

from pathlib import Path

import winrm

# WinRM uses Negotiate (NTLM) by default after Enable-PSRemoting.
# NTLM is preferred over Basic because credentials never travel in plaintext.
# Requires LocalAccountTokenFilterPolicy=1 on the guest for non-built-in admin accounts.
_TRANSPORT = "ntlm"


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
    stdout = result.std_out.decode("utf-8", errors="replace").strip()
    stderr = result.std_err.decode("utf-8", errors="replace").strip()
    body = "\n".join(filter(None, [stdout, stderr]))
    return result.status_code, header + body


def shutdown_guest(ip: str, admin_username: str, admin_password: str) -> None:
    """Issue a graceful shutdown to the guest via WinRM.

    The WinRM connection will drop before the command returns — that is expected.
    """
    session = _make_session(ip, admin_username, admin_password, timeout=30)
    try:
        session.run_ps("Stop-Computer -Force")
    except Exception:
        pass  # connection drop during shutdown is expected
