"""Guest remoting known-endpoint bind (#621)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lib import guest_endpoint as ge


_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class TestAssertGuestHostBound:
    def test_requires_vm_id(self):
        with pytest.raises(ge.GuestUnknownEndpointError, match="VM UUID"):
            ge.assert_guest_host_bound(host="10.0.0.1", vm_id="")

    def test_rejects_destroyed_hatch_status(self):
        with patch(
            "lib.guest_endpoint._hatch_status_for_uuid",
            return_value="destroyed",
        ):
            with pytest.raises(ge.GuestUnknownEndpointError, match="destroyed"):
                ge.assert_guest_host_bound(host="10.0.0.1", vm_id=_UUID)

    def test_rejects_unknown_uuid(self):
        provider = MagicMock()
        provider.get_vm_name_by_uuid.return_value = None
        with (
            patch("lib.guest_endpoint._hatch_status_for_uuid", return_value=None),
            patch("lib.nests.list_nests", return_value=[{"id": "local"}]),
            patch("lib.providers.factory.get_provider", return_value=provider),
        ):
            with pytest.raises(ge.GuestUnknownEndpointError, match="not known"):
                ge.assert_guest_host_bound(host="10.0.0.1", vm_id=_UUID)

    def test_rejects_ip_mismatch(self):
        provider = MagicMock()
        provider.get_vm_name_by_uuid.return_value = "win11"
        provider.get_vm_ip.return_value = "10.0.0.9"
        with (
            patch("lib.guest_endpoint._hatch_status_for_uuid", return_value="provisioning"),
            patch("lib.nests.list_nests", return_value=[{"id": "local"}]),
            patch("lib.providers.factory.get_provider", return_value=provider),
        ):
            with pytest.raises(ge.GuestUnknownEndpointError, match="does not match"):
                ge.assert_guest_host_bound(host="10.0.0.1", vm_id=_UUID)

    def test_ok_when_ip_matches(self):
        provider = MagicMock()
        provider.get_vm_name_by_uuid.return_value = "win11"
        provider.get_vm_ip.return_value = "10.0.0.1"
        with (
            patch("lib.guest_endpoint._hatch_status_for_uuid", return_value=None),
            patch("lib.nests.list_nests", return_value=[{"id": "local"}]),
            patch("lib.providers.factory.get_provider", return_value=provider),
        ):
            known = ge.assert_guest_host_bound(host="10.0.0.1", vm_id=_UUID)
        assert known.vm_id == _UUID
        assert known.nest_id == "local"
        assert known.name == "win11"
        assert known.host == "10.0.0.1"

    def test_no_ip_yet(self):
        provider = MagicMock()
        provider.get_vm_name_by_uuid.return_value = "win11"
        provider.get_vm_ip.return_value = None
        with (
            patch("lib.guest_endpoint._hatch_status_for_uuid", return_value=None),
            patch("lib.nests.list_nests", return_value=[{"id": "local"}]),
            patch("lib.providers.factory.get_provider", return_value=provider),
        ):
            with pytest.raises(ge.GuestUnknownEndpointError, match="no guest IP"):
                ge.resolve_known_guest(vm_id=_UUID)
