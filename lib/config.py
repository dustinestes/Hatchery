import os
import yaml
from pathlib import Path

_APP_NAME = "hatchery"
_DATA_SUBDIRS = ["clutches", "media", "automation"]


def _default_config_file() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / _APP_NAME / "config.yaml"


def _default_data_dir() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / _APP_NAME


CONFIG_FILE: Path = _default_config_file()
DEFAULT_DATA_DIR: Path = _default_data_dir()

_DEFAULTS: dict = {"data_dir": str(DEFAULT_DATA_DIR)}
_config: dict = {}


def load() -> dict:
    """Load config from disk, writing defaults if the file does not exist."""
    global _config
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            on_disk = yaml.safe_load(f) or {}
        _config = {**_DEFAULTS, **on_disk}
    else:
        _config = dict(_DEFAULTS)
        _write(_config)
    return _config


def save(cfg: dict) -> None:
    """Persist updated config to disk and update the in-memory state."""
    global _config
    _config = cfg
    _write(cfg)


def get() -> dict:
    """Return in-memory config, loading from disk on first call."""
    if not _config:
        load()
    return _config


def data_dir() -> Path:
    """Return the configured data directory as a Path."""
    return Path(get()["data_dir"])


def init_data_dir() -> None:
    """Create the data directory and all subdirectories if they do not exist."""
    root = data_dir()
    for subdir in _DATA_SUBDIRS:
        (root / subdir).mkdir(parents=True, exist_ok=True)


def _write(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False)
