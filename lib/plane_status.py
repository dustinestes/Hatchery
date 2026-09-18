"""Footer plane rollups — Hatchery (Controller) + Nests (#277).

Glanceable status only. Counts come from the live Nest registry and active
Alerts, not from the page URL. Drill-down stays on the Alerts bell and Nests pane.

Part of the status-surfaces contract (#282): validators gather, Alerts/snapshot
store, UI polls ``GET /api/plane-status`` via ``hatchery.refreshStatusSurfaces``.
"""

from __future__ import annotations

from typing import Any

from lib import alerts as alerts_lib
from lib import nest_reachability as nest_reachability_lib
from lib import nests as nests_lib


def footer_status() -> dict[str, Any]:
    """Return Hatchery + Nests footer payload for SSR and ``GET /api/plane-status``."""
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
    }
