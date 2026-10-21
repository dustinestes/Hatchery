"""Nest-plane event transcript (#611 / ADR-0041).

Append-only Nest Events keyed by Nest id - parallel to ``hatch_events``, not
Alerts and not hatch/provision lines. Controllers and Nest agents write rows;
Nest detail Events tile and ``hatchery nest events`` read them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from lib import db

SOURCES = frozenset({"controller", "nest"})
TOPICS = frozenset({"health", "transport", "cache_sync", "job", "general"})
LEVELS = frozenset({"INFO", "WARN", "ERROR"})


class NestEventsError(RuntimeError):
    """Raised when a Nest event cannot be accepted."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_source(raw: Any) -> str:
    val = str(raw or "").strip().lower()
    if val not in SOURCES:
        raise NestEventsError(f"source must be one of: {', '.join(sorted(SOURCES))}")
    return val


def _norm_topic(raw: Any) -> str:
    val = str(raw or "").strip().lower()
    if val not in TOPICS:
        raise NestEventsError(f"topic must be one of: {', '.join(sorted(TOPICS))}")
    return val


def _norm_level(raw: Any) -> str:
    val = str(raw or "").strip().upper()
    if val not in LEVELS:
        raise NestEventsError(f"level must be one of: {', '.join(sorted(LEVELS))}")
    return val


def add_event(
    nest_id: str,
    *,
    source: str,
    topic: str,
    level: str,
    message: str,
    component: str | None = None,
    ref: str | None = None,
    received_at: str | None = None,
) -> dict[str, Any]:
    """Insert one Nest Event; return the stored row (with ``id``)."""
    nid = str(nest_id or "").strip()
    if not nid:
        raise NestEventsError("nest_id is required")
    msg = str(message or "").strip()
    if not msg:
        raise NestEventsError("message is required")
    src = _norm_source(source)
    top = _norm_topic(topic)
    lvl = _norm_level(level)
    comp = str(component).strip() if component is not None and str(component).strip() else None
    job_ref = str(ref).strip() if ref is not None and str(ref).strip() else None
    ts = str(received_at or "").strip() or _utc_now()

    conn = db.get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO nest_events
               (nest_id, source, topic, level, component, message, ref, received_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (nid, src, top, lvl, comp, msg, job_ref, ts),
        )
        conn.commit()
        row_id = int(cur.lastrowid)
    finally:
        conn.close()
    return {
        "id": row_id,
        "nest_id": nid,
        "source": src,
        "topic": top,
        "level": lvl,
        "component": comp,
        "message": msg,
        "ref": job_ref,
        "received_at": ts,
    }


def add_events(nest_id: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert a batch of Nest Events (same nest_id). Returns stored rows."""
    if not isinstance(events, list) or not events:
        raise NestEventsError("events must be a non-empty list")
    out: list[dict[str, Any]] = []
    for raw in events:
        if not isinstance(raw, dict):
            raise NestEventsError("each event must be an object")
        out.append(
            add_event(
                nest_id,
                source=raw.get("source") or "nest",
                topic=raw.get("topic") or "general",
                level=raw.get("level") or "INFO",
                message=raw.get("message") or "",
                component=raw.get("component"),
                ref=raw.get("ref"),
                received_at=raw.get("received_at"),
            )
        )
    return out


def query_events(
    nest_id: str,
    *,
    topic: str | None = None,
    level: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Newest-first Nest Events page for one Nest."""
    nid = str(nest_id or "").strip()
    if not nid:
        raise NestEventsError("nest_id is required")
    lim = max(1, min(int(limit or 100), 200))
    off = max(0, int(offset or 0))
    clauses = ["nest_id = ?"]
    params: list[object] = [nid]

    if topic:
        clauses.append("topic = ?")
        params.append(_norm_topic(topic))
    if level:
        clauses.append("level = ?")
        params.append(_norm_level(level))
    if q:
        needle = f"%{str(q).strip()}%"
        clauses.append(
            "(message LIKE ? OR IFNULL(component, '') LIKE ?"
            " OR IFNULL(ref, '') LIKE ? OR source LIKE ? OR topic LIKE ?)"
        )
        params.extend([needle, needle, needle, needle, needle])

    where = " AND ".join(clauses)
    conn = db.get_connection()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM nest_events WHERE {where}",
            params,
        ).fetchone()["n"]
        rows = conn.execute(
            f"""SELECT id, nest_id, source, topic, level, component, message, ref, received_at
                FROM nest_events
                WHERE {where}
                ORDER BY id DESC
                LIMIT ? OFFSET ?""",
            [*params, lim, off],
        ).fetchall()
        return {
            "events": [dict(r) for r in rows],
            "total": int(total),
            "limit": lim,
            "offset": off,
        }
    finally:
        conn.close()


def prune_removed_nests(kept_ids: set[str]) -> None:
    """Delete Nest Events for Nest ids no longer in the registry."""
    conn = db.get_connection()
    try:
        if not kept_ids:
            conn.execute("DELETE FROM nest_events")
        else:
            placeholders = ", ".join("?" for _ in kept_ids)
            conn.execute(
                f"DELETE FROM nest_events WHERE nest_id NOT IN ({placeholders})",
                tuple(kept_ids),
            )
        conn.commit()
    finally:
        conn.close()


def record_controller(
    nest_id: str,
    *,
    topic: str,
    level: str,
    message: str,
    component: str | None = None,
    ref: str | None = None,
) -> dict[str, Any] | None:
    """Best-effort Controller writer (never raises into caller's main path)."""
    try:
        return add_event(
            nest_id,
            source="controller",
            topic=topic,
            level=level,
            message=message,
            component=component,
            ref=ref,
        )
    except Exception:
        return None
