"""Environment and validation alerts — conditions that need operator attention."""

from __future__ import annotations

from datetime import datetime, timezone

from lib import db

_VALID_TIERS = frozenset({"info", "warning", "alert"})


def normalize_tier(tier: str | None) -> str:
    """Return a toast-aligned alert tier: info | warning | alert."""
    raw = (tier or "alert").strip().lower()
    if raw == "error":
        return "alert"
    if raw in _VALID_TIERS:
        return raw
    return "alert"


def record_alert(message: str, tier: str = "alert") -> int:
    """Insert an alert and return the new row id.

    ``tier`` uses the same vocabulary as ``hatchery.showToast``:
    ``info``, ``warning``, or ``alert`` (alias ``error`` → ``alert``).
    Default ``alert`` preserves the historical health-condition posture.
    """
    now = datetime.now(timezone.utc).isoformat()
    normalized = normalize_tier(tier)
    conn = db.get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO alerts (created_at, message, tier) VALUES (?, ?, ?)",
            (now, message, normalized),
        )
        row_id = cursor.lastrowid
        conn.commit()
        return row_id
    finally:
        conn.close()


def list_recent(n: int = 50) -> list[dict]:
    """Return the n most recent alerts, newest first.

    Each dict includes ``tier`` for toast, tray, and Alerts pane styling.
    """
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, created_at, COALESCE(tier, 'alert') AS tier,
                   message, resolved, resolved_at
            FROM alerts
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (n,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def resolve(alert_id: int) -> None:
    """Mark an alert as resolved."""
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE alerts SET resolved = 1, resolved_at = ? WHERE id = ?",
            (now, alert_id),
        )
        conn.commit()
    finally:
        conn.close()


def resolve_alerts_by_prefix(prefix: str) -> None:
    """Resolve all active alerts whose message starts with the given prefix."""
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE alerts SET resolved = 1, resolved_at = ? WHERE resolved = 0 AND message LIKE ?",
            (now, f"{prefix}%"),
        )
        conn.commit()
    finally:
        conn.close()


# Nest-scoped findings embed a stable ``(nest_id)`` token in the message.
NEST_SCOPED_ALERT_PREFIXES = (
    "Nest reachability:",
    "Nest capability:",
    "Nest SSH identity expiry:",
)

CONTROLLER_ALERT_PREFIXES = (
    "Controller requirement:",
    "Invalid Clutch file:",
)


def resolve_alerts_for_nest_id(nest_id: str) -> None:
    """Resolve active Nest-scoped alerts that reference ``(nest_id)``.

    Keeps rows for history (sets ``resolved`` / ``resolved_at``); clears bell/tray.
    """
    nid = str(nest_id or "").strip()
    if not nid:
        return
    now = datetime.now(timezone.utc).isoformat()
    id_token = f"%({nid})%"
    conn = db.get_connection()
    try:
        for prefix in NEST_SCOPED_ALERT_PREFIXES:
            conn.execute(
                """
                UPDATE alerts SET resolved = 1, resolved_at = ?
                WHERE resolved = 0 AND message LIKE ? AND message LIKE ?
                """,
                (now, f"{prefix}%", id_token),
            )
        conn.commit()
    finally:
        conn.close()


def count_active_by_prefixes(
    prefixes: tuple[str, ...] | list[str],
    *,
    exclude_tiers: tuple[str, ...] | list[str] = (),
) -> int:
    """Count unresolved alerts whose message starts with any of ``prefixes``.

    ``exclude_tiers`` drops matching tiers (e.g. ``info`` import noise) from the count.
    """
    if not prefixes:
        return 0
    excluded = {normalize_tier(t) for t in exclude_tiers}
    conn = db.get_connection()
    try:
        total = 0
        for prefix in prefixes:
            rows = conn.execute(
                """
                SELECT COALESCE(tier, 'alert') AS tier
                FROM alerts
                WHERE resolved = 0 AND message LIKE ?
                """,
                (f"{prefix}%",),
            ).fetchall()
            for row in rows:
                if normalize_tier(row["tier"]) in excluded:
                    continue
                total += 1
        return total
    finally:
        conn.close()


def has_active_alert(message: str) -> bool:
    """Return True if an unresolved alert with this exact message already exists."""
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM alerts WHERE resolved = 0 AND message = ? LIMIT 1",
            (message,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def count_alerts_since(pattern: str, since_iso: str, *, like: bool = False) -> int:
    """Count alerts created at or after ``since_iso`` matching ``pattern``.

    When ``like`` is True, ``pattern`` is a SQL LIKE pattern (use ``%`` wildcards).
    Otherwise equality is used.
    """
    conn = db.get_connection()
    try:
        if like:
            row = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE created_at >= ? AND message LIKE ?",
                (since_iso, pattern),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE created_at >= ? AND message = ?",
                (since_iso, pattern),
            ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def count_active_alerts() -> int:
    """Return the count of unresolved alerts."""
    conn = db.get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM alerts WHERE resolved = 0").fetchone()[0]
    finally:
        conn.close()
