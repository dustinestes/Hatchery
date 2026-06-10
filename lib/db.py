from __future__ import annotations

import sqlite3
from pathlib import Path

_MAX_NOTIFICATIONS = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    tier        TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    resolved    INTEGER NOT NULL DEFAULT 0,
    resolved_at TEXT,
    dismissed   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS clutch_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT
);
"""

# Applied after schema creation so existing databases gain new columns without
# data loss. Each statement is attempted once; OperationalError means the column
# already exists and is silently skipped.
_MIGRATIONS = [
    "ALTER TABLE notifications ADD COLUMN resolved_at TEXT",
]

_db_path: Path | None = None


def init_db(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA)
        for migration in _MIGRATIONS:
            try:
                conn.execute(migration)
                conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists
    finally:
        conn.close()


def get_connection() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("db not initialized — call init_db() first")
    conn = sqlite3.connect(str(_db_path))
    conn.row_factory = sqlite3.Row
    return conn


def trim_notifications(conn: sqlite3.Connection) -> None:
    conn.execute(
        "DELETE FROM notifications WHERE id NOT IN "
        "(SELECT id FROM notifications ORDER BY id DESC LIMIT ?)",
        (_MAX_NOTIFICATIONS,),
    )
