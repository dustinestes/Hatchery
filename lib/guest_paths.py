"""Guest-plane path roles resolved from Clutch Guest OS (ADR-0025 / #474).

Never use Controller ``sys.platform`` here - paths are for the guest VM.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from lib.clutch import GuestOS

_WINDOWS_OS = frozenset(
    {
        GuestOS.WIN10.value,
        GuestOS.WIN11.value,
        GuestOS.SERVER2022.value,
        GuestOS.SERVER2025.value,
    }
)


@dataclass(frozen=True)
class GuestPaths:
    """Absolute guest paths for Hatchery-managed roles."""

    root: str
    logs: str
    temp: str
    software: str
    family: str  # windows | linux | macos

    def software_package(self, package_id: str) -> str:
        """Return ``software_package(id)`` for a sanitized package id."""
        safe = (
            PureWindowsPath(package_id).name
            if self.family == "windows"
            else PurePosixPath(package_id).name
        )
        if not safe or safe in (".", ".."):
            raise ValueError("package id is required")
        if self.family == "windows":
            return rf"{self.software}\{safe}"
        return f"{self.software}/{safe}"


def guest_paths_for(guest_os: GuestOS | str) -> GuestPaths:
    """Resolve path roles for a Clutch guest OS.

    Windows values are locked (ADR-0025). Linux/macOS raise until filled (#482).
    """
    os_key = guest_os.value if isinstance(guest_os, GuestOS) else str(guest_os or "").strip()
    if os_key in _WINDOWS_OS:
        root = r"C:\Program Files\Hatchery"
        return GuestPaths(
            root=root,
            logs=rf"{root}\logs",
            temp=rf"{root}\temp",
            software=rf"{root}\software",
            family="windows",
        )
    raise ValueError(
        f"guest_paths_for: guest OS '{os_key}' is not supported yet (Linux/macOS paths: #482)"
    )


def clutch_os_to_platform_key(guest_os: GuestOS | str) -> str:
    """Map Clutch GuestOS to Software ``platforms`` OS key."""
    os_key = guest_os.value if isinstance(guest_os, GuestOS) else str(guest_os or "").strip()
    if os_key in _WINDOWS_OS:
        return "windows"
    raise ValueError(f"unsupported Software platform for guest OS '{os_key}'")
