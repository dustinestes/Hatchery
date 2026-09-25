"""Library operator-cache drift checks (#308 / #382) — source_status + sync_state."""

from __future__ import annotations

from typing import Any

from lib import config
from lib import library as library_lib
from lib import library_provenance as prov

DRIFT_ALERT_PREFIX = "Library cache drift:"
_DOMAIN_LABELS = {
    "scripts": "Scripts",
    "clutches": "Clutches",
    "media": "Media",
}


def connection_and_binding_ids() -> tuple[set[str], set[str]]:
    raw = config.library_connections()
    try:
        connections = library_lib.parse_connections(raw, enforce_expiry_future=False)
    except ValueError:
        connections = []
    cids = {c["id"] for c in connections}
    bids: set[str] = set()
    for parse_fn, getter in (
        (library_lib.parse_script_bindings, config.library_script_bindings),
        (library_lib.parse_clutch_bindings, config.library_clutch_bindings),
        (library_lib.parse_media_bindings, config.library_media_bindings),
    ):
        try:
            bindings = parse_fn(getter() or [], connections)
        except ValueError:
            continue
        for b in bindings:
            bids.add(b["id"])
    return cids, bids


def connection_by_id() -> dict[str, dict]:
    try:
        connections = library_lib.parse_connections(
            config.library_connections(), enforce_expiry_future=False
        )
    except ValueError:
        return {}
    return {c["id"]: c for c in connections}


def _tip_indexes_by_connection(
    rows: list[dict[str, Any]],
    connections: dict[str, dict],
) -> dict[str, dict[str, Any]]:
    """Build per-connection tip batch outcomes.

    Each value: ``{index, complete, failure, detail}`` where ``failure`` is
    ``None``, ``rate_limited``, or ``unreachable``.
    """
    by_cid: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        cid = str(row.get("connection_id") or "")
        if cid and cid in connections:
            by_cid.setdefault(cid, []).append(row)
    out: dict[str, dict[str, Any]] = {}
    for cid, _group in by_cid.items():
        conn = connections[cid]
        ctype = conn.get("type")
        if ctype in ("forge", "api"):
            try:
                index = library_lib.tip_index_for_connection(conn)
                out[cid] = {
                    "index": index,
                    "complete": True,
                    "failure": None,
                    "detail": "",
                }
            except library_lib.LibraryRateLimitError:
                out[cid] = {
                    "index": None,
                    "complete": False,
                    "failure": "rate_limited",
                    "detail": "",
                }
            except Exception as exc:
                out[cid] = {
                    "index": None,
                    "complete": False,
                    "failure": "unreachable",
                    "detail": str(exc)[:240],
                }
        else:
            out[cid] = {
                "index": {},
                "complete": False,
                "failure": None,
                "detail": "",
            }
    return out


def _persist_axes(
    domain: str,
    name: str,
    *,
    target: str | None,
    source_status: str,
    sync_state: str,
    message: str | None = None,
    detail: str = "",
    cache_sha256: str | None = None,
    source_digest: str | None = None,
    source_digest_kind: str | None = None,
    promote_anchors: bool = False,
    touch_pulled_at: bool = False,
) -> dict[str, Any]:
    msg = message if message is not None else prov.catalog_message(source_status, detail)
    prov.apply_evaluate_result(
        domain,
        name,
        source_status=source_status,
        sync_state=sync_state,
        source_status_message=msg,
        cache_sha256=cache_sha256,
        source_digest=source_digest,
        source_digest_kind=source_digest_kind,
        promote_anchors=promote_anchors,
        media_target=target,
        touch_pulled_at=touch_pulled_at,
    )
    return {
        "source_status": source_status,
        "sync_state": sync_state,
        "source_status_message": msg,
        "drift_state": prov.derive_drift_state(source_status, sync_state),
        "cache_drifted": False,
        "source_drifted": False,
        "live_mismatch": False,
    }


def evaluate_row(
    row: dict[str, Any],
    *,
    connections: dict[str, dict],
    binding_ids: set[str],
    tip_index: dict[str, tuple[str, str]] | None = None,
    tip_index_failed: bool = False,
    tip_index_complete: bool = False,
    tip_failure: str | None = None,
    tip_failure_detail: str = "",
    single_file: bool = False,
    touch_pulled_at: bool = False,
) -> dict[str, Any]:
    """Refresh observed digests; set source_status + sync_state in one tip pass.

    Returns a summary dict with axes, derived drift_state, and drift flags.
    """
    cid = str(row.get("connection_id") or "")
    bid = str(row.get("binding_id") or "").strip()
    domain = row["domain"]
    name = row["cache_name"]
    target = row.get("media_target") or None

    if cid not in connections:
        summary = _persist_axes(
            domain,
            name,
            target=target,
            source_status="orphan",
            sync_state="unevaluated",
            message="Library connection missing",
        )
        return summary
    if bid and bid not in binding_ids:
        summary = _persist_axes(
            domain,
            name,
            target=target,
            source_status="orphan",
            sync_state="unevaluated",
            message="Library binding missing",
        )
        return summary

    conn = connections[cid]
    if not library_lib.connection_is_enabled(conn):
        return _persist_axes(
            domain,
            name,
            target=target,
            source_status="disabled",
            sync_state="unevaluated",
        )

    cache_path = library_lib.cache_path_for(
        domain, name, media_target=target, data_dir=config.data_dir()
    )
    cache_sha = ""
    if cache_path.is_file():
        cache_sha = library_lib.sha256_file(cache_path)

    failure = tip_failure
    if tip_index_failed and not failure:
        failure = "rate_limited"
    if failure == "rate_limited":
        summary = _persist_axes(
            domain,
            name,
            target=target,
            source_status="rate_limited",
            sync_state="unevaluated",
            cache_sha256=cache_sha or None,
        )
        summary["cache_sha256"] = cache_sha
        return summary
    if failure == "unreachable":
        summary = _persist_axes(
            domain,
            name,
            target=target,
            source_status="unreachable",
            sync_state="unevaluated",
            detail=tip_failure_detail,
            cache_sha256=cache_sha or None,
        )
        summary["cache_sha256"] = cache_sha
        return summary

    try:
        tip_result = library_lib.resolve_source_tip(
            conn,
            row["relative_path"],
            tip_index=tip_index,
            single_file=single_file,
            tip_index_complete=tip_index_complete,
        )
    except library_lib.LibraryRateLimitError:
        summary = _persist_axes(
            domain,
            name,
            target=target,
            source_status="rate_limited",
            sync_state="unevaluated",
            cache_sha256=cache_sha or None,
        )
        summary["cache_sha256"] = cache_sha
        return summary

    if tip_result.status != "ok":
        # Tip absent / unconfirmable / unreachable while cache may still exist.
        if tip_result.status == "missing" and not cache_path.is_file():
            # No tip and no cache: treat as out of sync once tip is ok elsewhere;
            # here tip is missing so axes stay non-ok.
            summary = _persist_axes(
                domain,
                name,
                target=target,
                source_status="missing",
                sync_state="unevaluated",
                detail=tip_result.detail,
                cache_sha256=cache_sha or "",
            )
            summary["cache_sha256"] = cache_sha
            summary["cache_drifted"] = True
            return summary
        summary = _persist_axes(
            domain,
            name,
            target=target,
            source_status=tip_result.status,
            sync_state="unevaluated",
            detail=tip_result.detail,
            cache_sha256=cache_sha or None,
        )
        summary["cache_sha256"] = cache_sha
        return summary

    assert tip_result.tip is not None
    kind, digest = tip_result.tip
    kind_n = (kind or "").strip().lower()
    synced_kind = (row.get("source_digest_kind") or "").strip().lower()
    if synced_kind and kind_n and kind_n != synced_kind:
        summary = _persist_axes(
            domain,
            name,
            target=target,
            source_status="unconfirmable",
            sync_state="unevaluated",
            message="Source tip kind changed; cannot compare digests",
            cache_sha256=cache_sha or None,
            source_digest=digest,
            source_digest_kind=kind_n,
        )
        summary["cache_sha256"] = cache_sha
        summary["source_digest"] = digest
        return summary

    if not cache_path.is_file():
        summary = _persist_axes(
            domain,
            name,
            target=target,
            source_status="ok",
            sync_state="out_of_sync",
            cache_sha256="",
            source_digest=digest,
            source_digest_kind=kind_n,
        )
        summary["cache_drifted"] = True
        summary["cache_sha256"] = ""
        summary["source_digest"] = digest
        return summary

    cache_synced = (row.get("cache_sha256_synced") or "").strip().lower()
    source_synced = row.get("source_digest_synced")
    cache_drifted = cache_sha != cache_synced
    source_drifted = str(source_synced or "") != str(digest)

    live_mismatch = False
    if kind_n in ("sha256", "git_blob"):
        identity = library_lib.content_identity_for_kind(cache_path, kind_n)
        if identity is None or identity != str(digest).strip().lower():
            live_mismatch = True

    if touch_pulled_at:
        if kind_n in ("sha256", "git_blob") and live_mismatch:
            sync = "out_of_sync"
        else:
            sync = "in_sync"
            cache_drifted = False
            source_drifted = False
            live_mismatch = False
    else:
        sync = "out_of_sync" if (cache_drifted or source_drifted or live_mismatch) else "in_sync"

    summary = _persist_axes(
        domain,
        name,
        target=target,
        source_status="ok",
        sync_state=sync,
        message="",
        cache_sha256=cache_sha,
        source_digest=digest,
        source_digest_kind=kind_n,
        promote_anchors=(sync == "in_sync"),
        touch_pulled_at=touch_pulled_at and sync == "in_sync",
    )
    summary.update(
        {
            "cache_drifted": cache_drifted,
            "source_drifted": source_drifted,
            "live_mismatch": live_mismatch,
            "cache_sha256": cache_sha,
            "source_digest": digest,
            "source_digest_kind": kind_n,
        }
    )
    return summary


def evaluate_one(
    domain: str,
    cache_name: str,
    *,
    media_target: str | None = None,
    single_file: bool = True,
    touch_pulled_at: bool = False,
) -> dict[str, Any] | None:
    """Evaluate a single provenance row (e.g. after Sync)."""
    row = prov.get_for_cache(domain, cache_name, media_target=media_target)
    if row is None:
        return None
    connections = connection_by_id()
    _, binding_ids = connection_and_binding_ids()
    return evaluate_row(
        row,
        connections=connections,
        binding_ids=binding_ids,
        single_file=single_file,
        touch_pulled_at=touch_pulled_at,
    )


def reconcile_domain_alerts(
    *,
    auto_sync: bool,
    counts_by_domain: dict[str, int] | None = None,
) -> None:
    """One Alert per domain from current out_of_sync counts (or clear all if auto_sync)."""
    from lib import alerts as alerts_lib

    if auto_sync:
        for label in _DOMAIN_LABELS.values():
            alerts_lib.resolve_alerts_by_prefix(f"{DRIFT_ALERT_PREFIX} {label}")
        return

    if counts_by_domain is None:
        counts_by_domain = {d: 0 for d in _DOMAIN_LABELS}
        for row in prov.list_all():
            if (row.get("source_status") == "ok" and row.get("sync_state") == "out_of_sync") or (
                # Compat for rows not yet re-evaluated
                row.get("source_status") in (None, "") and row.get("drift_state") == "out_of_sync"
            ):
                d = row["domain"]
                counts_by_domain[d] = counts_by_domain.get(d, 0) + 1

    for domain, label in _DOMAIN_LABELS.items():
        prefix = f"{DRIFT_ALERT_PREFIX} {label}"
        n = counts_by_domain.get(domain, 0)
        if n <= 0:
            alerts_lib.resolve_alerts_by_prefix(prefix)
            continue
        msg = f"{prefix}: {n} out of sync with Library"
        if not alerts_lib.has_active_alert(msg):
            alerts_lib.resolve_alerts_by_prefix(prefix)
            alerts_lib.record_alert(msg, tier="warning")


def sync_row(row: dict[str, Any], connections: dict[str, dict]) -> dict[str, Any] | None:
    """Overwrite cache from source, then evaluate_one. Return evaluate summary or None."""
    cid = str(row.get("connection_id") or "")
    conn = connections.get(cid)
    if not conn:
        return None
    status = (row.get("source_status") or "").strip().lower()
    sync = (row.get("sync_state") or "").strip().lower()
    if status == "ok" and sync == "out_of_sync":
        pass
    elif not status and row.get("drift_state") == "out_of_sync":
        pass
    else:
        return None
    rel = row["relative_path"]
    bid = row.get("binding_id")
    domain = row["domain"]
    name = row["cache_name"]
    target = row.get("media_target") or None
    if domain == "scripts":
        library_lib.sync_script(conn, rel, binding_id=bid)
    elif domain == "clutches":
        library_lib.sync_clutch(conn, rel, binding_id=bid)
    elif domain == "media":
        library_lib.sync_media(conn, rel, target=target or "iso", binding_id=bid)
    else:
        return None
    result = evaluate_one(domain, name, media_target=target, single_file=True, touch_pulled_at=True)
    return result


def run_drift_pass(*, auto_sync: bool) -> dict[str, Any]:
    """Evaluate all provenance rows; optionally auto-sync. Return summary counts."""
    connections = connection_by_id()
    _, binding_ids = connection_and_binding_ids()

    counts: dict[str, Any] = {
        "checked": 0,
        "in_sync": 0,
        "out_of_sync": 0,
        "unevaluated": 0,
        "unknown": 0,
        "orphan": 0,
        "synced": 0,
        "rate_limited": 0,
        "by_source_status": {s: 0 for s in sorted(prov.SOURCE_STATUSES)},
        "by_domain": {d: 0 for d in _DOMAIN_LABELS},
    }

    rows = prov.list_all()
    tip_maps = _tip_indexes_by_connection(rows, connections)
    out_of_sync_rows: list[dict[str, Any]] = []

    for row in rows:
        counts["checked"] += 1
        cid = str(row.get("connection_id") or "")
        batch = tip_maps.get(
            cid,
            {"index": {}, "complete": False, "failure": None, "detail": ""},
        )
        failure = batch.get("failure")
        if failure == "rate_limited":
            counts["rate_limited"] += 1
        summary = evaluate_row(
            row,
            connections=connections,
            binding_ids=binding_ids,
            tip_index=batch.get("index") if isinstance(batch.get("index"), dict) else None,
            tip_index_complete=bool(batch.get("complete")),
            tip_failure=failure,
            tip_failure_detail=str(batch.get("detail") or ""),
        )
        status = summary["source_status"]
        sync = summary["sync_state"]
        counts["by_source_status"][status] = counts["by_source_status"].get(status, 0) + 1
        if sync == "in_sync":
            counts["in_sync"] += 1
        elif sync == "out_of_sync":
            counts["out_of_sync"] += 1
            out_of_sync_rows.append(row)
            counts["by_domain"][row["domain"]] = counts["by_domain"].get(row["domain"], 0) + 1
        else:
            counts["unevaluated"] += 1
        # Compat counters
        derived = summary["drift_state"]
        if derived in ("unknown", "orphan"):
            counts[derived] = counts.get(derived, 0) + 1

    if auto_sync:
        for row in out_of_sync_rows:
            try:
                # Re-read axes after evaluate for sync_row gate.
                fresh = prov.get_for_cache(
                    row["domain"],
                    row["cache_name"],
                    media_target=row.get("media_target") or None,
                )
                result = sync_row(fresh or row, connections)
                if result and result.get("sync_state") == "in_sync":
                    counts["synced"] += 1
                    counts["out_of_sync"] -= 1
                    counts["in_sync"] += 1
                    domain = row["domain"]
                    counts["by_domain"][domain] = max(0, counts["by_domain"].get(domain, 0) - 1)
            except Exception:
                pass
        reconcile_domain_alerts(auto_sync=True)
        return counts

    reconcile_domain_alerts(auto_sync=False, counts_by_domain=counts["by_domain"])
    return counts
