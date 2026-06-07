from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass


@dataclass
class Requirement:
    name: str
    package: str
    required_for: str
    present: bool


_CLI_TOOLS = [
    ("virsh", "libvirt-clients", "VM lifecycle operations"),
    ("virt-install", "virtinst", "VM creation"),
    ("qemu-img", "qemu-utils", "Disk image operations"),
    ("virt-make-fs", "libguestfs-tools", "Answer file floppy image creation"),
    ("swtpm", "swtpm", "TPM 2.0 emulation (Win11 / Server 2025)"),
]


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
            importlib.util.find_spec("gi") is not None,
        )
    )
    return results


def missing(checks: list[Requirement]) -> list[Requirement]:
    return [r for r in checks if not r.present]


def apt_install_command(missing_list: list[Requirement]) -> str:
    if not missing_list:
        return ""
    packages = " ".join(r.package for r in missing_list)
    return f"sudo apt install {packages}"
