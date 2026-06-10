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

    def test_creates_notifications_table(self):
        conn = db_module.get_connection()
        try:
            names = [
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "notifications" in names
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

    def test_migration_adds_resolved_at_to_existing_db(self, tmp_path):
        import sqlite3

        path = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(path))
        conn.execute(
            "CREATE TABLE notifications ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "created_at TEXT NOT NULL, tier TEXT NOT NULL, "
            "message TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0, "
            "dismissed INTEGER NOT NULL DEFAULT 0)"
        )
        conn.commit()
        conn.close()
        db_module.init_db(path)
        conn = db_module.get_connection()
        try:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(notifications)").fetchall()]
            assert "resolved_at" in cols
        finally:
            conn.close()

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "hatchery.db"
        db_module.init_db(path)
        assert path.exists()

    def test_notifications_columns(self):
        conn = db_module.get_connection()
        try:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(notifications)").fetchall()]
            assert cols == [
                "id",
                "created_at",
                "tier",
                "message",
                "resolved",
                "resolved_at",
                "dismissed",
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
            conn.execute(
                "INSERT INTO notifications (created_at, tier, message) VALUES ('2024-01-01', 'activity', 'hello')"
            )
            conn.commit()
            row = conn.execute("SELECT * FROM notifications").fetchone()
            assert row["tier"] == "activity"
            assert row["message"] == "hello"
        finally:
            conn.close()


class TestTrimNotifications:
    def test_trims_beyond_cap(self, monkeypatch):
        monkeypatch.setattr(db_module, "_MAX_NOTIFICATIONS", 5)
        conn = db_module.get_connection()
        try:
            for i in range(10):
                conn.execute(
                    "INSERT INTO notifications (created_at, tier, message) VALUES (?, 'activity', ?)",
                    (f"2024-01-{i + 1:02d}", f"msg {i}"),
                )
            conn.commit()
            db_module.trim_notifications(conn)
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
            assert count == 5
        finally:
            conn.close()

    def test_keeps_newest_rows(self, monkeypatch):
        monkeypatch.setattr(db_module, "_MAX_NOTIFICATIONS", 3)
        conn = db_module.get_connection()
        try:
            for i in range(5):
                conn.execute(
                    "INSERT INTO notifications (created_at, tier, message) VALUES (?, 'activity', ?)",
                    (f"2024-01-{i + 1:02d}", f"msg {i}"),
                )
            conn.commit()
            db_module.trim_notifications(conn)
            conn.commit()
            messages = [
                r["message"]
                for r in conn.execute(
                    "SELECT message FROM notifications ORDER BY id DESC"
                ).fetchall()
            ]
            assert "msg 4" in messages
            assert "msg 0" not in messages
        finally:
            conn.close()

    def test_no_trim_when_under_cap(self):
        conn = db_module.get_connection()
        try:
            for i in range(3):
                conn.execute(
                    "INSERT INTO notifications (created_at, tier, message) VALUES (?, 'activity', ?)",
                    (f"2024-01-{i + 1:02d}", f"msg {i}"),
                )
            conn.commit()
            db_module.trim_notifications(conn)
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
            assert count == 3
        finally:
            conn.close()
