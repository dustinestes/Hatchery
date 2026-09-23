"""Nest reachability probes, Alerts, and footer/Nests status snapshot (#263).

Reachability is Nest transport (or Local co-location), not hypervisor capability
(#208) and not guest health. Status is persisted in ``app_settings`` so the
footer and Nests pane work across requests between validator ticks.

One validator contract; dynamic reason lives on the result:

- ``endpoint`` — host:port not reachable
- ``transport`` — endpoint found, Nest transport session not accessible
- ``config`` — cannot run a probe from this Nest row / session
"""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from typing import Any

from lib import alerts as alerts_lib
from lib import config
from lib import nests as nests_lib
from lib.nest_transport import NestHealthCheckResult, get_nest_transport

ALERT_PREFIX = "Nest reachability:"
_SETTINGS_KEY = "nest_reachability_status"

# Human labels for Alert / UI detail (hard contracts — not transient magic).
_FAILURE_LABELS = {
    "endpoint": "endpoint not reachable",
    "transport": "endpoint reachable; Nest transport not accessible",
    "config": "cannot probe (Nest configuration)",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_failure_detail(failure_class: str, detail: str) -> str:
    """Prefix probe detail with the diagnostic class label."""
    label = _FAILURE_LABELS.get(failure_class, failure_class)
    detail = (detail or "").strip()
    if not detail:
        return label
    return f"{label} - {detail}"


def alert_message(nest: dict, detail: str) -> str:
    nest_id = nest.get("id") or "?"
    nest_name = nest.get("name") or nest_id
    return f"{ALERT_PREFIX} '{nest_name}' ({nest_id}): {detail}"


def alert_prefix_for_nest(nest: dict) -> str:
    nest_id = nest.get("id") or "?"
    nest_name = nest.get("name") or nest_id
    return f"{ALERT_PREFIX} '{nest_name}' ({nest_id}):"


def probe_tcp_endpoint(host: str, port: int, *, timeout: float = 5.0) -> NestHealthCheckResult:
    """True TCP connect to host:port — endpoint exists and accepts connections."""
    host = (host or "").strip()
    if not host:
        return NestHealthCheckResult(
            ok=False,
            detail="Nest host is empty",
            failure_class="config",
        )
    try:
        port_n = int(port)
    except (TypeError, ValueError):
        return NestHealthCheckResult(
            ok=False,
            detail=f"Invalid Nest port: {port!r}",
            failure_class="config",
        )
    try:
        with socket.create_connection((host, port_n), timeout=timeout):
            return NestHealthCheckResult(
                ok=True,
                detail=f"TCP {host}:{port_n} open",
            )
    except TimeoutError:
        return NestHealthCheckResult(
            ok=False,
            detail=format_failure_detail(
                "endpoint",
                f"timed out connecting to {host}:{port_n}",
            ),
            failure_class="endpoint",
        )
    except OSError as exc:
        return NestHealthCheckResult(
            ok=False,
            detail=format_failure_detail(
                "endpoint",
                f"{host}:{port_n} - {exc}",
            ),
            failure_class="endpoint",
        )


def probe_nest(nest: dict, *, winrm_password: str | None = None) -> NestHealthCheckResult:
    """Probe one Nest: Local co-located; Remote = endpoint TCP then Nest transport."""
    location = nest.get("location") or "local"
    if location == "local":
        return NestHealthCheckResult(
            ok=True,
            detail="Local Nest - co-located with the Controller (no Nest transport).",
        )

    transport_name = nest.get("transport") or "ssh"
    if transport_name == "winrm" and not (winrm_password or "").strip():
        return NestHealthCheckResult(
            ok=False,
            detail=format_failure_detail(
                "config",
                "WinRM password required to probe reachability (not stored - #110).",
            ),
            failure_class="config",
        )

    try:
        connection = nests_lib.to_connection_config(nest, winrm_password=winrm_password)
        transport = get_nest_transport(connection)
    except (ValueError, TypeError) as exc:
        return NestHealthCheckResult(
            ok=False,
            detail=format_failure_detail("config", str(exc)),
            failure_class="config",
        )

    if transport is None:
        return NestHealthCheckResult(
            ok=True,
            detail="Local Nest - co-located with the Controller (no Nest transport).",
        )

    # Endpoint contract: can we open TCP to the Nest's transport port?
    if transport_name == "winrm" and connection.winrm is not None:
        host = connection.winrm.host
        port = int(connection.winrm.port)
        timeout = float(connection.winrm.operation_timeout_sec)
    elif connection.ssh is not None:
        host = connection.ssh.host
        port = int(connection.ssh.port)
        timeout = float(connection.ssh.connect_timeout_seconds)
    else:
        return NestHealthCheckResult(
            ok=False,
            detail=format_failure_detail("config", "Remote Nest missing transport config"),
            failure_class="config",
        )

    endpoint = probe_tcp_endpoint(host, port, timeout=min(timeout, 10.0))
    if not endpoint.ok:
        return endpoint

    # Transport contract: authenticated Nest session / trivial remote command.
    session = transport.test_connection()
    if session.ok:
        return NestHealthCheckResult(
            ok=True,
            detail="endpoint reachable; Nest transport OK",
        )
    detail = session.detail or "Nest transport session failed"
    if session.failure_class == "transport" or not detail.startswith("endpoint"):
        detail = format_failure_detail("transport", detail)
    return NestHealthCheckResult(
        ok=False,
        detail=detail,
        failure_class="transport",
    )


def _empty_snapshot() -> dict[str, Any]:
    return {
        "updated_at": None,
        "nests": {},
        "local_ok": True,
        "remotes_ok": True,
        "remote_total": 0,
        "remote_down": 0,
    }


def get_snapshot() -> dict[str, Any]:
    """Return last known reachability snapshot (may be empty before first probe)."""
    raw = config.get().get(_SETTINGS_KEY)
    if not isinstance(raw, dict):
        return _empty_snapshot()
    nests = raw.get("nests") if isinstance(raw.get("nests"), dict) else {}
    return {
        "updated_at": raw.get("updated_at"),
        "nests": nests,
        "local_ok": bool(raw.get("local_ok", True)),
        "remotes_ok": bool(raw.get("remotes_ok", True)),
        "remote_total": int(raw.get("remote_total") or 0),
        "remote_down": int(raw.get("remote_down") or 0),
    }


def _save_snapshot(snap: dict[str, Any]) -> None:
    # Partial write only - full config.save would clobber Library / retention (#366).
    config.update_settings({_SETTINGS_KEY: snap})


def record_probe(
    nest: dict,
    result: NestHealthCheckResult,
    *,
    checked_at: str | None = None,
) -> dict[str, Any]:
    """Merge one Nest probe into the persisted snapshot and return the nest entry."""
    nest_id = nest.get("id") or "?"
    entry = {
        "ok": bool(result.ok),
        "message": result.detail or ("OK" if result.ok else "Unreachable"),
        "failure_class": result.failure_class,
        "checked_at": checked_at or _utc_now(),
        "location": nest.get("location") or "local",
        "name": nest.get("name") or nest_id,
    }
    snap = get_snapshot()
    nests = dict(snap.get("nests") or {})
    nests[nest_id] = entry
    snap = _recompute_summary(nests)
    _save_snapshot(snap)
    return entry


def _recompute_summary(nests: dict[str, Any]) -> dict[str, Any]:
    local_ok = True
    remote_total = 0
    remote_down = 0
    for nid, entry in nests.items():
        if not isinstance(entry, dict):
            continue
        loc = entry.get("location") or ("local" if nid == nests_lib.LOCAL_NEST_ID else "remote")
        ok = bool(entry.get("ok"))
        if loc == "local" or nid == nests_lib.LOCAL_NEST_ID:
            local_ok = ok
        else:
            remote_total += 1
            if not ok:
                remote_down += 1
    return {
        "updated_at": _utc_now(),
        "nests": nests,
        "local_ok": local_ok,
        "remotes_ok": remote_down == 0,
        "remote_total": remote_total,
        "remote_down": remote_down,
    }


def sync_alert_for_probe(nest: dict, result: NestHealthCheckResult) -> None:
    """Open or clear the reachability alert for one Nest.

    Keys off Nest **id** (not display name) so renames / detail text changes cannot
    leave multiple active reachability Alerts for the same Nest (#288).
    """
    nest_id = str(nest.get("id") or "").strip() or "?"
    if result.ok:
        alerts_lib.resolve_alerts_for_prefix_and_nest_id(ALERT_PREFIX, nest_id)
        return
    detail = result.detail or "Unreachable"
    if result.failure_class == "config" and "WinRM password required" in detail:
        alerts_lib.resolve_alerts_for_prefix_and_nest_id(ALERT_PREFIX, nest_id)
        return

    active = alerts_lib.list_active_for_prefix_and_nest_id(ALERT_PREFIX, nest_id)
    if len(active) > 1:
        # Collapse rename / detail churn duplicates — keep newest.
        for row in active[1:]:
            alerts_lib.resolve(int(row["id"]))
        return
    if len(active) == 1:
        return
    alerts_lib.record_alert(alert_message(nest, detail))


def run_probes(
    *,
    nest_id: str | None = None,
    winrm_password: str | None = None,
    sync_alerts: bool = True,
) -> dict[str, Any]:
    """Probe one Nest or all registered Nests; update snapshot and optional Alerts."""
    rows = nests_lib.list_nests()
    if nest_id:
        rows = [n for n in rows if n.get("id") == nest_id]
    checked = 0
    down = 0
    for nest in rows:
        location = nest.get("location") or "local"
        transport_name = nest.get("transport") or "ssh"
        if (
            location == "remote"
            and transport_name == "winrm"
            and not (winrm_password or "").strip()
        ):
            # Cannot probe without password on schedule — leave prior status.
            continue
        result = probe_nest(nest, winrm_password=winrm_password)
        record_probe(nest, result)
        if sync_alerts:
            sync_alert_for_probe(nest, result)
        checked += 1
        if not result.ok:
            down += 1
    snap = get_snapshot()
    snap["last_run"] = {
        "checked": checked,
        "down": down,
        "at": _utc_now(),
    }
    _save_snapshot(snap)
    return snap


def prune_removed_nests(kept_ids: set[str]) -> None:
    """Drop snapshot entries for Nest ids no longer in the registry; recompute footer."""
    snap = get_snapshot()
    nests = dict(snap.get("nests") or {})
    if not nests:
        return
    pruned = {nid: entry for nid, entry in nests.items() if nid in kept_ids}
    if pruned.keys() == nests.keys():
        return
    _save_snapshot(_recompute_summary(pruned))


def nest_dot_class(nest_id: str) -> str:
    """CSS modifier for Nests pane status dot (green/red only — amber deferred)."""
    snap = get_snapshot()
    entry = (snap.get("nests") or {}).get(nest_id)
    if entry is None:
        return "nest-status-dot--green"
    return "nest-status-dot--green" if entry.get("ok") else "nest-status-dot--red"


def is_reachable_for_capability(nest: dict) -> bool:
    """Whether Nest capability checks may run for this Nest (#286).

    Local Nests are co-located — always True. Remote Nests require a successful
    reachability snapshot entry; unreachable or never-probed Remotes must not
    invent "missing tool" findings from failed transport probes.
    """
    location = nest.get("location") or "local"
    if location == "local":
        return True
    nest_id = nest.get("id")
    if not nest_id:
        return False
    entry = (get_snapshot().get("nests") or {}).get(nest_id)
    if not isinstance(entry, dict):
        return False
    return bool(entry.get("ok"))


def nest_reachability_label(nest_id: str) -> str:
    """Accessible text for reachability (not color-only)."""
    snap = get_snapshot()
    entry = (snap.get("nests") or {}).get(nest_id)
    if entry is None:
        return "Reachability not checked yet"
    if entry.get("ok"):
        return "Reachable"
    fc = entry.get("failure_class")
    if fc == "endpoint":
        return "Endpoint not reachable"
    if fc == "transport":
        return "Transport not accessible"
    if fc == "config":
        return "Cannot probe"
    return "Unreachable"
