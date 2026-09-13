"""Settings export/import — portable YAML for ``app_settings``.

Operational Settings (SQLite keys) can be downloaded and re-applied across
machines as a full document replace. Bootstrap ``data_dir`` is never applied
from an import; operators set that out of band.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import yaml

from lib import config as config_lib
from lib import library as library_lib
from lib import nest_key_expiry as nest_key_expiry_lib

DOCUMENT_VERSION = 1


def export_document(*, include_meta: bool = True) -> dict[str, Any]:
    """Build a versioned Settings document from the current in-memory Settings."""
    cfg = config_lib.get()
    settings: dict[str, Any] = {}
    for key in sorted(config_lib.exportable_setting_keys()):
        settings[key] = deepcopy(cfg.get(key, config_lib.default_for(key)))
    out: dict[str, Any] = {"version": DOCUMENT_VERSION, "settings": settings}
    if include_meta:
        out["exported_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


def dump_yaml(document: dict[str, Any]) -> str:
    """Serialize a Settings document to YAML text."""
    return yaml.dump(document, default_flow_style=False, sort_keys=False, allow_unicode=True)


def load_yaml(text: str) -> dict[str, Any]:
    """Parse YAML text into a Settings document dict (not yet validated)."""
    raw = yaml.safe_load(text)
    if raw is None:
        raise ValueError("Settings document is empty")
    if not isinstance(raw, dict):
        raise ValueError("Settings document must be a YAML mapping")
    return raw


def validate_document(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a Settings document.

    Returns ``{version, settings, warnings}``. ``settings`` contains only known
    exportable keys. Library bindings are checked against connections when both
    appear in the document; final cross-checks run in :func:`apply_document`.
    """
    warnings: list[str] = []
    version = raw.get("version")
    try:
        version_n = int(version)
    except (TypeError, ValueError) as exc:
        raise ValueError("Settings document version must be an integer") from exc
    if version_n != DOCUMENT_VERSION:
        raise ValueError(
            f"Unsupported Settings document version: {version_n} (expected {DOCUMENT_VERSION})"
        )

    if "data_dir" in raw or (
        isinstance(raw.get("settings"), dict) and "data_dir" in raw["settings"]
    ):
        warnings.append(
            "Bootstrap data_dir in the file was ignored — set the data directory under "
            "Settings → General on this machine."
        )

    settings_raw = raw.get("settings")
    if settings_raw is None:
        settings_raw = {k: v for k, v in raw.items() if k in config_lib.exportable_setting_keys()}
    if not isinstance(settings_raw, dict):
        raise ValueError("Settings document settings must be a mapping")

    unknown = sorted(set(settings_raw) - config_lib.exportable_setting_keys() - {"data_dir"})
    for key in unknown:
        warnings.append(f"Unknown settings key ignored: {key}")

    normalized: dict[str, Any] = {}
    for key in config_lib.exportable_setting_keys():
        if key not in settings_raw:
            continue
        normalized[key] = _normalize_setting(key, settings_raw[key])

    if "library_connections" in normalized:
        _validate_library_slice(normalized)

    return {"version": DOCUMENT_VERSION, "settings": normalized, "warnings": warnings}


def apply_document(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and replace live Settings with the document.

    Starts from exportable-key defaults, applies keys present in the file, keeps
    local ``data_dir``. Omitted keys reset to Hatchery defaults — what you import
    is what you get.

    Returns ``{ok, warnings, applied}``.
    """
    validated = validate_document(raw)
    incoming = validated["settings"]
    warnings = list(validated["warnings"])

    current = deepcopy(config_lib.get())
    data_dir = current["data_dir"]

    new_cfg = {**config_lib.defaults_for_exportable_settings(), "data_dir": data_dir}
    new_cfg.update(incoming)

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
    return {
        "ok": True,
        "warnings": warnings,
        "applied": sorted(config_lib.exportable_setting_keys()),
    }


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
    """Validate bindings in the document against connections also in the document."""
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
