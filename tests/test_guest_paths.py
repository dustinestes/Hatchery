"""Tests for guest path role resolution (#474)."""

import pytest

from lib.clutch import GuestOS
from lib.guest_paths import clutch_os_to_platform_key, guest_paths_for


class TestGuestPathsFor:
    def test_windows_locked_values(self):
        paths = guest_paths_for(GuestOS.WINDOWS)
        assert paths.root == r"C:\Program Files\Hatchery"
        assert paths.logs == r"C:\Program Files\Hatchery\logs"
        assert paths.temp == r"C:\Program Files\Hatchery\temp"
        assert paths.software == r"C:\Program Files\Hatchery\software"
        assert paths.family == "windows"

    def test_software_package_path(self):
        paths = guest_paths_for("server2022")
        assert (
            paths.software_package("Hatchery.SoftwareExample.1.0.0")
            == r"C:\Program Files\Hatchery\software\Hatchery.SoftwareExample.1.0.0"
        )

    def test_software_log_path(self):
        paths = guest_paths_for(GuestOS.WINDOWS)
        assert paths.software_logs_dir() == r"C:\Program Files\Hatchery\logs\software"
        assert (
            paths.software_log("Hatchery.SoftwareExample.1.0.0")
            == r"C:\Program Files\Hatchery\logs\software\Hatchery.SoftwareExample.1.0.0.log"
        )

    def test_software_package_rejects_empty_id(self):
        paths = guest_paths_for(GuestOS.WINDOWS)
        with pytest.raises(ValueError, match="package id"):
            paths.software_package("..")

    def test_linux_unsupported(self):
        with pytest.raises(ValueError, match="not supported"):
            guest_paths_for("linux")

    def test_platform_key_rejects_unknown(self):
        with pytest.raises(ValueError, match="unsupported Software platform"):
            clutch_os_to_platform_key("linux")


class TestClutchOsToPlatform:
    def test_windows_guests(self):
        assert clutch_os_to_platform_key(GuestOS.WINDOWS) == "windows"
        assert clutch_os_to_platform_key("server2025") == "windows"
