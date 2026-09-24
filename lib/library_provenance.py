"""Library operator-cache provenance — attribution + drift state (#308)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib import db

DOMAINS = frozenset({"scripts", "clutches", "media"})
DRIFT_STATES = frozenset({"in_sync", "out_of_sync", "unknown", "orphan"})
DIGEST_KINDS = frozenset({"sha256", "git_blob", "size_mtime"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_target(media_target: str | None) -> str:
    return (media_target or "").strip().lower()


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def upsert_on_pull(
    *,
    domain: str,
    cache_name: str,
    connection_id: str,
    relative_path: str,
    source_type: str,
    cache_sha256: str,
    source_digest: str | None = None,
    source_digest_kind: str | None = None,
    binding_id: str | None = None,
    media_target: str | None = None,
    drift_state: str = "in_sync",
) -> dict[str, Any]:
    """Insert or replace provenance after a successful first pull (anchors = observed)."""
    domain_n = (domain or "").strip().lower()
    if domain_n not in DOMAINS:
        raise ValueError(f"invalid provenance domain: {domain}")
    name = Path(cache_name).name
    if not name:
        raise ValueError("cache_name is required")
    cid = (connection_id or "").strip()
    if not cid:
        raise ValueError("connection_id is required")
    rel = (relative_path or "").replace("\\", "/").lstrip("/")
    if not rel:
        raise ValueError("relative_path is required")
    kind = (source_digest_kind or "").strip().lower() or None
    if kind and kind not in DIGEST_KINDS:
        raise ValueError(f"invalid source_digest_kind: {kind}")
    state = (drift_state or "in_sync").strip().lower()
    if state not in DRIFT_STATES:
        raise ValueError(f"invalid drift_state: {drift_state}")
    target = _norm_target(media_target)
    if domain_n != "media":
        target = ""
    now = _utc_now()
    sha = (cache_sha256 or "").strip().lower()
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO library_cache_provenance (
                domain, media_target, cache_name, connection_id, binding_id,
                relative_path, source_type, cache_sha256, cache_sha256_synced,
                source_digest, source_digest_synced, source_digest_kind, drift_state,
                checked_at, pulled_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(domain, media_target, cache_name) DO UPDATE SET
                connection_id = excluded.connection_id,
                binding_id = excluded.binding_id,
                relative_path = excluded.relative_path,
                source_type = excluded.source_type,
                cache_sha256 = excluded.cache_sha256,
                cache_sha256_synced = excluded.cache_sha256_synced,
                source_digest = excluded.source_digest,
                source_digest_synced = excluded.source_digest_synced,
                source_digest_kind = excluded.source_digest_kind,
                drift_state = excluded.drift_state,
                checked_at = excluded.checked_at,
                pulled_at = excluded.pulled_at,
                updated_at = excluded.updated_at
            """,
            (
                domain_n,
                target,
                name,
                cid,
                (binding_id or "").strip() or None,
                rel,
                (source_type or "").strip() or "path",
                sha,
                sha,
                source_digest,
                source_digest,
                kind,
                state,
                now,
                now,
                now,
            ),
        )
        conn.commit()
    row = get_for_cache(domain_n, name, media_target=target or None)
    assert row is not None
    return row


def get_for_cache(
    domain: str,
    cache_name: str,
    *,
    media_target: str | None = None,
) -> dict[str, Any] | None:
    domain_n = (domain or "").strip().lower()
    name = Path(cache_name).name
    target = _norm_target(media_target) if domain_n == "media" else ""
    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM library_cache_provenance
            WHERE domain = ? AND media_target = ? AND cache_name = ?
            """,
            (domain_n, target, name),
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_for_domain(domain: str, *, media_target: str | None = None) -> list[dict[str, Any]]:
    domain_n = (domain or "").strip().lower()
    with db.get_connection() as conn:
        if domain_n == "media" and media_target is not None:
            rows = conn.execute(
                """
                SELECT * FROM library_cache_provenance
                WHERE domain = ? AND media_target = ?
                ORDER BY cache_name COLLATE NOCASE
                """,
                (domain_n, _norm_target(media_target)),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM library_cache_provenance
                WHERE domain = ?
                ORDER BY media_target, cache_name COLLATE NOCASE
                """,
                (domain_n,),
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_all() -> list[dict[str, Any]]:
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM library_cache_provenance
            ORDER BY domain, media_target, cache_name COLLATE NOCASE
            """
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def counts_by_domain() -> dict[str, int]:
    """Linked operator-cache counts per domain (scripts / clutches / media).

    ``media`` combines ISO and VirtIO rows. Missing domains return 0.
    """
    out = {d: 0 for d in sorted(DOMAINS)}
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT domain, COUNT(*) AS n
            FROM library_cache_provenance
            GROUP BY domain
            """
        ).fetchall()
    for row in rows:
        domain = (row["domain"] or "").strip().lower()
        if domain in out:
            out[domain] = int(row["n"] or 0)
    return out


def counts_by_drift_state() -> dict[str, int]:
    """Linked operator-cache counts per stored ``drift_state``.

    Missing states return 0. Unknown DB values roll into ``unknown``.
    """
    out = {s: 0 for s in sorted(DRIFT_STATES)}
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT drift_state, COUNT(*) AS n
            FROM library_cache_provenance
            GROUP BY drift_state
            """
        ).fetchall()
    for row in rows:
        state = (row["drift_state"] or "").strip().lower()
        if state not in out:
            state = "unknown"
        out[state] += int(row["n"] or 0)
    return out


def apply_evaluate_result(
    domain: str,
    cache_name: str,
    *,
    drift_state: str,
    cache_sha256: str | None = None,
    source_digest: str | None = None,
    source_digest_kind: str | None = None,
    promote_anchors: bool = False,
    media_target: str | None = None,
    touch_pulled_at: bool = False,
) -> None:
    """Persist evaluate observations; optionally promote _synced anchors on in_sync."""
    state = (drift_state or "").strip().lower()
    if state not in DRIFT_STATES:
        raise ValueError(f"invalid drift_state: {drift_state}")
    domain_n = (domain or "").strip().lower()
    name = Path(cache_name).name
    target = _norm_target(media_target) if domain_n == "media" else ""
    now = _utc_now()
    kind = (source_digest_kind or "").strip().lower() or None
    if kind and kind not in DIGEST_KINDS:
        raise ValueError(f"invalid source_digest_kind: {kind}")
    sha = (cache_sha256 or "").strip().lower() if cache_sha256 is not None else None
    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT cache_sha256, cache_sha256_synced, source_digest, source_digest_synced,
                   source_digest_kind
            FROM library_cache_provenance
            WHERE domain = ? AND media_target = ? AND cache_name = ?
            """,
            (domain_n, target, name),
        ).fetchone()
        if row is None:
            return
        new_cache = sha if sha is not None else row["cache_sha256"]
        new_source = source_digest if source_digest is not None else row["source_digest"]
        new_kind = kind if kind is not None else row["source_digest_kind"]
        if promote_anchors and state == "in_sync":
            cache_synced = new_cache
            source_synced = new_source
        else:
            cache_synced = row["cache_sha256_synced"]
            source_synced = row["source_digest_synced"]
        if touch_pulled_at:
            conn.execute(
                """
                UPDATE library_cache_provenance
                SET drift_state = ?,
                    cache_sha256 = ?,
                    cache_sha256_synced = ?,
                    source_digest = ?,
                    source_digest_synced = ?,
                    source_digest_kind = ?,
                    checked_at = ?,
                    pulled_at = ?,
                    updated_at = ?
                WHERE domain = ? AND media_target = ? AND cache_name = ?
                """,
                (
                    state,
                    new_cache,
                    cache_synced,
                    new_source,
                    source_synced,
                    new_kind,
                    now,
                    now,
                    now,
                    domain_n,
                    target,
                    name,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE library_cache_provenance
                SET drift_state = ?,
                    cache_sha256 = ?,
                    cache_sha256_synced = ?,
                    source_digest = ?,
                    source_digest_synced = ?,
                    source_digest_kind = ?,
                    checked_at = ?,
                    updated_at = ?
                WHERE domain = ? AND media_target = ? AND cache_name = ?
                """,
                (
                    state,
                    new_cache,
                    cache_synced,
                    new_source,
                    source_synced,
                    new_kind,
                    now,
                    now,
                    domain_n,
                    target,
                    name,
                ),
            )
        conn.commit()


def set_drift_state(
    domain: str,
    cache_name: str,
    *,
    drift_state: str,
    source_digest: str | None = None,
    media_target: str | None = None,
) -> None:
    """Lightweight drift_state update (orphan / unknown without full evaluate)."""
    apply_evaluate_result(
        domain,
        cache_name,
        drift_state=drift_state,
        source_digest=source_digest,
        media_target=media_target,
        promote_anchors=False,
    )


def reattach(
    *,
    domain: str,
    cache_name: str,
    connection_id: str,
    relative_path: str,
    source_type: str,
    source_digest: str | None = None,
    source_digest_kind: str | None = None,
    binding_id: str | None = None,
    media_target: str | None = None,
) -> dict[str, Any]:
    """Rewrite provenance linkage after a successful re-attach Test (#308, #360).

    Updates connection/binding/path only. Does **not** promote sync anchors or
    mark the file in sync; callers should run single-file evaluate afterward.
    """
    existing = get_for_cache(domain, cache_name, media_target=media_target)
    if existing is None:
        raise ValueError("No provenance row for this cached file")
    domain_n = (domain or "").strip().lower()
    name = Path(cache_name).name
    cid = (connection_id or "").strip()
    if not cid:
        raise ValueError("connection_id is required")
    rel = (relative_path or "").replace("\\", "/").lstrip("/")
    if not rel:
        raise ValueError("relative_path is required")
    kind = (source_digest_kind or "").strip().lower() or None
    if kind and kind not in DIGEST_KINDS:
        raise ValueError(f"invalid source_digest_kind: {kind}")
    target = _norm_target(media_target) if domain_n == "media" else ""
    now = _utc_now()
    with db.get_connection() as conn:
        conn.execute(
            """
            UPDATE library_cache_provenance
            SET connection_id = ?,
                binding_id = ?,
                relative_path = ?,
                source_type = ?,
                source_digest = COALESCE(?, source_digest),
                source_digest_kind = COALESCE(?, source_digest_kind),
                drift_state = 'unknown',
                checked_at = ?,
                updated_at = ?
            WHERE domain = ? AND media_target = ? AND cache_name = ?
            """,
            (
                cid,
                (binding_id or "").strip() or None,
                rel,
                (source_type or "").strip() or "path",
                source_digest,
                kind,
                now,
                now,
                domain_n,
                target,
                name,
            ),
        )
        conn.commit()
    row = get_for_cache(domain_n, name, media_target=target or None)
    assert row is not None
    return row


def delete_row(
    domain: str,
    cache_name: str,
    *,
    media_target: str | None = None,
) -> bool:
    domain_n = (domain or "").strip().lower()
    name = Path(cache_name).name
    target = _norm_target(media_target) if domain_n == "media" else ""
    with db.get_connection() as conn:
        cur = conn.execute(
            """
            DELETE FROM library_cache_provenance
            WHERE domain = ? AND media_target = ? AND cache_name = ?
            """,
            (domain_n, target, name),
        )
        conn.commit()
        return cur.rowcount > 0


def rows_for_connection(connection_id: str) -> list[dict[str, Any]]:
    cid = (connection_id or "").strip()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM library_cache_provenance WHERE connection_id = ?",
            (cid,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def rows_for_binding(binding_id: str) -> list[dict[str, Any]]:
    bid = (binding_id or "").strip()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM library_cache_provenance WHERE binding_id = ?",
            (bid,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def annotate_orphan_states(
    rows: list[dict[str, Any]],
    *,
    connection_ids: set[str],
    binding_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return copies with drift_state forced to orphan when ids are missing."""
    bind_set = binding_ids
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        cid = str(item.get("connection_id") or "")
        bid = str(item.get("binding_id") or "").strip()
        orphan_reason = ""
        orphan = False
        if cid not in connection_ids:
            orphan = True
            orphan_reason = "Library connection missing"
        elif bid and bind_set is not None and bid not in bind_set:
            orphan = True
            orphan_reason = "Library binding missing"
        if orphan:
            item["drift_state"] = "orphan"
            item["orphan"] = True
            item["orphan_reason"] = orphan_reason
        else:
            item["orphan"] = item.get("drift_state") == "orphan"
            if item["orphan"]:
                item["orphan_reason"] = item.get("orphan_reason") or "Library source missing"
            else:
                item["orphan_reason"] = ""
        out.append(item)
    return out


def delete_attributed_cache_files(
    rows: list[dict[str, Any]],
    *,
    data_dir: Path,
) -> list[str]:
    """Delete operator-cache files for provenance rows; remove rows. Return deleted names."""
    from lib import library as library_lib

    deleted: list[str] = []
    for row in rows:
        domain = row["domain"]
        name = row["cache_name"]
        target = row.get("media_target") or ""
        path = library_lib.cache_path_for(
            domain, name, media_target=target or None, data_dir=data_dir
        )
        try:
            if path.is_file():
                path.unlink()
                deleted.append(name)
        except OSError:
            pass
        delete_row(domain, name, media_target=target or None)
    return deleted


def enrich_inventory(
    items: list[dict[str, Any]],
    *,
    domain: str,
    connection_ids: set[str],
    binding_ids: set[str] | None = None,
    media_target: str | None = None,
) -> list[dict[str, Any]]:
    """Attach provenance fields onto filesystem inventory dicts (keyed by name)."""
    by_name = {r["cache_name"]: r for r in list_for_domain(domain, media_target=media_target)}
    annotated = annotate_orphan_states(
        list(by_name.values()),
        connection_ids=connection_ids,
        binding_ids=binding_ids,
    )
    by_name = {r["cache_name"]: r for r in annotated}
    out: list[dict[str, Any]] = []
    for item in items:
        name = item.get("name") or ""
        row = by_name.get(name)
        enriched = dict(item)
        if row is None:
            enriched["library_provenance"] = None
            enriched["drift_state"] = "local"
            enriched["orphan"] = False
            enriched["orphan_reason"] = ""
        else:
            enriched["library_provenance"] = row
            enriched["drift_state"] = row["drift_state"]
            enriched["orphan"] = bool(row.get("orphan"))
            enriched["orphan_reason"] = row.get("orphan_reason") or ""
        out.append(enriched)
    return out
