"""Unit tests for Settings export/import (full replace)."""

from pathlib import Path

import pytest
import yaml

import lib.config as cfg
import lib.db as db_module
import lib.library_registry as library_registry
import lib.settings_io as settings_io


@pytest.fixture
def live_cfg(tmp_path, monkeypatch):
    """Isolated config with a Library connection + script binding in tables."""
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
    cfg.save(
        {
            **cfg.get(),
            "data_dir": str(data),
            "bg_interval": 90,
            "library_enabled": True,
            "display_timezone": "local",
        }
    )
    share = tmp_path / "share"
    share.mkdir()
    library_registry.replace_connections(
        [
            {
                "id": "conn1",
                "label": "Share",
                "type": "path",
                "base_uri": str(share),
                "token": "secret",
                "expires_at": None,
                "kinds": ["scripts"],
                "enabled": True,
            }
        ]
    )
    library_registry.replace_bindings_for_domain(
        "scripts",
        [
            {
                "id": "bind1",
                "connection_id": "conn1",
                "filter": "*.ps1",
                "domain": "scripts",
                "enabled": True,
            }
        ],
    )
    return cfg


class TestExportImport:
    def test_round_trip_preserves_non_library_settings(self, live_cfg):
        exported = settings_io.export_document(include_meta=False)
        assert exported["version"] == 1
        assert "data_dir" not in exported
        assert "data_dir" not in exported["settings"]
        assert "library_connections" not in exported["settings"]
        assert exported["settings"]["bg_interval"] == 90

        text = settings_io.dump_yaml(exported)
        raw = settings_io.load_yaml(text)
        live_cfg.save(
            {
                **live_cfg.defaults_for_exportable_settings(),
                "data_dir": live_cfg.get()["data_dir"],
            }
        )
        result = settings_io.apply_document(raw)
        assert result["ok"] is True
        assert live_cfg.get()["bg_interval"] == 90
        assert live_cfg.get()["library_enabled"] is True
        # Registry is not part of Settings import - prior table rows remain.
        assert library_registry.list_connections()[0]["label"] == "Share"
        assert library_registry.list_bindings(domain="scripts")[0]["filter"] == "*.ps1"
        assert Path(live_cfg.get()["data_dir"]).name == "data"

    def test_ignores_legacy_library_keys_in_document(self, live_cfg):
        raw = {
            "version": 1,
            "settings": {
                "bg_interval": 45,
                "library_connections": [{"id": "x", "label": "X", "type": "path"}],
            },
        }
        result = settings_io.apply_document(raw)
        assert any("Legacy Settings key" in w for w in result["warnings"])
        assert live_cfg.get()["bg_interval"] == 45
        assert library_registry.list_connections()[0]["id"] == "conn1"

    def test_ignores_data_dir_in_document(self, live_cfg):
        before = live_cfg.get()["data_dir"]
        raw = {
            "version": 1,
            "settings": {"bg_interval": 120, "data_dir": "/evil/path"},
        }
        result = settings_io.apply_document(raw)
        assert any("data_dir" in w for w in result["warnings"])
        assert live_cfg.get()["data_dir"] == before
        assert live_cfg.get()["bg_interval"] == 120
        assert live_cfg.get()["library_enabled"] is False

    def test_replace_resets_omitted_keys(self, live_cfg):
        raw = {"version": 1, "settings": {"bg_interval": 30}}
        settings_io.apply_document(raw)
        assert live_cfg.get()["bg_interval"] == 30
        assert live_cfg.get()["library_enabled"] is False
        assert live_cfg.get()["display_timezone"] == "UTC"

    def test_rejects_bad_version(self, live_cfg):
        with pytest.raises(ValueError, match="Unsupported Settings document version"):
            settings_io.apply_document({"version": 99, "settings": {}})

    def test_yaml_round_trip_structure(self, live_cfg):
        text = settings_io.dump_yaml(settings_io.export_document())
        loaded = yaml.safe_load(text)
        assert loaded["version"] == 1
        assert "library_enabled" in loaded["settings"]
        assert "library_connections" not in loaded["settings"]
