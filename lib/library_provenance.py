"""Library operator-cache provenance — attribution + drift state (#308 / #382)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib import db

DOMAINS = frozenset({"scripts", "clutches", "media"})
# Derived for one-release UI/API compat (ADR-0018). Prefer source_status + sync_state.
DRIFT_STATES = frozenset({"in_sync", "out_of_sync", "unknown", "orphan"})
SOURCE_STATUSES = frozenset(
    {
        "ok",
        "missing",
        "orphan",
        "disabled",
        "rate_limited",
        "unreachable",
        "unconfirmable",
    }
)
SYNC_STATES = frozenset({"in_sync", "out_of_sync", "unevaluated"})
DIGEST_KINDS = frozenset({"sha256", "git_blob", "size_mtime"})

SOURCE_STATUS_MESSAGES: dict[str, str] = {
    "ok": "",
    "missing": "Source path not found at the recorded location",
    "orphan": "Library connection or binding missing",
    "disabled": "Library connection is disabled",
    "rate_limited": "Source tip check rate-limited; try again later",
    "unreachable": "Could not reach Library source",
    "unconfirmable": "Source tip cannot be confirmed without downloading the file",
}


def catalog_message(source_status: str, detail: str = "") -> str:
    """Known catalog text, optionally appending operator-facing detail."""
    status = (source_status or "").strip().lower()
    base = SOURCE_STATUS_MESSAGES.get(status, "")
    detail_n = (detail or "").strip()
    if status == "orphan" and detail_n:
        return detail_n
    if not detail_n:
        return base
    if not base:
        return detail_n
    if detail_n.lower() == base.lower() or detail_n.startswith(base):
        return detail_n
    return f"{base}: {detail_n}"


def derive_drift_state(source_status: str, sync_state: str) -> str:
    """Map ADR-0018 axes onto legacy drift_state (compat only)."""
    status = (source_status or "").strip().lower()
    sync = (sync_state or "").strip().lower()
    if status == "orphan":
        return "orphan"
    if status == "ok" and sync == "in_sync":
        return "in_sync"
    if status == "ok" and sync == "out_of_sync":
        return "out_of_sync"
    return "unknown"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_target(media_target: str | None) -> str:
    return (media_target or "").strip().lower()


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _validate_axes(source_status: str, sync_state: str) -> tuple[str, str]:
    status = (source_status or "").strip().lower()
    sync = (sync_state or "").strip().lower()
    if status not in SOURCE_STATUSES:
        raise ValueError(f"invalid source_status: {source_status}")
    if sync not in SYNC_STATES:
        raise ValueError(f"invalid sync_state: {sync_state}")
    if status == "ok":
        if sync == "unevaluated":
            raise ValueError("sync_state cannot be unevaluated when source_status is ok")
    elif sync != "unevaluated":
        raise ValueError("sync_state must be unevaluated when source_status is not ok")
    return status, sync


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
    source_status: str = "ok",
    sync_state: str = "in_sync",
    source_status_message: str = "",
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
    # Prefer explicit axes; drift_state arg remains for call-site compat.
    if drift_state == "in_sync" and source_status == "ok" and sync_state == "in_sync":
        status, sync = "ok", "in_sync"
    else:
        status, sync = _validate_axes(source_status, sync_state)
    derived = derive_drift_state(status, sync)
    message = (
        source_status_message if source_status_message is not None else catalog_message(status)
    )
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
                source_status, source_status_message, sync_state,
                checked_at, pulled_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                source_status = excluded.source_status,
                source_status_message = excluded.source_status_message,
                sync_state = excluded.sync_state,
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
                derived,
                status,
                message,
                sync,
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
    source_status: str,
    sync_state: str,
    source_status_message: str | None = None,
    drift_state: str | None = None,
    cache_sha256: str | None = None,
    source_digest: str | None = None,
    source_digest_kind: str | None = None,
    promote_anchors: bool = False,
    media_target: str | None = None,
    touch_pulled_at: bool = False,
) -> None:
    """Persist evaluate observations; optionally promote _synced anchors on in_sync.

    ``drift_state`` is derived from the axes when omitted (compat column).
    """
    status, sync = _validate_axes(source_status, sync_state)
    derived = derive_drift_state(status, sync)
    if drift_state is not None:
        legacy = (drift_state or "").strip().lower()
        if legacy not in DRIFT_STATES:
            raise ValueError(f"invalid drift_state: {drift_state}")
        # Prefer axes; ignore mismatches by keeping derived.
    message = (
        source_status_message if source_status_message is not None else catalog_message(status)
    )
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
        if promote_anchors and sync == "in_sync" and status == "ok":
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
                    source_status = ?,
                    source_status_message = ?,
                    sync_state = ?,
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
                    derived,
                    status,
                    message,
                    sync,
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
                    source_status = ?,
                    source_status_message = ?,
                    sync_state = ?,
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
                    derived,
                    status,
                    message,
                    sync,
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
    source_status: str | None = None,
    sync_state: str | None = None,
    source_status_message: str | None = None,
) -> None:
    """Lightweight axis update (orphan / non-ok without full tip compare)."""
    legacy = (drift_state or "").strip().lower()
    if source_status is None or sync_state is None:
        if legacy == "orphan":
            status, sync = "orphan", "unevaluated"
            msg = source_status_message or catalog_message("orphan")
        elif legacy == "in_sync":
            status, sync = "ok", "in_sync"
            msg = source_status_message or ""
        elif legacy == "out_of_sync":
            status, sync = "ok", "out_of_sync"
            msg = source_status_message or ""
        else:
            status, sync = "unconfirmable", "unevaluated"
            msg = source_status_message or catalog_message("unconfirmable")
    else:
        status, sync = source_status, sync_state
        msg = source_status_message
    apply_evaluate_result(
        domain,
        cache_name,
        source_status=status,
        sync_state=sync,
        source_status_message=msg,
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
    pending_msg = "Re-attached; tip not yet confirmed"
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
                source_status = 'unconfirmable',
                source_status_message = ?,
                sync_state = 'unevaluated',
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
                pending_msg,
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
    """Return copies with orphan axes when connection/binding ids are missing."""
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
            item["source_status"] = "orphan"
            item["sync_state"] = "unevaluated"
            item["source_status_message"] = orphan_reason
            item["orphan"] = True
            item["orphan_reason"] = orphan_reason
        else:
            item["orphan"] = (
                item.get("source_status") == "orphan" or item.get("drift_state") == "orphan"
            )
            if item["orphan"]:
                item["orphan_reason"] = (
                    item.get("source_status_message")
                    or item.get("orphan_reason")
                    or "Library source missing"
                )
                item["source_status"] = "orphan"
                item["sync_state"] = "unevaluated"
            else:
                item["orphan_reason"] = ""
                item.setdefault("source_status", "unconfirmable")
                item.setdefault("sync_state", "unevaluated")
                item.setdefault("source_status_message", "")
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
            enriched["source_status"] = None
            enriched["sync_state"] = None
            enriched["source_status_message"] = ""
            enriched["orphan"] = False
            enriched["orphan_reason"] = ""
        else:
            enriched["library_provenance"] = row
            enriched["drift_state"] = row["drift_state"]
            enriched["source_status"] = row.get("source_status") or "unconfirmable"
            enriched["sync_state"] = row.get("sync_state") or "unevaluated"
            enriched["source_status_message"] = row.get("source_status_message") or ""
            enriched["orphan"] = bool(row.get("orphan"))
            enriched["orphan_reason"] = row.get("orphan_reason") or ""
        out.append(enriched)
    return out
