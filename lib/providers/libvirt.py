from __future__ import annotations

import getpass
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from lib import answerfile as answerfile_lib
from lib.clutch import GuestOS, VMConfig
from lib.providers.base import BaseProvider

_QEMU_CONF = Path("/etc/libvirt/qemu.conf")


def _system_env() -> dict[str, str]:
    """Strip the uv venv bin from PATH before spawning system Python scripts.

    virt-install uses '#!/usr/bin/env python3'. When Hatchery runs via uv,
    the venv bin is prepended to PATH so 'python3' resolves to the venv's
    Python, which lacks system site-packages (e.g. python3-gi). Removing the
    venv bin restores the system Python lookup without affecting C binaries.
    """
    env = os.environ.copy()
    venv = env.get("VIRTUAL_ENV", "")
    if venv:
        venv_bin = os.path.join(venv, "bin")
        env["PATH"] = os.pathsep.join(
            p for p in env.get("PATH", "").split(os.pathsep) if p != venv_bin
        )
    return env


def _qemu_user() -> str | None:
    """Return the user QEMU processes will run as, per /etc/libvirt/qemu.conf.

    Returns:
        - The configured username if the file is readable and has a user line.
        - 'libvirt-qemu' if the file is absent or readable but has no user line
          (compiled-in default).
        - None if the file exists but cannot be read — caller should skip access
          checks to avoid false positives.
    """
    try:
        content = _QEMU_CONF.read_text()
    except PermissionError:
        return None  # file exists but unreadable — QEMU user unknown
    except OSError:
        return "libvirt-qemu"  # file absent — compiled-in default
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == "user":
            return value.strip().strip("\"'")
    return "libvirt-qemu"


def _check_media_accessible(path: Path) -> None:
    """Raise PermissionError if the QEMU process cannot read the given media file.

    QEMU runs as 'libvirt-qemu' by default. It requires world-read on the file
    and world-execute on every directory in the path chain. Home directories are
    typically 0o750 (no world-execute), which blocks access silently.

    If qemu.conf configures QEMU to run as the current user or root, the check
    is skipped entirely — QEMU has the same access rights as the running user.

    Called before virt-install so the user gets an actionable error instead of a
    cryptic hypervisor message. Missing files are intentionally ignored — they
    are caught earlier by _resolve_media.
    """
    try:
        file_mode = path.stat().st_mode
    except OSError:
        return  # file does not exist; _resolve_media handles the error

    # Determine who QEMU will run as and skip the check when we can't tell.
    qemu_user = _qemu_user()
    if qemu_user is None:
        return  # qemu.conf unreadable — can't verify, skip to avoid false positives
    try:
        current_user = getpass.getuser()
    except Exception:  # pragma: no cover
        current_user = ""
    if qemu_user in (current_user, "root"):
        return

    if not (file_mode & 0o004):
        raise PermissionError(
            f"Media file is not world-readable: {path}\n"
            f"Run: chmod o+r '{path}'\n"
            "See Getting Started — Media Access for the recommended setup."
        )

    blocked = []
    for parent in path.parents:
        try:
            if not (parent.stat().st_mode & 0o001):
                blocked.append(parent)
        except OSError:  # pragma: no cover
            break

    if blocked:
        dirs = " ".join(f"'{p}'" for p in sorted(blocked, key=lambda p: len(str(p))))
        raise PermissionError(
            f"The hypervisor (libvirt-qemu) cannot access: {path.name}\n"
            f"Run: chmod o+x {dirs}\n"
            "See Getting Started — Media Access for the recommended setup."
        )


# OS types that require UEFI firmware and TPM 2.0 emulation
_UEFI_REQUIRED = {GuestOS.WIN11, GuestOS.SERVER2025}

# virt-install --os-variant values per guest OS
_OS_VARIANT: dict[GuestOS, str] = {
    GuestOS.WIN10: "win10",
    GuestOS.WIN11: "win11",
    GuestOS.SERVER2022: "win2k22",
    GuestOS.SERVER2025: "win2k25",
}


class LibvirtProvider(BaseProvider):
    def __init__(
        self,
        iso_dir: Path,
        virtio_dir: Path,
        automation_dir: Path,
        storage_pool: str = "default",
    ) -> None:
        self.iso_dir = Path(iso_dir)
        self.virtio_dir = Path(virtio_dir)
        self.automation_dir = Path(automation_dir)
        self.storage_pool = storage_pool

    # ── VM creation ───────────────────────────────────────────────────────────

    def create_vm(self, config: VMConfig, admin_password: str | None = None) -> None:
        os_media = self._resolve_media(config.os_media, self.iso_dir)
        virtio = (
            self._resolve_media(config.virtio_drivers, self.virtio_dir)
            if config.virtio_drivers
            else None
        )

        _check_media_accessible(os_media)
        if virtio:
            _check_media_accessible(virtio)

        cmd = self._build_create_cmd(config, os_media, virtio)
        answer_img: Path | None = None

        try:
            if config.admin_username and admin_password:
                xml = answerfile_lib.render(
                    config.os, config.name, config.admin_username, admin_password
                )
                answer_img = self._create_answer_image(xml, config.name)
                cmd += ["--disk", f"path={answer_img},device=floppy,format=raw"]
            elif config.os_config:
                os_config = self._resolve_automation(config.os_config)
                answer_img = self._create_answer_image(os_config.read_text(), config.name)
                cmd += ["--disk", f"path={answer_img},device=floppy,format=raw"]

            subprocess.run(cmd, check=True, env=_system_env())
        except Exception:
            # Clean up on failure only — on success the floppy must persist through
            # Windows installation. destroy_vm handles final cleanup.
            if answer_img and answer_img.exists():
                answer_img.unlink()
            raise

    def _build_create_cmd(
        self,
        config: VMConfig,
        os_media: Path,
        virtio: Path | None,
    ) -> list[str]:
        cmd = [
            "virt-install",
            "--name",
            config.name,
            "--memory",
            str(config.ram_gb * 1024),
            "--vcpus",
            str(config.vcpus),
            "--disk",
            f"size={config.disk_gb},format=qcow2,pool={self.storage_pool}",
            "--cdrom",
            str(os_media),
            "--os-variant",
            _OS_VARIANT[config.os],
            "--network",
            "network=default",
            "--graphics",
            "spice",
            "--noautoconsole",
        ]

        if config.os in _UEFI_REQUIRED:
            cmd += ["--boot", "uefi"]
            cmd += ["--tpm", "emulator,model=tpm-crb,version=2.0"]

        if virtio:
            cmd += ["--disk", f"path={virtio},device=cdrom,readonly=on"]

        return cmd

    def _floppy_path(self, vm_name: str) -> Path:
        """Return the stable path for a VM's answer file floppy image."""
        return Path(tempfile.gettempdir()) / f"{vm_name}-autounattend.img"

    def _create_answer_image(self, xml_content: str, vm_name: str) -> Path:  # pragma: no cover
        """Write xml_content into a FAT floppy image as Autounattend.xml.

        Uses mtools (mformat + mcopy) — no root or kernel access required.
        1.44 MB standard floppy: 2880 sectors × 512 bytes.
        Image is written to a stable path so it persists through Windows installation.
        """
        img = self._floppy_path(vm_name)
        xml_file = img.with_suffix(".xml")
        try:
            xml_file.write_text(xml_content, encoding="utf-8")
            subprocess.run(
                ["dd", "if=/dev/zero", f"of={img}", "bs=512", "count=2880"],
                check=True,
                capture_output=True,
            )
            subprocess.run(["mformat", "-i", str(img), "::"], check=True, capture_output=True)
            subprocess.run(
                ["mcopy", "-i", str(img), str(xml_file), "::Autounattend.xml"],
                check=True,
                capture_output=True,
            )
        finally:
            if xml_file.exists():
                xml_file.unlink()
        return img

    # ── Power state ───────────────────────────────────────────────────────────

    def start_vm(self, name: str) -> None:
        subprocess.run(["virsh", "start", name], check=True)

    def stop_vm(self, name: str) -> None:
        subprocess.run(["virsh", "shutdown", name], check=True)

    def force_stop_vm(self, name: str) -> None:
        subprocess.run(["virsh", "destroy", name], check=True)

    def destroy_vm(self, name: str) -> None:
        subprocess.run(["virsh", "undefine", name, "--remove-all-storage"], check=True)
        floppy = self._floppy_path(name)
        if floppy.exists():
            floppy.unlink()

    # ── Inventory ─────────────────────────────────────────────────────────────

    def list_vms(self) -> list[dict]:
        result = subprocess.run(
            ["virsh", "list", "--all", "--name"],
            check=True,
            capture_output=True,
            text=True,
        )
        names = [n.strip() for n in result.stdout.splitlines() if n.strip()]
        return [{"name": n, "status": self.get_status(n)} for n in names]

    def get_status(self, name: str) -> str:
        result = subprocess.run(
            ["virsh", "domstate", name],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    # ── Snapshots (Freeze / Thaw) ─────────────────────────────────────────────

    def create_snapshot(self, name: str, label: str) -> None:
        subprocess.run(
            ["virsh", "snapshot-create-as", name, "--name", label],
            check=True,
        )

    def list_snapshots(self, name: str) -> list[str]:
        result = subprocess.run(
            ["virsh", "snapshot-list", name, "--name"],
            check=True,
            capture_output=True,
            text=True,
        )
        return [s.strip() for s in result.stdout.splitlines() if s.strip()]

    def revert_snapshot(self, name: str, label: str) -> None:
        subprocess.run(
            ["virsh", "snapshot-revert", name, label],
            check=True,
        )

    def delete_snapshot(self, name: str, label: str) -> None:
        subprocess.run(
            ["virsh", "snapshot-delete", name, label],
            check=True,
        )

    # ── Fledged detection ─────────────────────────────────────────────────────

    def get_vm_ip(self, name: str) -> str | None:
        """Return the first IPv4 address assigned to a VM, or None if not yet available."""
        result = subprocess.run(
            ["virsh", "domifaddr", name],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[2] == "ipv4":
                return parts[3].split("/")[0]
        return None

    # ── Session metadata ──────────────────────────────────────────────────────

    _METADATA_URI = "https://hatchery.io/metadata"
    _METADATA_KEY = "hatchery"

    def tag_vm_session(self, vm_name: str, session_id: str, clutch_file: str) -> None:
        """Attach hatch session metadata to a VM so associations survive DB loss."""
        xml = (
            f"<hatchery>"
            f"<session_id>{session_id}</session_id>"
            f"<clutch_file>{clutch_file}</clutch_file>"
            f"</hatchery>"
        )
        subprocess.run(
            [
                "virsh",
                "metadata",
                vm_name,
                "--uri",
                self._METADATA_URI,
                "--key",
                self._METADATA_KEY,
                "--set",
                xml,
                "--live",
                "--config",
            ],
            check=True,
            capture_output=True,
        )

    def get_vm_session_tag(self, vm_name: str) -> dict | None:
        """Return the hatch session metadata dict for a VM, or None if untagged."""
        result = subprocess.run(
            [
                "virsh",
                "metadata",
                vm_name,
                "--uri",
                self._METADATA_URI,
                "--key",
                self._METADATA_KEY,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        try:
            root = ET.fromstring(result.stdout.strip())
            sid = root.findtext("session_id")
            cf = root.findtext("clutch_file")
            if sid and cf:
                return {"session_id": sid, "clutch_file": cf}
        except ET.ParseError:
            pass
        return None

    # ── Path resolution ───────────────────────────────────────────────────────

    def _resolve_media(self, filename: str, media_dir: Path) -> Path:
        path = Path(filename)
        if path.is_absolute():
            if not path.exists():
                raise FileNotFoundError(f"Media file not found: {path}")
            return path
        resolved = media_dir / filename
        if not resolved.exists():
            raise FileNotFoundError(f"Media file not found: {filename}")
        return resolved

    def _resolve_automation(self, filename: str) -> Path:
        path = Path(filename)
        if path.is_absolute():
            if not path.exists():
                raise FileNotFoundError(f"Automation file not found: {path}")
            return path
        resolved = self.automation_dir / filename
        if not resolved.exists():
            raise FileNotFoundError(
                f"os_config file not found in automation directory: {filename}\n"
                "Create or upload the answer file via the Automation pane before hatching."
            )
        return resolved
