from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    tier        TEXT    NOT NULL DEFAULT 'alert',
    resolved    INTEGER NOT NULL DEFAULT 0,
    resolved_at TEXT
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
    completed_at TEXT,
    archived_at  TEXT
);

CREATE TABLE IF NOT EXISTS hatch_vm_status (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT NOT NULL REFERENCES hatch_sessions(id),
    vm_name        TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    libvirt_uuid   TEXT,
    started_at     TEXT,
    fledged_at     TEXT,
    admin_username TEXT,
    admin_password TEXT,
    error          TEXT,
    UNIQUE(session_id, vm_name)
);

CREATE TABLE IF NOT EXISTS hatch_vm_scripts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT    NOT NULL REFERENCES hatch_sessions(id),
    vm_name      TEXT    NOT NULL,
    script_name  TEXT    NOT NULL,
    run_order    INTEGER NOT NULL,
    reboot_after INTEGER NOT NULL DEFAULT 0,
    status       TEXT    NOT NULL DEFAULT 'pending',
    exit_code    INTEGER,
    output       TEXT,
    parameters   TEXT,
    started_at   TEXT,
    completed_at TEXT,
    UNIQUE(session_id, vm_name, run_order)
);

CREATE TABLE IF NOT EXISTS hatch_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL REFERENCES hatch_sessions(id),
    vm_name     TEXT    NOT NULL,
    context     TEXT    NOT NULL,
    level       TEXT    NOT NULL,
    script_name TEXT,
    component   TEXT,
    message     TEXT    NOT NULL,
    received_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nests (
    id                    TEXT PRIMARY KEY,
    name                  TEXT NOT NULL,
    provider_type         TEXT NOT NULL,
    location              TEXT NOT NULL DEFAULT 'local',
    transport             TEXT,
    host                  TEXT,
    port                  INTEGER,
    ssh_user              TEXT,
    identity_file         TEXT,
    cert_path             TEXT,
    identity_expires_at   TEXT,
    known_hosts           TEXT,
    winrm_user            TEXT,
    credential_ref        TEXT,
    extra_json            TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS validator_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    validator_id    TEXT    NOT NULL,
    started_at      TEXT    NOT NULL,
    finished_at     TEXT,
    status          TEXT    NOT NULL,
    tier            TEXT    NOT NULL DEFAULT 'info',
    trigger         TEXT    NOT NULL,
    message         TEXT    NOT NULL,
    detail          TEXT,
    nest_id         TEXT,
    findings_count  INTEGER NOT NULL DEFAULT 0
);
"""

_db_path: Path | None = None


def init_db(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply additive column changes for existing local DBs (no version table yet)."""
    alert_cols = {r[1] for r in conn.execute("PRAGMA table_info(alerts)").fetchall()}
    if "tier" not in alert_cols:
        conn.execute("ALTER TABLE alerts ADD COLUMN tier TEXT NOT NULL DEFAULT 'alert'")
    _migrate_nests_columns(conn)
    _seed_local_nest(conn)


def _migrate_nests_columns(conn: sqlite3.Connection) -> None:
    """Add Nest SSH identity columns; copy legacy ``identity_ref`` paths when present."""
    nest_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nests'"
    ).fetchone()
    if not nest_table:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(nests)").fetchall()}
    if "identity_file" not in cols:
        conn.execute("ALTER TABLE nests ADD COLUMN identity_file TEXT")
    if "cert_path" not in cols:
        conn.execute("ALTER TABLE nests ADD COLUMN cert_path TEXT")
    if "identity_expires_at" not in cols:
        conn.execute("ALTER TABLE nests ADD COLUMN identity_expires_at TEXT")
    # Pre-colocation drafts used identity_ref (path or Security id). Prefer path-like values.
    if "identity_ref" in cols:
        conn.execute(
            """
            UPDATE nests
            SET identity_file = identity_ref
            WHERE (identity_file IS NULL OR identity_file = '')
              AND identity_ref IS NOT NULL
              AND identity_ref != ''
              AND (
                identity_ref LIKE '/%'
                OR identity_ref LIKE '~%'
                OR identity_ref LIKE '.%'
              )
            """
        )


def _seed_local_nest(conn: sqlite3.Connection) -> None:
    """Ensure the built-in local libvirt Nest exists (id ``local``)."""
    from datetime import datetime, timezone

    row = conn.execute("SELECT id FROM nests WHERE id = 'local'").fetchone()
    if row:
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """
        INSERT INTO nests (
            id, name, provider_type, location, transport,
            host, port, ssh_user, identity_file, cert_path, identity_expires_at,
            known_hosts, winrm_user, credential_ref, extra_json, created_at, updated_at
        ) VALUES ('local', 'Local', 'libvirt', 'local', NULL,
                  NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?)
        """,
        (now, now),
    )


def is_initialized() -> bool:
    """Return True after ``init_db`` has set the active database path."""
    return _db_path is not None


def get_connection() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("db not initialized — call init_db() first")
    conn = sqlite3.connect(str(_db_path))
    conn.row_factory = sqlite3.Row
    return conn
