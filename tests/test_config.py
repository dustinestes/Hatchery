import json

import pytest
import yaml

import lib.config as cfg
import lib.db as db_module


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    """Redirect paths, reset config state, and bind an isolated SQLite DB."""
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(cfg, "DEFAULT_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(
        cfg,
        "_DEFAULTS",
        {
            "data_dir": str(tmp_path / "data"),
            "bg_interval": 60,
            "validators": {},
            "validators_run_retention": 50,
            "show_passwords": False,
            "display_timezone": "UTC",
            "library_enabled": False,
            "library_connections": [],
            "library_script_bindings": [],
            "library_clutch_bindings": [],
            "library_media_bindings": [],
            "nest_key_alert_tiers": [
                {"days_before": 30, "alerts_per_day": 1},
                {"days_before": 7, "alerts_per_day": 2},
            ],
            "nest_ssh_identities": [],
        },
    )
    monkeypatch.setattr(cfg, "_config", {})
    monkeypatch.setattr(cfg, "_pending_yaml_settings", {})
    monkeypatch.setattr(cfg, "_db_bound", False)
    db_module.init_db(tmp_path / "hatchery.db")
    yield tmp_path
    db_module._db_path = None


def _bootstrap_on_disk():
    with open(cfg.CONFIG_FILE) as f:
        return yaml.safe_load(f)


class TestLoad:
    def test_creates_bootstrap_with_data_dir_when_missing(self, isolated_config):
        result = cfg.load()
        assert result["data_dir"] == str(isolated_config / "data")
        assert cfg.CONFIG_FILE.exists()
        on_disk = _bootstrap_on_disk()
        assert on_disk == {"data_dir": str(isolated_config / "data")}

    def test_written_bootstrap_is_valid_yaml(self, isolated_config):
        cfg.load()
        on_disk = _bootstrap_on_disk()
        assert on_disk["data_dir"] == str(isolated_config / "data")

    def test_reads_existing_bootstrap(self, isolated_config):
        cfg.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg.CONFIG_FILE, "w") as f:
            yaml.dump({"data_dir": str(isolated_config / "custom")}, f)
        result = cfg.load()
        assert result["data_dir"] == str(isolated_config / "custom")

    def test_merges_defaults_for_missing_keys(self, isolated_config):
        cfg.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg.CONFIG_FILE, "w") as f:
            yaml.dump({}, f)
        result = cfg.load()
        assert "data_dir" in result
        assert result["bg_interval"] == 60

    def test_empty_config_file_falls_back_to_defaults(self, isolated_config):
        cfg.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        cfg.CONFIG_FILE.write_text("")
        result = cfg.load()
        assert result["data_dir"] == str(isolated_config / "data")

    def test_legacy_yaml_settings_slims_bootstrap_and_pending(self, isolated_config):
        cfg.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg.CONFIG_FILE, "w") as f:
            yaml.dump(
                {
                    "data_dir": str(isolated_config / "data"),
                    "bg_interval": 45,
                    "show_passwords": True,
                },
                f,
            )
        result = cfg.load()
        assert result["bg_interval"] == 45
        assert result["show_passwords"] is True
        assert _bootstrap_on_disk() == {"data_dir": str(isolated_config / "data")}
        assert cfg._pending_yaml_settings["bg_interval"] == 45


class TestBindDb:
    def test_migrates_pending_yaml_into_sqlite(self, isolated_config):
        cfg.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg.CONFIG_FILE, "w") as f:
            yaml.dump(
                {
                    "data_dir": str(isolated_config / "data"),
                    "bg_interval": 42,
                    "display_timezone": "local",
                },
                f,
            )
        cfg.load()
        cfg.bind_db()
        assert cfg.bg_interval() == 42
        assert cfg.display_timezone() == "local"
        assert cfg._pending_yaml_settings == {}
        conn = db_module.get_connection()
        try:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", ("bg_interval",)
            ).fetchone()
            assert json.loads(row["value"]) == 42
        finally:
            conn.close()

    def test_loads_existing_db_settings(self, isolated_config):
        cfg.load()
        cfg.bind_db()
        cfg.save({**cfg.get(), "bg_interval": 99, "show_passwords": True})
        cfg._config = {}
        cfg._db_bound = False
        cfg.load()
        cfg.bind_db()
        assert cfg.bg_interval() == 99
        assert cfg.show_passwords() is True


class TestSave:
    def test_persists_data_dir_to_bootstrap_only(self, isolated_config):
        cfg.load()
        cfg.bind_db()
        new_cfg = {**cfg.get(), "data_dir": str(isolated_config / "saved"), "bg_interval": 77}
        cfg.save(new_cfg)
        on_disk = _bootstrap_on_disk()
        assert on_disk == {"data_dir": str(isolated_config / "saved")}
        assert "bg_interval" not in on_disk

    def test_persists_settings_to_sqlite(self, isolated_config):
        cfg.load()
        cfg.bind_db()
        cfg.save({**cfg.get(), "bg_interval": 33})
        conn = db_module.get_connection()
        try:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", ("bg_interval",)
            ).fetchone()
            assert json.loads(row["value"]) == 33
        finally:
            conn.close()

    def test_updates_in_memory_state(self, isolated_config):
        cfg.load()
        cfg.bind_db()
        cfg.save({**cfg.get(), "data_dir": str(isolated_config / "saved")})
        assert cfg.get()["data_dir"] == str(isolated_config / "saved")

    def test_creates_parent_directories(self, isolated_config):
        monkeypatch_path = isolated_config / "deep" / "nested" / "config.yaml"
        cfg.CONFIG_FILE = monkeypatch_path
        cfg.load()
        cfg.bind_db()
        cfg.save({**cfg.get(), "data_dir": str(isolated_config / "data")})
        assert monkeypatch_path.exists()


class TestGet:
    def test_loads_from_disk_on_first_call(self, isolated_config):
        assert cfg._config == {}
        result = cfg.get()
        assert "data_dir" in result

    def test_returns_same_instance_on_repeated_calls(self, isolated_config):
        first = cfg.get()
        second = cfg.get()
        assert first is second


class TestDataDir:
    def test_returns_path_object(self, isolated_config):
        from pathlib import Path

        assert isinstance(cfg.data_dir(), Path)

    def test_returns_configured_path(self, isolated_config):
        from pathlib import Path

        assert cfg.data_dir() == Path(str(isolated_config / "data"))


class TestInitDataDir:
    def test_creates_all_subdirectories(self, isolated_config):
        cfg.load()
        cfg.init_data_dir()
        root = cfg.data_dir()
        for subdir in ["clutches", "media", "automation/os_config", "automation/scripts"]:
            assert (root / subdir).is_dir(), f"Expected {subdir}/ to exist"

    def test_is_idempotent(self, isolated_config):
        cfg.load()
        cfg.init_data_dir()
        cfg.init_data_dir()

    def test_creates_root_if_missing(self, isolated_config):
        cfg.load()
        assert not cfg.data_dir().exists()
        cfg.init_data_dir()
        assert cfg.data_dir().is_dir()


class TestBgInterval:
    def test_returns_default(self, isolated_config):
        cfg.load()
        cfg.bind_db()
        assert cfg.bg_interval() == 60

    def test_returns_configured_value(self, isolated_config):
        cfg.load()
        cfg.bind_db()
        cfg.save({**cfg.get(), "bg_interval": 30})
        assert cfg.bg_interval() == 30

    def test_returns_int(self, isolated_config):
        cfg.load()
        cfg.bind_db()
        assert isinstance(cfg.bg_interval(), int)


class TestLibraryEnabled:
    def test_default_false(self, isolated_config):
        cfg.load()
        cfg.bind_db()
        assert cfg.library_enabled() is False

    def test_persists_true(self, isolated_config):
        cfg.load()
        cfg.bind_db()
        cfg.save({**cfg.get(), "library_enabled": True})
        cfg._config = {}
        cfg._db_bound = False
        cfg.load()
        cfg.bind_db()
        assert cfg.library_enabled() is True
