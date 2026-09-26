"""Guest reachability helpers (operator CLI + hatch progression).

Not Nest reachability - that lives under nest_reachability / nest test.
"""

from __future__ import annotations

import socket


def check_winrm(ip: str, port: int = 5985, timeout: float = 5.0) -> bool:
    """Return True if a TCP connection to the WinRM port succeeds."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def guest_health(provider, name: str) -> dict:
    """Return guest IP and WinRM TCP reachability for a VM.

    Keys: ``ip`` (str | None), ``winrm`` (bool), ``reachable`` (bool).
    ``reachable`` is True only when both IP and WinRM TCP succeed.
    """
    ip = provider.get_vm_ip(name)
    if not ip:
        return {"ip": None, "winrm": False, "reachable": False}
    winrm_ok = check_winrm(ip)
    return {"ip": ip, "winrm": winrm_ok, "reachable": winrm_ok}
