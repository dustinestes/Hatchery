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

CREATE TABLE IF NOT EXISTS library_cache_provenance (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    domain                  TEXT    NOT NULL,
    media_target            TEXT    NOT NULL DEFAULT '',
    cache_name              TEXT    NOT NULL,
    connection_id           TEXT    NOT NULL,
    binding_id              TEXT,
    relative_path           TEXT    NOT NULL,
    source_type             TEXT    NOT NULL,
    cache_sha256            TEXT    NOT NULL DEFAULT '',
    cache_sha256_synced     TEXT    NOT NULL,
    source_digest           TEXT,
    source_digest_synced    TEXT,
    source_digest_kind      TEXT,
    drift_state             TEXT    NOT NULL DEFAULT 'unknown',
    checked_at              TEXT,
    pulled_at               TEXT    NOT NULL,
    updated_at              TEXT    NOT NULL,
    UNIQUE(domain, media_target, cache_name)
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
    _migrate_library_cache_provenance(conn)
    # Local Nest is optional (#266 / ADR-0014). Do not seed id ``local`` on migrate.


def _migrate_library_cache_provenance(conn: sqlite3.Connection) -> None:
    """Rename #308 digest columns to cache_/source_ observed + _synced anchors."""
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='library_cache_provenance'"
    ).fetchone()
    if not table:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(library_cache_provenance)").fetchall()}
    if "cache_sha256_synced" in cols and "sha256_at_pull" not in cols:
        if "cache_sha256" not in cols:
            conn.execute(
                "ALTER TABLE library_cache_provenance ADD COLUMN cache_sha256 TEXT NOT NULL DEFAULT ''"
            )
            conn.execute(
                "UPDATE library_cache_provenance SET cache_sha256 = cache_sha256_synced "
                "WHERE cache_sha256 = '' OR cache_sha256 IS NULL"
            )
        return
    if "sha256_at_pull" not in cols:
        return
    conn.execute(
        """
        CREATE TABLE library_cache_provenance__new (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            domain                  TEXT    NOT NULL,
            media_target            TEXT    NOT NULL DEFAULT '',
            cache_name              TEXT    NOT NULL,
            connection_id           TEXT    NOT NULL,
            binding_id              TEXT,
            relative_path           TEXT    NOT NULL,
            source_type             TEXT    NOT NULL,
            cache_sha256            TEXT    NOT NULL DEFAULT '',
            cache_sha256_synced     TEXT    NOT NULL,
            source_digest           TEXT,
            source_digest_synced    TEXT,
            source_digest_kind      TEXT,
            drift_state             TEXT    NOT NULL DEFAULT 'unknown',
            checked_at              TEXT,
            pulled_at               TEXT    NOT NULL,
            updated_at              TEXT    NOT NULL,
            UNIQUE(domain, media_target, cache_name)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO library_cache_provenance__new (
            id, domain, media_target, cache_name, connection_id, binding_id,
            relative_path, source_type, cache_sha256, cache_sha256_synced,
            source_digest, source_digest_synced, source_digest_kind,
            drift_state, checked_at, pulled_at, updated_at
        )
        SELECT
            id, domain, media_target, cache_name, connection_id, binding_id,
            relative_path, source_type,
            COALESCE(sha256_at_pull, ''),
            COALESCE(sha256_at_pull, ''),
            last_source_digest,
            source_digest,
            source_digest_kind,
            drift_state, checked_at, pulled_at, updated_at
        FROM library_cache_provenance
        """
    )
    conn.execute("DROP TABLE library_cache_provenance")
    conn.execute("ALTER TABLE library_cache_provenance__new RENAME TO library_cache_provenance")


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


def is_initialized() -> bool:
    """Return True after ``init_db`` has set the active database path."""
    return _db_path is not None


def get_connection() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("db not initialized - call init_db() first")
    conn = sqlite3.connect(str(_db_path))
    conn.row_factory = sqlite3.Row
    return conn
