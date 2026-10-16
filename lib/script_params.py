"""Discover script parameter metadata and validate Clutch values (#571).

Product rule: discover constraints from the script via a kind adapter; never
invent types, enums, or lengths the script did not declare. Clutch UI and
early gates consume a neutral ParamSpec list. Empty metadata means no typed
fields and no strict param gate (honest degrade).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

ScriptKind = Literal["powershell", "shell", "unknown"]
ParamKind = Literal["string", "bool", "switch", "int", "float"]

_COMMON_PS_PARAMS = frozenset(
    {
        "Verbose",
        "Debug",
        "ErrorAction",
        "WarningAction",
        "InformationAction",
        "ProgressAction",
        "ErrorVariable",
        "WarningVariable",
        "InformationVariable",
        "OutVariable",
        "OutBuffer",
        "PipelineVariable",
        "WhatIf",
        "Confirm",
    }
)

_BOOL_TRUE = frozenset({"true", "1", "yes", "on"})
_BOOL_FALSE = frozenset({"false", "0", "no", "off"})

_PARAM_BIND_MARKERS = (
    "ParameterBindingArgumentTransformationException",
    "ParameterBindingException",
    "Cannot process argument transformation on parameter",
    "Missing an argument for parameter",
    "A parameter cannot be found that matches parameter name",
)


@dataclass(frozen=True)
class ParamSpec:
    """Neutral parameter metadata discovered from a script (not invented)."""

    name: str
    kind: ParamKind
    mandatory: bool = False
    default: Any = None
    help: str | None = None
    allowed_values: tuple[str, ...] = ()
    min_length: int | None = None
    max_length: int | None = None
    # Numeric bounds from the declared CLR/PowerShell type (e.g. uint → min 0),
    # not from ValidateRange (not discovered yet).
    min_value: int | float | None = None
    max_value: int | float | None = None
    source_kind: ScriptKind = "unknown"
    raw_type: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        """JSON shape for ``/api/automation/scripts/.../params``."""
        payload: dict[str, Any] = {
            "name": self.name,
            # Legacy key from #113; keep for older UI clients.
            "type": self.raw_type or self.kind,
            "kind": self.kind,
            "mandatory": self.mandatory,
            "default": self.default,
            "help": self.help,
            "source_kind": self.source_kind,
        }
        if self.allowed_values:
            payload["allowed_values"] = list(self.allowed_values)
            payload["validate_set"] = list(self.allowed_values)
        if self.min_length is not None:
            payload["min_length"] = self.min_length
        if self.max_length is not None:
            payload["max_length"] = self.max_length
        if self.min_value is not None:
            payload["min_value"] = self.min_value
        if self.max_value is not None:
            payload["max_value"] = self.max_value
        return payload


def detect_kind(path: Path | str) -> ScriptKind:
    """Return script kind from file extension (Controller cache path)."""
    suffix = Path(path).suffix.lower()
    if suffix == ".ps1":
        return "powershell"
    if suffix in {".sh", ".bash"}:
        return "shell"
    return "unknown"


def introspect(path: Path | str) -> list[ParamSpec]:
    """Discover ParamSpec for ``path`` via the kind adapter.

    Returns ``[]`` when the kind has no reader yet, the tool is missing, or
    the script declares no parameters. Callers must not invent specs.
    """
    script_path = Path(path)
    kind = detect_kind(script_path)
    if kind == "powershell":
        return _introspect_powershell(script_path)
    # Shell (and other kinds): no reader yet — honest empty metadata.
    return []


def specs_to_api(specs: list[ParamSpec]) -> list[dict[str, Any]]:
    return [s.to_api_dict() for s in specs]


def coerce_value(spec: ParamSpec, value: Any) -> Any:
    """Coerce a Clutch YAML/JSON value toward the discovered kind.

    Raises ``ValueError`` when the value cannot be coerced.
    """
    if value is None:
        return None
    if spec.kind == "switch" or spec.kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _BOOL_TRUE:
            return True
        if text in _BOOL_FALSE:
            return False
        raise ValueError(f"{spec.name}: expected boolean, got {value!r}")
    if spec.kind == "int":
        if isinstance(value, bool):
            raise ValueError(f"{spec.name}: expected integer, got boolean")
        if isinstance(value, int):
            return value
        text = str(value).strip()
        try:
            return int(text, 10)
        except ValueError as exc:
            raise ValueError(f"{spec.name}: expected integer, got {value!r}") from exc
    if spec.kind == "float":
        if isinstance(value, bool):
            raise ValueError(f"{spec.name}: expected number, got boolean")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        text = str(value).strip()
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(f"{spec.name}: expected number, got {value!r}") from exc
    return str(value)


def validate_values(specs: list[ParamSpec], values: dict[str, Any] | None) -> list[str]:
    """Return human-readable blockers for ``values`` against discovered specs.

    Only enforces constraints present on specs. Unknown keys in ``values`` are
    ignored (script may accept extras; we do not invent rejection).
    """
    values = values or {}
    errors: list[str] = []

    for spec in specs:
        raw = values.get(spec.name, None)
        present = spec.name in values and raw is not None and raw != ""

        if not present:
            if spec.mandatory and spec.default is None:
                errors.append(f"{spec.name}: required")
            continue

        try:
            coerced = coerce_value(spec, raw)
        except ValueError as exc:
            errors.append(str(exc))
            continue

        if spec.allowed_values:
            candidates = {str(coerced), str(raw)}
            if isinstance(coerced, bool):
                candidates.update({"True", "False", "true", "false"})
            allowed = set(spec.allowed_values)
            allowed_lower = {a.lower() for a in spec.allowed_values}
            if not (candidates & allowed) and not any(
                c.lower() in allowed_lower for c in candidates if isinstance(c, str)
            ):
                errors.append(f"{spec.name}: must be one of {', '.join(spec.allowed_values)}")
                continue

        if spec.kind == "string":
            text = str(coerced)
            if spec.min_length is not None and len(text) < spec.min_length:
                errors.append(f"{spec.name}: length must be at least {spec.min_length}")
            if spec.max_length is not None and len(text) > spec.max_length:
                errors.append(f"{spec.name}: length must be at most {spec.max_length}")

        if spec.kind in ("int", "float") and isinstance(coerced, (int, float)):
            if spec.min_value is not None and coerced < spec.min_value:
                errors.append(f"{spec.name}: must be at least {spec.min_value}")
            if spec.max_value is not None and coerced > spec.max_value:
                errors.append(f"{spec.name}: must be at most {spec.max_value}")

    # Values for names not in specs are not validated (no invented rules).
    return errors


def coerce_parameters(specs: list[ParamSpec], values: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy of ``values`` with known params coerced to typed natives."""
    values = dict(values or {})
    out: dict[str, Any] = {}
    by_name = {s.name: s for s in specs}
    for key, raw in values.items():
        spec = by_name.get(key)
        if spec is None:
            out[key] = raw
            continue
        if raw is None or raw == "":
            continue
        out[key] = coerce_value(spec, raw)
    return out


def validate_clutch_vms(
    vms: list[Any],
    *,
    scripts_dir: Path,
) -> list[str]:
    """Return hatch/save blockers for script automation parameters on all VMs."""
    errors: list[str] = []
    root = scripts_dir.resolve()
    for vm in vms:
        vm_name = getattr(vm, "name", None) or "?"
        automations = getattr(vm, "automations", None) or []
        for entry in automations:
            if getattr(entry, "type", None) != "script":
                continue
            script_name = getattr(entry, "name", "") or ""
            path = _resolve_script(root, script_name)
            if path is None or not path.is_file():
                # Missing script is covered elsewhere (#151); skip param gate.
                continue
            specs = introspect(path)
            if not specs:
                continue
            params = getattr(entry, "parameters", None) or {}
            for msg in validate_values(specs, params):
                errors.append(f"{vm_name} / {script_name}: {msg}")
    return errors


def encode_powershell_args(specs: list[ParamSpec], values: dict[str, Any] | None) -> str:
    """Build PowerShell named-argument fragment for ``& { ... } <args>``."""
    values = values or {}
    by_name = {s.name: s for s in specs}
    parts: list[str] = []

    # Prefer declared order; then any extra keys as quoted strings (legacy).
    ordered_names = [s.name for s in specs]
    for name in values:
        if name not in ordered_names:
            ordered_names.append(name)

    for name in ordered_names:
        if name not in values:
            continue
        raw = values[name]
        if raw is None or raw == "":
            continue
        spec = by_name.get(name)
        if spec is None:
            parts.append(f"-{name} {_ps_quote(str(raw))}")
            continue
        coerced = coerce_value(spec, raw)
        if spec.kind == "switch":
            if coerced:
                parts.append(f"-{name}")
            else:
                parts.append(f"-{name}:$false")
            continue
        if spec.kind == "bool":
            parts.append(f"-{name} ${'true' if coerced else 'false'}")
            continue
        if spec.kind in ("int", "float"):
            parts.append(f"-{name} {coerced}")
            continue
        parts.append(f"-{name} {_ps_quote(str(coerced))}")
    return " ".join(parts)


def looks_like_param_binding_failure(output: str | None) -> bool:
    """True when guest/script host rejected parameter binding."""
    text = output or ""
    return any(marker in text for marker in _PARAM_BIND_MARKERS)


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _resolve_script(root: Path, name: str) -> Path | None:
    safe = Path(name).name
    if not safe or safe != name:
        return None
    path = (root / safe).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _introspect_powershell(script_path: Path) -> list[ParamSpec]:
    if not shutil.which("pwsh"):
        return []
    if not script_path.is_file():
        return []

    # Escape single quotes for PowerShell single-quoted path literal.
    ps_path = str(script_path).replace("'", "''")
    ps_code = (
        "$p = (Get-Command -ErrorAction Stop '" + ps_path + "').Parameters.Values; "
        "$rows = foreach ($param in $p) { "
        "  if ($param.Name -in @("
        + ",".join(f"'{n}'" for n in sorted(_COMMON_PS_PARAMS))
        + ")) { continue } "
        "  $pa = @($param.Attributes | Where-Object { "
        "    $_ -is [System.Management.Automation.ParameterAttribute] }); "
        "  $mandatory = [bool]($pa | Where-Object { $_.Mandatory }); "
        "  $help = ($pa | Select-Object -First 1).HelpMessage; "
        "  $vs = @($param.Attributes | Where-Object { "
        "    $_ -is [System.Management.Automation.ValidateSetAttribute] } "
        "    | ForEach-Object { $_.ValidValues }) | ForEach-Object { $_ }; "
        "  $vl = $param.Attributes | Where-Object { "
        "    $_ -is [System.Management.Automation.ValidateLengthAttribute] } "
        "    | Select-Object -First 1; "
        "  [pscustomobject]@{ "
        "    Name = $param.Name; "
        "    Type = $param.ParameterType.Name; "
        "    FullName = $param.ParameterType.FullName; "
        "    Mandatory = $mandatory; "
        "    HelpMessage = $help; "
        "    Default = if ($null -ne $param.DefaultValue) { "
        "      [string]$param.DefaultValue } else { $null }; "
        "    ValidateSet = @($vs); "
        "    MinLength = if ($vl) { [int]$vl.MinLength } else { $null }; "
        "    MaxLength = if ($vl) { [int]$vl.MaxLength } else { $null } "
        "  } "
        "}; "
        "$rows | ConvertTo-Json -Depth 5"
    )
    try:
        result = subprocess.run(
            ["pwsh", "-NonInteractive", "-Command", ps_code],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0 or not (result.stdout or "").strip():
        return []
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [_param_spec_from_ps_row(row) for row in raw if isinstance(row, dict)]


def _param_spec_from_ps_row(row: dict[str, Any]) -> ParamSpec:
    name = str(row.get("Name") or "").strip()
    type_name = str(row.get("Type") or "String")
    full_name = str(row.get("FullName") or "")
    kind = _ps_type_to_kind(type_name, full_name)
    allowed: tuple[str, ...] = ()
    vs = row.get("ValidateSet") or []
    if isinstance(vs, list):
        allowed = tuple(str(v) for v in vs)
    elif vs:
        allowed = (str(vs),)
    min_length = row.get("MinLength")
    max_length = row.get("MaxLength")
    try:
        min_i = int(min_length) if min_length is not None else None
    except (TypeError, ValueError):
        min_i = None
    try:
        max_i = int(max_length) if max_length is not None else None
    except (TypeError, ValueError):
        max_i = None
    help_msg = row.get("HelpMessage") or None
    if isinstance(help_msg, list):
        help_msg = help_msg[0] if help_msg else None
    if help_msg is not None:
        help_msg = str(help_msg) or None
    default = row.get("Default")
    min_value, max_value = _ps_numeric_bounds(type_name, full_name, kind)
    return ParamSpec(
        name=name,
        kind=kind,
        mandatory=bool(row.get("Mandatory")),
        default=default,
        help=help_msg,
        allowed_values=allowed,
        min_length=min_i,
        max_length=max_i,
        min_value=min_value,
        max_value=max_value,
        source_kind="powershell",
        raw_type=type_name,
    )


def _ps_type_to_kind(type_name: str, full_name: str) -> ParamKind:
    combined = f"{full_name} {type_name}".lower()
    if "switchparameter" in combined or type_name.lower() == "switch":
        return "switch"
    if type_name.lower() in {"bool", "boolean"} or combined.endswith(".boolean"):
        return "bool"
    if type_name.lower() in {
        "int",
        "int16",
        "int32",
        "int64",
        "long",
        "short",
        "byte",
        "sbyte",
        "uint16",
        "uint32",
        "uint64",
    }:
        return "int"
    if type_name.lower() in {"double", "single", "float", "decimal"}:
        return "float"
    return "string"


def _ps_numeric_bounds(
    type_name: str, full_name: str, kind: ParamKind
) -> tuple[int | float | None, int | float | None]:
    """Return (min, max) implied by the CLR/PowerShell numeric type alone."""
    if kind not in ("int", "float"):
        return None, None
    t = type_name.lower()
    combined = f"{full_name} {type_name}".lower()
    # Unsigned / byte-range types: negatives are not valid.
    if t in {"byte", "uint16", "uint32", "uint64"} or "uint" in combined:
        if t == "byte":
            return 0, 255
        if t == "uint16":
            return 0, 65535
        return 0, None
    if t == "sbyte":
        return -128, 127
    if t in {"int16", "short"}:
        return -32768, 32767
    return None, None


# Re-export for tests / callers that want a stable dict dump.
def param_spec_asdict(spec: ParamSpec) -> dict[str, Any]:
    data = asdict(spec)
    data["allowed_values"] = list(spec.allowed_values)
    return data
