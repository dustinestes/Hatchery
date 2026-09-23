"""Per-validator Settings persisted in app_settings."""

from __future__ import annotations

from copy import deepcopy

from lib import config
from lib.validators.registry import all_validators

_MIN_INTERVAL = 10
_MIN_RETENTION = 10
_MAX_RETENTION = 500
_DEFAULT_RETENTION = 50

_SETTINGS_KEY = "validators"
_RETENTION_KEY = "validators_run_retention"


def _defaults_map() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for v in all_validators():
        row = {
            "enabled": v.default_enabled,
            "interval_seconds": max(_MIN_INTERVAL, int(v.default_interval_seconds)),
        }
        if getattr(v, "supports_auto_sync", False):
            row["auto_sync"] = bool(getattr(v, "default_auto_sync", False))
        out[v.id] = row
    return out


def get_run_retention() -> int:
    raw = config.get().get(_RETENTION_KEY, _DEFAULT_RETENTION)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = _DEFAULT_RETENTION
    return max(_MIN_RETENTION, min(_MAX_RETENTION, n))


def set_run_retention(n: int) -> None:
    config.update_settings({_RETENTION_KEY: max(_MIN_RETENTION, min(_MAX_RETENTION, int(n)))})


def get_validator_config(validator_id: str) -> dict:
    merged = list_validator_configs()
    for row in merged:
        if row["id"] == validator_id:
            return row
    return {
        "id": validator_id,
        "enabled": True,
        "interval_seconds": 60,
    }


def list_validator_configs() -> list[dict]:
    """Return registry validators merged with saved Settings."""
    stored = config.get().get(_SETTINGS_KEY) or {}
    if not isinstance(stored, dict):
        stored = {}
    defaults = _defaults_map()
    rows: list[dict] = []
    for v in all_validators():
        saved = stored.get(v.id) if isinstance(stored.get(v.id), dict) else {}
        enabled = bool(saved.get("enabled", defaults[v.id]["enabled"]))
        try:
            interval = int(saved.get("interval_seconds", defaults[v.id]["interval_seconds"]))
        except (TypeError, ValueError):
            interval = defaults[v.id]["interval_seconds"]
        interval = max(_MIN_INTERVAL, interval)
        row = {
            "id": v.id,
            "title": v.title,
            "description": v.description,
            "scope": v.scope,
            "enabled": enabled,
            "interval_seconds": interval,
            "stub": getattr(v, "stub", False),
            "supports_auto_sync": bool(getattr(v, "supports_auto_sync", False)),
        }
        if row["supports_auto_sync"]:
            default_auto = bool(getattr(v, "default_auto_sync", False))
            row["auto_sync"] = bool(saved.get("auto_sync", default_auto))
        rows.append(row)
    return rows


def cleaned_validator_settings(
    configs: dict[str, dict],
    *,
    retention: int | None = None,
) -> dict:
    """Normalize validator Settings keys for merging into a config dict."""
    allowed = {v.id for v in all_validators()}
    cleaned: dict[str, dict] = {}
    for vid, raw in (configs or {}).items():
        if vid not in allowed or not isinstance(raw, dict):
            continue
        try:
            interval = int(raw.get("interval_seconds", 60))
        except (TypeError, ValueError):
            interval = 60
        cleaned[vid] = {
            "enabled": bool(raw.get("enabled", True)),
            "interval_seconds": max(_MIN_INTERVAL, interval),
        }
        # Preserve auto_sync for validators that support it
        for v in all_validators():
            if v.id == vid and getattr(v, "supports_auto_sync", False):
                cleaned[vid]["auto_sync"] = bool(raw.get("auto_sync", False))
                break
    out: dict = {_SETTINGS_KEY: cleaned}
    if retention is not None:
        out[_RETENTION_KEY] = max(_MIN_RETENTION, min(_MAX_RETENTION, int(retention)))
    return out


def save_validator_configs(
    configs: dict[str, dict],
    *,
    retention: int | None = None,
) -> None:
    """Persist per-validator enabled/interval; optional retention."""
    config.update_settings(cleaned_validator_settings(configs, retention=retention))


def migrate_bg_interval() -> None:
    """One-shot: if validators map empty, seed intervals from legacy bg_interval."""
    cfg = config.get()
    stored = cfg.get(_SETTINGS_KEY)
    if isinstance(stored, dict) and stored:
        return
    try:
        legacy = max(_MIN_INTERVAL, int(cfg.get("bg_interval", 60)))
    except (TypeError, ValueError):
        legacy = 60
    seeded = deepcopy(_defaults_map())
    for row in seeded.values():
        row["interval_seconds"] = legacy
    config.update_settings({_SETTINGS_KEY: seeded})
