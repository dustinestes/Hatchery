from __future__ import annotations

from pathlib import Path
from typing import Any

import jinja2
import yaml

from lib.clutch import GuestOS, VMConfig

SETUP_SCRIPT_NAME = "hatchery-setup-windows.ps1"

# Injected from the Clutch VM / hatch session - never exposed as user params.
RESERVED_SYSTEM_TOKENS = frozenset({"vm_name", "admin_username", "admin_password"})

# Guests that require a selected Answer File at hatch (Windows Autounattend today).
# Same set drives Clutch form Admin Username / Answer File visibility (#453 / #501).
_ANSWER_FILE_REQUIRED_OS = frozenset({GuestOS.WINDOWS})
# Legacy SKU strings still treated as Windows during clutch migration.
_ANSWER_FILE_REQUIRED_LEGACY = frozenset({"win10", "win11", "server2022", "server2025"})


class AnswerFileError(ValueError):
    """Raised when an Answer File cannot be validated or rendered for hatch."""


def requires_answer_file(os_type: GuestOS | str) -> bool:
    """Return True when hatch requires a selected Answer File for this Guest OS."""
    if isinstance(os_type, GuestOS):
        return os_type in _ANSWER_FILE_REQUIRED_OS
    key = str(os_type or "").strip().lower()
    if key in _ANSWER_FILE_REQUIRED_LEGACY:
        return True
    try:
        return GuestOS(key) in _ANSWER_FILE_REQUIRED_OS
    except ValueError:
        return False


def needs_windows_hatch_fields(os_type: GuestOS | str) -> bool:
    """Return True when the Clutch form should show Admin Username and Answer File.

    Today this matches ``requires_answer_file`` (Windows Autounattend hatch path).
    """
    return requires_answer_file(os_type)


def windows_hatch_os_values() -> tuple[str, ...]:
    """Guest OS string values that use Windows hatch Answer File / admin fields."""
    return (GuestOS.WINDOWS.value,)


def parse_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    """Parse leading YAML frontmatter delimited by ``---`` lines.

    Returns ``(hatchery_dict, body)`` when a valid ``hatchery:`` mapping is present.
    Invalid or missing frontmatter returns ``(None, original text)``.
    """
    if not text.startswith("---"):
        return None, text

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, text

    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None, text

    yaml_text = "".join(lines[1:end_idx])
    body = "".join(lines[end_idx + 1 :])
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return None, text
    if not isinstance(data, dict):
        return None, text
    hatchery = data.get("hatchery")
    if not isinstance(hatchery, dict):
        return None, text
    return hatchery, body


def declared_parameters(text_or_path: str | Path) -> list[dict[str, Any]]:
    """Return user-declared parameters from Answer File ``hatchery.parameters``.

    Accepts raw template text or a filesystem path. Reserved system tokens and
    entries without a ``name`` are skipped. Shape matches script params UI JSON.
    """
    text = _read_text(text_or_path)
    hatchery, _body = parse_frontmatter(text)
    if hatchery is None:
        return []

    raw_params = hatchery.get("parameters")
    if not isinstance(raw_params, list):
        return []

    result: list[dict[str, Any]] = []
    for entry in raw_params:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        if name in RESERVED_SYSTEM_TOKENS:
            continue
        label = entry.get("label")
        label_str = str(label) if label is not None and str(label).strip() else None
        item: dict[str, Any] = {
            "name": name,
            "type": "String",
            "mandatory": bool(entry["mandatory"]) if "mandatory" in entry else False,
            "default": entry.get("default"),
            "help": label_str,
        }
        if label_str is not None:
            item["label"] = label_str
        result.append(item)
    return result


def companion_names(hatchery: dict[str, Any] | None) -> list[str]:
    """Return companion basenames from frontmatter (path separators rejected)."""
    if not hatchery:
        return []
    raw = hatchery.get("companions")
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for entry in raw:
        if not isinstance(entry, str):
            continue
        name = entry.strip()
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            continue
        names.append(name)
    return names


def render_user_answer_file(
    path: Path,
    *,
    vm_name: str,
    admin_username: str = "",
    admin_password: str = "",
    user_params: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Render a user-owned Answer File with system tokens and declared params.

    Returns ``(rendered_body, companion_basenames)``. Frontmatter is stripped
    before Jinja render. Missing Jinja variables raise ``AnswerFileError``.
    """
    text = path.read_text(encoding="utf-8")
    hatchery, body = parse_frontmatter(text)
    if hatchery is None:
        body = text
        companions: list[str] = []
        defaults: dict[str, Any] = {}
    else:
        companions = companion_names(hatchery)
        defaults = _parameter_defaults(hatchery)

    context: dict[str, Any] = {**defaults, **(user_params or {})}
    context["vm_name"] = (vm_name or "")[:15]
    context["admin_username"] = admin_username or ""
    context["admin_password"] = admin_password or ""

    env = jinja2.Environment(autoescape=True, undefined=jinja2.StrictUndefined)
    try:
        rendered = env.from_string(body).render(**context)
    except jinja2.TemplateError as exc:
        raise AnswerFileError(f"Answer File '{path.name}': {exc}") from exc
    return rendered, companions


def validate_vm_answer_file(
    vm: VMConfig,
    *,
    automation_dir: Path,
    admin_password: str | None = None,
) -> list[str]:
    """Return human-readable hatch blockers for one VM's Answer File (empty if OK)."""
    errors: list[str] = []
    if not requires_answer_file(vm.os):
        return errors

    if not vm.answer_file or not str(vm.answer_file).strip():
        errors.append(
            f"{vm.name}: Answer File is required for {vm.os.value} guests. "
            "Select an Answer File on the Clutch before hatching."
        )
        return errors

    filename = str(vm.answer_file).strip()
    path = _resolve_under(automation_dir, filename)
    if path is None or not path.is_file():
        errors.append(
            f"{vm.name}: Answer File '{filename}' not found in automation/answerfiles/. "
            "Pull or import the file before hatching."
        )
        return errors

    text = path.read_text(encoding="utf-8")
    hatchery, _body = parse_frontmatter(text)
    user_params = dict(vm.answer_file_parameters or {})
    for param in declared_parameters(text):
        name = param["name"]
        value = user_params.get(name)
        if value is not None and str(value).strip() != "":
            continue
        default = param.get("default")
        if default is not None and str(default).strip() != "":
            continue
        if param.get("mandatory"):
            errors.append(
                f"{vm.name}: Answer File parameter '{name}' is required "
                f"(no value and no default on '{filename}')."
            )

    for companion in companion_names(hatchery):
        cpath = _resolve_under(automation_dir, companion)
        if cpath is None or not cpath.is_file():
            errors.append(
                f"{vm.name}: Answer File companion '{companion}' not found in "
                "automation/answerfiles/. Pull or import it alongside the template."
            )

    # Dry-run render so missing Jinja tokens fail before virt-install.
    if not errors:
        try:
            render_user_answer_file(
                path,
                vm_name=vm.name,
                admin_username=vm.admin_username or "",
                admin_password=admin_password or "",
                user_params=user_params,
            )
        except AnswerFileError as exc:
            errors.append(f"{vm.name}: {exc}")

    return errors


def validate_clutch_answer_files(
    vms: list[VMConfig],
    *,
    automation_dir: Path,
    passwords: dict[str, str | None] | None = None,
) -> list[str]:
    """Return hatch blockers for all VMs (empty if OK)."""
    passwords = passwords or {}
    errors: list[str] = []
    for vm in vms:
        errors.extend(
            validate_vm_answer_file(
                vm,
                automation_dir=automation_dir,
                admin_password=passwords.get(vm.name),
            )
        )
    return errors


def _parameter_defaults(hatchery: dict[str, Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    raw_params = hatchery.get("parameters")
    if not isinstance(raw_params, list):
        return defaults
    for entry in raw_params:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        if name in RESERVED_SYSTEM_TOKENS:
            continue
        if "default" in entry and entry["default"] is not None:
            defaults[name] = entry["default"]
    return defaults


def _read_text(text_or_path: str | Path) -> str:
    if isinstance(text_or_path, Path):
        return text_or_path.read_text(encoding="utf-8")
    candidate = Path(text_or_path)
    if "\n" not in text_or_path and candidate.is_file():
        return candidate.read_text(encoding="utf-8")
    return text_or_path


def _resolve_under(root: Path, filename: str) -> Path | None:
    """Resolve ``filename`` under ``root``; reject absolute paths and traversal."""
    name = (filename or "").strip()
    if not name or Path(name).is_absolute():
        return None
    if ".." in Path(name).parts:
        return None
    resolved = (root / name).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved
