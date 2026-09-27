"""Software package inventory under ``automation/software/`` (#469, ADR-0025).

Package id = directory name ``Publisher.Product.Version``. Display labels come from
``software.yaml`` (light parse; full schema validation is #471).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from lib import config

SUBDIR = "automation/software"
DEFINITION_FILENAME = "software.yaml"


def software_root() -> Path:
    """Return the Software packages directory under the data dir."""
    return config.data_dir() / "automation" / "software"


def resolve_package_path(package_id: str) -> Path | None:
    """Return the package directory path, or None if the id is invalid / escapes."""
    safe = Path(package_id).name
    if not safe or safe in (".", ".."):
        return None
    root = software_root().resolve()
    candidate = (root / safe).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def resolve_definition_path(package_id: str) -> Path | None:
    """Return ``software.yaml`` under the package dir, or None if invalid."""
    pkg = resolve_package_path(package_id)
    if pkg is None:
        return None
    return pkg / DEFINITION_FILENAME


def load_display_meta(definition_path: Path) -> dict[str, str]:
    """Light-parse ``software.yaml`` for inventory display fields.

    Tolerates missing or invalid YAML (#471 owns authoritative validation).
    Returns publisher / product / version / architecture strings (possibly empty).
    """
    out = {
        "publisher": "",
        "product": "",
        "version": "",
        "architecture": "",
    }
    if not definition_path.is_file():
        return out
    try:
        raw = yaml.safe_load(definition_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return out
    if not isinstance(raw, dict):
        return out
    hatchery = raw.get("hatchery")
    if not isinstance(hatchery, dict):
        return out
    for key in out:
        val = hatchery.get(key)
        if val is None:
            continue
        out[key] = str(val).strip()
    return out


def display_subtitle(meta: dict[str, str]) -> str:
    """Short rail subtitle from YAML meta (fallback when sparse)."""
    parts = [meta.get("publisher") or "", meta.get("product") or ""]
    label = " · ".join(p for p in parts if p)
    version = meta.get("version") or ""
    if label and version:
        return f"{label} {version}"
    if label:
        return label
    if version:
        return version
    return "Software"


def scan_inventory() -> list[dict[str, Any]]:
    """Return inventory metadata for package dirs under ``automation/software/``."""
    path = software_root()
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    for entry in sorted(path.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        definition = entry / DEFINITION_FILENAME
        meta = load_display_meta(definition)
        try:
            mtime = entry.stat().st_mtime
            if definition.is_file():
                mtime = max(mtime, definition.stat().st_mtime)
        except OSError:
            continue
        modified = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        items.append(
            {
                "name": entry.name,
                "relative_path": f"{SUBDIR}/{entry.name}",
                "absolute_path": str(entry.resolve()),
                "publisher": meta["publisher"],
                "product": meta["product"],
                "version": meta["version"],
                "architecture": meta["architecture"],
                "subtitle": display_subtitle(meta),
                "modified_at": modified,
                "has_definition": definition.is_file(),
            }
        )
    return items


def delete_package(package_id: str) -> tuple[bool, str]:
    """Remove a package directory tree. Returns ``(ok, error_message)``."""
    import shutil

    pkg = resolve_package_path(package_id)
    if pkg is None or not pkg.is_dir():
        return False, "not found"
    try:
        shutil.rmtree(pkg)
    except OSError as exc:
        return False, str(exc)
    return True, ""
