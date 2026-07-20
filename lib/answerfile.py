from __future__ import annotations

from pathlib import Path

import jinja2

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
