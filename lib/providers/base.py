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
