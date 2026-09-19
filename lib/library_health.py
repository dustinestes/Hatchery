"""Library connection health — reachability / auth Alerts and token expiry (#254).

Stable prefixes feed the Libraries footer rollup via ``lib/plane_status.py``.
Opens belong to the ``library_connections`` validator; Settings → Test connection
only resolves a reachability Alert on success for a saved connection.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from lib import alerts as alerts_lib
from lib import library as library_lib
from lib import nest_key_expiry as nest_key_expiry_lib

# Messages: ``PREFIX 'label' (connection_id) …``
_CONN_ID_IN_MESSAGE = re.compile(r"'[^']*'\s*\(([^)]+)\)")

CONNECTION_ALERT_PREFIX = "Library connection:"
TOKEN_EXPIRY_ALERT_PREFIX = "Library connection token expiry:"

LIBRARY_SCOPED_ALERT_PREFIXES = (
    CONNECTION_ALERT_PREFIX,
    TOKEN_EXPIRY_ALERT_PREFIX,
)


def connection_alert_message(conn: dict, detail: str) -> str:
    label = conn.get("label") or conn.get("id") or "?"
    cid = conn.get("id") or "?"
    return f"{CONNECTION_ALERT_PREFIX} '{label}' ({cid}) — {detail}"


def token_expiry_alert_message(conn: dict, expires: date, days_left: int) -> str:
    label = conn.get("label") or conn.get("id") or "?"
    cid = conn.get("id") or "?"
    date_s = expires.isoformat()
    if days_left < 0:
        return f"{TOKEN_EXPIRY_ALERT_PREFIX} '{label}' ({cid}) expired on {date_s}"
    return f"{TOKEN_EXPIRY_ALERT_PREFIX} '{label}' ({cid}) expires in {days_left} day(s) ({date_s})"


def resolve_alerts_for_connection_id(connection_id: str) -> None:
    """Resolve Library-scoped Alerts that embed ``(connection_id)``."""
    cid = str(connection_id or "").strip()
    if not cid:
        return
    for prefix in LIBRARY_SCOPED_ALERT_PREFIXES:
        alerts_lib.resolve_alerts_for_prefix_and_nest_id(prefix, cid)


def resolve_connection_alert(connection_id: str) -> None:
    """Resolve only reachability/auth Alerts for ``connection_id``."""
    cid = str(connection_id or "").strip()
    if not cid:
        return
    alerts_lib.resolve_alerts_for_prefix_and_nest_id(CONNECTION_ALERT_PREFIX, cid)


def resolve_all_library_alerts() -> None:
    """Resolve every active Library-scoped Alert (e.g. Library feature disabled)."""
    for prefix in LIBRARY_SCOPED_ALERT_PREFIXES:
        alerts_lib.resolve_alerts_by_prefix(prefix)


def prune_alerts_for_removed_connections(current_ids: set[str] | list[str]) -> None:
    """Resolve Library Alerts whose embedded connection id is no longer registered."""
    keep = {str(i).strip() for i in current_ids if str(i).strip()}
    active = alerts_lib.list_recent(500)
    seen: set[str] = set()
    for row in active:
        if row.get("resolved"):
            continue
        msg = str(row.get("message") or "")
        if not any(msg.startswith(p) for p in LIBRARY_SCOPED_ALERT_PREFIXES):
            continue
        cid = _connection_id_from_message(msg)
        if cid and cid not in keep and cid not in seen:
            seen.add(cid)
            resolve_alerts_for_connection_id(cid)


def _connection_id_from_message(message: str) -> str | None:
    """Extract connection id from a Library alert message."""
    match = _CONN_ID_IN_MESSAGE.search(message)
    if not match:
        return None
    return match.group(1).strip() or None


def sync_connection_alerts(
    connections: list[dict],
    *,
    note_finding=None,
) -> dict[str, int]:
    """Probe connections via ``library.test_connection``; open/resolve Alerts.

    Git connections are skipped (test/list/pull not implemented yet — #251).
    Returns ``{checked, down, skipped_git}``.
    """
    checked = 0
    down = 0
    skipped_git = 0
    for conn in connections:
        ctype = (conn.get("type") or "").strip().lower()
        if ctype == "git":
            skipped_git += 1
            # Do not leave stale reachability Alerts if type flipped to git.
            resolve_connection_alert(str(conn.get("id") or ""))
            continue
        checked += 1
        result = library_lib.test_connection(conn)
        cid = str(conn.get("id") or "")
        if result.get("ok"):
            resolve_connection_alert(cid)
            continue
        down += 1
        detail = str(result.get("message") or "unreachable")
        msg = connection_alert_message(conn, detail)
        if alerts_lib.has_active_alert(msg):
            if note_finding:
                note_finding("alert")
            continue
        resolve_connection_alert(cid)
        alerts_lib.record_alert(msg, tier="alert")
        if note_finding:
            note_finding("alert")
    return {"checked": checked, "down": down, "skipped_git": skipped_git}


def sync_token_expiry_alerts(
    connections: list[dict],
    tiers: list[nest_key_expiry_lib.NestKeyAlertTier] | None = None,
    *,
    now: datetime | None = None,
    note_finding=None,
) -> list[str]:
    """Alert when a connection's ``expires_at`` is inside a warning window or past due.

    Empty ``expires_at`` → no token-expiry Alert for that connection. Uses the same
    default day windows as Nest SSH identity expiry (30 / 7) unless ``tiers`` given.
    Returns messages that were newly recorded.
    """
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(timezone.utc).date()
    tiers = tiers or list(nest_key_expiry_lib.DEFAULT_ALERT_TIERS)
    recorded: list[str] = []

    for conn in connections:
        cid = str(conn.get("id") or "").strip()
        if not cid:
            continue
        expires_raw = conn.get("expires_at")
        if not expires_raw:
            alerts_lib.resolve_alerts_for_prefix_and_nest_id(TOKEN_EXPIRY_ALERT_PREFIX, cid)
            continue
        try:
            expires = date.fromisoformat(str(expires_raw)[:10])
        except ValueError:
            alerts_lib.resolve_alerts_for_prefix_and_nest_id(TOKEN_EXPIRY_ALERT_PREFIX, cid)
            continue

        days_left = (expires - today).days
        tier = nest_key_expiry_lib.matching_tier(days_left, tiers)
        if tier is None:
            alerts_lib.resolve_alerts_for_prefix_and_nest_id(TOKEN_EXPIRY_ALERT_PREFIX, cid)
            continue

        msg = token_expiry_alert_message(conn, expires, days_left)
        if not _should_fire_token_alert(cid, tier.alerts_per_day, now=now):
            continue
        if alerts_lib.has_active_alert(msg):
            if note_finding:
                note_finding("warning" if days_left >= 0 else "alert")
            continue
        alerts_lib.resolve_alerts_for_prefix_and_nest_id(TOKEN_EXPIRY_ALERT_PREFIX, cid)
        alerts_lib.record_alert(msg, tier="warning" if days_left >= 0 else "alert")
        recorded.append(msg)
        if note_finding:
            note_finding("warning" if days_left >= 0 else "alert")
    return recorded


def _should_fire_token_alert(connection_id: str, alerts_per_day: int, *, now: datetime) -> bool:
    since = (now - timedelta(hours=24)).isoformat()
    pattern = f"{TOKEN_EXPIRY_ALERT_PREFIX} %({connection_id})%"
    count = alerts_lib.count_alerts_since(pattern, since, like=True)
    return count < alerts_per_day


def apply_manual_test_result(conn: dict, result: dict[str, Any], *, registered: bool) -> None:
    """Side effects for Settings → Test connection (resolve only on success)."""
    if not registered:
        return
    cid = str(conn.get("id") or "").strip()
    if not cid:
        return
    if result.get("ok"):
        resolve_connection_alert(cid)
