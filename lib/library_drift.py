"""Library operator-cache drift checks (#308) — bidirectional cache + source compare."""

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
) -> dict[str, dict[str, tuple[str, str]] | None]:
    """Build per-connection tip maps. Value None means rate-limited / failed batch."""
    by_cid: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        cid = str(row.get("connection_id") or "")
        if cid and cid in connections:
            by_cid.setdefault(cid, []).append(row)
    out: dict[str, dict[str, tuple[str, str]] | None] = {}
    for cid, _group in by_cid.items():
        conn = connections[cid]
        ctype = conn.get("type")
        if ctype in ("forge", "api"):
            try:
                out[cid] = library_lib.tip_index_for_connection(conn)
            except library_lib.LibraryRateLimitError:
                out[cid] = None
            except Exception:
                out[cid] = {}
        else:
            out[cid] = {}
    return out


def evaluate_row(
    row: dict[str, Any],
    *,
    connections: dict[str, dict],
    binding_ids: set[str],
    tip_index: dict[str, tuple[str, str]] | None = None,
    tip_index_failed: bool = False,
    single_file: bool = False,
    touch_pulled_at: bool = False,
) -> dict[str, Any]:
    """Refresh observed digests, set drift_state, optionally promote anchors.

    Returns a summary dict with drift_state and drift flags.
    """
    cid = str(row.get("connection_id") or "")
    bid = str(row.get("binding_id") or "").strip()
    domain = row["domain"]
    name = row["cache_name"]
    target = row.get("media_target") or None

    if cid not in connections:
        prov.set_drift_state(domain, name, drift_state="orphan", media_target=target)
        return {
            "drift_state": "orphan",
            "cache_drifted": False,
            "source_drifted": False,
            "live_mismatch": False,
        }
    if bid and bid not in binding_ids:
        prov.set_drift_state(domain, name, drift_state="orphan", media_target=target)
        return {
            "drift_state": "orphan",
            "cache_drifted": False,
            "source_drifted": False,
            "live_mismatch": False,
        }

    conn = connections[cid]
    if not library_lib.connection_is_enabled(conn):
        prov.set_drift_state(domain, name, drift_state="unknown", media_target=target)
        return {
            "drift_state": "unknown",
            "cache_drifted": False,
            "source_drifted": False,
            "live_mismatch": False,
        }

    cache_path = library_lib.cache_path_for(
        domain, name, media_target=target, data_dir=config.data_dir()
    )
    cache_sha = ""
    if cache_path.is_file():
        cache_sha = library_lib.sha256_file(cache_path)

    if tip_index_failed:
        prov.apply_evaluate_result(
            domain,
            name,
            drift_state="unknown",
            cache_sha256=cache_sha or None,
            media_target=target,
        )
        return {
            "drift_state": "unknown",
            "cache_drifted": False,
            "source_drifted": False,
            "live_mismatch": False,
            "cache_sha256": cache_sha,
        }

    try:
        tip = library_lib.resolve_source_digest(
            conn,
            row["relative_path"],
            tip_index=tip_index,
            single_file=single_file,
        )
    except library_lib.LibraryRateLimitError:
        prov.apply_evaluate_result(
            domain,
            name,
            drift_state="unknown",
            cache_sha256=cache_sha or None,
            media_target=target,
        )
        return {
            "drift_state": "unknown",
            "cache_drifted": False,
            "source_drifted": False,
            "live_mismatch": False,
            "cache_sha256": cache_sha,
        }

    if tip is None:
        if not cache_path.is_file():
            prov.apply_evaluate_result(
                domain,
                name,
                drift_state="out_of_sync",
                cache_sha256=cache_sha or "",
                media_target=target,
            )
            return {
                "drift_state": "out_of_sync",
                "cache_drifted": True,
                "source_drifted": False,
                "live_mismatch": False,
                "cache_sha256": cache_sha,
            }
        prov.apply_evaluate_result(
            domain,
            name,
            drift_state="unknown",
            cache_sha256=cache_sha or None,
            media_target=target,
        )
        return {
            "drift_state": "unknown",
            "cache_drifted": False,
            "source_drifted": False,
            "live_mismatch": False,
            "cache_sha256": cache_sha,
        }

    kind, digest = tip
    kind_n = (kind or "").strip().lower()
    synced_kind = (row.get("source_digest_kind") or "").strip().lower()
    if synced_kind and kind_n and kind_n != synced_kind:
        prov.apply_evaluate_result(
            domain,
            name,
            drift_state="unknown",
            cache_sha256=cache_sha or None,
            source_digest=digest,
            source_digest_kind=kind_n,
            media_target=target,
        )
        return {
            "drift_state": "unknown",
            "cache_drifted": False,
            "source_drifted": False,
            "live_mismatch": False,
            "cache_sha256": cache_sha,
            "source_digest": digest,
        }

    if not cache_path.is_file():
        prov.apply_evaluate_result(
            domain,
            name,
            drift_state="out_of_sync",
            cache_sha256="",
            source_digest=digest,
            source_digest_kind=kind_n,
            media_target=target,
        )
        return {
            "drift_state": "out_of_sync",
            "cache_drifted": True,
            "source_drifted": False,
            "live_mismatch": False,
            "cache_sha256": "",
            "source_digest": digest,
        }

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
        # Sync just overwrote bytes (tip verified when content-addressable). Promote
        # anchors when live tip matches; path size_mtime has no live content↔tip check.
        if kind_n in ("sha256", "git_blob") and live_mismatch:
            state = "out_of_sync"
        else:
            state = "in_sync"
            cache_drifted = False
            source_drifted = False
            live_mismatch = False
    else:
        state = "out_of_sync" if (cache_drifted or source_drifted or live_mismatch) else "in_sync"

    prov.apply_evaluate_result(
        domain,
        name,
        drift_state=state,
        cache_sha256=cache_sha,
        source_digest=digest,
        source_digest_kind=kind_n,
        promote_anchors=(state == "in_sync"),
        media_target=target,
        touch_pulled_at=touch_pulled_at and state == "in_sync",
    )
    return {
        "drift_state": state,
        "cache_drifted": cache_drifted,
        "source_drifted": source_drifted,
        "live_mismatch": live_mismatch,
        "cache_sha256": cache_sha,
        "source_digest": digest,
        "source_digest_kind": kind_n,
    }


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
            if row.get("drift_state") == "out_of_sync":
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

    counts = {
        "checked": 0,
        "in_sync": 0,
        "out_of_sync": 0,
        "unknown": 0,
        "orphan": 0,
        "synced": 0,
        "rate_limited": 0,
        "by_domain": {d: 0 for d in _DOMAIN_LABELS},
    }

    rows = prov.list_all()
    tip_maps = _tip_indexes_by_connection(rows, connections)
    out_of_sync_rows: list[dict[str, Any]] = []

    for row in rows:
        counts["checked"] += 1
        cid = str(row.get("connection_id") or "")
        tip_map = tip_maps.get(cid, {})
        tip_failed = tip_map is None
        if tip_failed:
            counts["rate_limited"] += 1
        summary = evaluate_row(
            row,
            connections=connections,
            binding_ids=binding_ids,
            tip_index=tip_map if isinstance(tip_map, dict) else None,
            tip_index_failed=tip_failed,
        )
        state = summary["drift_state"]
        counts[state] = counts.get(state, 0) + 1
        if state == "out_of_sync":
            out_of_sync_rows.append(row)
            counts["by_domain"][row["domain"]] = counts["by_domain"].get(row["domain"], 0) + 1

    if auto_sync:
        for row in out_of_sync_rows:
            try:
                result = sync_row(row, connections)
                if result and result.get("drift_state") == "in_sync":
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
