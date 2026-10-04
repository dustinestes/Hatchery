"""Guest reachability helpers (operator CLI + hatch progression).

Not Nest reachability - that lives under nest_reachability / nest test.
"""

from __future__ import annotations

import socket


def check_tcp(ip: str, port: int, timeout: float = 5.0) -> bool:
    """Return True if a TCP connection to ``ip:port`` succeeds."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_ssh(ip: str, port: int = 22, timeout: float = 5.0) -> bool:
    """Return True if a TCP connection to the guest SSH port succeeds."""
    return check_tcp(ip, port, timeout=timeout)


def check_winrm(ip: str, port: int = 5985, timeout: float = 5.0) -> bool:
    """Return True if a TCP connection to the WinRM port succeeds."""
    return check_tcp(ip, port, timeout=timeout)


def guest_health(provider, name: str) -> dict:
    """Return guest IP and remoting TCP reachability for a VM.

    Keys: ``ip`` (str | None), ``ssh`` (bool), ``winrm`` (bool), ``reachable`` (bool).
    ``reachable`` is True when IP is set and SSH or WinRM TCP succeeds.
    """
    ip = provider.get_vm_ip(name)
    if not ip:
        return {"ip": None, "ssh": False, "winrm": False, "reachable": False}
    ssh_ok = check_ssh(ip)
    winrm_ok = check_winrm(ip)
    return {
        "ip": ip,
        "ssh": ssh_ok,
        "winrm": winrm_ok,
        "reachable": ssh_ok or winrm_ok,
    }
