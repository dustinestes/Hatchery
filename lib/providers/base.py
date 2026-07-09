from __future__ import annotations

from abc import ABC, abstractmethod

from lib.clutch import VMConfig


class BaseProvider(ABC):
    """Abstract interface all hypervisor providers must implement."""

    @abstractmethod
    def create_vm(self, config: VMConfig, admin_password: str | None = None) -> None:
        """Hatch a new VM from the given configuration."""

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
    def destroy_vm(self, name: str) -> None:
        """Cull a VM — undefine it and remove its allocated storage."""

    @abstractmethod
    def create_snapshot(self, name: str, label: str) -> None:
        """Freeze a VM — save disk and memory state."""

    @abstractmethod
    def list_snapshots(self, name: str) -> list[str]:
        """Return all frozen states for a VM."""

    @abstractmethod
    def revert_snapshot(self, name: str, label: str) -> None:
        """Thaw a VM — restore to a previously frozen state."""

    @abstractmethod
    def delete_snapshot(self, name: str, label: str) -> None:
        """Delete a frozen state."""

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
    def set_poweroff_action(self, name: str, action: str) -> None:
        """Set the on_poweroff lifecycle action on the live running domain.

        Windows OOBE issues an ACPI power-off (not reboot) at the end of setup.
        Patching only the live domain means the persistent config retains the default
        on_poweroff=destroy, so after the OOBE-triggered restart normal shutdown
        behaviour is restored automatically with no cleanup step needed.
        """
