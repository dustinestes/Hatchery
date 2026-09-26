"""UI chrome helpers — topbar page titles from ``active_pane`` (#390).

New panes: set ``active_pane`` on the route and add a label here (or rely on the
humanize fallback). Optional ``page_title`` overrides the map when the sidebar
pane id must stay parent-group (e.g. Build/Edit under Clutches).
"""

from __future__ import annotations

# Short admin-console labels (sidebar leaf / topbar). Not browser-tab strings.
PANE_TITLES: dict[str, str] = {
    "dashboard": "Dashboard",
    "nests": "Nests",
    "clutches": "Clutches",
    "build": "New Clutch",
    "edit": "Edit Clutch",
    "hatch_clutch": "Hatch Clutch",
    "automation_scripts": "Scripts",
    "media_iso": "ISO",
    "media_virtio": "VirtIO",
    "library_content": "Content",
    "library_connections": "Connections",
    "alerts": "Alerts",
    "events": "Events",
    "validators": "Validators",
    "settings_general": "General",
    "settings_security": "Security",
    "settings_display": "Display",
    "settings_nests": "Nests",
}


def resolve_topbar_title(
    active_pane: str | None = None,
    page_title: str | None = None,
) -> str:
    """Return the topbar context title for the current render."""
    override = (page_title or "").strip()
    if override:
        return override
    key = (active_pane or "").strip()
    if key in PANE_TITLES:
        return PANE_TITLES[key]
    if not key:
        return "Hatchery"
    if key.startswith("settings_"):
        rest = key[len("settings_") :].replace("_", " ").strip()
        if not rest:
            return "Settings"
        return rest[:1].upper() + rest[1:]
    words = key.replace("-", "_").split("_")
    return " ".join(w[:1].upper() + w[1:] for w in words if w)
