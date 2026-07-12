from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class Requirement:
    name: str
    package: str
    required_for: str
    present: bool
    optional: bool = False


_CLI_TOOLS = [
    ("virsh", "libvirt-clients", "VM lifecycle operations"),
    ("virt-install", "virtinst", "VM creation"),
    ("qemu-img", "qemu-utils", "Disk image operations"),
    ("virt-make-fs", "libguestfs-tools", "Answer file floppy image creation"),
    ("swtpm", "swtpm", "TPM 2.0 emulation (Win11 / Server 2025)"),
]

# Optional tools — absent means degraded functionality, not a hard failure.
_OPTIONAL_CLI_TOOLS = [
    (
        "pwsh",
        "powershell",
        "Script parameter introspection — required to detect and configure automation script parameters",
    ),
]


def _check_python3_gi() -> bool:
    """Check via dpkg-query — bypasses venv PATH issues that fool subprocess python3."""
    result = subprocess.run(
        ["dpkg-query", "--show", "--showformat=${Status}", "python3-gi"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "install ok installed"


def check_all() -> list[Requirement]:
    results = [
        Requirement(name, package, required_for, shutil.which(name) is not None)
        for name, package, required_for in _CLI_TOOLS
    ]
    results.append(
        Requirement(
            "python3-gi",
            "python3-gi",
            "virt-install Python runtime dependency",
            _check_python3_gi(),
        )
    )
    for name, package, required_for in _OPTIONAL_CLI_TOOLS:
        results.append(
            Requirement(name, package, required_for, shutil.which(name) is not None, optional=True)
        )
    return results


def pwsh_available() -> bool:
    return shutil.which("pwsh") is not None


def missing(checks: list[Requirement]) -> list[Requirement]:
    return [r for r in checks if not r.present]


def apt_install_command(missing_list: list[Requirement]) -> str:
    if not missing_list:
        return ""
    packages = " ".join(r.package for r in missing_list)
    return f"sudo apt install {packages}"
