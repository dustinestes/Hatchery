"""Registry of Library API adapters (#255)."""

from __future__ import annotations

from lib.library_api.base import BaseLibraryApiAdapter

_REGISTRY: dict[str, BaseLibraryApiAdapter] = {}


def register(adapter: BaseLibraryApiAdapter) -> None:
    """Register (or replace) an adapter by ``adapter.id``."""
    aid = str(getattr(adapter, "id", "") or "").strip()
    if not aid:
        raise ValueError("Library API adapter id is required")
    _REGISTRY[aid] = adapter


def get_adapter(provider_id: str | None) -> BaseLibraryApiAdapter | None:
    """Return the adapter for ``provider_id``, or None."""
    key = str(provider_id or "").strip().lower()
    if not key:
        return None
    return _REGISTRY.get(key)


def all_providers() -> list[BaseLibraryApiAdapter]:
    """Return registered adapters sorted by id (for Settings dropdowns)."""
    return [(_REGISTRY[k]) for k in sorted(_REGISTRY)]


def clear_registry() -> None:
    """Remove all adapters (tests only)."""
    _REGISTRY.clear()
