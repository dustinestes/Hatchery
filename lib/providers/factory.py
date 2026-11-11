"""Nest id → BaseProvider factory.

Routes VM lifecycle through the Nest registry (#207). Free HEAD is Local Nest
only (#620). Remote Nest / Nest transport paths raise UnsupportedProviderError;
Enterprise Remote Nest is Nest Agent (#345).
"""

from __future__ import annotations

from pathlib import Path

from lib import config
from lib import nest_cache as nest_cache_lib
from lib import nests as nests_lib
from lib.providers.base import BaseProvider
from lib.providers.hyperv import HyperVProvider
from lib.providers.libvirt import LibvirtProvider

_REMOTE_UNAVAILABLE = (
    "Remote Nests are not available in Hatchery free (#620). "
    "Use a Local Nest on this Controller, or Hatchery Enterprise (Nest Agent)."
)


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

    if location != "local":
        raise UnsupportedProviderError(_REMOTE_UNAVAILABLE)

    # Nest nest_storage SoR: Nest detail volumes / extra.nest_storage (#538 / ADR-0039).
    extra = nest.get("extra") if isinstance(nest.get("extra"), dict) else {}
    nest_storage_raw = (extra or {}).get("nest_storage")
    nest_storage = Path(str(nest_storage_raw)) if nest_storage_raw else None

    # Nest nest_cache SoR: Local = Controller data_dir (#215 / #607).
    controller_root = data_dir or config.data_dir()
    data = nest_cache_lib.resolve_nest_cache_for_provider(nest, data_dir=controller_root)

    if provider_type == "libvirt":
        return LibvirtProvider(
            iso_dir=data / "media" / "iso",
            virtio_dir=data / "media" / "virtio",
            automation_dir=data / "automation" / "answerfiles",
            nest_cache=data,
            nest_storage=nest_storage,
        )

    if provider_type == "hyperv":
        return HyperVProvider(
            nid,
            transport=None,
            iso_dir=data / "media" / "iso",
            virtio_dir=data / "media" / "virtio",
            automation_dir=data / "automation" / "answerfiles",
            nest_cache=data,
            nest_storage=nest_storage,
        )

    raise UnsupportedProviderError(
        f"Nest provider '{provider_type}' is not implemented yet for Nest '{nid}'"
    )
