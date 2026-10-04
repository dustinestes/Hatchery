"""Nest id → BaseProvider factory.

Routes VM lifecycle through the Nest registry (#207). Local libvirt and
Hyper-V (local or remote over Nest transport) are instantiable; UTM and
remote libvirt raise UnsupportedProviderError until those adapters land.
"""

from __future__ import annotations

from pathlib import Path

from lib import config
from lib import nests as nests_lib
from lib.nest_transport import get_nest_transport
from lib.providers.base import BaseProvider
from lib.providers.hyperv import HyperVProvider
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
            "No Nest selected - register a Nest in Settings, or pass an explicit Nest id "
            "(exactly one registered Nest may be used as the default)"
        )


def get_provider(nest_id: str | None = None, *, data_dir: Path | None = None) -> BaseProvider:
    """Return a ``BaseProvider`` for ``nest_id``.

    When ``nest_id`` is omitted, uses the sole registered Nest if exactly one
    exists (ADR-0014). Does not auto-seed Local Nest.

    Raises:
        NoNestSelectedError: Nest id omitted and zero or many Nests registered.
        UnknownNestError: Nest id is not registered.
        UnsupportedProviderError: Nest provider / location is not wired yet.
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

    if provider_type == "libvirt":
        if location == "remote":
            raise UnsupportedProviderError(
                f"Remote Nest '{nid}' (libvirt) is registered but VM ops are not available yet"
            )
        data = data_dir or config.data_dir()
        return LibvirtProvider(
            iso_dir=data / "media" / "iso",
            virtio_dir=data / "media" / "virtio",
            automation_dir=data / "automation" / "answerfiles",
        )

    if provider_type == "hyperv":
        transport = None
        if location == "remote":
            connection = nests_lib.to_connection_config(nest)
            transport = get_nest_transport(connection)
            if transport is None:
                raise UnsupportedProviderError(
                    f"Remote Nest '{nid}' (hyperv) has no Nest transport"
                )
        data = data_dir or config.data_dir()
        return HyperVProvider(
            nid,
            transport=transport,
            iso_dir=data / "media" / "iso",
            virtio_dir=data / "media" / "virtio",
            automation_dir=data / "automation" / "answerfiles",
        )

    raise UnsupportedProviderError(
        f"Nest provider '{provider_type}' is not implemented yet for Nest '{nid}'"
    )
