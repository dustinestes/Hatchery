from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from lib.clutch import GuestOS, VMConfig
from lib.providers.base import BaseProvider


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
        media_dir: Path,
        automation_dir: Path,
        storage_pool: str = "default",
    ) -> None:
        self.media_dir = Path(media_dir)
        self.automation_dir = Path(automation_dir)
        self.storage_pool = storage_pool

    # ── VM creation ───────────────────────────────────────────────────────────

    def create_vm(self, config: VMConfig) -> None:
        os_media = self._resolve_media(config.os_media)
        virtio = self._resolve_media(config.virtio_drivers) if config.virtio_drivers else None
        os_config = self._resolve_automation(config.os_config) if config.os_config else None

        answer_img: Path | None = None
        try:
            cmd = self._build_create_cmd(config, os_media, virtio)

            if os_config:
                answer_img = self._create_answer_image(os_config)
                cmd += ["--disk", f"path={answer_img},device=floppy,format=raw"]

            subprocess.run(cmd, check=True, env=_system_env())
        finally:
            if answer_img and answer_img.exists():
                answer_img.unlink()

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

    def _create_answer_image(self, answer_file: Path) -> Path:  # pragma: no cover
        """Wrap an answer file in a FAT image using virt-make-fs."""
        with tempfile.TemporaryDirectory() as staging:
            shutil.copy(answer_file, Path(staging) / "Autounattend.xml")
            img = Path(tempfile.mktemp(suffix="-autounattend.img"))
            subprocess.run(
                [
                    "virt-make-fs",
                    "--type=fat",
                    "--size=1M",
                    "--format=raw",
                    staging,
                    str(img),
                ],
                check=True,
                capture_output=True,
                env=_system_env(),
            )
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

    # ── Path resolution ───────────────────────────────────────────────────────

    def _resolve_media(self, filename: str) -> Path:
        path = Path(filename)
        if path.is_absolute():
            if not path.exists():
                raise FileNotFoundError(f"Media file not found: {path}")
            return path
        resolved = self.media_dir / filename
        if not resolved.exists():
            raise FileNotFoundError(f"Media file not found in media directory: {filename}")
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
