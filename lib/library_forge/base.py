"""Abstract Library forge adapter — provider plugins implement this (#307)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseLibraryForgeAdapter(ABC):
    """Pluggable forge backend for Library connections with ``type=forge``."""

    id: str
    title: str
    description: str = ""

    @abstractmethod
    def test(self, conn: dict[str, Any]) -> dict[str, Any]:
        """Return ``{ok, message}`` for Settings → Test connection."""

    @abstractmethod
    def list_hits(
        self,
        conn: dict[str, Any],
        filt: str,
        *,
        extensions: frozenset[str],
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return Hatchery catalog hits for ``filt`` limited to ``extensions``.

        Each hit: ``name``, ``relative_path``, ``sha256`` (or None),
        ``connection_id``, ``source_type`` (``\"forge\"``).
        Git blob SHAs must not be used as ``sha256``.
        """

    @abstractmethod
    def pull_file(
        self,
        conn: dict[str, Any],
        relative_path: str,
        dest: Path,
    ) -> dict[str, Any]:
        """Download one file to ``dest`` (caller ensures create-only).

        Return ``{name, sha256, dest}`` with content SHA-256.
        """
