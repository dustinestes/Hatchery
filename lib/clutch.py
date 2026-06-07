from __future__ import annotations

from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError, field_validator, model_validator


class GuestOS(str, Enum):
    WIN10 = "win10"
    WIN11 = "win11"
    SERVER2022 = "server2022"
    SERVER2025 = "server2025"


class VMConfig(BaseModel):
    name: str
    os: GuestOS
    vcpus: int
    ram_gb: int
    disk_gb: int
    os_media: str
    virtio_drivers: str | None = None
    os_config: str | None = None
    automations: list[str] = []
    depends_on: list[str] = []

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

        return self


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


def _format_errors(exc: ValidationError, path: Path) -> str:
    lines = [f"Invalid Clutch file '{path.name}':"]
    for err in exc.errors():
        loc = " -> ".join(str(p) for p in err["loc"]) if err["loc"] else "clutch"
        lines.append(f"  {loc}: {err['msg']}")
    return "\n".join(lines)
