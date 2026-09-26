import pytest

import lib.db as db_module


@pytest.fixture(autouse=True)
def isolate_db(tmp_path):
    db_module.init_db(tmp_path / "hatchery.db")
    yield
    db_module._db_path = None


class TestInitDb:
    def test_creates_db_file(self, tmp_path):
        path = tmp_path / "sub" / "hatchery.db"
        db_module.init_db(path)
        assert path.exists()

    def test_creates_alerts_table(self):
        conn = db_module.get_connection()
        try:
            names = [
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "alerts" in names
        finally:
            conn.close()

    def test_creates_app_settings_table(self):
        conn = db_module.get_connection()
        try:
            names = [
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "app_settings" in names
        finally:
            conn.close()

    def test_creates_clutch_instances_table(self):
        conn = db_module.get_connection()
        try:
            names = [
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "clutch_instances" in names
        finally:
            conn.close()

    def test_idempotent(self, tmp_path):
        path = tmp_path / "hatchery.db"
        db_module.init_db(path)
        db_module.init_db(path)
        assert path.exists()

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "hatchery.db"
        db_module.init_db(path)
        assert path.exists()

    def test_alerts_columns(self):
        conn = db_module.get_connection()
        try:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(alerts)").fetchall()]
            assert cols == ["id", "created_at", "message", "tier", "resolved", "resolved_at"]
        finally:
            conn.close()

    def test_migrates_alerts_tier_on_existing_db(self, tmp_path):
        path = tmp_path / "legacy.db"
        conn = __import__("sqlite3").connect(str(path))
        try:
            conn.execute(
                """
                CREATE TABLE alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    message TEXT NOT NULL,
                    resolved INTEGER NOT NULL DEFAULT 0,
                    resolved_at TEXT
                )
                """
            )
            conn.execute("INSERT INTO alerts (created_at, message) VALUES ('2024-01-01', 'old')")
            conn.commit()
        finally:
            conn.close()

        db_module.init_db(path)
        conn = db_module.get_connection()
        try:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(alerts)").fetchall()]
            assert "tier" in cols
            row = conn.execute("SELECT tier, message FROM alerts").fetchone()
            assert row["message"] == "old"
            assert row["tier"] == "alert"
        finally:
            conn.close()

    def test_creates_nests_table_empty(self):
        conn = db_module.get_connection()
        try:
            names = [
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "nests" in names
            count = conn.execute("SELECT COUNT(*) AS n FROM nests").fetchone()["n"]
            assert count == 0
        finally:
            conn.close()

    def test_creates_hatch_sessions_table(self):
        conn = db_module.get_connection()
        try:
            names = [
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "hatch_sessions" in names
        finally:
            conn.close()

    def test_creates_hatch_vm_status_table(self):
        conn = db_module.get_connection()
        try:
            names = [
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "hatch_vm_status" in names
        finally:
            conn.close()

    def test_hatch_sessions_columns(self):
        conn = db_module.get_connection()
        try:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(hatch_sessions)").fetchall()]
            assert cols == [
                "id",
                "nest",
                "clutch_file",
                "clutch_name",
                "hatched_at",
                "completed_at",
                "archived_at",
            ]
        finally:
            conn.close()

    def test_hatch_vm_status_columns(self):
        conn = db_module.get_connection()
        try:
            cols = [
                r["name"] for r in conn.execute("PRAGMA table_info(hatch_vm_status)").fetchall()
            ]
            assert cols == [
                "id",
                "session_id",
                "vm_name",
                "status",
                "libvirt_uuid",
                "started_at",
                "fledged_at",
                "admin_username",
                "admin_password",
                "error",
            ]
        finally:
            conn.close()


class TestGetConnection:
    def test_raises_when_not_initialized(self, monkeypatch):
        monkeypatch.setattr(db_module, "_db_path", None)
        with pytest.raises(RuntimeError, match="db not initialized"):
            db_module.get_connection()

    def test_returns_connection(self):
        conn = db_module.get_connection()
        try:
            assert conn is not None
        finally:
            conn.close()

    def test_row_factory_enables_column_access(self):
        conn = db_module.get_connection()
        try:
            conn.execute("INSERT INTO alerts (created_at, message) VALUES ('2024-01-01', 'hello')")
            conn.commit()
            row = conn.execute("SELECT * FROM alerts").fetchone()
            assert row["message"] == "hello"
        finally:
            conn.close()


class TestLibraryDropGitType:
    def test_fresh_schema_excludes_git_from_type_check(self):
        conn = db_module.get_connection()
        try:
            ddl = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='library_connections'"
            ).fetchone()[0]
            assert "'git'" not in ddl
            assert "'forge'" in ddl
        finally:
            conn.close()

    def test_migrates_legacy_check_when_no_git_rows(self, tmp_path):
        path = tmp_path / "legacy-git-check.db"
        sqlite3 = __import__("sqlite3")
        conn = sqlite3.connect(str(path))
        try:
            conn.executescript(
                """
                CREATE TABLE library_connections (
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
                );
                CREATE TABLE library_connection_kinds (
                    connection_id   TEXT    NOT NULL,
                    kind            TEXT    NOT NULL,
                    PRIMARY KEY (connection_id, kind),
                    FOREIGN KEY (connection_id) REFERENCES library_connections(id)
                        ON DELETE CASCADE,
                    CHECK (kind IN ('scripts', 'clutches', 'media', 'packages'))
                );
                INSERT INTO library_connections (
                    id, label, type, provider, base_uri, token, expires_at,
                    enabled, created_at, updated_at
                ) VALUES (
                    'c1', 'Share', 'path', '', '/tmp/share', '', NULL,
                    1, '2026-01-01', '2026-01-01'
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

        db_module.init_db(path)
        conn = db_module.get_connection()
        try:
            ddl = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='library_connections'"
            ).fetchone()[0]
            assert "'git'" not in ddl
            row = conn.execute("SELECT type FROM library_connections WHERE id='c1'").fetchone()
            assert row["type"] == "path"
        finally:
            conn.close()

    def test_keeps_git_in_check_while_legacy_rows_exist(self, tmp_path):
        path = tmp_path / "legacy-git-row.db"
        sqlite3 = __import__("sqlite3")
        conn = sqlite3.connect(str(path))
        try:
            conn.executescript(
                """
                CREATE TABLE library_connections (
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
                );
                CREATE TABLE library_connection_kinds (
                    connection_id   TEXT    NOT NULL,
                    kind            TEXT    NOT NULL,
                    PRIMARY KEY (connection_id, kind)
                );
                INSERT INTO library_connections (
                    id, label, type, provider, base_uri, token, expires_at,
                    enabled, created_at, updated_at
                ) VALUES (
                    'g1', 'Old git', 'git', '', 'https://example.com/r.git', '', NULL,
                    1, '2026-01-01', '2026-01-01'
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

        db_module.init_db(path)
        conn = db_module.get_connection()
        try:
            ddl = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='library_connections'"
            ).fetchone()[0]
            assert "'git'" in ddl
            row = conn.execute("SELECT type FROM library_connections WHERE id='g1'").fetchone()
            assert row["type"] == "git"
        finally:
            conn.close()
