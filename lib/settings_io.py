"""Settings export/import - portable YAML for ``app_settings``.

Operational Settings (SQLite keys) can be downloaded and re-applied across
machines as a full document replace. Bootstrap ``data_dir`` is never applied
from an import; operators set that out of band.

Library connections/bindings live in first-class tables (ADR-0017) and are not
part of Settings export/import. Legacy keys in an old document are ignored with
a warning (registry is not wiped).
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import yaml

from lib import config as config_lib
from lib import nest_key_expiry as nest_key_expiry_lib

DOCUMENT_VERSION = 1

_LEGACY_LIBRARY_KEYS = frozenset(
    {
        "library_connections",
        "library_script_bindings",
        "library_clutch_bindings",
        "library_media_bindings",
    }
)


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
    exportable keys.
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
            "Bootstrap data_dir in the file was ignored - set the data directory under "
            "Settings → General on this machine."
        )

    settings_raw = raw.get("settings")
    if settings_raw is None:
        settings_raw = {k: v for k, v in raw.items() if k in config_lib.exportable_setting_keys()}
    if not isinstance(settings_raw, dict):
        raise ValueError("Settings document settings must be a mapping")

    for key in sorted(set(settings_raw) & _LEGACY_LIBRARY_KEYS):
        warnings.append(
            f"Legacy Settings key ignored (Library registry is SQLite, ADR-0017): {key}"
        )

    unknown = sorted(
        set(settings_raw)
        - config_lib.exportable_setting_keys()
        - {"data_dir"}
        - _LEGACY_LIBRARY_KEYS
    )
    for key in unknown:
        warnings.append(f"Unknown settings key ignored: {key}")

    normalized: dict[str, Any] = {}
    for key in config_lib.exportable_setting_keys():
        if key not in settings_raw:
            continue
        normalized[key] = _normalize_setting(key, settings_raw[key])

    return {"version": DOCUMENT_VERSION, "settings": normalized, "warnings": warnings}


def apply_document(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and replace live Settings with the document.

    Starts from exportable-key defaults, applies keys present in the file, keeps
    local ``data_dir``. Omitted keys reset to Hatchery defaults - what you import
    is what you get. Library connection/binding tables are not modified.

    Returns ``{ok, warnings, applied}``.
    """
    validated = validate_document(raw)
    incoming = validated["settings"]
    warnings = list(validated["warnings"])

    current = deepcopy(config_lib.get())
    data_dir = current["data_dir"]

    new_cfg = {**config_lib.defaults_for_exportable_settings(), "data_dir": data_dir}
    new_cfg.update(incoming)

    nest_key_expiry_lib.parse_tiers(new_cfg.get("nest_key_alert_tiers"))
    nest_key_expiry_lib.parse_identities(new_cfg.get("nest_ssh_identities") or [])

    bg = int(new_cfg.get("bg_interval", 60))
    if bg < 10:
        raise ValueError("bg_interval must be at least 10 seconds")
    new_cfg["bg_interval"] = bg

    retention = int(new_cfg.get("validators_run_retention", 50))
    if retention < 10 or retention > 500:
        raise ValueError("validators_run_retention must be between 10 and 500")
    new_cfg["validators_run_retention"] = retention

    validators = new_cfg.get("validators") or {}
    if not isinstance(validators, dict):
        raise ValueError("validators must be an object map")
    new_cfg["validators"] = validators

    tz = str(new_cfg.get("display_timezone") or "UTC")
    if tz not in ("UTC", "local"):
        raise ValueError("display_timezone must be UTC or local")
    new_cfg["display_timezone"] = tz
    new_cfg["show_passwords"] = bool(new_cfg.get("show_passwords", False))
    new_cfg["library_enabled"] = bool(new_cfg.get("library_enabled", False))
    new_cfg["data_dir"] = data_dir

    config_lib.save(new_cfg)
    from lib import library_health as library_health_lib
    from lib import library_registry as library_registry_lib

    if not new_cfg.get("library_enabled"):
        library_health_lib.resolve_all_library_alerts()
    else:
        library_health_lib.prune_alerts_for_removed_connections(
            {c["id"] for c in library_registry_lib.list_connections()}
        )
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
    if key == "validators_run_retention":
        try:
            n = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("validators_run_retention must be an integer") from exc
        if n < 10 or n > 500:
            raise ValueError("validators_run_retention must be between 10 and 500")
        return n
    if key == "validators":
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("validators must be an object")
        return value
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
    raise ValueError(f"Unsupported settings key: {key}")
