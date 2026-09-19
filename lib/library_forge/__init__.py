"""Library forge connection adapters — pluggable providers (#307).

Connection ``type=forge`` dispatches through a registry of adapters. Vendor HTTP
and filter grammar live in adapter modules; shared catalog hits stay in
``lib.library``. See ADR-0010.
"""

from __future__ import annotations

from lib.library_forge.base import BaseLibraryForgeAdapter
from lib.library_forge.registry import all_providers, get_adapter, register

__all__ = [
    "BaseLibraryForgeAdapter",
    "all_providers",
    "get_adapter",
    "register",
    "register_builtins",
]


def register_builtins() -> None:
    """Idempotent registration of built-in forge adapters."""
    from lib.library_forge import registry as reg
    from lib.library_forge.github import GitHubAdapter

    for adapter in (GitHubAdapter(),):
        if reg.get_adapter(adapter.id) is None:
            register(adapter)
