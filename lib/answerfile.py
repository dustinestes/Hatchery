from __future__ import annotations

from pathlib import Path
from typing import Any

import jinja2
import yaml

from lib.clutch import GuestOS

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "answerfiles"

_TEMPLATES: dict[GuestOS, str] = {
    GuestOS.WIN10: "win10.xml.j2",
    GuestOS.WIN11: "win11.xml.j2",
    GuestOS.SERVER2022: "server2022.xml.j2",
    GuestOS.SERVER2025: "server2025.xml.j2",
}

SETUP_SCRIPT_NAME = "hatchery-setup.ps1"
_SETUP_SCRIPT_TEMPLATE = "hatchery-setup.ps1.j2"

# Injected from the Clutch VM / hatch session - never exposed as user params.
RESERVED_SYSTEM_TOKENS = frozenset({"vm_name", "admin_username", "admin_password"})

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=False,
)

_xml_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,
)


def render(os_type: GuestOS, vm_name: str, admin_username: str, admin_password: str) -> str:
    """Render an Autounattend.xml answer file for the given OS type and credentials."""
    template = _xml_env.get_template(_TEMPLATES[os_type])
    return template.render(
        vm_name=vm_name[:15],
        admin_username=admin_username,
        admin_password=admin_password,
    )


def render_setup_script() -> str:
    """Render the first-boot orchestrator script written to the floppy alongside the answer file."""
    return _env.get_template(_SETUP_SCRIPT_TEMPLATE).render()


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
    if isinstance(text_or_path, Path):
        text = text_or_path.read_text(encoding="utf-8")
    else:
        candidate = Path(text_or_path)
        if "\n" not in text_or_path and candidate.is_file():
            text = candidate.read_text(encoding="utf-8")
        else:
            text = text_or_path

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
