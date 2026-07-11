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

    def test_creates_activity_table(self):
        conn = db_module.get_connection()
        try:
            names = [
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "activity" in names
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
            assert cols == ["id", "created_at", "message", "resolved", "resolved_at"]
        finally:
            conn.close()

    def test_activity_columns(self):
        conn = db_module.get_connection()
        try:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(activity)").fetchall()]
            assert cols == ["id", "created_at", "message"]
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
            conn.execute(
                "INSERT INTO activity (created_at, message) VALUES ('2024-01-01', 'hello')"
            )
            conn.commit()
            row = conn.execute("SELECT * FROM activity").fetchone()
            assert row["message"] == "hello"
        finally:
            conn.close()


class TestTrimAlerts:
    def test_trims_beyond_cap(self, monkeypatch):
        monkeypatch.setattr(db_module, "_MAX_ALERTS", 5)
        conn = db_module.get_connection()
        try:
            for i in range(10):
                conn.execute(
                    "INSERT INTO alerts (created_at, message) VALUES (?, ?)",
                    (f"2024-01-{i + 1:02d}", f"msg {i}"),
                )
            conn.commit()
            db_module.trim_alerts(conn)
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
            assert count == 5
        finally:
            conn.close()

    def test_keeps_newest_rows(self, monkeypatch):
        monkeypatch.setattr(db_module, "_MAX_ALERTS", 3)
        conn = db_module.get_connection()
        try:
            for i in range(5):
                conn.execute(
                    "INSERT INTO alerts (created_at, message) VALUES (?, ?)",
                    (f"2024-01-{i + 1:02d}", f"msg {i}"),
                )
            conn.commit()
            db_module.trim_alerts(conn)
            conn.commit()
            messages = [
                r["message"]
                for r in conn.execute("SELECT message FROM alerts ORDER BY id DESC").fetchall()
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
                    "INSERT INTO alerts (created_at, message) VALUES (?, ?)",
                    (f"2024-01-{i + 1:02d}", f"msg {i}"),
                )
            conn.commit()
            db_module.trim_alerts(conn)
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
            assert count == 3
        finally:
            conn.close()


class TestTrimActivity:
    def test_trims_beyond_cap(self, monkeypatch):
        monkeypatch.setattr(db_module, "_MAX_ACTIVITY", 5)
        conn = db_module.get_connection()
        try:
            for i in range(10):
                conn.execute(
                    "INSERT INTO activity (created_at, message) VALUES (?, ?)",
                    (f"2024-01-{i + 1:02d}", f"msg {i}"),
                )
            conn.commit()
            db_module.trim_activity(conn)
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0]
            assert count == 5
        finally:
            conn.close()

    def test_keeps_newest_rows(self, monkeypatch):
        monkeypatch.setattr(db_module, "_MAX_ACTIVITY", 3)
        conn = db_module.get_connection()
        try:
            for i in range(5):
                conn.execute(
                    "INSERT INTO activity (created_at, message) VALUES (?, ?)",
                    (f"2024-01-{i + 1:02d}", f"msg {i}"),
                )
            conn.commit()
            db_module.trim_activity(conn)
            conn.commit()
            messages = [
                r["message"]
                for r in conn.execute("SELECT message FROM activity ORDER BY id DESC").fetchall()
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
                    "INSERT INTO activity (created_at, message) VALUES (?, ?)",
                    (f"2024-01-{i + 1:02d}", f"msg {i}"),
                )
            conn.commit()
            db_module.trim_activity(conn)
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0]
            assert count == 3
        finally:
            conn.close()
