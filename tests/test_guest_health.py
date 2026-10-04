"""Guest TCP reachability helpers (#497)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from lib import guest_health as gh


def test_check_ssh_and_winrm():
    with patch("lib.guest_health.socket.create_connection") as conn:
        assert gh.check_ssh("10.0.0.1") is True
        conn.assert_called_with(("10.0.0.1", 22), timeout=5.0)
    with patch("lib.guest_health.socket.create_connection", side_effect=OSError):
        assert gh.check_winrm("10.0.0.1") is False


def test_guest_health_reachable_via_ssh():
    provider = MagicMock()
    provider.get_vm_ip.return_value = "10.0.0.2"
    with (
        patch("lib.guest_health.check_ssh", return_value=True),
        patch("lib.guest_health.check_winrm", return_value=False),
    ):
        result = gh.guest_health(provider, "vm1")
    assert result == {
        "ip": "10.0.0.2",
        "ssh": True,
        "winrm": False,
        "reachable": True,
    }


def test_guest_health_no_ip():
    provider = MagicMock()
    provider.get_vm_ip.return_value = None
    assert gh.guest_health(provider, "vm1")["reachable"] is False
