"""Unit tests for Settings export/import (full replace)."""

from pathlib import Path

import pytest
import yaml

import lib.config as cfg
import lib.settings_io as settings_io


@pytest.fixture
def live_cfg(tmp_path, monkeypatch):
    """Isolated config with a Library connection + script binding."""
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(cfg, "DEFAULT_DATA_DIR", tmp_path / "data")
    cfg._config = {}
    cfg._db_bound = False
    cfg._pending_yaml_settings = {}
    data = tmp_path / "data"
    data.mkdir()
    cfg.load()
    cfg.save(
        {
            **cfg.get(),
            "data_dir": str(data),
            "bg_interval": 90,
            "library_enabled": True,
            "display_timezone": "local",
            "library_connections": [
                {
                    "id": "conn1",
                    "label": "Share",
                    "type": "path",
                    "base_uri": str(tmp_path / "share"),
                    "token": "secret",
                    "expires_at": None,
                    "kinds": ["scripts"],
                }
            ],
            "library_script_bindings": [
                {
                    "id": "bind1",
                    "connection_id": "conn1",
                    "filter": "*.ps1",
                    "domain": "scripts",
                }
            ],
        }
    )
    return cfg


class TestExportImport:
    def test_round_trip_preserves_library(self, live_cfg):
        exported = settings_io.export_document(include_meta=False)
        assert exported["version"] == 1
        assert "data_dir" not in exported
        assert "data_dir" not in exported["settings"]
        assert exported["settings"]["library_connections"][0]["token"] == "secret"
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
        assert live_cfg.get()["library_connections"][0]["label"] == "Share"
        assert live_cfg.get()["library_script_bindings"][0]["filter"] == "*.ps1"
        assert Path(live_cfg.get()["data_dir"]).name == "data"

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
        # Omitted keys reset to defaults on replace.
        assert live_cfg.get()["library_enabled"] is False
        assert live_cfg.get()["library_connections"] == []

    def test_replace_resets_omitted_keys(self, live_cfg):
        raw = {"version": 1, "settings": {"bg_interval": 30}}
        settings_io.apply_document(raw)
        assert live_cfg.get()["bg_interval"] == 30
        assert live_cfg.get()["library_enabled"] is False
        assert live_cfg.get()["library_connections"] == []
        assert live_cfg.get()["display_timezone"] == "UTC"

    def test_rejects_bad_version(self, live_cfg):
        with pytest.raises(ValueError, match="Unsupported Settings document version"):
            settings_io.apply_document({"version": 99, "settings": {}})

    def test_yaml_round_trip_structure(self, live_cfg):
        text = settings_io.dump_yaml(settings_io.export_document())
        loaded = yaml.safe_load(text)
        assert loaded["version"] == 1
        assert "library_connections" in loaded["settings"]
