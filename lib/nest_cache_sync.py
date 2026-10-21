"""Nest-reported nest_cache sync status (#608 / ADR-0040).

Controller aggregates and persists Nest reports. Nest owns compare.
Local Nest: Nest plane is this host - run content check in-process under
Controller ``data_dir``. Remote Nest: never SSH-SHA Nest disks; Check may
record ``unavailable`` until Nest pull (#609); ingest accepts Nest reports.

File lists use the product noun **content** (not inventory). Full Nest-plane
transcript lines land in Nest Events (#611); this module keeps a single latest
``message`` for the Cache tile status console.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib import config as config_lib
from lib import nest_cache as nest_cache_lib
from lib import nests as nests_lib

_SETTINGS_KEY = "nest_cache_sync"

SYNC_STATES = frozenset({"unevaluated", "in_sync", "out_of_sync", "syncing", "unavailable"})
REPORT_SOURCES = frozenset({"local_verify", "nest_report"})
CONTENT_STATES = frozenset({"present", "missing", "mismatch", "extra"})

_LAYOUT_DIRS: tuple[str, ...] = (
    "media/iso",
    "media/virtio",
    "automation/answerfiles",
    "automation/scripts",
    "automation/software",
)

_REMOTE_UNAVAILABLE_MSG = (
    "Remote Nest cache sync check is not available yet "
    "(Nest-owned pull / report - see #609 / #345). "
    "Controller does not SHA Nest disks over the control plane."
)


class NestCacheSyncError(RuntimeError):
    """Raised when Nest cache sync report cannot be accepted or run."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_snapshot() -> dict[str, Any]:
    return {"updated_at": None, "nests": {}}


def get_snapshot() -> dict[str, Any]:
    """Return last known nest_cache sync snapshot (may be empty)."""
    raw = config_lib.get().get(_SETTINGS_KEY)
    if not isinstance(raw, dict):
        return _empty_snapshot()
    nests = raw.get("nests") if isinstance(raw.get("nests"), dict) else {}
    return {
        "updated_at": raw.get("updated_at"),
        "nests": nests,
    }


def _save_snapshot(snap: dict[str, Any]) -> None:
    config_lib.update_settings({_SETTINGS_KEY: snap})


def get_sync(nest_id: str) -> dict[str, Any] | None:
    """Return persisted sync report for one Nest, or None."""
    entry = (get_snapshot().get("nests") or {}).get(str(nest_id or "").strip())
    return dict(entry) if isinstance(entry, dict) else None


def empty_report(*, nest_id: str | None = None) -> dict[str, Any]:
    """Default unevaluated report (before first check / Nest report)."""
    return {
        "nest_id": nest_id,
        "sync_state": "unevaluated",
        "checked_at": None,
        "message": "Not checked",
        "source": None,
        "content": [],
    }


def prune_removed_nests(kept_ids: set[str]) -> None:
    """Drop sync snapshot entries for Nest ids no longer in the registry."""
    snap = get_snapshot()
    nests = dict(snap.get("nests") or {})
    if not nests:
        return
    pruned = {nid: entry for nid, entry in nests.items() if nid in kept_ids}
    if pruned.keys() == nests.keys():
        return
    _save_snapshot({"updated_at": _utc_now(), "nests": pruned})


def _normalize_content_item(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    path = str(raw.get("path") or "").strip().replace("\\", "/")
    basename = str(raw.get("basename") or "").strip() or (Path(path).name if path else "")
    kind = str(raw.get("kind") or "").strip()
    if not kind and path:
        for prefix in _LAYOUT_DIRS:
            if path == prefix or path.startswith(prefix + "/"):
                kind = prefix
                break
    state = str(raw.get("state") or "present").strip().lower()
    if state not in CONTENT_STATES:
        state = "present"
    size_raw = raw.get("size_bytes")
    size_bytes: int | None
    try:
        size_bytes = int(size_raw) if size_raw is not None else None
    except (TypeError, ValueError):
        size_bytes = None
    mtime = raw.get("mtime")
    mtime_text = str(mtime).strip() if mtime is not None else None
    item: dict[str, Any] = {
        "kind": kind or None,
        "basename": basename or None,
        "path": path or None,
        "size_bytes": size_bytes,
        "mtime": mtime_text or None,
        "state": state,
    }
    sha = str(raw.get("sha256") or "").strip()
    if sha:
        item["sha256"] = sha
    if not item["path"] and not item["basename"]:
        return None
    return item


def normalize_report(payload: dict[str, Any], *, nest_id: str) -> dict[str, Any]:
    """Validate and normalize a Nest sync report body."""
    if not isinstance(payload, dict):
        raise NestCacheSyncError("sync report must be an object")
    state = str(payload.get("sync_state") or "").strip().lower()
    if state not in SYNC_STATES:
        raise NestCacheSyncError(
            f"invalid sync_state: {payload.get('sync_state')!r} "
            f"(expected one of {sorted(SYNC_STATES)})"
        )
    source_raw = payload.get("source")
    source: str | None
    if source_raw is None or source_raw == "":
        source = None
    else:
        source = str(source_raw).strip().lower()
        if source not in REPORT_SOURCES:
            raise NestCacheSyncError(
                f"invalid source: {source_raw!r} (expected one of {sorted(REPORT_SOURCES)})"
            )
    content_raw = payload.get("content")
    if content_raw is None:
        content_raw = []
    if not isinstance(content_raw, list):
        raise NestCacheSyncError("content must be a list")
    content: list[dict[str, Any]] = []
    for entry in content_raw:
        item = _normalize_content_item(entry)
        if item is not None:
            content.append(item)
    checked_at = payload.get("checked_at")
    checked_text = str(checked_at).strip() if checked_at else _utc_now()
    message = str(payload.get("message") or "").strip() or None
    return {
        "nest_id": nest_id,
        "sync_state": state,
        "checked_at": checked_text,
        "message": message,
        "source": source,
        "content": content,
    }


def record_report(nest_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a normalized Nest sync report and return it."""
    nid = str(nest_id or "").strip()
    if not nid:
        raise NestCacheSyncError("nest_id is required")
    report = normalize_report(payload, nest_id=nid)
    snap = get_snapshot()
    nests = dict(snap.get("nests") or {})
    nests[nid] = report
    _save_snapshot({"updated_at": _utc_now(), "nests": nests})
    return report


def _scan_local_content(root: Path) -> list[dict[str, Any]]:
    """List files under known nest_cache layout dirs (no SHA hashing)."""
    items: list[dict[str, Any]] = []
    if not root.is_dir():
        return items
    for kind in _LAYOUT_DIRS:
        base = root / kind
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                continue
            try:
                st = path.stat()
                size_bytes = int(st.st_size)
                mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            except OSError:
                size_bytes = None
                mtime = None
            items.append(
                {
                    "kind": kind,
                    "basename": path.name,
                    "path": rel,
                    "size_bytes": size_bytes,
                    "mtime": mtime,
                    "state": "present",
                }
            )
    return items


def run_check(nest: dict[str, Any]) -> dict[str, Any]:
    """Run Nest-side sync check (Local verify) or Remote unavailable stub.

    Remote Check does not wipe prior Nest-reported content when
    ``source=nest_report``.
    """
    nid = str(nest.get("id") or "").strip() or "?"
    location = str(nest.get("location") or "local").strip().lower()
    if location != "remote":
        try:
            root = nest_cache_lib.resolve_nest_cache(nest)
        except nest_cache_lib.NestCacheError as exc:
            report = {
                "sync_state": "unavailable",
                "checked_at": _utc_now(),
                "message": str(exc),
                "source": "local_verify",
                "content": [],
            }
            return record_report(nid, report)
        content = _scan_local_content(root)
        report = {
            "sync_state": "in_sync",
            "checked_at": _utc_now(),
            "message": f"Local nest_cache content ({len(content)} item(s))",
            "source": "local_verify",
            "content": content,
        }
        return record_report(nid, report)

    prior = get_sync(nid)
    content: list[dict[str, Any]] = []
    if (
        isinstance(prior, dict)
        and prior.get("source") == "nest_report"
        and isinstance(prior.get("content"), list)
    ):
        content = list(prior["content"])
    report = {
        "sync_state": "unavailable",
        "checked_at": _utc_now(),
        "message": _REMOTE_UNAVAILABLE_MSG,
        "source": "nest_report" if content else None,
        "content": content,
    }
    return record_report(nid, report)


def sync_status_for_nest(nest: dict[str, Any]) -> dict[str, Any]:
    """Return persisted sync report or unevaluated default for API/UI."""
    nid = str(nest.get("id") or "").strip()
    stored = get_sync(nid) if nid else None
    if stored is None:
        return empty_report(nest_id=nid or None)
    out = dict(stored)
    out.setdefault("nest_id", nid)
    out.setdefault("content", [])
    return out


def run_as_validator(ctx: Any) -> str:
    """Validator entry: check each Nest (or ``ctx.nest_id`` when set)."""
    nests = nests_lib.list_nests()
    filter_id = getattr(ctx, "nest_id", None)
    if filter_id:
        nests = [n for n in nests if n.get("id") == filter_id]
    if not nests:
        return "No Nests registered"
    parts: list[str] = []
    for nest in nests:
        report = run_check(nest)
        nid = nest.get("id") or "?"
        parts.append(f"{nid}:{report.get('sync_state')}")
    return f"nest_cache_sync {', '.join(parts)}"
