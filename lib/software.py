"""Software package inventory and ``software.yaml`` definition schema (#469 / #471).

Package id = directory name ``Publisher.Product.Version``. Lifecycle is keyed by
``platforms.{os}.{arch}`` (ADR-0025); payloads live under ``{os}/{arch}/``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from lib import config

SUBDIR = "automation/software"
DEFINITION_FILENAME = "software.yaml"
PLATFORM_KEYS = frozenset({"windows", "linux", "macos"})
ARCH_KEYS = frozenset({"x86", "x64", "arm64", "any"})


class HookStep(BaseModel):
    """One pre_install / post_install entry: exactly one of command or script."""

    model_config = {"extra": "forbid"}

    command: str | None = None
    script: str | None = None
    success_exit_codes: list[int] = Field(default_factory=lambda: [0])

    @model_validator(mode="after")
    def exactly_one_action(self) -> HookStep:
        cmd = (self.command or "").strip()
        script = (self.script or "").strip()
        if bool(cmd) == bool(script):
            raise ValueError("each hook item needs exactly one of command or script")
        object.__setattr__(self, "command", cmd or None)
        object.__setattr__(self, "script", script or None)
        if not self.success_exit_codes:
            raise ValueError("success_exit_codes must not be empty")
        return self


class InstallStep(BaseModel):
    model_config = {"extra": "forbid"}

    command: str
    success_exit_codes: list[int] = Field(default_factory=lambda: [0])
    reboot_after: bool = False

    @field_validator("command")
    @classmethod
    def command_nonempty(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("command must not be empty")
        return text

    @field_validator("success_exit_codes")
    @classmethod
    def codes_nonempty(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("success_exit_codes must not be empty")
        return v


class CommandStep(BaseModel):
    """Uninstall or detect: required command + success_exit_codes."""

    model_config = {"extra": "forbid"}

    command: str
    success_exit_codes: list[int] = Field(default_factory=lambda: [0])

    @field_validator("command")
    @classmethod
    def command_nonempty(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("command must not be empty")
        return text

    @field_validator("success_exit_codes")
    @classmethod
    def codes_nonempty(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("success_exit_codes must not be empty")
        return v


class ArchUnit(BaseModel):
    """Lifecycle for one ``platforms.{os}.{arch}`` unit."""

    model_config = {"extra": "forbid"}

    pre_install: list[HookStep] = Field(default_factory=list)
    install: InstallStep
    post_install: list[HookStep] = Field(default_factory=list)
    uninstall: CommandStep
    detect: CommandStep


class SoftwareMeta(BaseModel):
    model_config = {"extra": "forbid"}

    kind: Literal["software"] = "software"
    publisher: str
    product: str
    version: str

    @field_validator("publisher", "product", "version")
    @classmethod
    def required_label(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class SoftwareDefinition(BaseModel):
    """Authoritative ``software.yaml`` document (#471 / ADR-0025)."""

    model_config = {"extra": "forbid"}

    hatchery: SoftwareMeta
    platforms: dict[str, dict[str, ArchUnit]]

    @field_validator("platforms")
    @classmethod
    def known_os_and_arch(cls, v: dict[str, dict[str, ArchUnit]]) -> dict[str, dict[str, ArchUnit]]:
        if not v:
            raise ValueError("platforms must declare at least one OS")
        unknown_os = sorted(set(v) - PLATFORM_KEYS)
        if unknown_os:
            raise ValueError(
                f"unknown platform key(s): {', '.join(unknown_os)} "
                f"(expected {', '.join(sorted(PLATFORM_KEYS))})"
            )
        for os_key, arches in v.items():
            if not arches:
                raise ValueError(f"platforms.{os_key}: must declare at least one architecture")
            unknown_arch = sorted(set(arches) - ARCH_KEYS)
            if unknown_arch:
                raise ValueError(
                    f"platforms.{os_key}: unknown architecture key(s): "
                    f"{', '.join(unknown_arch)} "
                    f"(expected {', '.join(sorted(ARCH_KEYS))})"
                )
            if "any" in arches and len(arches) > 1:
                raise ValueError(
                    f"platforms.{os_key}: 'any' cannot be combined with other architecture keys"
                )
        return v

    def architecture_labels(self) -> list[str]:
        """Sorted unique arch keys across all OSes (for inventory display)."""
        labels: set[str] = set()
        for arches in self.platforms.values():
            labels.update(arches)
        return sorted(labels)

    def any_install_reboot_after(self) -> bool:
        """True if any ``platforms.*.*.install.reboot_after`` is set (#563)."""
        for arches in self.platforms.values():
            for unit in arches.values():
                if unit.install.reboot_after:
                    return True
        return False

    def resolve_unit(self, os_key: str, arch_key: str) -> tuple[str, ArchUnit] | None:
        """Return ``(arch_used, unit)`` for guest OS + preferred arch.

        Prefers an exact arch match; falls back to ``any`` under that OS.
        """
        os_n = (os_key or "").strip().lower()
        arch_n = (arch_key or "").strip().lower()
        arches = self.platforms.get(os_n)
        if not arches:
            return None
        if arch_n in arches:
            return arch_n, arches[arch_n]
        if "any" in arches:
            return "any", arches["any"]
        return None

    def payload_relpath(self, os_key: str, arch_key: str) -> str | None:
        """Relative payload dir under the package id (``{os}/{arch}``)."""
        resolved = self.resolve_unit(os_key, arch_key)
        if resolved is None:
            return None
        arch_used, _ = resolved
        return f"{os_key.strip().lower()}/{arch_used}"


def format_validation_errors(exc: ValidationError, *, path: Path | None = None) -> str:
    """Human-readable multi-line validation summary (no raw Pydantic dump)."""
    label = path.name if path is not None else DEFINITION_FILENAME
    lines = [f"Invalid Software definition '{label}':"]
    for err in exc.errors():
        loc = " -> ".join(str(p) for p in err["loc"]) if err["loc"] else "software.yaml"
        msg = err["msg"]
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, ") :]
        lines.append(f"  {loc}: {msg}")
    return "\n".join(lines)


def parse_definition(raw: Any, *, path: Path | None = None) -> SoftwareDefinition:
    """Validate an already-loaded YAML object into ``SoftwareDefinition``."""
    try:
        return SoftwareDefinition.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(format_validation_errors(exc, path=path)) from exc


def load_definition(path: Path | str) -> SoftwareDefinition:
    """Load and validate ``software.yaml`` from disk. Raises ``ValueError`` on failure."""
    definition_path = Path(path)
    try:
        text = definition_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"Cannot read Software definition '{definition_path.name}': {exc}"
        ) from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in '{definition_path.name}': {exc}") from exc
    if raw is None:
        raise ValueError(f"Invalid Software definition '{definition_path.name}': document is empty")
    if not isinstance(raw, dict):
        raise ValueError(
            f"Invalid Software definition '{definition_path.name}': root must be a mapping"
        )
    return parse_definition(raw, path=definition_path)


def try_load_definition(path: Path | str) -> tuple[SoftwareDefinition | None, str | None]:
    """Return ``(definition, None)`` or ``(None, error_message)``."""
    try:
        return load_definition(path), None
    except ValueError as exc:
        return None, str(exc)


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

    Tolerates missing or invalid YAML so the rail still lists packages; use
    ``load_definition`` / ``try_load_definition`` for authoritative checks.
    ``architecture`` is a display join of ``platforms.*.*`` arch keys (not a
    ``hatchery`` field).
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
    if isinstance(hatchery, dict):
        for key in ("publisher", "product", "version"):
            val = hatchery.get(key)
            if val is None:
                continue
            out[key] = str(val).strip()
    platforms = raw.get("platforms")
    if isinstance(platforms, dict):
        labels: set[str] = set()
        for arches in platforms.values():
            if isinstance(arches, dict):
                labels.update(str(k) for k in arches)
        out["architecture"] = ", ".join(sorted(labels))
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
        definition_valid: bool | None = None
        definition_error = ""
        definition_reboot_after = False
        if definition.is_file():
            parsed, err = try_load_definition(definition)
            definition_valid = err is None
            definition_error = err or ""
            if parsed is not None:
                meta["architecture"] = ", ".join(parsed.architecture_labels())
                definition_reboot_after = parsed.any_install_reboot_after()
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
                "definition_valid": definition_valid,
                "definition_error": definition_error,
                "definition_reboot_after": definition_reboot_after,
            }
        )
    return items


def package_definition_reboot_after(package_id: str) -> bool:
    """Return whether any platform unit forces install reboot for ``package_id``."""
    path = resolve_definition_path(package_id)
    if path is None or not path.is_file():
        return False
    parsed, _err = try_load_definition(path)
    if parsed is None:
        return False
    return parsed.any_install_reboot_after()


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
