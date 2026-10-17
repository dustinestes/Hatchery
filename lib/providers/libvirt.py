from __future__ import annotations

import getpass
import os
import subprocess
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from lib import answerfile as answerfile_lib
from lib.clutch import GuestOS, VMConfig
from lib.providers.base import (
    BaseProvider,
    MediaCleanupStep,
    answer_media_path,
    is_answer_media_basename,
    legacy_answer_media_path,
    resolve_nest_storage_root,
    rmdir_if_empty,
    vm_disk_path,
    vm_nest_dir,
)
from lib.requirements import NestToolSpec
from lib.run_cmd import run_cmd

_QEMU_CONF = Path("/etc/libvirt/qemu.conf")

# Nest-plane tools for a Local or Remote libvirt Nest (#208).
_LIBVIRT_NEST_TOOLS: tuple[NestToolSpec, ...] = (
    NestToolSpec(
        name="virsh",
        required_for="VM lifecycle operations",
        packages={
            "linux": "libvirt-clients",
            "macos": "libvirt",
            "windows": "libvirt",
        },
    ),
    NestToolSpec(
        name="virt-install",
        required_for="VM creation",
        packages={"linux": "virtinst", "macos": "virt-manager", "windows": "virtinst"},
    ),
    NestToolSpec(
        name="qemu-img",
        required_for="Disk image operations",
        packages={"linux": "qemu-utils", "macos": "qemu", "windows": "qemu"},
    ),
    NestToolSpec(
        name="mformat",
        required_for="Answer File floppy image creation",
        packages={"linux": "mtools", "macos": "mtools", "windows": "mtools"},
    ),
    NestToolSpec(
        name="mcopy",
        required_for="Answer File floppy image creation",
        packages={"linux": "mtools", "macos": "mtools", "windows": "mtools"},
    ),
    NestToolSpec(
        name="swtpm",
        required_for="TPM 2.0 emulation (Win11 / Server 2025)",
        packages={"linux": "swtpm", "macos": "swtpm", "windows": "swtpm"},
    ),
    NestToolSpec(
        name="python3-gi",
        required_for="virt-install Python runtime dependency",
        packages={"linux": "python3-gi", "macos": "pygobject", "windows": "PyGObject"},
        check="python3_gi",
    ),
)


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
        # Unix venvs use ``bin``; Windows uses ``Scripts``.
        strip = {
            os.path.join(venv, "bin"),
            os.path.join(venv, "Scripts"),
        }
        env["PATH"] = os.pathsep.join(
            p for p in env.get("PATH", "").split(os.pathsep) if p and p not in strip
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
            "See Getting Started - Media Access for the recommended setup."
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
            "See Getting Started - Media Access for the recommended setup."
        )


def _os_variant_for(config: VMConfig) -> str:
    """Resolve virt-install --os-variant from providers.libvirt or Windows default."""
    overlays = getattr(config, "providers", None)
    libvirt = getattr(overlays, "libvirt", None) if overlays else None
    pin = getattr(libvirt, "os_variant", None) if libvirt else None
    if pin and str(pin).strip():
        return str(pin).strip()
    if config.os == GuestOS.WINDOWS:
        return "win11"
    # linux/macos: generic until provider inventories land (#504 / #505).
    return "generic"


class LibvirtProvider(BaseProvider):
    supports_answer_file_attach = True

    def __init__(
        self,
        iso_dir: Path,
        virtio_dir: Path,
        automation_dir: Path,
        storage_pool: str = "default",
        nest_cache: Path | None = None,
        nest_storage: Path | None = None,
    ) -> None:
        self.iso_dir = Path(iso_dir)
        self.virtio_dir = Path(virtio_dir)
        self.automation_dir = Path(automation_dir)
        self.storage_pool = storage_pool
        # Local Nest: operator data_dir is Nest cache (ADR-0007). Content only (#215).
        self.nest_cache = Path(nest_cache) if nest_cache is not None else self.iso_dir.parent.parent
        self.nest_storage = Path(nest_storage) if nest_storage is not None else None

    @classmethod
    def nest_tool_specs(cls) -> list[NestToolSpec]:
        return list(_LIBVIRT_NEST_TOOLS)

    # ── Nest storage ──────────────────────────────────────────────────────────

    def _provider_default_storage_root(self) -> Path | None:
        """Conventional libvirt default pool path when it exists on this Nest."""
        candidate = Path("/var/lib/libvirt/images")
        return candidate if candidate.is_dir() else None

    def resolve_storage_root(self) -> Path:
        root = resolve_nest_storage_root(
            nest_storage=self.nest_storage,
            provider_default=self._provider_default_storage_root(),
        )
        if root is None:
            raise ValueError(
                "Nest storage root is required for VM disk and answer media (#587). "
                "Register Nest nest_storage on Nest detail (#538 / #600)."
            )
        if not root.is_dir():
            raise FileNotFoundError(
                f"Storage path does not exist: {root}\n"
                "Create the directory before hatching, or set Nest nest_storage "
                "to an existing Nest directory (#600)."
            )
        return root

    def _vm_dir_for(self, vm_id: str) -> Path:
        root = self.resolve_storage_root()
        path = vm_nest_dir(root, vm_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ── VM creation ───────────────────────────────────────────────────────────

    def prepare_answer_file_media(
        self,
        config: VMConfig,
        *,
        admin_password: str | None = None,
        vm_id: str | None = None,
    ) -> Path | None:
        """Render the user Answer File and pack Autounattend + companions onto a floppy."""
        if not answerfile_lib.requires_answer_file(config.os):
            return None
        if not config.answer_file or not str(config.answer_file).strip():
            raise ValueError(
                f"Answer File is required for {config.os.value} guest "
                f"'{config.name}'. Select an Answer File on the Clutch "
                "before hatching."
            )
        resolved_id = (vm_id or "").strip() or str(uuid.uuid4())
        vm_dir = self._vm_dir_for(resolved_id)
        answer_src = self._resolve_automation(config.answer_file)
        xml, companion_names = answerfile_lib.render_user_answer_file(
            answer_src,
            vm_name=config.name,
            admin_username=config.admin_username or "",
            admin_password=admin_password or "",
            user_params=dict(config.answer_file_parameters or {}),
        )
        companions: list[tuple[str, str]] = []
        for name in companion_names:
            companion_path = self._resolve_automation(name)
            companions.append((name, companion_path.read_text(encoding="utf-8")))
        return self._create_answer_image(xml, vm_dir, companions)

    def create_vm(
        self,
        config: VMConfig,
        admin_password: str | None = None,
        vm_id: str | None = None,
    ) -> None:
        resolved_id = (vm_id or "").strip() or str(uuid.uuid4())
        vm_dir = self._vm_dir_for(resolved_id)

        os_media = self._resolve_media(config.os_media, self.iso_dir)
        virtio = (
            self._resolve_media(config.virtio_drivers, self.virtio_dir)
            if config.virtio_drivers
            else None
        )

        _check_media_accessible(os_media)
        if virtio:
            _check_media_accessible(virtio)

        cmd = self._build_create_cmd(config, os_media, virtio, vm_dir=vm_dir, vm_id=resolved_id)
        answer_img: Path | None = None

        try:
            answer_img = self.prepare_answer_file_media(
                config,
                admin_password=admin_password,
                vm_id=resolved_id,
            )
            if answer_img:
                cmd += ["--disk", f"path={answer_img},device=floppy,format=raw"]

            subprocess.run(cmd, check=True, env=_system_env())
        except Exception:
            # Clean up on failure only - on success the floppy must persist through
            # Windows installation. Post-ready cleanup (#144) or destroy_vm removes it.
            if answer_img and answer_img.exists():
                answer_img.unlink()
            rmdir_if_empty(vm_dir)
            raise

    def _build_create_cmd(
        self,
        config: VMConfig,
        os_media: Path,
        virtio: Path | None,
        *,
        vm_dir: Path,
        vm_id: str,
    ) -> list[str]:
        disk = vm_disk_path(vm_dir, ".qcow2")
        disk_arg = f"path={disk},size={config.disk_gb},format=qcow2"

        cmd = [
            "virt-install",
            "--name",
            config.name,
            "--uuid",
            vm_id,
            "--memory",
            str(config.ram_gb * 1024),
            "--vcpus",
            str(config.vcpus),
            "--disk",
            disk_arg,
            "--cdrom",
            str(os_media),
            "--os-variant",
            _os_variant_for(config),
            "--network",
            "network=default",
            "--graphics",
            "spice",
            "--noautoconsole",
        ]

        from lib.clutch import Firmware

        firmware = getattr(config, "firmware", None)
        tpm = getattr(config, "tpm", None)
        if firmware == Firmware.UEFI or (isinstance(firmware, str) and firmware == "uefi"):
            cmd += ["--boot", "uefi"]
        if tpm:
            cmd += ["--tpm", "emulator,model=tpm-crb,version=2.0"]

        if virtio:
            cmd += ["--disk", f"path={virtio},device=cdrom,readonly=on"]

        return cmd

    def create_command_description(
        self,
        config: VMConfig,
        vm_id: str | None = None,
    ) -> str:
        """Return the virt-install command that will be used to create this VM."""
        os_media = Path(config.os_media)
        if not os_media.is_absolute():
            os_media = self.iso_dir / config.os_media
        virtio = None
        if config.virtio_drivers:
            vp = Path(config.virtio_drivers)
            virtio = vp if vp.is_absolute() else self.virtio_dir / config.virtio_drivers
        resolved_id = (vm_id or "").strip() or "<vm-uuid>"
        try:
            root = self.resolve_storage_root()
            vm_dir = vm_nest_dir(root, resolved_id if vm_id else "_pending_")
        except (ValueError, FileNotFoundError):
            vm_dir = Path("<nest_storage>") / resolved_id
        return " ".join(
            self._build_create_cmd(config, os_media, virtio, vm_dir=vm_dir, vm_id=resolved_id)
        )

    def _floppy_path(self, vm_dir: Path) -> Path:
        """Return the Nest-storage path for a VM's answer file floppy image."""
        path = answer_media_path(vm_dir, ".img")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _create_answer_image(
        self,
        xml_content: str,
        vm_dir: Path,
        companions: list[tuple[str, str]] | None = None,
    ) -> Path:  # pragma: no cover
        """Write rendered Autounattend.xml and companions into a FAT floppy image.

        Uses mtools (mformat + mcopy) - no root or kernel access required.
        1.44 MB standard floppy: 2880 sectors × 512 bytes.
        Image lives under ``{nest_storage}/{vm_id}/autounattend.img`` (#587).
        ``companions`` is a list of ``(floppy_basename, file_content)``.
        """
        img = self._floppy_path(vm_dir)
        xml_file = img.with_suffix(".xml")
        companion_files: list[tuple[Path, str]] = []
        try:
            xml_file.write_text(xml_content, encoding="utf-8")
            for floppy_name, content in companions or []:
                tmp = img.parent / f"{img.stem}-{floppy_name}"
                tmp.write_text(content, encoding="utf-8")
                companion_files.append((tmp, floppy_name))
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
            for tmp, floppy_name in companion_files:
                subprocess.run(
                    ["mcopy", "-i", str(img), str(tmp), f"::{floppy_name}"],
                    check=True,
                    capture_output=True,
                )
        finally:
            if xml_file.exists():
                xml_file.unlink()
            for tmp, _name in companion_files:
                if tmp.exists():
                    tmp.unlink()
        return img

    def _classify_disk_media(self, device: str, source: str) -> tuple[str, str] | None:
        """Return ``(kind, basename)`` for hatch install media, or None if not cleanup target."""
        if not source:
            return None
        path = Path(source)
        basename = path.name
        if device == "floppy":
            return ("answer", basename)
        if device != "cdrom":
            return None
        if is_answer_media_basename(basename):
            return ("answer", basename)
        try:
            virtio_root = self.virtio_dir.resolve()
        except OSError:
            virtio_root = self.virtio_dir
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if "virtio" in basename.lower() or (
            virtio_root in resolved.parents or resolved.parent == virtio_root
        ):
            return ("drivers", basename)
        return ("installation", basename)

    def _list_cleanup_disks(self, name: str) -> list[tuple[str, str, str, str]]:
        """Return ``(kind, basename, target, source)`` for attached install media."""
        xml = run_cmd(["virsh", "dumpxml", name]).stdout or ""
        root = ET.fromstring(xml)
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"
        out: list[tuple[str, str, str, str]] = []
        for disk in root.findall(f".//{ns}devices/{ns}disk"):
            device = (disk.get("device") or "").strip().lower()
            source_el = disk.find(f"{ns}source")
            target_el = disk.find(f"{ns}target")
            if source_el is None or target_el is None:
                continue
            source = (source_el.get("file") or source_el.get("dev") or "").strip()
            target = (target_el.get("dev") or "").strip()
            if not source or not target:
                continue
            classified = self._classify_disk_media(device, source)
            if classified is None:
                continue
            kind, basename = classified
            out.append((kind, basename, target, source))
        # Prefer installation, then drivers, then answer (detach before delete).
        order = {"installation": 0, "drivers": 1, "answer": 2}
        out.sort(key=lambda row: order.get(row[0], 9))
        return out

    def _eject_media(self, name: str, target: str) -> None:
        run_cmd(
            [
                "virsh",
                "change-media",
                name,
                target,
                "--eject",
                "--live",
                "--config",
            ]
        )

    def _eject_media_config(self, name: str, target: str) -> None:
        """Eject from inactive domain config (Destroy path after force-off, #601)."""
        run_cmd(
            [
                "virsh",
                "change-media",
                name,
                target,
                "--eject",
                "--config",
            ],
            check=False,
            echo_failure=False,
        )

    def _path_under_dir(self, path: Path, root: Path) -> bool:
        try:
            resolved = path.resolve()
            root_r = root.resolve()
        except OSError:
            resolved = path
            root_r = root
        return root_r in resolved.parents or resolved.parent == root_r

    def _should_eject_before_destroy(
        self,
        kind: str,
        basename: str,
        source: str,
        protect_media_basenames: frozenset[str] | None,
    ) -> bool:
        """Whether this attach must leave the domain before ``--remove-all-storage``."""
        if kind == "answer" or is_answer_media_basename(basename):
            return True
        if protect_media_basenames is not None:
            protect = {b.casefold() for b in protect_media_basenames}
            return basename.casefold() in protect
        # No clutch snapshot: protect shared catalog roots only (#601).
        path = Path(source)
        return self._path_under_dir(path, self.iso_dir) or self._path_under_dir(
            path, self.virtio_dir
        )

    def _eject_protected_media_before_destroy(
        self,
        name: str,
        protect_media_basenames: frozenset[str] | None,
    ) -> None:
        """Detach clutch/catalog install media so undefine does not delete ISOs (#601)."""
        try:
            disks = self._list_cleanup_disks(name)
        except Exception:
            return
        for kind, basename, target, source in disks:
            if not self._should_eject_before_destroy(
                kind, basename, source, protect_media_basenames
            ):
                continue
            self._eject_media_config(name, target)

    def cleanup_install_media(self, name: str) -> list[MediaCleanupStep]:
        """Eject OS ISO / VirtIO / answer floppy; delete Nest answer media when detached."""
        steps: list[MediaCleanupStep] = []
        try:
            disks = self._list_cleanup_disks(name)
        except Exception as exc:
            return [
                MediaCleanupStep(
                    kind="installation",
                    action="detach",
                    basename=name,
                    target="-",
                    ok=False,
                    error=str(exc),
                )
            ]

        answer_path: Path | None = None
        answer_detached_ok = False
        saw_answer_disk = False
        for kind, basename, target, source in disks:
            if kind == "answer":
                saw_answer_disk = True
                answer_path = Path(source)
            try:
                self._eject_media(name, target)
                steps.append(
                    MediaCleanupStep(
                        kind=kind,  # type: ignore[arg-type]
                        action="detach",
                        basename=basename,
                        target=target,
                        path=source,
                        ok=True,
                    )
                )
                if kind == "answer":
                    answer_detached_ok = True
            except Exception as exc:
                steps.append(
                    MediaCleanupStep(
                        kind=kind,  # type: ignore[arg-type]
                        action="detach",
                        basename=basename,
                        target=target,
                        path=source,
                        ok=False,
                        error=str(exc),
                    )
                )

        # Orphan answer file after a prior eject (not in domain XML anymore).
        if not saw_answer_disk:
            for candidate in self._orphan_answer_candidates(name):
                if candidate.exists():
                    answer_path = candidate
                    answer_detached_ok = True
                    break

        if answer_path is not None and answer_detached_ok:
            try:
                if answer_path.exists():
                    answer_path.unlink()
                steps.append(
                    MediaCleanupStep(
                        kind="answer",
                        action="delete",
                        basename=answer_path.name,
                        target="nest_storage",
                        path=str(answer_path),
                        ok=True,
                    )
                )
                rmdir_if_empty(answer_path.parent)
            except Exception as exc:
                steps.append(
                    MediaCleanupStep(
                        kind="answer",
                        action="delete",
                        basename=answer_path.name,
                        target="nest_storage",
                        path=str(answer_path),
                        ok=False,
                        error=str(exc),
                    )
                )
        return steps

    def _orphan_answer_candidates(self, name: str) -> list[Path]:
        """Possible leftover answer media paths for cleanup/destroy."""
        out: list[Path] = []
        try:
            uid = self.get_vm_uuid(name)
        except Exception:
            uid = None
        if uid:
            for root in self._storage_roots_to_scan():
                out.append(answer_media_path(vm_nest_dir(root, uid), ".img"))
        out.append(legacy_answer_media_path(self.nest_cache, name, ".img"))
        return out

    def _storage_roots_to_scan(self) -> list[Path]:
        roots: list[Path] = []
        if self.nest_storage is not None:
            roots.append(self.nest_storage)
        default = self._provider_default_storage_root()
        if default is not None and default not in roots:
            roots.append(default)
        return roots

    def _domain_disk_source_paths(self, name: str) -> list[Path]:
        """Return file-backed disk source paths from domain XML (before undefine)."""
        result = run_cmd(
            ["virsh", "dumpxml", name],
            check=False,
            echo_failure=False,
        )
        xml = (result.stdout or "").strip()
        if not xml:
            return []
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return []
        out: list[Path] = []
        for disk in root.findall("./devices/disk"):
            source = disk.find("source")
            if source is None:
                continue
            file_attr = source.get("file")
            if file_attr:
                out.append(Path(file_attr))
        return out

    def _collect_destroy_vm_dirs(self, name: str, vm_id: str | None) -> list[Path]:
        """Nest VM dirs to clean after Destroy.

        Disks may live under a former Clutch path or Nest ``nest_storage`` /
        the libvirt default pool (#592 / #600). Prefer parents of domain
        ``disk.qcow2`` / ``autounattend.img``, plus ``{root}/{vm_id}`` under
        known storage roots.
        """
        dirs: list[Path] = []
        alias = (vm_id or "").strip() or None
        for src in self._domain_disk_source_paths(name):
            parent = src.parent
            if src.name in {"disk.qcow2", "autounattend.img"} or (
                alias is not None and parent.name == alias
            ):
                if parent not in dirs:
                    dirs.append(parent)
        if alias:
            for root in self._storage_roots_to_scan():
                candidate = vm_nest_dir(root, alias)
                if candidate not in dirs:
                    dirs.append(candidate)
        return dirs

    def _cleanup_vm_nest_dir(self, vm_dir: Path) -> None:
        """Remove Nest VM dir leftovers (disk/answer) and the dir when empty."""
        if not vm_dir.is_dir():
            return
        for path in (
            answer_media_path(vm_dir, ".img"),
            vm_disk_path(vm_dir, ".qcow2"),
        ):
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
        # Virsh --remove-all-storage may already have deleted the disk, leaving
        # an empty uuid dir (or only stray files). Clear remaining files then
        # remove the directory.
        try:
            for child in list(vm_dir.iterdir()):
                if child.is_file() or child.is_symlink():
                    try:
                        child.unlink()
                    except OSError:
                        pass
        except OSError:
            pass
        rmdir_if_empty(vm_dir)

    def _cleanup_nest_storage_after_destroy(
        self,
        name: str,
        vm_dirs: list[Path],
    ) -> None:
        """Delete Nest VM dir leftovers after undefine (#592 / ADR-0036)."""
        for vm_dir in vm_dirs:
            self._cleanup_vm_nest_dir(vm_dir)
        legacy = legacy_answer_media_path(self.nest_cache, name, ".img")
        if legacy.exists():
            try:
                legacy.unlink()
            except OSError:
                pass

    # ── Power state ───────────────────────────────────────────────────────────

    def start_vm(self, name: str) -> None:
        run_cmd(["virsh", "start", name])

    def stop_vm(self, name: str) -> None:
        run_cmd(["virsh", "shutdown", name])

    def force_stop_vm(self, name: str) -> None:
        run_cmd(["virsh", "destroy", name])

    def pause_vm(self, name: str) -> None:
        run_cmd(["virsh", "suspend", name])

    def resume_vm(self, name: str) -> None:
        run_cmd(["virsh", "resume", name])

    def destroy_vm(
        self,
        name: str,
        *,
        protect_media_basenames: frozenset[str] | None = None,
    ) -> None:
        """Undefine the domain and remove Nest storage leftovers (#592 / #601).

        UEFI guests keep an NVRAM vars file (and often swtpm state). ``virsh
        undefine`` without ``--nvram`` / ``--tpm`` fails with ``cannot undefine
        domain with nvram`` even after Force Stop. Undefine also requires an
        inactive domain, so best-effort ``virsh destroy`` runs first.

        Before ``--remove-all-storage``, eject clutch-snapshot (or catalog-root)
        install media so shared OS/VirtIO ISOs are not deleted (#601).
        """
        try:
            vm_id = self.get_vm_uuid(name)
        except Exception:
            vm_id = None
        # Capture Nest VM dirs from domain XML before undefine drops the domain.
        vm_dirs = self._collect_destroy_vm_dirs(name, vm_id)
        # Inactive domain required for --remove-all-storage / undefine.
        run_cmd(["virsh", "destroy", name], check=False, echo_failure=False)
        # Eject after force-off so --config applies on an inactive domain.
        self._eject_protected_media_before_destroy(name, protect_media_basenames)
        run_cmd(
            [
                "virsh",
                "undefine",
                name,
                "--remove-all-storage",
                "--nvram",
                "--tpm",
            ]
        )
        self._cleanup_nest_storage_after_destroy(name, vm_dirs)

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

    # ── Snapshots ─────────────────────────────────────────────────────────────

    def create_snapshot(self, name: str, label: str) -> None:
        run_cmd(["virsh", "snapshot-create-as", name, "--name", label])

    def list_snapshots(self, name: str) -> list[str]:
        result = run_cmd(["virsh", "snapshot-list", name, "--name"])
        return [s.strip() for s in result.stdout.splitlines() if s.strip()]

    def revert_snapshot(self, name: str, label: str) -> None:
        run_cmd(["virsh", "snapshot-revert", name, label])

    def delete_snapshot(self, name: str, label: str) -> None:
        run_cmd(["virsh", "snapshot-delete", name, label])

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

    def get_vm_uuid(self, name: str) -> str | None:
        """Return the libvirt UUID of a VM, or None if the VM does not exist."""
        result = subprocess.run(["virsh", "domuuid", name], capture_output=True, text=True)
        if result.returncode != 0:
            return None
        uuid = result.stdout.strip()
        return uuid if uuid else None

    def get_vm_name_by_uuid(self, uuid: str) -> str | None:
        """Return the current name of a VM by UUID, or None if not found."""
        result = subprocess.run(["virsh", "domname", uuid], capture_output=True, text=True)
        if result.returncode != 0:
            return None
        name = result.stdout.strip()
        return name if name else None

    def send_key(self, name: str, key: str) -> None:
        """Send a key press to a VM's console.

        A short holdtime helps UEFI firmware register the key during the CD boot prompt.
        """
        subprocess.run(
            ["virsh", "send-key", name, "--holdtime", "100", key],
            check=True,
            capture_output=True,
        )

    def set_poweroff_action(self, name: str, action: str) -> None:
        """Set on_poweroff on the live running domain only (not the persistent config).

        We only need to patch the live domain so that the OOBE power-off restarts the
        VM instead of stopping it. The persistent config retains on_poweroff=destroy,
        so after the OOBE-triggered restart the VM automatically reverts to correct
        shutdown behaviour with no cleanup step required.
        """
        subprocess.run(
            ["virsh", "set-lifecycle-action", name, "poweroff", action, "--live"],
            check=True,
            capture_output=True,
        )

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
                f"answer_file not found in automation/answerfiles: {filename}\n"
                "Create or upload the Answer File via the Automations pane before hatching."
            )
        return resolved
