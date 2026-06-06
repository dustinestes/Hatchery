import yaml
import pytest
import lib.config as cfg


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    """Redirect all paths to tmp_path and reset in-memory state for each test."""
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(cfg, "DEFAULT_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(cfg, "_DEFAULTS", {"data_dir": str(tmp_path / "data")})
    monkeypatch.setattr(cfg, "_config", {})
    return tmp_path


class TestLoad:
    def test_creates_config_file_with_defaults_when_missing(self, isolated_config):
        result = cfg.load()
        assert result["data_dir"] == str(isolated_config / "data")
        assert cfg.CONFIG_FILE.exists()

    def test_written_config_is_valid_yaml(self, isolated_config):
        cfg.load()
        with open(cfg.CONFIG_FILE) as f:
            on_disk = yaml.safe_load(f)
        assert on_disk["data_dir"] == str(isolated_config / "data")

    def test_reads_existing_config(self, isolated_config):
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

    def test_empty_config_file_falls_back_to_defaults(self, isolated_config):
        cfg.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        cfg.CONFIG_FILE.write_text("")
        result = cfg.load()
        assert result["data_dir"] == str(isolated_config / "data")


class TestSave:
    def test_persists_to_disk(self, isolated_config):
        new_cfg = {"data_dir": str(isolated_config / "saved")}
        cfg.save(new_cfg)
        with open(cfg.CONFIG_FILE) as f:
            on_disk = yaml.safe_load(f)
        assert on_disk["data_dir"] == str(isolated_config / "saved")

    def test_updates_in_memory_state(self, isolated_config):
        new_cfg = {"data_dir": str(isolated_config / "saved")}
        cfg.save(new_cfg)
        assert cfg.get()["data_dir"] == str(isolated_config / "saved")

    def test_creates_parent_directories(self, isolated_config):
        monkeypatch_path = isolated_config / "deep" / "nested" / "config.yaml"
        cfg.CONFIG_FILE = monkeypatch_path
        cfg.save({"data_dir": str(isolated_config / "data")})
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
        for subdir in ["clutches", "eggs", "automation"]:
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
