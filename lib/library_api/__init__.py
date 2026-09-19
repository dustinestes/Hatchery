"""Library API connection adapters — pluggable catalog providers (#255).

Connection ``type=api`` dispatches through a registry of adapters. Vendor HTTP
and filter grammar live in adapter modules; shared catalog hits stay in
``lib.library``. See ADR-0001.
"""

from __future__ import annotations

from lib.library_api.base import BaseLibraryApiAdapter
from lib.library_api.registry import all_providers, get_adapter, register

__all__ = [
    "BaseLibraryApiAdapter",
    "all_providers",
    "get_adapter",
    "register",
    "register_builtins",
]


def register_builtins() -> None:
    """Idempotent registration of built-in API adapters."""
    from lib.library_api.artifactory import ArtifactoryAdapter
    from lib.library_api import registry as reg

    for adapter in (ArtifactoryAdapter(),):
        if reg.get_adapter(adapter.id) is None:
            register(adapter)
