from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal

from lib.clutch import VMConfig

MediaCleanupKind = Literal["installation", "answer", "drivers"]
MediaCleanupAction = Literal["detach", "delete"]


@dataclass(frozen=True)
class MediaCleanupStep:
    """One Nest install-media cleanup attempt for hatchery-context events (#144)."""

    kind: MediaCleanupKind
    action: MediaCleanupAction
    basename: str
    target: str
    path: str | None = None
    ok: bool = True
    error: str | None = None


def resolve_nest_storage_root(
    *,
    nest_storage: Path | str | None = None,
    clutch_storage_path: Path | str | None = None,
    provider_default: Path | str | None = None,
) -> Path | None:
    """Resolve Nest VM file root: nest_storage → Clutch storage_path → provider default.

    Never falls back to Controller ``data_dir`` / ``nest_cache`` (#587).
    """
    for raw in (nest_storage, clutch_storage_path, provider_default):
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return Path(text)
    return None


def vm_nest_dir(storage_root: Path, vm_id: str) -> Path:
    """Per-VM Nest directory ``{nest_storage}/{vm_id}/``."""
    return Path(storage_root) / str(vm_id)


def answer_media_path(vm_dir: Path, suffix: str) -> Path:
    """Path for ``autounattend.{img|iso}`` under a VM Nest directory (#587)."""
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    return Path(vm_dir) / f"autounattend{ext}"


def vm_disk_path(vm_dir: Path, suffix: str) -> Path:
    """Path for ``disk.{qcow2|vhdx}`` under a VM Nest directory."""
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    return Path(vm_dir) / f"disk{ext}"


def legacy_answer_media_path(nest_cache: Path, vm_name: str, suffix: str) -> Path:
    """Pre-#587 path under ``nest_cache/nest-work/answer-media/`` (cleanup only)."""
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    return Path(nest_cache) / "nest-work" / "answer-media" / f"{vm_name}-autounattend{ext}"


def rmdir_if_empty(path: Path) -> bool:
    """Remove ``path`` when it exists and is an empty directory. Return True if removed."""
    try:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            return True
    except OSError:
        return False
    return False


def is_answer_media_basename(basename: str) -> bool:
    """True when a disk basename looks like Hatchery answer media."""
    lower = (basename or "").lower()
    return lower in {"autounattend.img", "autounattend.iso"} or "autounattend" in lower


class BaseProvider(ABC):
    """Abstract interface all hypervisor providers must implement."""

    #: Whether this Nest can pack and attach Answer File media at hatch time.
    #: Libvirt local floppy is the first working backend (#454 / ADR-0024).
    #: Hyper-V / UTM remain Planned (see docs/providers.md).
    supports_answer_file_attach: ClassVar[bool] = False

    @classmethod
    def nest_tool_specs(cls) -> list:
        """Return Nest-plane tool specs for this provider (empty if none declared).

        Used by the ``nest_capability`` validator (#208). Controller-plane tools
        do not belong here.
        """
        return []

    def prepare_answer_file_media(
        self,
        config: VMConfig,
        *,
        admin_password: str | None = None,
        vm_id: str | None = None,
        storage_path: str | None = None,
    ) -> Path | None:
        """Render and pack Answer File media for Nest attach, or None if not required.

        Providers that set ``supports_answer_file_attach`` must override this and return
        a Nest-local path for ``create_vm`` to attach. Default raises when the guest
        requires an Answer File but this Nest cannot attach.
        """
        from lib import answerfile as answerfile_lib

        if not answerfile_lib.requires_answer_file(config.os):
            return None
        raise ValueError(
            f"Nest provider {type(self).__name__} does not support Answer File attach. "
            "Windows Autounattend attach works on libvirt local today; "
            "Hyper-V and UTM are Planned (see docs/providers.md)."
        )

    def cleanup_install_media(self, name: str) -> list[MediaCleanupStep]:
        """Detach hatch install media and delete Nest answer-media when safe.

        Default is a no-op (providers without attach/cleanup). Override on Nests that
        attach OS ISO / answer media / VirtIO at hatch. Failures are returned as
        ``ok=False`` steps; callers must not abandon the hatch for cleanup errors.
        """
        return []

    @abstractmethod
    def create_vm(
        self,
        config: VMConfig,
        admin_password: str | None = None,
        storage_path: str | None = None,
        vm_id: str | None = None,
    ) -> None:
        """Hatch a new VM from the given configuration.

        ``vm_id`` is a pre-minted UUID used as Nest storage directory name and
        hypervisor domain identity when the provider supports it (#587).
        """

    @abstractmethod
    def list_vms(self) -> list[dict]:
        """Return all VMs known to this provider."""

    @abstractmethod
    def get_status(self, name: str) -> str:
        """Return the current power state of a VM."""

    @abstractmethod
    def start_vm(self, name: str) -> None:
        """Power on a VM."""

    @abstractmethod
    def stop_vm(self, name: str) -> None:
        """Gracefully shut down a VM."""

    @abstractmethod
    def force_stop_vm(self, name: str) -> None:
        """Forcibly power off a VM."""

    @abstractmethod
    def pause_vm(self, name: str) -> None:
        """Suspend a running VM (hypervisor pause)."""

    @abstractmethod
    def resume_vm(self, name: str) -> None:
        """Resume a paused VM."""

    @abstractmethod
    def destroy_vm(
        self,
        name: str,
        *,
        protect_media_basenames: frozenset[str] | None = None,
    ) -> None:
        """Destroy a VM: undefine it and remove its allocated storage.

        ``protect_media_basenames`` is clutch-snapshot OS/VirtIO basenames to
        eject before libvirt ``--remove-all-storage`` (#601). ``None`` means
        the caller had no snapshot: providers that need it should fall back to
        catalog roots (``iso_dir`` / ``virtio_dir``). Hyper-V ignores this
        (Destroy already removes hard disks only).
        """

    @abstractmethod
    def create_snapshot(self, name: str, label: str) -> None:
        """Create a named snapshot of a VM (disk and memory state as supported)."""

    @abstractmethod
    def list_snapshots(self, name: str) -> list[str]:
        """Return all snapshot labels for a VM."""

    @abstractmethod
    def revert_snapshot(self, name: str, label: str) -> None:
        """Revert a VM to a previously created snapshot."""

    @abstractmethod
    def delete_snapshot(self, name: str, label: str) -> None:
        """Delete a snapshot."""

    @abstractmethod
    def get_vm_ip(self, name: str) -> str | None:
        """Return the first IPv4 address of a running VM, or None if unavailable."""

    @abstractmethod
    def get_vm_uuid(self, name: str) -> str | None:
        """Return the hypervisor UUID of a VM, or None if the VM does not exist."""

    @abstractmethod
    def get_vm_name_by_uuid(self, uuid: str) -> str | None:
        """Return the current name of a VM identified by UUID, or None if not found."""

    @abstractmethod
    def send_key(self, name: str, key: str) -> None:
        """Send a key press to a VM's console (e.g. KEY_ENTER to dismiss boot prompt)."""

    @abstractmethod
    def get_vm_session_tag(self, name: str) -> dict | None:
        """Return the Hatchery session metadata for a VM, or None if untagged.

        Returns a dict with 'session_id' and 'clutch_file' keys when present.
        """

    @abstractmethod
    def set_poweroff_action(self, name: str, action: str) -> None:
        """Set the on_poweroff lifecycle action on the live running domain.

        Windows OOBE issues an ACPI power-off (not reboot) at the end of setup.
        Patching only the live domain means the persistent config retains the default
        on_poweroff=destroy, so after the OOBE-triggered restart normal shutdown
        behaviour is restored automatically with no cleanup step needed.
        """

    def create_command_description(self, config: VMConfig) -> str:
        """Return a human-readable description of the command used to create a VM.

        Default implementation returns a generic summary. Providers override this to
        return the actual hypervisor command so it can be surfaced in the event log.
        """
        return (
            f"create VM '{config.name}' ({config.os}, {config.vcpus} vCPU, "
            f"{config.ram_gb}GB RAM, {config.disk_gb}GB disk)"
        )
