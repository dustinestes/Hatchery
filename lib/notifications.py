from __future__ import annotations

from datetime import datetime, timezone

from lib import db


def record_alert(message: str) -> int:
    """Insert a health alert and return the new row id."""
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO alerts (created_at, message) VALUES (?, ?)",
            (now, message),
        )
        row_id = cursor.lastrowid
        db.trim_alerts(conn)
        conn.commit()
        return row_id
    finally:
        conn.close()


def record_activity(message: str) -> int:
    """Insert an activity entry and return the new row id."""
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO activity (created_at, message) VALUES (?, ?)",
            (now, message),
        )
        row_id = cursor.lastrowid
        db.trim_activity(conn)
        conn.commit()
        return row_id
    finally:
        conn.close()


def list_recent(n: int = 50) -> list[dict]:
    """Return the n most recent entries from both tables, newest first.

    Each dict includes a synthesized 'tier' field ('alert' or 'activity') for
    template rendering and JS filtering.
    """
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, created_at, 'alert' AS tier, message, resolved, resolved_at
            FROM alerts
            UNION ALL
            SELECT id, created_at, 'activity' AS tier, message, 0 AS resolved, NULL AS resolved_at
            FROM activity
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


def count_active_alerts() -> int:
    """Return the count of unresolved alerts."""
    conn = db.get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM alerts WHERE resolved = 0").fetchone()[0]
    finally:
        conn.close()
