"""Application configuration: minimal bootstrap file + SQLite settings.

Bootstrap (``~/.config/hatchery/config.yaml``) holds only ``data_dir`` so Hatchery
can locate ``hatchery.db``. Operational Settings live in the ``app_settings``
table inside that database.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from lib import db as db_module

_APP_NAME = "hatchery"
_DATA_SUBDIRS = [
    "clutches",
    "media/iso",
    "media/virtio",
    "media/vhd",
    "media/qemu",
    "automation/os_config",
    "automation/scripts",
]

# Keys that may live in the external bootstrap YAML (only data_dir for now).
_BOOTSTRAP_KEYS = frozenset({"data_dir"})

# Operational Settings persisted in SQLite ``app_settings``.
_DB_SETTING_KEYS = frozenset(
    {
        "bg_interval",
        "show_passwords",
        "display_timezone",
        "nest_key_alert_tiers",
        "nest_ssh_identities",
    }
)


def _default_config_file() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / _APP_NAME / "config.yaml"


def _default_data_dir() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / _APP_NAME


CONFIG_FILE: Path = _default_config_file()
DEFAULT_DATA_DIR: Path = _default_data_dir()

_DEFAULTS: dict = {
    "data_dir": str(DEFAULT_DATA_DIR),
    "bg_interval": 60,
    "show_passwords": False,
    "display_timezone": "UTC",
    # Nest SSH identity expiry alerts (#219) — tiers + tracked identities (until Nest registry).
    "nest_key_alert_tiers": [
        {"days_before": 30, "alerts_per_day": 1},
        {"days_before": 7, "alerts_per_day": 2},
    ],
    "nest_ssh_identities": [],
}
_config: dict = {}
# Legacy non-bootstrap keys found in config.yaml pending first DB bind.
_pending_yaml_settings: dict = {}
_db_bound: bool = False


def load() -> dict:
    """Load the bootstrap file and merge defaults into memory.

    Does not read SQLite — call :func:`bind_db` after ``db.init_db``.
    """
    global _config, _pending_yaml_settings, _db_bound
    _db_bound = False
    _pending_yaml_settings = {}

    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            on_disk = yaml.safe_load(f) or {}
        if not isinstance(on_disk, dict):
            on_disk = {}
        data_dir = on_disk.get("data_dir", _DEFAULTS["data_dir"])
        legacy = {k: v for k, v in on_disk.items() if k in _DB_SETTING_KEYS}
        _pending_yaml_settings = dict(legacy)
        _config = {**_DEFAULTS, **legacy, "data_dir": str(data_dir)}
        if set(on_disk.keys()) - _BOOTSTRAP_KEYS:
            # Drop migrated keys from the bootstrap file; pending values stay in
            # memory until bind_db writes them into SQLite.
            _write_bootstrap({"data_dir": _config["data_dir"]})
    else:
        _config = dict(_DEFAULTS)
        _write_bootstrap({"data_dir": _config["data_dir"]})
    return _config


def bind_db() -> dict:
    """Load or migrate Settings from SQLite into memory. Requires ``db.init_db``."""
    global _config, _pending_yaml_settings, _db_bound
    if not _config:
        load()

    existing = _read_db_settings()
    if not existing:
        source = dict(_pending_yaml_settings) if _pending_yaml_settings else {}
        for key in _DB_SETTING_KEYS:
            if key not in source:
                source[key] = _config.get(key, _DEFAULTS[key])
        _write_db_settings(source)
        existing = source
    else:
        missing = {k: _DEFAULTS[k] for k in _DB_SETTING_KEYS if k not in existing}
        if missing:
            _write_db_settings({**existing, **missing})
            existing = {**existing, **missing}

    _config = {
        **_DEFAULTS,
        **{k: existing[k] for k in _DB_SETTING_KEYS if k in existing},
        "data_dir": _config["data_dir"],
    }
    _pending_yaml_settings = {}
    _db_bound = True
    _write_bootstrap({"data_dir": _config["data_dir"]})
    return _config


def save(cfg: dict) -> None:
    """Persist ``data_dir`` to the bootstrap file and other keys to SQLite."""
    global _config
    merged = {**_DEFAULTS, **cfg}
    _config = merged
    _write_bootstrap({"data_dir": merged["data_dir"]})
    if _db_path_ready():
        _write_db_settings({k: merged[k] for k in _DB_SETTING_KEYS})
        global _db_bound
        _db_bound = True


def get() -> dict:
    """Return in-memory config, loading the bootstrap file on first call."""
    if not _config:
        load()
    return _config


def data_dir() -> Path:
    """Return the configured data directory as a Path."""
    return Path(get()["data_dir"])


def bg_interval() -> int:
    """Return the background re-evaluation interval in seconds."""
    return int(get()["bg_interval"])


def show_passwords() -> bool:
    """Return whether admin passwords should be displayed in the VM inventory."""
    return bool(get().get("show_passwords", False))


def display_timezone() -> str:
    """Return the timestamp timezone preference: 'UTC' or 'local'."""
    val = str(get().get("display_timezone", "UTC"))
    return val if val in ("UTC", "local") else "UTC"


def nest_key_alert_tiers() -> list:
    """Return Nest SSH key expiry alert tiers (list of dicts)."""
    return list(get().get("nest_key_alert_tiers") or [])


def nest_ssh_identities() -> list:
    """Return tracked Nest SSH identities for expiry alerts (list of dicts)."""
    return list(get().get("nest_ssh_identities") or [])


def init_data_dir() -> None:
    """Create the data directory and all subdirectories if they do not exist."""
    root = data_dir()
    for subdir in _DATA_SUBDIRS:
        (root / subdir).mkdir(parents=True, exist_ok=True)


def _write_bootstrap(cfg: dict) -> None:
    """Write only bootstrap keys to the external YAML file."""
    payload = {k: cfg[k] for k in _BOOTSTRAP_KEYS if k in cfg}
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(payload, f, default_flow_style=False)


def _db_path_ready() -> bool:
    return db_module.is_initialized()


def _read_db_settings() -> dict:
    if not _db_path_ready():
        return {}
    conn = db_module.get_connection()
    try:
        rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    finally:
        conn.close()
    out: dict = {}
    for row in rows:
        key = row["key"]
        if key not in _DB_SETTING_KEYS:
            continue
        try:
            out[key] = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            continue
    return out


def _write_db_settings(settings: dict) -> None:
    if not _db_path_ready():
        raise RuntimeError("db not initialized — call init_db() before saving settings")
    conn = db_module.get_connection()
    try:
        for key in _DB_SETTING_KEYS:
            if key not in settings:
                continue
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(settings[key])),
            )
        conn.commit()
    finally:
        conn.close()
