"""Application configuration: minimal bootstrap file + SQLite settings.

Bootstrap (``~/.config/hatchery/config.yaml``) holds only ``data_dir`` so Hatchery
can locate ``hatchery.db``. Operational Settings live in the ``app_settings``
table inside that database.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
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
        "validators",
        "validators_run_retention",
        "nest_reachability_status",
        "show_passwords",
        "display_timezone",
        "nest_key_alert_tiers",
        "nest_ssh_identities",
        "library_enabled",
        "library_connections",
        "library_script_bindings",
        "library_clutch_bindings",
        "library_media_bindings",
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
    "validators": {},
    "validators_run_retention": 50,
    "nest_reachability_status": {},
    "show_passwords": False,
    "display_timezone": "UTC",
    "library_enabled": False,
    "library_connections": [],
    "library_script_bindings": [],
    "library_clutch_bindings": [],
    "library_media_bindings": [],
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
# Session-only data_dir from CLI / HATCHERY_DATA_DIR (ADR-0013). Never written to bootstrap.
_runtime_data_dir: str | None = None
# Session-only: register this Controller as Local Nest (ADR-0014). CLI / HATCHERY_NEST_LOCAL.
_runtime_nest_local: bool = False
# Last bootstrap data_dir from disk (or default); used when writing bootstrap under an override.
_bootstrap_data_dir: str | None = None


def set_runtime_data_dir(path: str | Path | None) -> None:
    """Set or clear a session-only ``data_dir`` override (does not write Settings)."""
    global _runtime_data_dir
    if path is None or path == "":
        _runtime_data_dir = None
        return
    _runtime_data_dir = str(Path(path).expanduser().resolve())


def runtime_data_dir() -> str | None:
    """Return the session ``data_dir`` override, if any."""
    return _runtime_data_dir


def set_runtime_nest_local(enabled: bool) -> None:
    """Set or clear session-only Local Nest registration (does not write Settings)."""
    global _runtime_nest_local
    _runtime_nest_local = bool(enabled)


def runtime_nest_local() -> bool:
    """Return whether the session requested Local Nest registration."""
    return _runtime_nest_local


def nest_local_enabled() -> bool:
    """True when CLI ``--nest-local`` or env ``HATCHERY_NEST_LOCAL`` is set."""
    if _runtime_nest_local:
        return True
    env = os.environ.get("HATCHERY_NEST_LOCAL", "").strip().lower()
    return env in ("1", "true", "yes")


def _effective_data_dir(bootstrap: str) -> str:
    env = os.environ.get("HATCHERY_DATA_DIR", "").strip()
    if _runtime_data_dir:
        return _runtime_data_dir
    if env:
        return str(Path(env).expanduser().resolve())
    return bootstrap


def load() -> dict:
    """Load the bootstrap file and merge defaults into memory.

    Does not read SQLite — call :func:`bind_db` after ``db.init_db``.
    Honors :func:`set_runtime_data_dir` and ``HATCHERY_DATA_DIR`` without writing them
    back to the bootstrap file (ADR-0013).
    """
    global _config, _pending_yaml_settings, _db_bound, _bootstrap_data_dir
    _db_bound = False
    _pending_yaml_settings = {}

    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            on_disk = yaml.safe_load(f) or {}
        if not isinstance(on_disk, dict):
            on_disk = {}
        bootstrap = str(on_disk.get("data_dir", _DEFAULTS["data_dir"]))
        legacy = {k: v for k, v in on_disk.items() if k in _DB_SETTING_KEYS}
        _pending_yaml_settings = dict(legacy)
        _bootstrap_data_dir = bootstrap
        _config = {**_DEFAULTS, **legacy, "data_dir": _effective_data_dir(bootstrap)}
        if set(on_disk.keys()) - _BOOTSTRAP_KEYS:
            # Drop migrated keys from the bootstrap file; pending values stay in
            # memory until bind_db writes them into SQLite.
            if runtime_data_dir() is None and not os.environ.get("HATCHERY_DATA_DIR", "").strip():
                _write_bootstrap({"data_dir": _bootstrap_data_dir})
    else:
        _bootstrap_data_dir = str(_DEFAULTS["data_dir"])
        _config = {**_DEFAULTS, "data_dir": _effective_data_dir(_bootstrap_data_dir)}
        if runtime_data_dir() is None and not os.environ.get("HATCHERY_DATA_DIR", "").strip():
            _write_bootstrap({"data_dir": _bootstrap_data_dir})
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

    effective = _effective_data_dir(_bootstrap_data_dir or _config["data_dir"])
    _config = {
        **_DEFAULTS,
        **{k: existing[k] for k in _DB_SETTING_KEYS if k in existing},
        "data_dir": effective,
    }
    _pending_yaml_settings = {}
    _db_bound = True
    if runtime_data_dir() is None and not os.environ.get("HATCHERY_DATA_DIR", "").strip():
        _write_bootstrap({"data_dir": _bootstrap_data_dir or _config["data_dir"]})
    return _config


def save(cfg: dict) -> None:
    """Persist ``data_dir`` to the bootstrap file and other keys to SQLite.

    When a session ``data_dir`` override is active, bootstrap ``data_dir`` is left
    unchanged; only SQLite Settings keys are written.
    """
    global _config, _bootstrap_data_dir, _db_bound
    merged = {**_DEFAULTS, **cfg}
    override_active = bool(runtime_data_dir() or os.environ.get("HATCHERY_DATA_DIR", "").strip())
    if override_active:
        _config = {
            **merged,
            "data_dir": _effective_data_dir(_bootstrap_data_dir or merged["data_dir"]),
        }
    else:
        _bootstrap_data_dir = str(merged["data_dir"])
        _config = merged
        _write_bootstrap({"data_dir": _bootstrap_data_dir})
    if _db_path_ready():
        _write_db_settings({k: merged[k] for k in _DB_SETTING_KEYS})
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
    """Return the Hatch status poll interval in seconds."""
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


def library_enabled() -> bool:
    """Return whether the Library feature (Settings section + Import-from-library) is on."""
    return bool(get().get("library_enabled", False))


def library_connections() -> list:
    """Return Library connection registry (list of dicts)."""
    return list(get().get("library_connections") or [])


def library_script_bindings() -> list:
    """Return Scripts domain bindings (list of dicts)."""
    return list(get().get("library_script_bindings") or [])


def library_clutch_bindings() -> list:
    """Return Clutches domain bindings (list of dicts)."""
    return list(get().get("library_clutch_bindings") or [])


def library_media_bindings() -> list:
    """Return Media domain bindings (list of dicts)."""
    return list(get().get("library_media_bindings") or [])


def exportable_setting_keys() -> frozenset[str]:
    """Keys included in Settings export/import (not bootstrap ``data_dir``).

    Runtime caches such as ``nest_reachability_status`` stay in SQLite but are
    not exported.
    """
    return _DB_SETTING_KEYS - {"nest_reachability_status"}


def default_for(key: str):
    """Return the default value for a config key."""
    return deepcopy(_DEFAULTS[key]) if key in _DEFAULTS else None


def defaults_for_exportable_settings() -> dict:
    """Return a copy of all exportable (DB) setting defaults — excludes ``data_dir``."""
    return {k: deepcopy(_DEFAULTS[k]) for k in exportable_setting_keys()}


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
