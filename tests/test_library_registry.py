"""Tests for Library connection/binding registry (ADR-0017 / #367)."""

from __future__ import annotations

import json

import lib.config as cfg
import lib.db as db_module
import lib.library_registry as registry


def _init(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(cfg, "DEFAULT_DATA_DIR", tmp_path / "data")
    cfg._config = {}
    cfg._db_bound = False
    cfg._pending_yaml_settings = {}
    cfg.set_runtime_data_dir(None)
    data = tmp_path / "data"
    data.mkdir()
    cfg.load()
    db_module.init_db(data / "hatchery.db")
    cfg.bind_db()
    return data


def test_migrate_from_app_settings_json(tmp_path, monkeypatch):
    data = _init(tmp_path, monkeypatch)
    # Simulate pre-#367 Settings rows.
    conn = db_module.get_connection()
    try:
        conn.execute("DELETE FROM library_bindings")
        conn.execute("DELETE FROM library_connections")
        conn.execute(
            "INSERT OR REPLACE INTO app_settings(key, value) VALUES (?, ?)",
            (
                "library_connections",
                json.dumps(
                    [
                        {
                            "id": "c1",
                            "label": "Share",
                            "type": "path",
                            "base_uri": "/tmp",
                            "token": "",
                            "kinds": ["scripts"],
                            "enabled": True,
                        }
                    ]
                ),
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO app_settings(key, value) VALUES (?, ?)",
            (
                "library_script_bindings",
                json.dumps(
                    [
                        {
                            "id": "b1",
                            "connection_id": "c1",
                            "filter": "*.ps1",
                            "domain": "scripts",
                            "enabled": True,
                        }
                    ]
                ),
            ),
        )
        conn.commit()
        registry.migrate_from_app_settings(conn)
        conn.commit()
        leftover = conn.execute(
            "SELECT key FROM app_settings WHERE key LIKE 'library_%' AND key != 'library_enabled'"
        ).fetchall()
        assert leftover == []
        kinds = conn.execute(
            "SELECT kind FROM library_connection_kinds WHERE connection_id = ?",
            ("c1",),
        ).fetchall()
        assert [r["kind"] for r in kinds] == ["scripts"]
    finally:
        conn.close()

    conns = registry.list_connections()
    assert conns[0]["id"] == "c1"
    assert conns[0]["kinds"] == ["scripts"]
    assert registry.list_bindings(domain="scripts")[0]["filter"] == "*.ps1"
    # Idempotent
    conn = db_module.get_connection()
    try:
        registry.migrate_from_app_settings(conn)
        conn.commit()
    finally:
        conn.close()
    assert len(registry.list_connections()) == 1
    assert (data / "hatchery.db").is_file()


def test_upsert_and_delete_cascade(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    registry.upsert_connection(
        {
            "id": "c1",
            "label": "A",
            "type": "path",
            "base_uri": "/tmp",
            "kinds": ["scripts", "media"],
            "enabled": True,
        }
    )
    registry.upsert_binding(
        {
            "id": "b1",
            "connection_id": "c1",
            "domain": "scripts",
            "filter": "*",
            "label": "All scripts",
            "enabled": True,
        }
    )
    assert cfg.library_connections()[0]["label"] == "A"
    assert cfg.library_connections()[0]["kinds"] == ["media", "scripts"]
    assert cfg.library_script_bindings()[0]["label"] == "All scripts"
    conn = db_module.get_connection()
    try:
        assert (
            conn.execute(
                "SELECT COUNT(*) AS n FROM library_connection_kinds WHERE connection_id = ?",
                ("c1",),
            ).fetchone()["n"]
            == 2
        )
    finally:
        conn.close()
    registry.delete_connection("c1")
    assert registry.list_connections() == []
    assert registry.list_bindings() == []
    conn = db_module.get_connection()
    try:
        assert (
            conn.execute("SELECT COUNT(*) AS n FROM library_connection_kinds").fetchone()["n"] == 0
        )
    finally:
        conn.close()


def test_migrate_kinds_json_sketch_column(tmp_path, monkeypatch):
    """Existing sketch DBs with kinds_json are rebuilt onto the junction table."""
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(cfg, "DEFAULT_DATA_DIR", tmp_path / "data")
    cfg._config = {}
    cfg._db_bound = False
    cfg._pending_yaml_settings = {}
    cfg.set_runtime_data_dir(None)
    data = tmp_path / "data"
    data.mkdir()
    db_path = data / "hatchery.db"
    # Pre-create sketch-shaped tables (kinds_json) before init_db migration.
    import sqlite3

    raw = sqlite3.connect(str(db_path))
    try:
        raw.executescript(
            """
            CREATE TABLE library_connections (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                type TEXT NOT NULL,
                provider TEXT,
                base_uri TEXT,
                token TEXT,
                expires_at TEXT,
                kinds_json TEXT NOT NULL DEFAULT '[]',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE library_bindings (
                id TEXT PRIMARY KEY,
                connection_id TEXT NOT NULL,
                domain TEXT NOT NULL,
                media_target TEXT NOT NULL DEFAULT '',
                label TEXT NOT NULL,
                filter TEXT NOT NULL DEFAULT '*',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO library_connections (
                id, label, type, provider, base_uri, token, expires_at,
                kinds_json, enabled, created_at, updated_at
            ) VALUES (
                'c1', 'Share', 'path', '', '/tmp', '', NULL,
                '["scripts","clutches"]', 1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            );
            """
        )
        raw.commit()
    finally:
        raw.close()

    cfg.load()
    db_module.init_db(db_path)
    cfg.bind_db()

    conns = registry.list_connections()
    assert len(conns) == 1
    assert conns[0]["kinds"] == ["clutches", "scripts"]
    conn = db_module.get_connection()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(library_connections)").fetchall()}
        assert "kinds_json" not in cols
    finally:
        conn.close()


def test_ensure_hatchery_library_seeds_empty_registry(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    assert registry.list_connections() == []
    assert cfg.library_enabled() is False

    assert registry.ensure_hatchery_library() is True
    assert cfg.library_enabled() is True

    conns = registry.list_connections()
    assert len(conns) == 1
    conn = conns[0]
    assert conn["id"] == registry.HATCHERY_LIBRARY_CONNECTION_ID
    assert conn["label"] == "Hatchery Library"
    assert conn["type"] == "forge"
    assert conn["provider"] == "github"
    assert conn["base_uri"] == registry.HATCHERY_LIBRARY_BASE_URI
    assert conn["token"] == ""
    assert set(conn["kinds"]) == {"scripts", "clutches", "media", "packages"}

    scripts = registry.list_bindings(domain="scripts")
    clutches = registry.list_bindings(domain="clutches")
    media = registry.list_bindings(domain="media")
    assert [(b["label"], b["filter"]) for b in scripts] == [("All Scripts", "*")]
    assert [(b["label"], b["filter"]) for b in clutches] == [("All Clutches", "*")]
    by_target = {(b["target"], b["label"], b["filter"]) for b in media}
    assert by_target == {("iso", "All ISOs", "*"), ("virtio", "All VirtIO", "*")}

    # Second call is a no-op once any connection exists.
    assert registry.ensure_hatchery_library() is False


def test_ensure_hatchery_library_skips_nonempty_registry(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    registry.upsert_connection(
        {
            "id": "other",
            "label": "Other",
            "type": "path",
            "base_uri": str(tmp_path / "share"),
            "kinds": ["scripts"],
            "enabled": True,
        }
    )
    assert registry.ensure_hatchery_library() is False
    assert [c["id"] for c in registry.list_connections()] == ["other"]
    assert cfg.library_enabled() is False
