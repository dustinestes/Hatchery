"""Shared Library status cue vocabulary (#387 / ADR-0018).

Maps ``source_status`` + ``sync_state`` to short operator labels, severity, and
action flags. Keep :mod:`static/library_status_cues.js` in sync with this module
so Cached panes and Library → Content stay 1:1.
"""

from __future__ import annotations

from typing import Any

# Short rail / filter labels (visible text; not hover-only).
SOURCE_SHORT: dict[str, str] = {
    "ok": "",
    "missing": "source missing",
    "orphan": "orphaned",
    "disabled": "connection disabled",
    "rate_limited": "rate limited",
    "unreachable": "unreachable",
    "unconfirmable": "tip unconfirmable",
}

SYNC_SHORT: dict[str, str] = {
    "in_sync": "synced",
    "out_of_sync": "out of sync",
    "unevaluated": "",
}

# Cue id for CSS / icons (rollup where useful).
# communication = rate_limited ∪ unreachable
CUE_SYNCED = "synced"
CUE_OUT_OF_SYNC = "out_of_sync"
CUE_ORPHAN = "orphan"
CUE_MISSING = "missing"
CUE_COMMUNICATION = "communication"
CUE_DISABLED = "disabled"
CUE_UNCONFIRMABLE = "unconfirmable"
CUE_LOCAL = "local"
CUE_LINKED = "linked"  # soft-disable residue (#408): was linked; Sync/re-attach off

SEVERITY_OK = "ok"
SEVERITY_ACTION = "action"
SEVERITY_WARN = "warn"
SEVERITY_MUTED = "muted"


def resolve(
    *,
    source_status: str | None = None,
    sync_state: str | None = None,
    source_status_message: str = "",
    drift_state: str | None = None,
    orphan: bool = False,
    orphan_reason: str = "",
    cache_name: str = "",
    library_enabled: bool = True,
) -> dict[str, Any]:
    """Return cue dict for one inventory / provenance row.

    Local (no Library link): pass ``drift_state='local'`` or omit statuses.
    When ``library_enabled`` is false and a link remains, return the soft-disable
    ``linked`` cue (no Sync / re-attach) instead of live sync chrome (#408).
    """
    drift = (drift_state or "").strip().lower()
    if drift == "local" or (not source_status and not orphan and drift in ("", "local")):
        return {
            "cue": CUE_LOCAL,
            "short": "",
            "severity": SEVERITY_MUTED,
            "show_rail_icon": False,
            "can_sync": False,
            "can_reattach": False,
            "header_label": "",
            "header_aria": "",
            "message": "",
            "source_status": None,
            "sync_state": None,
            "filter_keys": ["local"],
        }

    status = (source_status or "").strip().lower()
    sync = (sync_state or "").strip().lower()
    message = (source_status_message or orphan_reason or "").strip()

    # Compat: legacy drift_state / orphan flags when axes absent.
    if not status:
        if orphan or drift == "orphan":
            status = "orphan"
            sync = "unevaluated"
            message = message or orphan_reason or "Library connection or binding missing"
        elif drift == "out_of_sync":
            status = "ok"
            sync = "out_of_sync"
        elif drift == "in_sync":
            status = "ok"
            sync = "in_sync"
        elif drift == "unknown":
            status = "unconfirmable"
            sync = "unevaluated"
        else:
            status = "unconfirmable"
            sync = "unevaluated"

    if not sync:
        sync = "unevaluated" if status != "ok" else "in_sync"

    if orphan or status == "orphan":
        status = "orphan"
        sync = "unevaluated"
        message = message or orphan_reason or "Library connection or binding missing"

    # Soft disable: keep a quiet linked cue; suppress Sync / re-attach (#408).
    if not library_enabled:
        return {
            "cue": CUE_LINKED,
            "short": "linked",
            "severity": SEVERITY_MUTED,
            "show_rail_icon": True,
            "can_sync": False,
            "can_reattach": False,
            "header_label": "Linked",
            "header_aria": "Linked from Library (Library is disabled)",
            "message": "Library is disabled. Sync and re-attach are unavailable.",
            "source_status": status,
            "sync_state": sync,
            "filter_keys": ["linked"],
        }

    short = ""
    cue = CUE_UNCONFIRMABLE
    severity = SEVERITY_WARN
    can_sync = False
    can_reattach = False
    show_rail = True
    filter_keys: list[str] = []

    if status == "ok" and sync == "in_sync":
        cue = CUE_SYNCED
        short = SYNC_SHORT["in_sync"]
        severity = SEVERITY_OK
        show_rail = True  # healthy link cue (visible)
        filter_keys = ["in_sync", "ok"]
    elif status == "ok" and sync == "out_of_sync":
        cue = CUE_OUT_OF_SYNC
        short = SYNC_SHORT["out_of_sync"]
        severity = SEVERITY_ACTION
        can_sync = True
        filter_keys = ["out_of_sync", "ok"]
    elif status == "orphan":
        cue = CUE_ORPHAN
        short = SOURCE_SHORT["orphan"]
        severity = SEVERITY_WARN
        can_reattach = True
        filter_keys = ["orphan"]
    elif status == "missing":
        cue = CUE_MISSING
        short = SOURCE_SHORT["missing"]
        severity = SEVERITY_WARN
        can_reattach = True
        filter_keys = ["missing"]
    elif status in ("rate_limited", "unreachable"):
        cue = CUE_COMMUNICATION
        short = SOURCE_SHORT.get(status, status.replace("_", " "))
        severity = SEVERITY_WARN
        filter_keys = ["communication", status]
    elif status == "disabled":
        cue = CUE_DISABLED
        short = SOURCE_SHORT["disabled"]
        severity = SEVERITY_MUTED
        filter_keys = ["disabled"]
    else:
        cue = CUE_UNCONFIRMABLE
        short = SOURCE_SHORT.get(status, "tip unconfirmable")
        severity = SEVERITY_MUTED
        filter_keys = ["unconfirmable", status]

    name = (cache_name or "").strip()
    if can_sync:
        header_label = "Out of sync"
        header_aria = f"Sync {name} from Library" if name else "Sync from Library"
    elif can_reattach:
        header_label = short[:1].upper() + short[1:] if short else "Re-attach"
        header_aria = message or header_label
    elif cue == CUE_SYNCED:
        header_label = "Synced"
        header_aria = "In sync with Library"
    else:
        header_label = short[:1].upper() + short[1:] if short else "Library status"
        header_aria = message or header_label

    return {
        "cue": cue,
        "short": short,
        "severity": severity,
        "show_rail_icon": show_rail,
        "can_sync": can_sync,
        "can_reattach": can_reattach,
        "header_label": header_label,
        "header_aria": header_aria,
        "message": message,
        "source_status": status,
        "sync_state": sync,
        "filter_keys": filter_keys,
    }


def attach_to_inventory_item(
    item: dict[str, Any],
    *,
    library_enabled: bool = True,
) -> dict[str, Any]:
    """Mutate/enrich a filesystem inventory dict with ``library_cue_*`` fields."""
    cue = resolve(
        source_status=item.get("source_status"),
        sync_state=item.get("sync_state"),
        source_status_message=item.get("source_status_message") or "",
        drift_state=item.get("drift_state"),
        orphan=bool(item.get("orphan")),
        orphan_reason=item.get("orphan_reason") or "",
        cache_name=item.get("name") or "",
        library_enabled=library_enabled,
    )
    item["library_cue"] = cue["cue"]
    item["library_cue_short"] = cue["short"]
    item["library_cue_severity"] = cue["severity"]
    item["library_show_rail_icon"] = cue["show_rail_icon"]
    item["library_can_sync"] = cue["can_sync"]
    item["library_can_reattach"] = cue["can_reattach"]
    item["library_header_label"] = cue["header_label"]
    item["library_header_aria"] = cue["header_aria"]
    item["library_filter_keys"] = cue["filter_keys"]
    return item
