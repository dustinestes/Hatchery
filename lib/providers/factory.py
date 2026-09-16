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


def get_provider(nest_id: str | None = None, *, data_dir: Path | None = None) -> BaseProvider:
    """Return a ``BaseProvider`` for ``nest_id`` (default: local Nest).

    Raises:
        UnknownNestError: Nest id is not registered.
        UnsupportedProviderError: Nest is remote or provider_type is not wired yet.
    """
    nests_lib.ensure_local_nest()
    nid = (nest_id or nests_lib.LOCAL_NEST_ID).strip() or nests_lib.LOCAL_NEST_ID
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
