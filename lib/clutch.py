from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError, field_validator, model_validator


class GuestOS(str, Enum):
    WIN10 = "win10"
    WIN11 = "win11"
    SERVER2022 = "server2022"
    SERVER2025 = "server2025"


class AutomationScript(BaseModel):
    """A post-boot script entry. Accepts a plain string (name only) or a mapping."""

    name: str
    reboot_after: bool = False

    @classmethod
    def coerce(cls, v: Any) -> "AutomationScript":
        if isinstance(v, str):
            return cls(name=v)
        return cls.model_validate(v)


class VMConfig(BaseModel):
    name: str
    os: GuestOS
    vcpus: int
    ram_gb: int
    disk_gb: int
    os_media: str
    virtio_drivers: str | None = None
    os_config: str | None = None
    admin_username: str | None = None
    automations: list[AutomationScript] = []
    parallel: bool = False
    depends_on: list[str] = []

    @field_validator("automations", mode="before")
    @classmethod
    def coerce_automations(cls, v: Any) -> list[AutomationScript]:
        if not isinstance(v, list):
            return []
        return [AutomationScript.coerce(item) for item in v]

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


class Clutch(BaseModel):
    name: str
    description: str | None = None
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

    return {"name": data.get("name", ""), "description": data.get("description"), "vms": vms}


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
        # Compact automations: plain string when reboot_after is False
        if "automations" in vm:
            vm["automations"] = [
                s["name"] if not s.get("reboot_after") else s for s in vm["automations"]
            ]
        # Omit parallel when False (default)
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
