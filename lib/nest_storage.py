"""Nest ``nest_storage`` volumes - guest VM disk roots on a Nest (#538).

Persisted on the Nest row ``extra`` JSON:

- ``nest_storage_volumes``: list of ``{id, path, primary}``
- ``nest_storage``: primary path (factory / provider SoR; ADR-0039)

Distinct from ``nest_cache`` (Library/media content root; #215).
"""

from __future__ import annotations

import uuid
from typing import Any

from lib import nests as nests_lib


class NestStorageError(ValueError):
    """Invalid nest_storage volume operation."""


def list_storage_volumes(nest: dict) -> list[dict[str, Any]]:
    """Return normalized nest_storage volumes for a Nest row."""
    extra = nest.get("extra") if isinstance(nest.get("extra"), dict) else {}
    raw = extra.get("nest_storage_volumes")
    volumes: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            vid = str(item.get("id") or "").strip()
            if not path or not vid:
                continue
            volumes.append(
                {
                    "id": vid,
                    "path": path,
                    "primary": bool(item.get("primary")),
                }
            )
    # Legacy: single nest_storage path without volumes list.
    if not volumes:
        legacy = str(extra.get("nest_storage") or "").strip()
        if legacy:
            volumes.append(
                {
                    "id": "primary",
                    "path": legacy,
                    "primary": True,
                }
            )
    return _normalize_primaries(volumes)


def _normalize_primaries(volumes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not volumes:
        return []
    primary_ids = [v["id"] for v in volumes if v.get("primary")]
    if len(primary_ids) == 1:
        return volumes
    # Exactly one primary: first volume wins when none/many marked.
    out: list[dict[str, Any]] = []
    for i, vol in enumerate(volumes):
        row = dict(vol)
        row["primary"] = i == 0 if not primary_ids else vol["id"] == primary_ids[0]
        out.append(row)
    if not any(v["primary"] for v in out) and out:
        out[0]["primary"] = True
    return out


def _storage_extra_patch(volumes: list[dict[str, Any]]) -> dict[str, Any]:
    """Keys to merge into Nest ``extra`` for the volumes list + primary path."""
    volumes = _normalize_primaries(volumes)
    primary_path = next((v["path"] for v in volumes if v.get("primary")), None)
    patch: dict[str, Any] = {"nest_storage_volumes": volumes}
    if primary_path:
        patch["nest_storage"] = primary_path
    else:
        patch["nest_storage"] = None
    return patch


def _persist_volumes(nest_id: str, volumes: list[dict[str, Any]]) -> None:
    nests_lib.update_nest_extra(nest_id, _storage_extra_patch(volumes))


def add_storage_volume(
    nest_id: str,
    path: str,
    *,
    primary: bool = False,
) -> dict[str, Any]:
    """Register a nest_storage path on the Nest; return the new volume."""
    nest = nests_lib.get_nest(nest_id)
    if nest is None:
        raise NestStorageError(f"Unknown Nest id: {nest_id}")
    path_text = (path or "").strip()
    if not path_text:
        raise NestStorageError("nest_storage path is required")
    volumes = list_storage_volumes(nest)
    for vol in volumes:
        if vol["path"] == path_text:
            raise NestStorageError(f"nest_storage path already registered: {path_text}")
    if primary or not volumes:
        for vol in volumes:
            vol["primary"] = False
        primary = True
    volume = {
        "id": uuid.uuid4().hex[:12],
        "path": path_text,
        "primary": bool(primary),
    }
    volumes.append(volume)
    _persist_volumes(nest_id, volumes)
    return volume


def remove_storage_volume(nest_id: str, volume_id: str) -> None:
    """Remove a nest_storage volume by id."""
    nest = nests_lib.get_nest(nest_id)
    if nest is None:
        raise NestStorageError(f"Unknown Nest id: {nest_id}")
    vid = (volume_id or "").strip()
    if not vid:
        raise NestStorageError("volume id is required")
    before = list_storage_volumes(nest)
    volumes = [v for v in before if v["id"] != vid]
    if len(volumes) == len(before):
        raise NestStorageError(f"Unknown nest_storage volume: {vid}")
    _persist_volumes(nest_id, volumes)


def update_storage_volume(
    nest_id: str,
    volume_id: str,
    *,
    path: str | None = None,
    primary: bool | None = None,
) -> dict[str, Any]:
    """Update path and/or primary flag for an existing nest_storage volume."""
    nest = nests_lib.get_nest(nest_id)
    if nest is None:
        raise NestStorageError(f"Unknown Nest id: {nest_id}")
    vid = (volume_id or "").strip()
    if not vid:
        raise NestStorageError("volume id is required")
    volumes = list_storage_volumes(nest)
    found: dict[str, Any] | None = None
    for vol in volumes:
        if vol["id"] == vid:
            found = vol
            break
    if found is None:
        raise NestStorageError(f"Unknown nest_storage volume: {vid}")
    if path is not None:
        path_text = str(path).strip()
        if not path_text:
            raise NestStorageError("nest_storage path is required")
        for vol in volumes:
            if vol["id"] != vid and vol["path"] == path_text:
                raise NestStorageError(f"nest_storage path already registered: {path_text}")
        found["path"] = path_text
    if primary is True:
        for vol in volumes:
            vol["primary"] = vol["id"] == vid
    elif primary is False and found.get("primary"):
        # Clearing primary: first remaining volume becomes primary.
        found["primary"] = False
        for vol in volumes:
            if vol["id"] != vid:
                vol["primary"] = True
                break
        else:
            found["primary"] = True
    _persist_volumes(nest_id, volumes)
    nest = nests_lib.get_nest(nest_id)
    assert nest is not None
    for vol in list_storage_volumes(nest):
        if vol["id"] == vid:
            return vol
    raise NestStorageError(f"Unknown nest_storage volume: {vid}")


def set_primary_storage_volume(nest_id: str, volume_id: str) -> dict[str, Any]:
    """Mark one volume primary; sync ``extra.nest_storage``."""
    nest = nests_lib.get_nest(nest_id)
    if nest is None:
        raise NestStorageError(f"Unknown Nest id: {nest_id}")
    vid = (volume_id or "").strip()
    volumes = list_storage_volumes(nest)
    found = None
    for vol in volumes:
        vol["primary"] = vol["id"] == vid
        if vol["primary"]:
            found = vol
    if found is None:
        raise NestStorageError(f"Unknown nest_storage volume: {vid}")
    _persist_volumes(nest_id, volumes)
    return found
