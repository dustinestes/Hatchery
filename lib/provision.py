from __future__ import annotations

from pathlib import Path

import winrm


def run_script(
    ip: str,
    admin_username: str,
    admin_password: str,
    script_path: str | Path,
    timeout: int = 300,
) -> tuple[int, str]:
    """Execute a PowerShell script on a remote Windows guest via WinRM.

    Returns (exit_code, output) where output combines stdout and stderr.
    Raises an exception if the WinRM connection cannot be established.
    """
    content = Path(script_path).read_text(encoding="utf-8")
    session = winrm.Session(
        f"http://{ip}:5985/wsman",
        auth=(admin_username, admin_password),
        transport="ntlm",
        operation_timeout_sec=timeout,
        read_timeout_sec=timeout + 10,
    )
    result = session.run_ps(content)
    stdout = result.std_out.decode("utf-8", errors="replace").strip()
    stderr = result.std_err.decode("utf-8", errors="replace").strip()
    output = "\n".join(filter(None, [stdout, stderr]))
    return result.status_code, output


def shutdown_guest(ip: str, admin_username: str, admin_password: str) -> None:
    """Issue a graceful shutdown to the guest via WinRM.

    The WinRM connection will drop before the command returns — that is expected.
    """
    session = winrm.Session(
        f"http://{ip}:5985/wsman",
        auth=(admin_username, admin_password),
        transport="ntlm",
        operation_timeout_sec=30,
        read_timeout_sec=40,
    )
    try:
        session.run_ps("Stop-Computer -Force")
    except Exception:
        pass  # connection drop during shutdown is expected
