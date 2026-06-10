from __future__ import annotations

from datetime import datetime, timezone

from lib import db

_TIERS = {"warning", "activity"}


def record(tier: str, message: str) -> int:
    """Insert a notification, trim the table to the cap, and return the new row id."""
    if tier not in _TIERS:
        raise ValueError(f"tier must be one of {sorted(_TIERS)}, got {tier!r}")
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO notifications (created_at, tier, message) VALUES (?, ?, ?)",
            (now, tier, message),
        )
        row_id = cursor.lastrowid
        db.trim_notifications(conn)
        conn.commit()
        return row_id
    finally:
        conn.close()


def list_recent(n: int = 50) -> list[dict]:
    """Return the n most recent notifications, newest first."""
    conn = db.get_connection()
    try:
        rows = conn.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def resolve(notification_id: int) -> None:
    """Mark a warning notification as resolved."""
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE notifications SET resolved = 1, resolved_at = ? WHERE id = ?",
            (now, notification_id),
        )
        conn.commit()
    finally:
        conn.close()


def dismiss(notification_id: int) -> None:
    """Mark a notification as dismissed by the user."""
    conn = db.get_connection()
    try:
        conn.execute("UPDATE notifications SET dismissed = 1 WHERE id = ?", (notification_id,))
        conn.commit()
    finally:
        conn.close()


def resolve_by_message_prefix(prefix: str) -> None:
    """Resolve all unresolved warnings whose message starts with the given prefix."""
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE notifications SET resolved = 1, resolved_at = ? "
            "WHERE tier = 'warning' AND resolved = 0 AND message LIKE ?",
            (now, f"{prefix}%"),
        )
        conn.commit()
    finally:
        conn.close()


def has_active_warning(message: str) -> bool:
    """Return True if an unresolved warning with this exact message already exists."""
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM notifications WHERE tier = 'warning' AND resolved = 0 AND message = ? LIMIT 1",
            (message,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def count_unresolved_warnings() -> int:
    """Return the count of unresolved warning notifications."""
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE tier = 'warning' AND resolved = 0"
        ).fetchone()[0]
    finally:
        conn.close()
