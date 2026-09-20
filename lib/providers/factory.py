"""Nest id → BaseProvider factory.

Routes VM lifecycle through the Nest registry (#207). Today only local libvirt
is instantiable; remote / UTM / Hyper-V raise UnsupportedProviderError until
those adapters land.
"""

from __future__ import annotations

from pathlib import Path

from lib import config
from lib import nests as nests_lib
from lib.providers.base import BaseProvider
from lib.providers.libvirt import LibvirtProvider


class UnknownNestError(KeyError):
    """Raised when a Nest id is not in the registry."""

    def __init__(self, nest_id: str) -> None:
        self.nest_id = nest_id
        super().__init__(nest_id)

    def __str__(self) -> str:
        return f"Unknown Nest id: {self.nest_id}"


class UnsupportedProviderError(RuntimeError):
    """Raised when a Nest's provider cannot be instantiated yet."""


class NoNestSelectedError(RuntimeError):
    """Raised when a Nest id is required but none can be resolved."""

    def __str__(self) -> str:
        return (
            "No Nest selected — register a Nest in Settings, or pass an explicit Nest id "
            "(exactly one registered Nest may be used as the default)"
        )


def get_provider(nest_id: str | None = None, *, data_dir: Path | None = None) -> BaseProvider:
    """Return a ``BaseProvider`` for ``nest_id``.

    When ``nest_id`` is omitted, uses the sole registered Nest if exactly one
    exists (ADR-0014). Does not auto-seed Local Nest.

    Raises:
        NoNestSelectedError: Nest id omitted and zero or many Nests registered.
        UnknownNestError: Nest id is not registered.
        UnsupportedProviderError: Nest is remote or provider_type is not wired yet.
    """
    explicit = (nest_id or "").strip()
    nid = explicit or nests_lib.default_nest_id()
    if not nid:
        raise NoNestSelectedError()
    nest = nests_lib.get_nest(nid)
    if nest is None:
        raise UnknownNestError(nid)

    provider_type = nest["provider_type"]
    location = nest["location"]

    if location == "remote":
        raise UnsupportedProviderError(
            f"Remote Nest '{nid}' ({provider_type}) is registered but VM ops are not available yet"
        )

    if provider_type == "libvirt":
        data = data_dir or config.data_dir()
        return LibvirtProvider(
            iso_dir=data / "media" / "iso",
            virtio_dir=data / "media" / "virtio",
            automation_dir=data / "automation" / "os_config",
        )

    raise UnsupportedProviderError(
        f"Nest provider '{provider_type}' is not implemented yet for Nest '{nid}'"
    )
