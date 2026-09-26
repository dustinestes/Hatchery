"""Library connection and binding registry (ADR-0017 / #367).

Rows live in SQLite ``library_connections``, ``library_connection_kinds``, and
``library_bindings``. ``library_enabled`` remains an app setting.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from lib import db as db_module
from lib.library import CONNECTION_KINDS, CONNECTION_TYPES, MEDIA_TARGETS

DOMAINS = frozenset({"scripts", "clutches", "media"})


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_kinds(raw: Any) -> list[str]:
    if isinstance(raw, str):
        items = [k.strip() for k in raw.split(",") if k.strip()]
    elif isinstance(raw, list):
        items = [str(k).strip().lower() for k in raw if str(k).strip()]
    else:
        items = []
    kinds = sorted({k for k in items if k in CONNECTION_KINDS})
    return kinds


def _kinds_map(conn: sqlite3.Connection, connection_ids: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {cid: [] for cid in connection_ids}
    if not connection_ids:
        return out
    placeholders = ",".join("?" * len(connection_ids))
    rows = conn.execute(
        f"""
        SELECT connection_id, kind FROM library_connection_kinds
        WHERE connection_id IN ({placeholders})
        ORDER BY kind
        """,
        connection_ids,
    ).fetchall()
    for row in rows:
        out[row["connection_id"]].append(row["kind"])
    return out


def _replace_kinds(conn: sqlite3.Connection, connection_id: str, kinds: list[str]) -> None:
    conn.execute(
        "DELETE FROM library_connection_kinds WHERE connection_id = ?",
        (connection_id,),
    )
    for kind in kinds:
        conn.execute(
            """
            INSERT INTO library_connection_kinds (connection_id, kind)
            VALUES (?, ?)
            """,
            (connection_id, kind),
        )


def _conn_row_to_dict(row: Any, kinds: list[str]) -> dict:
    return {
        "id": row["id"],
        "label": row["label"],
        "type": row["type"],
        "provider": row["provider"] or "",
        "base_uri": row["base_uri"] or "",
        "token": row["token"] or "",
        "expires_at": row["expires_at"],
        "kinds": list(kinds),
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _bind_row_to_dict(row: Any) -> dict:
    domain = row["domain"]
    out = {
        "id": row["id"],
        "connection_id": row["connection_id"],
        "label": row["label"] or row["filter"] or "*",
        "filter": row["filter"] or "*",
        "domain": domain,
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if domain == "media":
        out["target"] = row["media_target"] or "iso"
    return out


def list_connections() -> list[dict]:
    """Return all Library connections ordered by label."""
    if not db_module.is_initialized():
        return []
    conn = db_module.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM library_connections
            ORDER BY label COLLATE NOCASE, id
            """
        ).fetchall()
        kinds = _kinds_map(conn, [r["id"] for r in rows])
        return [_conn_row_to_dict(r, kinds.get(r["id"], [])) for r in rows]
    finally:
        conn.close()


def get_connection(connection_id: str) -> dict | None:
    cid = str(connection_id or "").strip()
    if not cid or not db_module.is_initialized():
        return None
    conn = db_module.get_connection()
    try:
        row = conn.execute("SELECT * FROM library_connections WHERE id = ?", (cid,)).fetchone()
        if not row:
            return None
        kinds = _kinds_map(conn, [cid]).get(cid, [])
        return _conn_row_to_dict(row, kinds)
    finally:
        conn.close()


def list_bindings(*, domain: str | None = None) -> list[dict]:
    """Return bindings, optionally filtered by domain."""
    if not db_module.is_initialized():
        return []
    conn = db_module.get_connection()
    try:
        if domain:
            key = str(domain).strip().lower()
            rows = conn.execute(
                """
                SELECT * FROM library_bindings
                WHERE domain = ?
                ORDER BY label COLLATE NOCASE, id
                """,
                (key,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM library_bindings
                ORDER BY domain, label COLLATE NOCASE, id
                """
            ).fetchall()
        return [_bind_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def replace_connections(connections: list[dict]) -> list[dict]:
    """Replace the full connection set.

    Callers that need bindings preserved across a full Settings save must
    rewrite bindings afterward (CASCADE removes them with their connections).
    """
    if not db_module.is_initialized():
        raise RuntimeError("db not initialized")
    now = _now()
    conn = db_module.get_connection()
    try:
        conn.execute("DELETE FROM library_connections")
        for item in connections:
            cid = str(item.get("id") or "").strip()
            if not cid:
                continue
            kinds = _normalize_kinds(item.get("kinds"))
            if not kinds:
                continue
            ctype = str(item.get("type") or "path").strip() or "path"
            if ctype not in CONNECTION_TYPES:
                ctype = "path"
            conn.execute(
                """
                INSERT INTO library_connections (
                    id, label, type, provider, base_uri, token, expires_at,
                    enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cid,
                    str(item.get("label") or cid).strip() or cid,
                    ctype,
                    str(item.get("provider") or "").strip(),
                    str(item.get("base_uri") or "").strip(),
                    str(item.get("token") or ""),
                    item.get("expires_at"),
                    1 if item.get("enabled", True) else 0,
                    str(item.get("created_at") or now),
                    now,
                ),
            )
            _replace_kinds(conn, cid, kinds)
        conn.commit()
    finally:
        conn.close()
    return list_connections()


def replace_bindings_for_domain(domain: str, bindings: list[dict]) -> list[dict]:
    """Replace all bindings for one domain."""
    key = str(domain or "").strip().lower()
    if key not in DOMAINS:
        raise ValueError(f"invalid binding domain: {domain}")
    if not db_module.is_initialized():
        raise RuntimeError("db not initialized")
    now = _now()
    conn = db_module.get_connection()
    try:
        conn.execute("DELETE FROM library_bindings WHERE domain = ?", (key,))
        for item in bindings:
            bid = str(item.get("id") or "").strip()
            cid = str(item.get("connection_id") or "").strip()
            if not bid or not cid:
                continue
            filt = str(item.get("filter") or "").strip() or "*"
            label = str(item.get("label") or "").strip() or filt
            target = ""
            if key == "media":
                target = str(item.get("target") or "iso").strip().lower() or "iso"
                if target not in MEDIA_TARGETS:
                    target = "iso"
            conn.execute(
                """
                INSERT INTO library_bindings (
                    id, connection_id, domain, media_target, label, filter,
                    enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bid,
                    cid,
                    key,
                    target,
                    label,
                    filt,
                    1 if item.get("enabled", True) else 0,
                    str(item.get("created_at") or now),
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return list_bindings(domain=key)


def upsert_connection(item: dict) -> dict:
    """Insert or update one connection by id."""
    if not db_module.is_initialized():
        raise RuntimeError("db not initialized")
    cid = str(item.get("id") or "").strip()
    if not cid:
        raise ValueError("connection id is required")
    kinds = _normalize_kinds(item.get("kinds"))
    if not kinds:
        raise ValueError("connection requires at least one kind")
    ctype = str(item.get("type") or "path").strip() or "path"
    if ctype not in CONNECTION_TYPES:
        raise ValueError(f"invalid connection type: {ctype}")
    now = _now()
    conn = db_module.get_connection()
    try:
        existing = conn.execute(
            "SELECT created_at FROM library_connections WHERE id = ?", (cid,)
        ).fetchone()
        created = existing["created_at"] if existing else now
        conn.execute(
            """
            INSERT INTO library_connections (
                id, label, type, provider, base_uri, token, expires_at,
                enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                label = excluded.label,
                type = excluded.type,
                provider = excluded.provider,
                base_uri = excluded.base_uri,
                token = excluded.token,
                expires_at = excluded.expires_at,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (
                cid,
                str(item.get("label") or cid).strip() or cid,
                ctype,
                str(item.get("provider") or "").strip(),
                str(item.get("base_uri") or "").strip(),
                str(item.get("token") or ""),
                item.get("expires_at"),
                1 if item.get("enabled", True) else 0,
                created,
                now,
            ),
        )
        _replace_kinds(conn, cid, kinds)
        conn.commit()
    finally:
        conn.close()
    row = get_connection(cid)
    assert row is not None
    return row


def delete_connection(connection_id: str) -> bool:
    """Delete a connection (kinds + bindings CASCADE). Returns True if removed."""
    cid = str(connection_id or "").strip()
    if not cid or not db_module.is_initialized():
        return False
    conn = db_module.get_connection()
    try:
        cur = conn.execute("DELETE FROM library_connections WHERE id = ?", (cid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def upsert_binding(item: dict) -> dict:
    """Insert or update one binding by id."""
    if not db_module.is_initialized():
        raise RuntimeError("db not initialized")
    bid = str(item.get("id") or "").strip()
    cid = str(item.get("connection_id") or "").strip()
    domain = str(item.get("domain") or "").strip().lower()
    if not bid:
        raise ValueError("binding id is required")
    if not cid:
        raise ValueError("connection_id is required")
    if domain not in DOMAINS:
        raise ValueError(f"invalid binding domain: {domain}")
    filt = str(item.get("filter") or "").strip() or "*"
    label = str(item.get("label") or "").strip() or filt
    target = ""
    if domain == "media":
        target = str(item.get("target") or "iso").strip().lower() or "iso"
        if target not in MEDIA_TARGETS:
            raise ValueError(f"invalid media target: {target}")
    now = _now()
    conn = db_module.get_connection()
    try:
        parent = conn.execute("SELECT id FROM library_connections WHERE id = ?", (cid,)).fetchone()
        if parent is None:
            raise ValueError(f"unknown connection id: {cid}")
        existing = conn.execute(
            "SELECT created_at FROM library_bindings WHERE id = ?", (bid,)
        ).fetchone()
        created = existing["created_at"] if existing else now
        conn.execute(
            """
            INSERT INTO library_bindings (
                id, connection_id, domain, media_target, label, filter,
                enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                connection_id = excluded.connection_id,
                domain = excluded.domain,
                media_target = excluded.media_target,
                label = excluded.label,
                filter = excluded.filter,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (
                bid,
                cid,
                domain,
                target,
                label,
                filt,
                1 if item.get("enabled", True) else 0,
                created,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    matches = [b for b in list_bindings(domain=domain) if b["id"] == bid]
    assert matches
    return matches[0]


def delete_binding(binding_id: str) -> bool:
    bid = str(binding_id or "").strip()
    if not bid or not db_module.is_initialized():
        return False
    conn = db_module.get_connection()
    try:
        cur = conn.execute("DELETE FROM library_bindings WHERE id = ?", (bid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def migrate_from_app_settings(conn: sqlite3.Connection) -> bool:
    """Copy Settings JSON arrays into tables once. Returns True if migration ran.

    Idempotent: skips when ``library_connections`` already has rows.
    Clears the four Settings keys after a successful copy (or when already migrated
    and keys still linger).
    """
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='library_connections'"
    ).fetchone()
    if not table:
        return False

    existing = conn.execute("SELECT COUNT(*) AS n FROM library_connections").fetchone()
    already = int((existing[0] if existing else 0) or 0) > 0

    def _load_json(key: str) -> list:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        if not row:
            return []
        try:
            data = json.loads(row[0])
        except (TypeError, json.JSONDecodeError, KeyError):
            return []
        return data if isinstance(data, list) else []

    if not already:
        connections = _load_json("library_connections")
        now = _now()
        for item in connections:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("id") or "").strip()
            if not cid:
                continue
            kinds = _normalize_kinds(item.get("kinds"))
            if not kinds:
                continue
            ctype = str(item.get("type") or "path").strip() or "path"
            if ctype not in CONNECTION_TYPES:
                ctype = "path"
            conn.execute(
                """
                INSERT OR IGNORE INTO library_connections (
                    id, label, type, provider, base_uri, token, expires_at,
                    enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cid,
                    str(item.get("label") or cid).strip() or cid,
                    ctype,
                    str(item.get("provider") or "").strip(),
                    str(item.get("base_uri") or "").strip(),
                    str(item.get("token") or ""),
                    item.get("expires_at"),
                    1 if item.get("enabled", True) else 0,
                    now,
                    now,
                ),
            )
            for kind in kinds:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO library_connection_kinds (connection_id, kind)
                    VALUES (?, ?)
                    """,
                    (cid, kind),
                )

        domain_keys = (
            ("scripts", "library_script_bindings"),
            ("clutches", "library_clutch_bindings"),
            ("media", "library_media_bindings"),
        )
        for domain, key in domain_keys:
            for item in _load_json(key):
                if not isinstance(item, dict):
                    continue
                bid = str(item.get("id") or "").strip()
                cid = str(item.get("connection_id") or "").strip()
                if not bid or not cid:
                    continue
                parent = conn.execute(
                    "SELECT 1 FROM library_connections WHERE id = ?", (cid,)
                ).fetchone()
                if parent is None:
                    continue
                filt = str(item.get("filter") or "").strip() or "*"
                label = str(item.get("label") or "").strip() or filt
                target = ""
                if domain == "media":
                    target = str(item.get("target") or "iso").strip().lower() or "iso"
                    if target not in MEDIA_TARGETS:
                        target = "iso"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO library_bindings (
                        id, connection_id, domain, media_target, label, filter,
                        enabled, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        bid,
                        cid,
                        domain,
                        target,
                        label,
                        filt,
                        1 if item.get("enabled", True) else 0,
                        now,
                        now,
                    ),
                )

    # Always drop legacy Settings keys once tables exist (ADR-0017).
    for key in (
        "library_connections",
        "library_script_bindings",
        "library_clutch_bindings",
        "library_media_bindings",
    ):
        conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
    return True


# Well-known demo catalog (#315). Seeded only when the registry is empty
# (fresh Controller). No token - public GitHub repo.
HATCHERY_LIBRARY_CONNECTION_ID = "hatchery-library"
HATCHERY_LIBRARY_BASE_URI = "https://github.com/dustinestes/Hatchery-Library"


def ensure_hatchery_library() -> bool:
    """Seed the public Hatchery Library forge connection + bindings if empty.

    First-run / empty-registry only: never re-inserts after the operator has
    any connection (including after they delete this one and keep others).
    Enables ``library_enabled`` when seeding so the Connection is visible.
    Idempotent no-op when connections already exist. Returns True if seeded.
    """
    if not db_module.is_initialized():
        return False
    if list_connections():
        return False

    upsert_connection(
        {
            "id": HATCHERY_LIBRARY_CONNECTION_ID,
            "label": "Hatchery Library",
            "type": "forge",
            "provider": "github",
            "base_uri": HATCHERY_LIBRARY_BASE_URI,
            "token": "",
            "expires_at": None,
            "kinds": ["scripts", "clutches", "media", "packages"],
            "enabled": True,
        }
    )
    cid = HATCHERY_LIBRARY_CONNECTION_ID
    for item in (
        {
            "id": "hatchery-library-scripts",
            "connection_id": cid,
            "domain": "scripts",
            "label": "All Scripts",
            "filter": "*",
            "enabled": True,
        },
        {
            "id": "hatchery-library-clutches",
            "connection_id": cid,
            "domain": "clutches",
            "label": "All Clutches",
            "filter": "*",
            "enabled": True,
        },
        {
            "id": "hatchery-library-media-iso",
            "connection_id": cid,
            "domain": "media",
            "target": "iso",
            "label": "All ISOs",
            "filter": "*",
            "enabled": True,
        },
        {
            "id": "hatchery-library-media-virtio",
            "connection_id": cid,
            "domain": "media",
            "target": "virtio",
            "label": "All VirtIO",
            "filter": "*",
            "enabled": True,
        },
    ):
        upsert_binding(item)

    from lib import config as config_lib

    config_lib.update_settings({"library_enabled": True})
    return True
