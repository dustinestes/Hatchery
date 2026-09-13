"""Settings profile export/import — portable YAML for ``app_settings``.

Profiles carry operational Settings (SQLite keys) across machines. Bootstrap
``data_dir`` is never applied from a profile; operators set that out of band.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal

import yaml

from lib import config as config_lib
from lib import library as library_lib
from lib import nest_key_expiry as nest_key_expiry_lib

PROFILE_VERSION = 1
ApplyMode = Literal["merge", "replace"]

_LIST_KEYS_BY_ID = frozenset(
    {
        "library_connections",
        "library_script_bindings",
        "library_clutch_bindings",
        "library_media_bindings",
        "nest_ssh_identities",
    }
)


def export_profile(*, include_meta: bool = True) -> dict[str, Any]:
    """Build a versioned profile dict from the current in-memory Settings."""
    cfg = config_lib.get()
    settings: dict[str, Any] = {}
    for key in sorted(config_lib.profile_setting_keys()):
        settings[key] = deepcopy(cfg.get(key, config_lib.default_for(key)))
    out: dict[str, Any] = {"version": PROFILE_VERSION, "settings": settings}
    if include_meta:
        out["exported_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


def dump_yaml(profile: dict[str, Any]) -> str:
    """Serialize a profile dict to YAML text."""
    return yaml.dump(profile, default_flow_style=False, sort_keys=False, allow_unicode=True)


def load_yaml(text: str) -> dict[str, Any]:
    """Parse YAML text into a profile dict (not yet validated)."""
    raw = yaml.safe_load(text)
    if raw is None:
        raise ValueError("Profile is empty")
    if not isinstance(raw, dict):
        raise ValueError("Profile must be a YAML mapping")
    return raw


def validate_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a profile. Returns ``{version, settings, warnings}``.

    ``settings`` contains only known profile keys, fully normalized. Library
    bindings are checked against connections when both appear in the profile;
    final cross-checks run in :func:`apply_profile` against the merged config.
    """
    warnings: list[str] = []
    version = raw.get("version")
    try:
        version_n = int(version)
    except (TypeError, ValueError) as exc:
        raise ValueError("Profile version must be an integer") from exc
    if version_n != PROFILE_VERSION:
        raise ValueError(f"Unsupported profile version: {version_n} (expected {PROFILE_VERSION})")

    if "data_dir" in raw or (
        isinstance(raw.get("settings"), dict) and "data_dir" in raw["settings"]
    ):
        warnings.append(
            "Bootstrap data_dir in the profile was ignored — set the data directory under "
            "Settings → General on this machine."
        )

    settings_raw = raw.get("settings")
    if settings_raw is None:
        settings_raw = {k: v for k, v in raw.items() if k in config_lib.profile_setting_keys()}
    if not isinstance(settings_raw, dict):
        raise ValueError("Profile settings must be a mapping")

    unknown = sorted(set(settings_raw) - config_lib.profile_setting_keys() - {"data_dir"})
    for key in unknown:
        warnings.append(f"Unknown settings key ignored: {key}")

    normalized: dict[str, Any] = {}
    for key in config_lib.profile_setting_keys():
        if key not in settings_raw:
            continue
        normalized[key] = _normalize_setting(key, settings_raw[key])

    if "library_connections" in normalized:
        _validate_library_slice(normalized)

    return {"version": PROFILE_VERSION, "settings": normalized, "warnings": warnings}


def apply_profile(raw: dict[str, Any], *, mode: ApplyMode) -> dict[str, Any]:
    """Validate and apply a profile to live Settings.

    Returns ``{ok, mode, warnings, applied}``.
    """
    if mode not in ("merge", "replace"):
        raise ValueError("mode must be 'merge' or 'replace'")
    validated = validate_profile(raw)
    incoming = validated["settings"]
    warnings = list(validated["warnings"])

    current = deepcopy(config_lib.get())
    data_dir = current["data_dir"]

    if mode == "replace":
        new_cfg = {**config_lib.defaults_for_profile(), "data_dir": data_dir}
        new_cfg.update(incoming)
    else:
        new_cfg = current
        for key, value in incoming.items():
            if key in _LIST_KEYS_BY_ID:
                new_cfg[key] = _merge_by_id(list(new_cfg.get(key) or []), value)
            else:
                # Scalars and nest_key_alert_tiers (whole-list replace when present).
                new_cfg[key] = value

    _validate_library_full(new_cfg)
    nest_key_expiry_lib.parse_tiers(new_cfg.get("nest_key_alert_tiers"))
    nest_key_expiry_lib.parse_identities(new_cfg.get("nest_ssh_identities") or [])

    bg = int(new_cfg.get("bg_interval", 60))
    if bg < 10:
        raise ValueError("bg_interval must be at least 10 seconds")
    new_cfg["bg_interval"] = bg

    tz = str(new_cfg.get("display_timezone") or "UTC")
    if tz not in ("UTC", "local"):
        raise ValueError("display_timezone must be UTC or local")
    new_cfg["display_timezone"] = tz
    new_cfg["show_passwords"] = bool(new_cfg.get("show_passwords", False))
    new_cfg["library_enabled"] = bool(new_cfg.get("library_enabled", False))
    new_cfg["data_dir"] = data_dir

    config_lib.save(new_cfg)
    applied = (
        sorted(incoming.keys()) if mode == "merge" else sorted(config_lib.profile_setting_keys())
    )
    return {"ok": True, "mode": mode, "warnings": warnings, "applied": applied}


def _normalize_setting(key: str, value: Any) -> Any:
    if key == "bg_interval":
        try:
            n = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("bg_interval must be an integer") from exc
        if n < 10:
            raise ValueError("bg_interval must be at least 10 seconds")
        return n
    if key == "show_passwords":
        return bool(value)
    if key == "library_enabled":
        return bool(value)
    if key == "display_timezone":
        text = str(value or "UTC").strip()
        if text not in ("UTC", "local"):
            raise ValueError("display_timezone must be UTC or local")
        return text
    if key == "nest_key_alert_tiers":
        tiers = nest_key_expiry_lib.parse_tiers(value)
        return [{"days_before": t.days_before, "alerts_per_day": t.alerts_per_day} for t in tiers]
    if key == "nest_ssh_identities":
        if not isinstance(value, list):
            raise ValueError("nest_ssh_identities must be a list")
        nest_key_expiry_lib.parse_identities(value)
        return deepcopy(value)
    if key == "library_connections":
        if not isinstance(value, list):
            raise ValueError("library_connections must be a list")
        return library_lib.parse_connections(value, enforce_expiry_future=False)
    if key in (
        "library_script_bindings",
        "library_clutch_bindings",
        "library_media_bindings",
    ):
        if not isinstance(value, list):
            raise ValueError(f"{key} must be a list")
        return deepcopy(value)
    raise ValueError(f"Unsupported settings key: {key}")


def _validate_library_slice(settings: dict[str, Any]) -> None:
    """Validate bindings in the profile against connections also in the profile."""
    conns = settings["library_connections"]
    if "library_script_bindings" in settings:
        settings["library_script_bindings"] = library_lib.parse_script_bindings(
            settings["library_script_bindings"], conns
        )
    if "library_clutch_bindings" in settings:
        settings["library_clutch_bindings"] = library_lib.parse_clutch_bindings(
            settings["library_clutch_bindings"], conns
        )
    if "library_media_bindings" in settings:
        settings["library_media_bindings"] = library_lib.parse_media_bindings(
            settings["library_media_bindings"], conns
        )


def _validate_library_full(cfg: dict[str, Any]) -> None:
    conns = library_lib.parse_connections(
        cfg.get("library_connections") or [],
        enforce_expiry_future=False,
    )
    cfg["library_connections"] = conns
    cfg["library_script_bindings"] = library_lib.parse_script_bindings(
        cfg.get("library_script_bindings") or [], conns
    )
    cfg["library_clutch_bindings"] = library_lib.parse_clutch_bindings(
        cfg.get("library_clutch_bindings") or [], conns
    )
    cfg["library_media_bindings"] = library_lib.parse_media_bindings(
        cfg.get("library_media_bindings") or [], conns
    )


def _merge_by_id(existing: list, incoming: list) -> list:
    by_id: dict[str, Any] = {}
    order: list[str] = []
    for item in existing:
        if not isinstance(item, dict):
            continue
        iid = str(item.get("id") or "").strip()
        if not iid:
            continue
        by_id[iid] = deepcopy(item)
        order.append(iid)
    for item in incoming:
        if not isinstance(item, dict):
            continue
        iid = str(item.get("id") or "").strip()
        if not iid:
            continue
        if iid not in by_id:
            order.append(iid)
        by_id[iid] = deepcopy(item)
    return [by_id[i] for i in order]
