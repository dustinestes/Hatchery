"""Dashboard Nest, VM, Clutch, Library, and Validators rollups (#329 / #331 / #334 / #373).

Nests use stored reachability / validator run data (no probe on paint).
VMs, Clutches, Library linked counts, and Validators aggregate for the
Dashboard only via ``/api/dashboard-summary``; do not put them on
``/api/plane-status`` (that bus polls every pane).
"""

from __future__ import annotations

from typing import Any

from lib import config
from lib import hatch as hatch_lib
from lib import nest_reachability as nest_reachability_lib
from lib import nests as nests_lib
from lib.providers.factory import UnknownNestError, UnsupportedProviderError, get_provider
from lib.validators import runs as validator_runs


_PAUSED_POWER = frozenset({"paused", "suspended", "pmsuspended"})
_SESSION_STATUSES = ("in_progress", "completed", "failed", "degraded", "unknown")

# Dashboard tile → validator ids that back its validated stamp (#373).
# Empty tuple with label "not implemented" = placeholder until a validator exists.
# Alerts / Validators tiles omit stamps (no domain validator; max-of-all is noise).
_TILE_VALIDATORS: dict[str, tuple[str, ...]] = {
    "nests": ("nest_reachability", "nest_capability", "nest_key_expiry"),
    "clutches": ("clutch_files",),
    "library": ("library_connections", "library_cache_drift"),
}


def nest_tile_fields(
    registered: list[dict] | None = None,
    *,
    snap_nests: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Nest counts + last-validated for plane-status / Nest tile."""
    nests = registered if registered is not None else nests_lib.list_nests()
    snap = (
        snap_nests
        if snap_nests is not None
        else (nest_reachability_lib.get_snapshot().get("nests") or {})
    )
    if not isinstance(snap, dict):
        snap = {}

    total = len(nests)
    reachable = 0
    unreachable = 0
    unchecked = 0
    checked_ats: list[str] = []
    by_provider = {key: 0 for key in ("libvirt", "utm", "hyperv")}

    for nest in nests:
        nid = nest.get("id")
        provider = str(nest.get("provider_type") or "libvirt").strip().lower()
        if provider in by_provider:
            by_provider[provider] += 1
        entry = snap.get(nid) if nid else None
        if not isinstance(entry, dict):
            unchecked += 1
            continue
        if entry.get("ok"):
            reachable += 1
        else:
            unreachable += 1
        at = entry.get("checked_at")
        if isinstance(at, str) and at:
            checked_ats.append(at)

    last_validated = _latest_iso(checked_ats)
    if last_validated is None:
        snap_updated = nest_reachability_lib.get_snapshot().get("updated_at")
        if isinstance(snap_updated, str) and snap_updated:
            last_validated = snap_updated
    if last_validated is None:
        latest = validator_runs.latest_by_validator().get("nest_reachability") or {}
        finished = latest.get("finished_at") or latest.get("started_at")
        if isinstance(finished, str) and finished:
            last_validated = finished

    return {
        "nest_total": total,
        "nest_reachable": reachable,
        "nest_unreachable": unreachable,
        "nest_unchecked": unchecked,
        "nest_last_validated_at": last_validated,
        "nest_by_provider": by_provider,
    }


def vm_summary() -> dict[str, Any]:
    """Cross-Nest VM power + hatch counts (lightweight; no IP/scripts)."""
    by_power = {
        "running": 0,
        "shut_off": 0,
        "paused": 0,
        "other": 0,
    }
    by_hatch = {
        "pending": 0,
        "hatching": 0,
        "provisioning": 0,
        "fledged": 0,
        "failed": 0,
        "culled": 0,
        "none": 0,
    }
    total = 0
    nests_unavailable = 0

    for nest in nests_lib.list_nests():
        nid = nest.get("id")
        if not nid:
            nests_unavailable += 1
            continue
        try:
            provider = get_provider(nid)
            vms = provider.list_vms()
        except (UnknownNestError, UnsupportedProviderError, OSError, RuntimeError):
            nests_unavailable += 1
            continue

        for vm in vms:
            total += 1
            power = (vm.get("status") or "").strip().lower()
            if power == "running":
                by_power["running"] += 1
            elif power == "shut off":
                by_power["shut_off"] += 1
            elif power in _PAUSED_POWER:
                by_power["paused"] += 1
            else:
                by_power["other"] += 1

            hatch_status = None
            name = vm.get("name")
            if name:
                try:
                    tag = provider.get_vm_session_tag(name)
                except Exception:
                    tag = None
                if tag and tag.get("session_id"):
                    row = hatch_lib.get_vm_record(tag["session_id"], name)
                    if row:
                        hatch_status = row.get("status")

            if hatch_status in by_hatch:
                by_hatch[hatch_status] += 1
            else:
                by_hatch["none"] += 1

    return {
        "total": total,
        "by_power": by_power,
        "by_hatch": by_hatch,
        "nests_unavailable": nests_unavailable,
    }


def clutch_summary() -> dict[str, Any]:
    """Clutch file count + active hatch sessions across Nests (#331)."""
    clutch_dir = config.data_dir() / "clutches"
    file_count = 0
    if clutch_dir.is_dir():
        file_count = sum(
            1 for p in clutch_dir.iterdir() if p.is_file() and p.suffix.lower() == ".yaml"
        )

    by_status = {key: 0 for key in _SESSION_STATUSES}
    sessions: list[dict] = []
    nest_ids: set[str] = set()
    clutch_files: set[str] = set()

    for nest in nests_lib.list_nests():
        nid = nest.get("id")
        if not nid:
            continue
        for session in hatch_lib.list_sessions(nid):
            sessions.append(session)
            nest_ids.add(nid)
            cf = session.get("clutch_file")
            if isinstance(cf, str) and cf:
                clutch_files.add(cf)
            status = session.get("status") or "unknown"
            if status in by_status:
                by_status[status] += 1
            else:
                by_status["unknown"] += 1

    nests_used: list[dict[str, str]] = []
    for nid in sorted(nest_ids):
        row = nests_lib.get_nest(nid)
        name = (row or {}).get("name") or nid
        nests_used.append({"id": nid, "name": str(name)})

    return {
        "file_count": file_count,
        "session_total": len(sessions),
        "by_status": by_status,
        "nests_used": nests_used,
        "unique_clutch_files": len(clutch_files),
    }


def library_summary() -> dict[str, Any]:
    """Linked operator-cache counts by domain for the Library tile (#373).

    ``linked`` counts provenance rows (Library-attributed cache), not
    bindings and not live catalog hits.
    """
    from lib import library_provenance as prov

    linked = prov.counts_by_domain()
    return {
        "linked": {
            "scripts": int(linked.get("scripts") or 0),
            "clutches": int(linked.get("clutches") or 0),
            "media": int(linked.get("media") or 0),
        },
    }


def validators_summary() -> dict[str, Any]:
    """Enabled/off + latest-run rollup from Settings and ``validator_runs`` (#334).

    Reads stored config and run history only; does not schedule or execute validators.
    """
    from lib.validators.settings import list_validator_configs

    configs = list_validator_configs()
    latest = validator_runs.latest_by_validator()
    total = len(configs)
    enabled_rows = [c for c in configs if c.get("enabled")]
    enabled = len(enabled_rows)
    disabled = total - enabled

    by_status = {"ok": 0, "findings": 0, "error": 0}
    never_run = 0
    degraded = 0
    findings_total = 0
    finished_ats: list[str] = []

    for run in latest.values():
        at = run.get("finished_at") or run.get("started_at")
        if isinstance(at, str) and at:
            finished_ats.append(at)

    for row in enabled_rows:
        vid = row.get("id")
        run = latest.get(vid) if vid else None
        if not run:
            never_run += 1
            continue
        status = run.get("status") if run.get("status") in by_status else "error"
        by_status[status] += 1
        if status in ("findings", "error"):
            degraded += 1
        try:
            findings_total += int(run.get("findings_count") or 0)
        except (TypeError, ValueError):
            pass

    return {
        "total": total,
        "enabled": enabled,
        "disabled": disabled,
        "never_run": never_run,
        "by_status": by_status,
        "degraded": degraded,
        "findings_total": findings_total,
        "last_run_at": _latest_iso(finished_ats),
    }


def tile_validation_stamps(
    *,
    nest_last_validated_at: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Per-tile validated stamp payload for the Dashboard (#373).

    Each value is ``{"has_validator": bool, "at": iso|None}`` plus optional
    ``label`` for placeholders (e.g. VMs: ``not implemented``).

    Alerts and Validators tiles are omitted: Alerts has no validator; the
    Validators tile's max-of-all run time is not a meaningful rollup.
    """
    latest = validator_runs.latest_by_validator()

    def _stamp_for(ids: tuple[str, ...]) -> dict[str, Any]:
        times: list[str] = []
        for vid in ids:
            run = latest.get(vid) or {}
            at = run.get("finished_at") or run.get("started_at")
            if isinstance(at, str) and at:
                times.append(at)
        return {"has_validator": True, "at": _latest_iso(times)}

    stamps: dict[str, dict[str, Any]] = {
        key: _stamp_for(ids) for key, ids in _TILE_VALIDATORS.items()
    }

    # Prefer Nest reachability snapshot when it is newer than validator runs.
    nest_stamp = stamps["nests"]
    if nest_last_validated_at and (
        not nest_stamp.get("at") or nest_last_validated_at > nest_stamp["at"]
    ):
        stamps["nests"] = {"has_validator": True, "at": nest_last_validated_at}

    stamps["vms"] = {
        "has_validator": False,
        "at": None,
        "label": "not implemented",
    }
    return stamps


def dashboard_summary() -> dict[str, Any]:
    """Payload for ``GET /api/dashboard-summary``."""
    from lib import alerts as alerts_lib

    nest_fields = nest_tile_fields()
    alert_count = alerts_lib.count_active_by_prefixes(alerts_lib.NEST_SCOPED_ALERT_PREFIXES)
    validators = validators_summary()
    return {
        "nests": {
            "total": nest_fields["nest_total"],
            "reachable": nest_fields["nest_reachable"],
            "unreachable": nest_fields["nest_unreachable"],
            "unchecked": nest_fields["nest_unchecked"],
            "alert_count": alert_count,
            "last_validated_at": nest_fields["nest_last_validated_at"],
            "by_provider": nest_fields["nest_by_provider"],
        },
        "vms": vm_summary(),
        "clutches": clutch_summary(),
        "library": library_summary(),
        "validators": validators,
        "validated": tile_validation_stamps(
            nest_last_validated_at=nest_fields["nest_last_validated_at"],
        ),
    }


def _latest_iso(values: list[str]) -> str | None:
    if not values:
        return None
    return max(values)
