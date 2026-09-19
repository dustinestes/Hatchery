"""Registry of Library forge adapters (#307)."""

from __future__ import annotations

from lib.library_forge.base import BaseLibraryForgeAdapter

_REGISTRY: dict[str, BaseLibraryForgeAdapter] = {}


def register(adapter: BaseLibraryForgeAdapter) -> None:
    """Register (or replace) an adapter by ``adapter.id``."""
    aid = str(getattr(adapter, "id", "") or "").strip()
    if not aid:
        raise ValueError("Library forge adapter id is required")
    _REGISTRY[aid] = adapter


def get_adapter(provider_id: str | None) -> BaseLibraryForgeAdapter | None:
    """Return the adapter for ``provider_id``, or None."""
    key = str(provider_id or "").strip().lower()
    if not key:
        return None
    return _REGISTRY.get(key)


def all_providers() -> list[BaseLibraryForgeAdapter]:
    """Return registered adapters sorted by id (for Settings dropdowns)."""
    return [(_REGISTRY[k]) for k in sorted(_REGISTRY)]


def clear_registry() -> None:
    """Remove all adapters (tests only)."""
    _REGISTRY.clear()
