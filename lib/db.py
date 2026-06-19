from __future__ import annotations

import sqlite3
from pathlib import Path

_MAX_ALERTS = 500
_MAX_ACTIVITY = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    resolved    INTEGER NOT NULL DEFAULT 0,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS activity (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT    NOT NULL,
    message    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS clutch_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT
);

CREATE TABLE IF NOT EXISTS hatch_sessions (
    id           TEXT PRIMARY KEY,
    nest         TEXT NOT NULL DEFAULT 'local',
    clutch_file  TEXT NOT NULL,
    clutch_name  TEXT NOT NULL,
    hatched_at   TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS hatch_vm_status (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES hatch_sessions(id),
    vm_name    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    fledged_at TEXT,
    error      TEXT,
    UNIQUE(session_id, vm_name)
);
"""

_MIGRATIONS: list[str] = []

_db_path: Path | None = None


def init_db(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA)
        for migration in _MIGRATIONS:  # pragma: no cover
            try:
                conn.execute(migration)
                conn.commit()
            except sqlite3.OperationalError:
                pass
    finally:
        conn.close()


def get_connection() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("db not initialized — call init_db() first")
    conn = sqlite3.connect(str(_db_path))
    conn.row_factory = sqlite3.Row
    return conn


def trim_alerts(conn: sqlite3.Connection) -> None:
    conn.execute(
        "DELETE FROM alerts WHERE id NOT IN (SELECT id FROM alerts ORDER BY id DESC LIMIT ?)",
        (_MAX_ALERTS,),
    )


def trim_activity(conn: sqlite3.Connection) -> None:
    conn.execute(
        "DELETE FROM activity WHERE id NOT IN (SELECT id FROM activity ORDER BY id DESC LIMIT ?)",
        (_MAX_ACTIVITY,),
    )
