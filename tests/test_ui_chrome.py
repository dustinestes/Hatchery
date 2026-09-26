"""Topbar page title resolution (#390)."""

from __future__ import annotations

from lib.ui_chrome import PANE_TITLES, resolve_topbar_title


def test_known_panes():
    assert resolve_topbar_title("dashboard") == "Dashboard"
    assert resolve_topbar_title("library_content") == "Content"
    assert resolve_topbar_title("automation_scripts") == "Scripts"
    assert resolve_topbar_title("settings_general") == "General"
    assert resolve_topbar_title("hatch_clutch") == "Hatch Clutch"


def test_page_title_override():
    assert resolve_topbar_title("clutches", page_title="New Clutch") == "New Clutch"
    assert resolve_topbar_title("clutches", page_title="  Edit Clutch  ") == "Edit Clutch"


def test_future_pane_fallback():
    assert resolve_topbar_title("settings_tokens") == "Tokens"
    assert resolve_topbar_title("package_defs") == "Package Defs"
    assert resolve_topbar_title("") == "Hatchery"
    assert resolve_topbar_title(None) == "Hatchery"


def test_pane_titles_cover_sidebar_leaves():
    required = {
        "dashboard",
        "nests",
        "clutches",
        "automation_scripts",
        "media_iso",
        "media_virtio",
        "library_content",
        "library_connections",
        "alerts",
        "events",
        "validators",
        "settings_general",
        "settings_security",
        "settings_display",
        "settings_nests",
    }
    assert required <= set(PANE_TITLES)
