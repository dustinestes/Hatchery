from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


class GuestOS(str, Enum):
    """Guest OS family (#501). Legacy SKUs migrate on load."""

    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"


class Firmware(str, Enum):
    BIOS = "bios"
    UEFI = "uefi"


class EnvScope(str, Enum):
    MACHINE = "machine"
    USER = "user"


class EnvMode(str, Enum):
    REPLACE = "replace"
    APPEND = "append"


# Legacy Clutch os values → (family, firmware, tpm)
_LEGACY_OS_MIGRATE: dict[str, tuple[str, str, bool]] = {
    "win11": ("windows", "uefi", True),
    "server2025": ("windows", "uefi", True),
    "win10": ("windows", "bios", False),
    "server2022": ("windows", "bios", False),
}


class AutomationEntry(BaseModel):
    """Typed post-boot automation (#473 / ADR-0025).

    Every entry must declare ``type: script`` or ``type: software`` plus ``name``.
    Bare strings are rejected (pre-release break).
    """

    type: str
    name: str
    reboot_after: bool = False
    parameters: dict[str, str] = Field(default_factory=dict)
    clean_payload_on_success: bool = True

    @field_validator("type")
    @classmethod
    def known_type(cls, v: str) -> str:
        t = (v or "").strip().lower()
        if t not in ("script", "software"):
            raise ValueError("type must be 'script' or 'software'")
        return t

    @field_validator("name")
    @classmethod
    def name_nonempty(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("name must not be empty")
        return text

    @model_validator(mode="after")
    def type_specific_fields(self) -> AutomationEntry:
        if self.type == "software" and self.parameters:
            raise ValueError("software automations do not accept parameters")
        return self

    @classmethod
    def coerce(cls, v: Any) -> AutomationEntry:
        if isinstance(v, AutomationEntry):
            return v
        if isinstance(v, str):
            raise ValueError(
                "bare-string automations are not supported; use {type: script|software, name: ...}"
            )
        if not isinstance(v, dict):
            raise ValueError("automation entry must be a mapping with type and name")
        return cls.model_validate(v)


# Back-compat alias for imports that still say AutomationScript.
AutomationScript = AutomationEntry


class EnvironmentEntry(BaseModel):
    """Clutch user guest environment variable (#501 / ADR-0026)."""

    name: str
    value: str = ""
    scope: EnvScope = EnvScope.MACHINE
    persist: bool = True
    mode: EnvMode = EnvMode.REPLACE

    @field_validator("name")
    @classmethod
    def name_portable(cls, v: str) -> str:
        from lib.guest_env import RESERVED_ALL, is_reserved_name

        key = (v or "").strip()
        if not key:
            raise ValueError("environment name must not be empty")
        import re

        if not re.fullmatch(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            raise ValueError(
                f"environment name {key!r} must be a portable identifier "
                "(letters, digits, underscore; not starting with a digit)"
            )
        if is_reserved_name(key):
            raise ValueError(
                f"environment name {key!r} is reserved for Hatchery path roles "
                f"({', '.join(sorted(RESERVED_ALL))})"
            )
        return key


class LibvirtProviderSettings(BaseModel):
    """Stub for ``providers.libvirt`` (#504 / #505). Unknown keys rejected."""

    model_config = ConfigDict(extra="forbid")

    os_variant: str | None = None


class HyperVProviderSettings(BaseModel):
    """Stub for ``providers.hyperv`` (#504 / #506). Unknown keys rejected."""

    model_config = ConfigDict(extra="forbid")


class UtmProviderSettings(BaseModel):
    """Stub for ``providers.utm`` (#504 / #507). Unknown keys rejected."""

    model_config = ConfigDict(extra="forbid")


class ProviderOverlays(BaseModel):
    """Keyed Nest provider overlays (#504). Only the active Nest's bag is applied."""

    model_config = ConfigDict(extra="forbid")

    libvirt: LibvirtProviderSettings | None = None
    hyperv: HyperVProviderSettings | None = None
    utm: UtmProviderSettings | None = None


class VMConfig(BaseModel):
    name: str
    os: GuestOS
    vcpus: int
    ram_gb: int
    disk_gb: int
    os_media: str
    virtio_drivers: str | None = None
    firmware: Firmware | None = None
    tpm: bool | None = None
    answer_file: str | None = Field(
        default=None,
        validation_alias=AliasChoices("answer_file", "os_config"),
    )
    answer_file_parameters: dict[str, str] = {}
    environment: list[EnvironmentEntry] = Field(default_factory=list)
    providers: ProviderOverlays = Field(default_factory=ProviderOverlays)
    admin_username: str | None = None
    automations: list[AutomationEntry] = []
    parallel: bool = False
    depends_on: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_os(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        os_raw = out.get("os")
        os_key = os_raw.value if isinstance(os_raw, Enum) else str(os_raw or "").strip()
        migrated = _LEGACY_OS_MIGRATE.get(os_key.lower() if os_key else "")
        if migrated:
            family, fw, tpm = migrated
            out["os"] = family
            out.setdefault("firmware", fw)
            out.setdefault("tpm", tpm)
        return out

    @field_validator("automations", mode="before")
    @classmethod
    def coerce_automations(cls, v: Any) -> list[AutomationEntry]:
        if not isinstance(v, list):
            return []
        return [AutomationEntry.coerce(item) for item in v]

    @field_validator("environment", mode="before")
    @classmethod
    def coerce_environment(cls, v: Any) -> list[dict[str, Any]]:
        if v is None:
            return []
        # Flat map shorthand: KEY: value → structured entries with defaults.
        if isinstance(v, dict):
            return [
                {"name": str(k), "value": "" if val is None else str(val)} for k, val in v.items()
            ]
        if not isinstance(v, list):
            raise ValueError("environment must be a list of entries or a mapping of name to value")
        return v

    @field_validator("providers", mode="before")
    @classmethod
    def coerce_providers(cls, v: Any) -> Any:
        if v is None:
            return {}
        return v

    @field_validator("vcpus")
    @classmethod
    def vcpus_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be at least 1")
        return v

    @field_validator("ram_gb", "disk_gb")
    @classmethod
    def size_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be at least 1")
        return v

    @model_validator(mode="after")
    def defaults_firmware_tpm_and_env_dupes(self) -> VMConfig:
        if self.os == GuestOS.WINDOWS:
            if self.firmware is None:
                self.firmware = Firmware.UEFI
            if self.tpm is None:
                self.tpm = True
        if self.tpm and self.firmware != Firmware.UEFI:
            raise ValueError("tpm: true requires firmware: uefi")
        seen: set[str] = set()
        for entry in self.environment:
            upper = entry.name.upper()
            if upper in seen:
                raise ValueError(
                    f"environment name {entry.name!r} is defined more than once "
                    "(names are compared case-insensitively)"
                )
            seen.add(upper)
        return self

    def environment_as_process_map(self) -> dict[str, str]:
        """Name→value map for job process injection (all user entries)."""
        return {e.name: e.value for e in self.environment}

    def environment_persist_entries(self) -> list[EnvironmentEntry]:
        """User entries marked persist=true."""
        return [e for e in self.environment if e.persist]


class Clutch(BaseModel):
    name: str
    description: str | None = None
    storage_path: str | None = None
    vms: list[VMConfig]

    @model_validator(mode="after")
    def validate_vms(self) -> Clutch:
        if not self.vms:
            raise ValueError("at least one VM entry is required")

        vm_names: set[str] = set()
        for vm in self.vms:
            if vm.name in vm_names:
                raise ValueError(f"duplicate VM name: {vm.name!r}")
            vm_names.add(vm.name)

        for vm in self.vms:
            for dep in vm.depends_on:
                if dep == vm.name:
                    raise ValueError(f"VM {vm.name!r} cannot depend on itself")
                if dep not in vm_names:
                    raise ValueError(f"VM {vm.name!r} depends_on unknown VM {dep!r}")

        graph = {vm.name: list(vm.depends_on) for vm in self.vms}
        cycle = _detect_cycle(graph)
        if cycle:
            raise ValueError(f"Circular dependency detected: {' → '.join(cycle)}")

        return self


def _detect_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """Return the cycle as an ordered list of node names (last == first), or None."""
    visited: set[str] = set()
    in_stack: set[str] = set()
    stack: list[str] = []

    def dfs(name: str) -> list[str] | None:
        visited.add(name)
        in_stack.add(name)
        stack.append(name)
        for dep in graph.get(name, []):
            if dep not in visited:
                result = dfs(dep)
                if result is not None:
                    return result
            elif dep in in_stack:
                return stack[stack.index(dep) :] + [dep]
        stack.pop()
        in_stack.discard(name)
        return None

    for name in graph:
        if name not in visited:
            result = dfs(name)
            if result is not None:
                return result
    return None


def load_raw(path: str | Path) -> dict:
    """Load a Clutch YAML without cross-VM validation.

    Parses individual VMConfig fields but skips Clutch-level checks (duplicate names,
    dependency references, cycle detection). Returns a plain dict with 'name',
    'description', and 'vms' keys. Use this to recover data from a clutch that fails
    full validation so it can still be displayed for editing.

    Raises FileNotFoundError or ValueError for unrecoverable parse failures.
    """
    path = Path(path)
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Clutch file not found: {path}")
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in '{path.name}': {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"'{path.name}' must be a YAML mapping, not {type(data).__name__}")

    vms = []
    for vm_data in data.get("vms") or []:
        try:
            vm = VMConfig.model_validate(vm_data)
            vms.append(vm.model_dump(mode="json", exclude_none=True))
        except ValidationError:
            pass

    return {
        "name": data.get("name", ""),
        "description": data.get("description"),
        "storage_path": data.get("storage_path"),
        "vms": vms,
    }


def load(path: str | Path) -> Clutch:
    """Load and validate a Clutch file, returning a Clutch object.

    Raises FileNotFoundError if the file does not exist.
    Raises ValueError with a descriptive message if the YAML is malformed
    or the schema is invalid.
    """
    path = Path(path)

    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Clutch file not found: {path}")
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in '{path.name}': {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"'{path.name}' must be a YAML mapping, not {type(data).__name__}")

    try:
        return Clutch.model_validate(data)
    except ValidationError as exc:
        raise ValueError(_format_errors(exc, path)) from exc


def export(clutch_obj: Clutch, filename: str, clutches_dir: Path) -> Path:
    """Write a Clutch to a new YAML file in clutches_dir.

    Raises FileExistsError if a file with that name already exists.
    """
    clutches_dir = Path(clutches_dir)
    if not filename.endswith(".yaml"):
        filename = f"{filename}.yaml"
    path = clutches_dir / filename
    if path.exists():
        raise FileExistsError(f"Clutch file already exists: {filename}")
    _write_yaml(clutch_obj, path)
    return path


def save(clutch_obj: Clutch, path: str | Path) -> Path:
    """Write a Clutch to a specific path, creating or overwriting."""
    path = Path(path)
    _write_yaml(clutch_obj, path)
    return path


def append_vm(config: VMConfig, path: str | Path) -> Clutch:
    """Append a VM entry to an existing Clutch file.

    Raises ValueError if a VM with the same name already exists.
    Re-validates the full Clutch after appending.
    """
    path = Path(path)
    existing = load(path)
    vm_names = {vm.name for vm in existing.vms}
    if config.name in vm_names:
        raise ValueError(f"VM {config.name!r} already exists in '{path.name}'")
    updated = Clutch(
        name=existing.name, description=existing.description, vms=[*existing.vms, config]
    )
    _write_yaml(updated, path)
    return updated


def _write_yaml(clutch_obj: Clutch, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = clutch_obj.model_dump(mode="json", exclude_none=True)
    for vm in data.get("vms", []):
        # Always emit typed automations (ADR-0025 / #473); omit default-false/empty fields.
        if "automations" in vm:
            compacted = []
            for s in vm["automations"]:
                entry: dict[str, Any] = {
                    "type": s.get("type") or "script",
                    "name": s["name"],
                }
                if s.get("reboot_after"):
                    entry["reboot_after"] = True
                if entry["type"] == "script" and s.get("parameters"):
                    entry["parameters"] = s["parameters"]
                if entry["type"] == "software" and not s.get("clean_payload_on_success", True):
                    entry["clean_payload_on_success"] = False
                compacted.append(entry)
            vm["automations"] = compacted
        if not vm.get("answer_file_parameters"):
            vm.pop("answer_file_parameters", None)
        env = vm.get("environment") or []
        if not env:
            vm.pop("environment", None)
        else:
            # Always emit scope/persist/mode (no default-hiding) so Clutch YAML is explicit.
            compacted_env = []
            for e in env:
                compacted_env.append(
                    {
                        "name": e["name"],
                        "value": e.get("value", ""),
                        "scope": e.get("scope") or "machine",
                        "persist": bool(e.get("persist", True)),
                        "mode": e.get("mode") or "replace",
                    }
                )
            vm["environment"] = compacted_env
        providers = vm.get("providers") or {}
        if not any(providers.get(k) for k in ("libvirt", "hyperv", "utm")):
            vm.pop("providers", None)
        else:
            cleaned: dict[str, Any] = {}
            for key in ("libvirt", "hyperv", "utm"):
                bag = providers.get(key)
                if bag:
                    cleaned[key] = {k: v for k, v in bag.items() if v is not None}
            vm["providers"] = cleaned if cleaned else None
            if not vm.get("providers"):
                vm.pop("providers", None)
        if not vm.get("parallel"):
            vm.pop("parallel", None)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _format_errors(exc: ValidationError, path: Path) -> str:
    lines = [f"Invalid Clutch file '{path.name}':"]
    for err in exc.errors():
        loc = " -> ".join(str(p) for p in err["loc"]) if err["loc"] else "clutch"
        lines.append(f"  {loc}: {err['msg']}")
    return "\n".join(lines)
