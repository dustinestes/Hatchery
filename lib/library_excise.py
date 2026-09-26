"""Library disable / excise teardown helpers (#407 / ADR-0019).

Apply optional Clear Connections / Content / Links before setting
``library_enabled=false``. Soft disable = all toggles off.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lib import library as library_lib
from lib import library_provenance as prov
from lib import library_registry as library_registry_lib


def apply_disable_excise(
    *,
    clear_connections: bool,
    clear_content: bool,
    clear_links: bool,
    data_dir: Path,
) -> dict[str, Any]:
    """Apply teardown depth for Library disable.

    Order: content or links first (while connections still exist), then clear
    connections. Caller sets ``library_enabled=false`` afterward.

    Raises:
        ValueError: if ``clear_content`` and ``clear_links`` are both True.
    """
    if clear_content and clear_links:
        raise ValueError("Clear Content and Clear Links are mutually exclusive")

    connections_deleted = 0
    files_deleted = 0
    links_cleared = 0

    if clear_content:
        deleted_names = prov.delete_attributed_cache_files(
            prov.list_all(),
            data_dir=data_dir,
        )
        files_deleted = len(deleted_names)
    elif clear_links:
        links_cleared = prov.delete_all_rows()

    if clear_connections:
        for conn in list(library_registry_lib.list_connections()):
            cid = str(conn.get("id") or "").strip()
            if not cid:
                continue
            if library_registry_lib.delete_connection(cid):
                connections_deleted += 1
            try:
                library_lib.purge_legacy_git_cache(cid)
            except (ValueError, OSError):
                pass

    return {
        "connections_deleted": connections_deleted,
        "files_deleted": files_deleted,
        "links_cleared": links_cleared,
    }
