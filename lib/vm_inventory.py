"""Cross-Nest VM inventory enrichment (UI + operator surfaces).

Live hypervisor list via Nest factory, plus Hatch session metadata when tagged.
"""

from __future__ import annotations

from typing import Any

from lib import config
from lib import hatch as hatch_lib
from lib import nests as nests_lib
from lib.providers.factory import (
    NoNestSelectedError,
    UnknownNestError,
    UnsupportedProviderError,
    get_provider,
)


class VmInventoryError(Exception):
    """Base error for Nest-scoped inventory reads."""

    def __init__(self, message: str, *, code: str = "error") -> None:
        super().__init__(message)
        self.code = code


class NestNotFoundError(VmInventoryError):
    def __init__(self, nest_id: str) -> None:
        super().__init__(f"Unknown Nest id: {nest_id}", code="not_found")
        self.nest_id = nest_id


class NestProviderUnavailableError(VmInventoryError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="unavailable")


def list_enriched_vms(nest_id: str, *, show_passwords: bool | None = None) -> list[dict[str, Any]]:
    """Return enriched VM rows for one Nest.

    Each row includes ``nest``, power ``status``, hatch metadata when tagged,
    and ``hatchery_sourced`` (True when a Hatchery session tag is present).
    """
    nest_row = nests_lib.get_nest(nest_id)
    if nest_row is None:
        raise NestNotFoundError(nest_id)

    try:
        provider = get_provider(nest_id)
    except (NoNestSelectedError, UnknownNestError, UnsupportedProviderError) as exc:
        raise NestProviderUnavailableError(str(exc)) from exc

    if show_passwords is None:
        show_passwords = config.show_passwords()

    vms = provider.list_vms()
    result: list[dict[str, Any]] = []
    for vm in vms:
        name = vm["name"]
        record: dict[str, Any] = {
            "nest": nest_id,
            "name": name,
            "status": vm["status"],
            "hatchery_sourced": False,
            "hatch_status": None,
            "ip": None,
            "clutch_file": None,
            "session_id": None,
            "started_at": None,
            "admin_username": None,
            "admin_password": None,
            "os": None,
            "scripts": [],
        }

        try:
            record["ip"] = provider.get_vm_ip(name)
        except Exception:
            pass

        try:
            tag = provider.get_vm_session_tag(name)
        except Exception:
            tag = None

        if not tag:
            result.append(record)
            continue

        record["hatchery_sourced"] = True
        session = hatch_lib.get_session(tag["session_id"]) if tag.get("session_id") else None
        if session is not None and session.get("nest") != nest_id:
            result.append(record)
            continue

        record["session_id"] = tag.get("session_id")
        record["clutch_file"] = tag.get("clutch_file")
        sid = tag.get("session_id")
        if sid:
            db_row = hatch_lib.get_vm_record(sid, name)
            if db_row:
                record["hatch_status"] = db_row.get("status")
                record["started_at"] = db_row.get("started_at")
                record["admin_username"] = db_row.get("admin_username")
                if show_passwords:
                    record["admin_password"] = db_row.get("admin_password")
            scripts = hatch_lib.get_vm_scripts(sid, name)
            last_events = hatch_lib.get_last_script_event_messages(sid, name)
            for script in scripts:
                script["last_event"] = last_events.get(script["script_name"])
            record["scripts"] = scripts

        result.append(record)
    return result


def list_enriched_vms_all_nests(
    *,
    show_passwords: bool | None = None,
    hatchery_sourced_only: bool | None = None,
) -> dict[str, Any]:
    """Return cross-Nest inventory plus unavailable Nest ids.

    Returns ``{"vms": [...], "nests_unavailable": [id, ...]}``.

    When ``hatchery_sourced_only`` is None, uses Settings ``vms_show_external``
    (default hide external). Pass True/False to override.
    """
    if hatchery_sourced_only is None:
        hatchery_sourced_only = not config.vms_show_external()
    vms: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for nest in nests_lib.list_nests():
        nid = nest.get("id")
        if not nid:
            continue
        try:
            rows = list_enriched_vms(nid, show_passwords=show_passwords)
        except (NestNotFoundError, NestProviderUnavailableError):
            unavailable.append(nid)
            continue
        if hatchery_sourced_only:
            rows = [r for r in rows if r.get("hatchery_sourced")]
        vms.extend(rows)
    return {"vms": vms, "nests_unavailable": unavailable}


def filter_external(rows: list[dict[str, Any]], *, include_external: bool) -> list[dict[str, Any]]:
    """Filter Nest-scoped rows by Hatchery provenance."""
    if include_external:
        return rows
    return [r for r in rows if r.get("hatchery_sourced")]
