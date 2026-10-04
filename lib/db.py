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
    id              TEXT PRIMARY KEY,
    nest            TEXT NOT NULL DEFAULT 'local',
    clutch_file     TEXT NOT NULL,
    clutch_name     TEXT NOT NULL,
    hatched_at      TEXT NOT NULL,
    completed_at    TEXT,
    archived_at     TEXT,
    clutch_snapshot TEXT
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
    guest_os       TEXT,
    UNIQUE(session_id, vm_name)
);

CREATE TABLE IF NOT EXISTS hatch_vm_scripts (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id                TEXT    NOT NULL REFERENCES hatch_sessions(id),
    vm_name                   TEXT    NOT NULL,
    script_name               TEXT    NOT NULL,
    run_order                 INTEGER NOT NULL,
    reboot_after              INTEGER NOT NULL DEFAULT 0,
    status                    TEXT    NOT NULL DEFAULT 'pending',
    exit_code                 INTEGER,
    output                    TEXT,
    parameters                TEXT,
    started_at                TEXT,
    completed_at              TEXT,
    entry_type                TEXT    NOT NULL DEFAULT 'script',
    clean_payload_on_success  INTEGER NOT NULL DEFAULT 1,
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

CREATE TABLE IF NOT EXISTS remoting_identities (
    id                    TEXT PRIMARY KEY,
    name                  TEXT NOT NULL,
    kind                  TEXT NOT NULL,
    identity_file         TEXT NOT NULL,
    pubkey                TEXT,
    cert_path             TEXT,
    identity_expires_at   TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    CHECK (kind IN ('hatchery', 'path'))
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
    source_status           TEXT    NOT NULL DEFAULT 'unconfirmable',
    source_status_message   TEXT    NOT NULL DEFAULT '',
    sync_state              TEXT    NOT NULL DEFAULT 'unevaluated',
    checked_at              TEXT,
    pulled_at               TEXT    NOT NULL,
    updated_at              TEXT    NOT NULL,
    UNIQUE(domain, media_target, cache_name)
);

CREATE TABLE IF NOT EXISTS library_connections (
    id          TEXT PRIMARY KEY,
    label       TEXT    NOT NULL,
    type        TEXT    NOT NULL,
    provider    TEXT    NOT NULL DEFAULT '',
    base_uri    TEXT    NOT NULL,
    token       TEXT    NOT NULL DEFAULT '',
    expires_at  TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    CHECK (type IN ('path', 'https', 'api', 'forge')),
    CHECK (enabled IN (0, 1))
);

CREATE TABLE IF NOT EXISTS library_connection_kinds (
    connection_id   TEXT    NOT NULL,
    kind            TEXT    NOT NULL,
    PRIMARY KEY (connection_id, kind),
    FOREIGN KEY (connection_id) REFERENCES library_connections(id) ON DELETE CASCADE,
    CHECK (kind IN ('scripts', 'clutches', 'media', 'answerfiles', 'software'))
);

CREATE TABLE IF NOT EXISTS library_bindings (
    id              TEXT PRIMARY KEY,
    connection_id   TEXT    NOT NULL,
    domain          TEXT    NOT NULL,
    media_target    TEXT    NOT NULL DEFAULT '',
    label           TEXT    NOT NULL,
    filter          TEXT    NOT NULL DEFAULT '*',
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    FOREIGN KEY (connection_id) REFERENCES library_connections(id) ON DELETE CASCADE,
    CHECK (domain IN ('scripts', 'clutches', 'media', 'answerfiles', 'software')),
    CHECK (
        (domain != 'media' AND media_target = '')
        OR (domain = 'media' AND media_target IN ('iso', 'virtio'))
    ),
    CHECK (enabled IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_library_connections_enabled
    ON library_connections(enabled);
CREATE INDEX IF NOT EXISTS idx_library_connections_type
    ON library_connections(type);
CREATE INDEX IF NOT EXISTS idx_library_connection_kinds_kind
    ON library_connection_kinds(kind);
CREATE INDEX IF NOT EXISTS idx_library_bindings_connection
    ON library_bindings(connection_id);
CREATE INDEX IF NOT EXISTS idx_library_bindings_domain
    ON library_bindings(domain, media_target);
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
    _migrate_library_cache_provenance_axes(conn)
    _migrate_library_registry(conn)
    _migrate_library_drop_git_connection_type(conn)
    _migrate_library_answerfiles_domain(conn)
    _migrate_library_software_domain(conn)
    _migrate_hatch_vm_scripts_typed(conn)
    _migrate_hatch_vm_status_guest_os(conn)
    _migrate_hatch_sessions_clutch_snapshot(conn)
    _migrate_remoting_identities(conn)
    # Local Nest is optional (#266 / ADR-0014). Do not seed id ``local`` on migrate.
    # Library connections/bindings: tables created via _SCHEMA; copy from app_settings once.
    from lib import library_registry as library_registry_lib

    library_registry_lib.migrate_from_app_settings(conn)


def _migrate_library_registry(conn: sqlite3.Connection) -> None:
    """Promote sketch ``kinds_json`` to ``library_connection_kinds``; tighten columns.

    Fresh DBs get the ADR-0017 shape from ``_SCHEMA``. Existing sketch DBs that
    still have ``kinds_json`` are rebuilt once. Junction table is always ensured.
    """
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='library_connections'"
    ).fetchone()
    if not table:
        return

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS library_connection_kinds (
            connection_id   TEXT    NOT NULL,
            kind            TEXT    NOT NULL,
            PRIMARY KEY (connection_id, kind),
            FOREIGN KEY (connection_id) REFERENCES library_connections(id) ON DELETE CASCADE,
            CHECK (kind IN ('scripts', 'clutches', 'media', 'answerfiles', 'software'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_library_connection_kinds_kind
            ON library_connection_kinds(kind)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_library_connections_enabled
            ON library_connections(enabled)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_library_connections_type
            ON library_connections(type)
        """
    )

    cols = {r[1] for r in conn.execute("PRAGMA table_info(library_connections)").fetchall()}
    if "kinds_json" not in cols:
        # Normalize nullables if an older sketch left them NULL without kinds_json.
        for col, default in (("provider", "''"), ("token", "''"), ("base_uri", "''")):
            if col in cols:
                conn.execute(
                    f"UPDATE library_connections SET {col} = {default} WHERE {col} IS NULL"
                )
        return

    import json

    # Rebuild may DROP while bindings / kinds still reference the old table.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        rows = conn.execute("SELECT * FROM library_connections").fetchall()
        col_names = [
            r[1] for r in conn.execute("PRAGMA table_info(library_connections)").fetchall()
        ]
        by_name = {name: i for i, name in enumerate(col_names)}

        for row in rows:
            cid = row[by_name["id"]]
            raw = row[by_name["kinds_json"]] if "kinds_json" in by_name else "[]"
            try:
                kinds = json.loads(raw) if raw else []
            except (TypeError, json.JSONDecodeError):
                kinds = []
            if not isinstance(kinds, list):
                kinds = []
            for kind in kinds:
                k = str(kind).strip().lower()
                if k not in ("scripts", "clutches", "media", "answerfiles", "software"):
                    continue
                conn.execute(
                    """
                    INSERT OR IGNORE INTO library_connection_kinds (connection_id, kind)
                    VALUES (?, ?)
                    """,
                    (cid, k),
                )

        conn.execute(
            """
            CREATE TABLE library_connections__new (
                id          TEXT PRIMARY KEY,
                label       TEXT    NOT NULL,
                type        TEXT    NOT NULL,
                provider    TEXT    NOT NULL DEFAULT '',
                base_uri    TEXT    NOT NULL,
                token       TEXT    NOT NULL DEFAULT '',
                expires_at  TEXT,
                enabled     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL,
                CHECK (type IN ('path', 'https', 'git', 'api', 'forge')),
                CHECK (enabled IN (0, 1))
            )
            """
        )
        conn.execute(
            """
            INSERT INTO library_connections__new (
                id, label, type, provider, base_uri, token, expires_at,
                enabled, created_at, updated_at
            )
            SELECT
                id, label, type,
                COALESCE(provider, ''),
                COALESCE(base_uri, ''),
                COALESCE(token, ''),
                expires_at, enabled, created_at, updated_at
            FROM library_connections
            """
        )
        conn.execute(
            """
            CREATE TABLE library_connection_kinds__new (
                connection_id   TEXT    NOT NULL,
                kind            TEXT    NOT NULL,
                PRIMARY KEY (connection_id, kind),
                FOREIGN KEY (connection_id) REFERENCES library_connections__new(id)
                    ON DELETE CASCADE,
                CHECK (kind IN ('scripts', 'clutches', 'media', 'answerfiles', 'software'))
            )
            """
        )
        conn.execute(
            """
            INSERT INTO library_connection_kinds__new (connection_id, kind)
            SELECT connection_id, kind FROM library_connection_kinds
            """
        )
        conn.execute("DROP TABLE library_connection_kinds")
        conn.execute("DROP TABLE library_connections")
        conn.execute("ALTER TABLE library_connections__new RENAME TO library_connections")
        conn.execute("ALTER TABLE library_connection_kinds__new RENAME TO library_connection_kinds")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_library_connection_kinds_kind
                ON library_connection_kinds(kind)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_library_connections_enabled
                ON library_connections(enabled)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_library_connections_type
                ON library_connections(type)
            """
        )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _migrate_library_drop_git_connection_type(conn: sqlite3.Connection) -> None:
    """Drop ``git`` from ``library_connections.type`` CHECK when no legacy rows remain.

    ADR-0020 / #406: leave legacy ``type: git`` rows readable until the operator
    deletes them; only tighten the CHECK after the table has none.
    """
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='library_connections'"
    ).fetchone()
    if not table:
        return
    ddl_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='library_connections'"
    ).fetchone()
    ddl = (ddl_row[0] if ddl_row else "") or ""
    if "'git'" not in ddl:
        return
    git_count = conn.execute(
        "SELECT COUNT(*) FROM library_connections WHERE type = 'git'"
    ).fetchone()[0]
    if git_count:
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute(
            """
            CREATE TABLE library_connections__nogit (
                id          TEXT PRIMARY KEY,
                label       TEXT    NOT NULL,
                type        TEXT    NOT NULL,
                provider    TEXT    NOT NULL DEFAULT '',
                base_uri    TEXT    NOT NULL,
                token       TEXT    NOT NULL DEFAULT '',
                expires_at  TEXT,
                enabled     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL,
                CHECK (type IN ('path', 'https', 'api', 'forge')),
                CHECK (enabled IN (0, 1))
            )
            """
        )
        conn.execute(
            """
            INSERT INTO library_connections__nogit (
                id, label, type, provider, base_uri, token, expires_at,
                enabled, created_at, updated_at
            )
            SELECT
                id, label, type, provider, base_uri, token, expires_at,
                enabled, created_at, updated_at
            FROM library_connections
            """
        )
        conn.execute(
            """
            CREATE TABLE library_connection_kinds__nogit (
                connection_id   TEXT    NOT NULL,
                kind            TEXT    NOT NULL,
                PRIMARY KEY (connection_id, kind),
                FOREIGN KEY (connection_id) REFERENCES library_connections__nogit(id)
                    ON DELETE CASCADE,
                CHECK (kind IN ('scripts', 'clutches', 'media', 'answerfiles', 'software'))
            )
            """
        )
        conn.execute(
            """
            INSERT INTO library_connection_kinds__nogit (connection_id, kind)
            SELECT connection_id, kind FROM library_connection_kinds
            """
        )
        # Recreate bindings FK against the rebuilt connections table when present.
        bindings = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='library_bindings'"
        ).fetchone()
        if bindings:
            conn.execute(
                """
                CREATE TABLE library_bindings__nogit (
                    id              TEXT PRIMARY KEY,
                    connection_id   TEXT    NOT NULL,
                    domain          TEXT    NOT NULL,
                    media_target    TEXT    NOT NULL DEFAULT '',
                    label           TEXT    NOT NULL,
                    filter          TEXT    NOT NULL DEFAULT '*',
                    enabled         INTEGER NOT NULL DEFAULT 1,
                    created_at      TEXT    NOT NULL,
                    updated_at      TEXT    NOT NULL,
                    FOREIGN KEY (connection_id) REFERENCES library_connections__nogit(id)
                        ON DELETE CASCADE,
                    CHECK (domain IN ('scripts', 'clutches', 'media', 'answerfiles', 'software')),
                    CHECK (
                        (domain != 'media' AND media_target = '')
                        OR (domain = 'media' AND media_target IN ('iso', 'virtio'))
                    ),
                    CHECK (enabled IN (0, 1))
                )
                """
            )
            conn.execute(
                """
                INSERT INTO library_bindings__nogit (
                    id, connection_id, domain, media_target, label, filter,
                    enabled, created_at, updated_at
                )
                SELECT
                    id, connection_id, domain, media_target, label, filter,
                    enabled, created_at, updated_at
                FROM library_bindings
                """
            )
            conn.execute("DROP TABLE library_bindings")
        conn.execute("DROP TABLE library_connection_kinds")
        conn.execute("DROP TABLE library_connections")
        conn.execute("ALTER TABLE library_connections__nogit RENAME TO library_connections")
        conn.execute(
            "ALTER TABLE library_connection_kinds__nogit RENAME TO library_connection_kinds"
        )
        if bindings:
            conn.execute("ALTER TABLE library_bindings__nogit RENAME TO library_bindings")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_library_bindings_connection
                    ON library_bindings(connection_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_library_bindings_domain
                    ON library_bindings(domain, media_target)
                """
            )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_library_connection_kinds_kind
                ON library_connection_kinds(kind)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_library_connections_enabled
                ON library_connections(enabled)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_library_connections_type
                ON library_connections(type)
            """
        )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _migrate_library_answerfiles_domain(conn: sqlite3.Connection) -> None:
    """Widen kinds/bindings CHECKs to include ``answerfiles`` (#449 / ADR-0024)."""
    kinds_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='library_connection_kinds'"
    ).fetchone()
    bindings_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='library_bindings'"
    ).fetchone()
    if not kinds_table and not bindings_table:
        return

    need_kinds = False
    need_bindings = False
    if kinds_table:
        ddl_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='library_connection_kinds'"
        ).fetchone()
        ddl = (ddl_row[0] if ddl_row else "") or ""
        if "answerfiles" not in ddl:
            need_kinds = True
    if bindings_table:
        ddl_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='library_bindings'"
        ).fetchone()
        ddl = (ddl_row[0] if ddl_row else "") or ""
        if "answerfiles" not in ddl:
            need_bindings = True
    if not need_kinds and not need_bindings:
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        if need_kinds:
            conn.execute(
                """
                CREATE TABLE library_connection_kinds__af (
                    connection_id   TEXT    NOT NULL,
                    kind            TEXT    NOT NULL,
                    PRIMARY KEY (connection_id, kind),
                    FOREIGN KEY (connection_id) REFERENCES library_connections(id)
                        ON DELETE CASCADE,
                    CHECK (kind IN ('scripts', 'clutches', 'media', 'answerfiles', 'software'))
                )
                """
            )
            conn.execute(
                """
                INSERT INTO library_connection_kinds__af (connection_id, kind)
                SELECT connection_id, kind FROM library_connection_kinds
                """
            )
            conn.execute("DROP TABLE library_connection_kinds")
            conn.execute(
                "ALTER TABLE library_connection_kinds__af RENAME TO library_connection_kinds"
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_library_connection_kinds_kind
                    ON library_connection_kinds(kind)
                """
            )
        if need_bindings:
            conn.execute(
                """
                CREATE TABLE library_bindings__af (
                    id              TEXT PRIMARY KEY,
                    connection_id   TEXT    NOT NULL,
                    domain          TEXT    NOT NULL,
                    media_target    TEXT    NOT NULL DEFAULT '',
                    label           TEXT    NOT NULL,
                    filter          TEXT    NOT NULL DEFAULT '*',
                    enabled         INTEGER NOT NULL DEFAULT 1,
                    created_at      TEXT    NOT NULL,
                    updated_at      TEXT    NOT NULL,
                    FOREIGN KEY (connection_id) REFERENCES library_connections(id)
                        ON DELETE CASCADE,
                    CHECK (domain IN ('scripts', 'clutches', 'media', 'answerfiles', 'software')),
                    CHECK (
                        (domain != 'media' AND media_target = '')
                        OR (domain = 'media' AND media_target IN ('iso', 'virtio'))
                    ),
                    CHECK (enabled IN (0, 1))
                )
                """
            )
            conn.execute(
                """
                INSERT INTO library_bindings__af (
                    id, connection_id, domain, media_target, label, filter,
                    enabled, created_at, updated_at
                )
                SELECT
                    id, connection_id, domain, media_target, label, filter,
                    enabled, created_at, updated_at
                FROM library_bindings
                """
            )
            conn.execute("DROP TABLE library_bindings")
            conn.execute("ALTER TABLE library_bindings__af RENAME TO library_bindings")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_library_bindings_connection
                    ON library_bindings(connection_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_library_bindings_domain
                    ON library_bindings(domain, media_target)
                """
            )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _migrate_library_software_domain(conn: sqlite3.Connection) -> None:
    """Migrate Library kind ``packages`` → ``software``; add bindings domain (#470 / ADR-0025)."""
    kinds_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='library_connection_kinds'"
    ).fetchone()
    bindings_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='library_bindings'"
    ).fetchone()
    if not kinds_table and not bindings_table:
        return

    need_kinds = False
    need_bindings = False
    if kinds_table:
        ddl_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='library_connection_kinds'"
        ).fetchone()
        ddl = (ddl_row[0] if ddl_row else "") or ""
        if "packages" in ddl or "software" not in ddl:
            need_kinds = True
    if bindings_table:
        ddl_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='library_bindings'"
        ).fetchone()
        ddl = (ddl_row[0] if ddl_row else "") or ""
        if "software" not in ddl:
            need_bindings = True
    if not need_kinds and not need_bindings:
        # Still remap any leftover kind rows if CHECK already allows software.
        if kinds_table:
            conn.execute(
                "UPDATE library_connection_kinds SET kind = 'software' WHERE kind = 'packages'"
            )
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        if need_kinds:
            conn.execute(
                """
                CREATE TABLE library_connection_kinds__sw (
                    connection_id   TEXT    NOT NULL,
                    kind            TEXT    NOT NULL,
                    PRIMARY KEY (connection_id, kind),
                    FOREIGN KEY (connection_id) REFERENCES library_connections(id)
                        ON DELETE CASCADE,
                    CHECK (kind IN ('scripts', 'clutches', 'media', 'answerfiles', 'software'))
                )
                """
            )
            conn.execute(
                """
                INSERT INTO library_connection_kinds__sw (connection_id, kind)
                SELECT connection_id,
                       CASE WHEN kind = 'packages' THEN 'software' ELSE kind END
                FROM library_connection_kinds
                WHERE kind IN ('scripts', 'clutches', 'media', 'answerfiles', 'packages', 'software')
                """
            )
            # Deduplicate if both packages and software existed (unlikely).
            conn.execute(
                """
                DELETE FROM library_connection_kinds__sw
                WHERE rowid NOT IN (
                    SELECT MIN(rowid) FROM library_connection_kinds__sw
                    GROUP BY connection_id, kind
                )
                """
            )
            conn.execute("DROP TABLE library_connection_kinds")
            conn.execute(
                "ALTER TABLE library_connection_kinds__sw RENAME TO library_connection_kinds"
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_library_connection_kinds_kind
                    ON library_connection_kinds(kind)
                """
            )
        if need_bindings:
            conn.execute(
                """
                CREATE TABLE library_bindings__sw (
                    id              TEXT PRIMARY KEY,
                    connection_id   TEXT    NOT NULL,
                    domain          TEXT    NOT NULL,
                    media_target    TEXT    NOT NULL DEFAULT '',
                    label           TEXT    NOT NULL,
                    filter          TEXT    NOT NULL DEFAULT '*',
                    enabled         INTEGER NOT NULL DEFAULT 1,
                    created_at      TEXT    NOT NULL,
                    updated_at      TEXT    NOT NULL,
                    FOREIGN KEY (connection_id) REFERENCES library_connections(id)
                        ON DELETE CASCADE,
                    CHECK (domain IN ('scripts', 'clutches', 'media', 'answerfiles', 'software')),
                    CHECK (
                        (domain != 'media' AND media_target = '')
                        OR (domain = 'media' AND media_target IN ('iso', 'virtio'))
                    ),
                    CHECK (enabled IN (0, 1))
                )
                """
            )
            conn.execute(
                """
                INSERT INTO library_bindings__sw (
                    id, connection_id, domain, media_target, label, filter,
                    enabled, created_at, updated_at
                )
                SELECT
                    id, connection_id, domain, media_target, label, filter,
                    enabled, created_at, updated_at
                FROM library_bindings
                """
            )
            conn.execute("DROP TABLE library_bindings")
            conn.execute("ALTER TABLE library_bindings__sw RENAME TO library_bindings")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_library_bindings_connection
                    ON library_bindings(connection_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_library_bindings_domain
                    ON library_bindings(domain, media_target)
                """
            )
        elif kinds_table and not need_kinds:
            conn.execute(
                "UPDATE library_connection_kinds SET kind = 'software' WHERE kind = 'packages'"
            )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


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


def _migrate_library_cache_provenance_axes(conn: sqlite3.Connection) -> None:
    """Add ADR-0018 source_status / sync_state / message; backfill from drift_state."""
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='library_cache_provenance'"
    ).fetchone()
    if not table:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(library_cache_provenance)").fetchall()}
    if "source_status" not in cols:
        conn.execute(
            "ALTER TABLE library_cache_provenance "
            "ADD COLUMN source_status TEXT NOT NULL DEFAULT 'unconfirmable'"
        )
    if "source_status_message" not in cols:
        conn.execute(
            "ALTER TABLE library_cache_provenance "
            "ADD COLUMN source_status_message TEXT NOT NULL DEFAULT ''"
        )
    if "sync_state" not in cols:
        conn.execute(
            "ALTER TABLE library_cache_provenance "
            "ADD COLUMN sync_state TEXT NOT NULL DEFAULT 'unevaluated'"
        )
    # One-shot backfill from legacy drift_state (re-evaluate on next validator pass).
    conn.execute(
        """
        UPDATE library_cache_provenance
        SET source_status = 'ok',
            sync_state = 'in_sync',
            source_status_message = ''
        WHERE drift_state = 'in_sync'
          AND (source_status = 'unconfirmable' OR source_status = '' OR source_status IS NULL)
        """
    )
    conn.execute(
        """
        UPDATE library_cache_provenance
        SET source_status = 'ok',
            sync_state = 'out_of_sync',
            source_status_message = ''
        WHERE drift_state = 'out_of_sync'
          AND sync_state = 'unevaluated'
        """
    )
    conn.execute(
        """
        UPDATE library_cache_provenance
        SET source_status = 'orphan',
            sync_state = 'unevaluated',
            source_status_message = 'Library connection or binding missing'
        WHERE drift_state = 'orphan'
          AND sync_state = 'unevaluated'
        """
    )
    conn.execute(
        """
        UPDATE library_cache_provenance
        SET source_status = 'unconfirmable',
            sync_state = 'unevaluated',
            source_status_message = 'Pending re-evaluate'
        WHERE drift_state = 'unknown'
          AND sync_state = 'unevaluated'
          AND (source_status_message = '' OR source_status_message IS NULL)
        """
    )


def _migrate_hatch_vm_scripts_typed(conn: sqlite3.Connection) -> None:
    """Add typed automation columns for mixed script|software hatch rows (#474)."""
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='hatch_vm_scripts'"
    ).fetchone()
    if not table:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(hatch_vm_scripts)").fetchall()}
    if "entry_type" not in cols:
        conn.execute(
            "ALTER TABLE hatch_vm_scripts ADD COLUMN entry_type TEXT NOT NULL DEFAULT 'script'"
        )
    if "clean_payload_on_success" not in cols:
        conn.execute(
            "ALTER TABLE hatch_vm_scripts "
            "ADD COLUMN clean_payload_on_success INTEGER NOT NULL DEFAULT 1"
        )


def _migrate_hatch_vm_status_guest_os(conn: sqlite3.Connection) -> None:
    """Store Clutch guest OS on hatch VM rows for Software path resolution (#474)."""
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='hatch_vm_status'"
    ).fetchone()
    if not table:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(hatch_vm_status)").fetchall()}
    if "guest_os" not in cols:
        conn.execute("ALTER TABLE hatch_vm_status ADD COLUMN guest_os TEXT")


def _migrate_hatch_sessions_clutch_snapshot(conn: sqlite3.Connection) -> None:
    """Immutable Clutch JSON at hatch start so mid-hatch edits cannot alter the session (#514)."""
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='hatch_sessions'"
    ).fetchone()
    if not table:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(hatch_sessions)").fetchall()}
    if "clutch_snapshot" not in cols:
        conn.execute("ALTER TABLE hatch_sessions ADD COLUMN clutch_snapshot TEXT")


def _migrate_remoting_identities(conn: sqlite3.Connection) -> None:
    """Ensure remoting_identities catalog exists (ADR-0030 / #522)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS remoting_identities (
            id                    TEXT PRIMARY KEY,
            name                  TEXT NOT NULL,
            kind                  TEXT NOT NULL,
            identity_file         TEXT NOT NULL,
            pubkey                TEXT,
            cert_path             TEXT,
            identity_expires_at   TEXT,
            created_at            TEXT NOT NULL,
            updated_at            TEXT NOT NULL,
            CHECK (kind IN ('hatchery', 'path'))
        )
        """
    )


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
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
