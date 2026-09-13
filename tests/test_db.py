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
