"""Footer plane rollups — Hatchery + Nests + Libraries (#277 / #254).

Glanceable status only. Counts come from the live Nest registry, Library
connection registry, and active Alerts — not from the page URL. Drill-down
stays on the Alerts bell.

Part of the status-surfaces contract (#282): validators gather, Alerts/snapshot
store, UI polls ``GET /api/plane-status`` via ``hatchery.refreshStatusSurfaces``.
"""

from __future__ import annotations

from typing import Any

from lib import alerts as alerts_lib
from lib import config
from lib import nest_reachability as nest_reachability_lib
from lib import nests as nests_lib


def footer_status() -> dict[str, Any]:
    """Return footer payload for SSR and ``GET /api/plane-status``."""
    controller_issues = alerts_lib.count_active_by_prefixes(
        alerts_lib.CONTROLLER_ALERT_PREFIXES,
        exclude_tiers=("info",),
    )
    if controller_issues:
        hatchery_dot = "red"
        hatchery_title = f"Hatchery: {controller_issues} Controller issue(s) — see Alerts"
        hatchery_ok = False
    else:
        hatchery_dot = "green"
        hatchery_title = "Hatchery Controller OK"
        hatchery_ok = True

    # Do not force-seed Local here — empty registry is a valid future state (#266).
    registered = nests_lib.list_nests()
    nest_total = len(registered)
    snap_nests = nest_reachability_lib.get_snapshot().get("nests") or {}

    unreachable = 0
    for nest in registered:
        nid = nest.get("id")
        entry = snap_nests.get(nid) if nid else None
        if isinstance(entry, dict) and not entry.get("ok"):
            unreachable += 1

    nest_alert_count = alerts_lib.count_active_by_prefixes(alerts_lib.NEST_SCOPED_ALERT_PREFIXES)

    if nest_total == 0:
        nests_dot = "muted"
        nests_title = "No Nests registered"
        nests_ok = True
    elif unreachable or nest_alert_count:
        nests_dot = "red"
        parts: list[str] = []
        if unreachable:
            parts.append(f"{unreachable} of {nest_total} unreachable")
        if nest_alert_count:
            parts.append(f"{nest_alert_count} Nest alert(s)")
        nests_title = "Nests: " + "; ".join(parts) + " — see Alerts"
        nests_ok = False
    else:
        nests_dot = "green"
        nests_title = f"All {nest_total} Nest(s) OK"
        nests_ok = True

    library_enabled = bool(config.library_enabled())
    library_connections = list(config.library_connections() or []) if library_enabled else []
    library_connection_total = len(library_connections) if library_enabled else 0
    library_alert_count = (
        alerts_lib.count_active_by_prefixes(
            alerts_lib.LIBRARY_SCOPED_ALERT_PREFIXES,
            exclude_tiers=("info",),
        )
        if library_enabled
        else 0
    )

    if not library_enabled:
        libraries_visible = False
        libraries_dot = "muted"
        libraries_title = "Library disabled"
        libraries_ok = True
    elif library_connection_total == 0:
        libraries_visible = True
        libraries_dot = "muted"
        libraries_title = "No Library connections"
        libraries_ok = True
    elif library_alert_count:
        libraries_visible = True
        libraries_dot = "red"
        libraries_title = f"Libraries: {library_alert_count} connection issue(s) — see Alerts"
        libraries_ok = False
    else:
        libraries_visible = True
        libraries_dot = "green"
        libraries_title = f"All {library_connection_total} Library connection(s) OK"
        libraries_ok = True

    return {
        "hatchery_ok": hatchery_ok,
        "hatchery_title": hatchery_title,
        "hatchery_dot": hatchery_dot,
        "hatchery_issue_count": controller_issues,
        "nests_ok": nests_ok,
        "nests_title": nests_title,
        "nests_dot": nests_dot,
        "nest_total": nest_total,
        "nest_unreachable": unreachable,
        "nest_alert_count": nest_alert_count,
        "library_enabled": library_enabled,
        "libraries_visible": libraries_visible,
        "libraries_ok": libraries_ok,
        "libraries_title": libraries_title,
        "libraries_dot": libraries_dot,
        "library_connection_total": library_connection_total,
        "library_alert_count": library_alert_count,
    }
