"""Cross-Nest VM inventory enrichment (UI + operator surfaces).

Live hypervisor list via Nest factory, plus Hatch session metadata when tagged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lib import config
from lib import hatch as hatch_lib
from lib import nests as nests_lib
from lib import software as software_lib
from lib.providers.base import resolve_nest_storage_root, vm_nest_dir
from lib.providers.factory import (
    NoNestSelectedError,
    UnknownNestError,
    UnsupportedProviderError,
    get_provider,
)


def _enrich_script_reboot_source(script: dict[str, Any]) -> None:
    """Attach reboot-after source for Nest/VM detail automation rows (#563).

    Clutch ``reboot_after`` is stored on the hatch row. Software may also force
    a mid-walk reboot via ``software.yaml`` ``install.reboot_after``.
    """
    clutch = bool(script.get("reboot_after"))
    yaml_reboot = False
    if (script.get("entry_type") or "script") == "software":
        yaml_reboot = software_lib.package_definition_reboot_after(script.get("script_name") or "")
    script["definition_reboot_after"] = yaml_reboot
    if clutch and yaml_reboot:
        source = "both"
    elif yaml_reboot:
        source = "yaml"
    elif clutch:
        source = "clutch"
    else:
        source = "none"
    script["reboot_after_source"] = source
    script["reboot_after_effective"] = clutch or yaml_reboot


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


def _vm_from_clutch_source(
    *,
    session_id: str | None,
    clutch_file: str | None,
    vm_name: str,
):
    """Resolve VMConfig from hatch session snapshot (#514), else live Clutch file."""
    from lib import clutch as clutch_lib
    from lib import hatch as hatch_lib

    if session_id:
        snap_vm = hatch_lib.load_session_vm_config(session_id, vm_name)
        if snap_vm is not None:
            return snap_vm
    if not clutch_file:
        return None
    path = config.data_dir() / "clutches" / Path(clutch_file).name
    try:
        clutch = clutch_lib.load(path)
    except Exception:
        return None
    for vm in clutch.vms:
        if vm.name == vm_name:
            return vm
    return None


def _resolved_environment(
    guest_os: str,
    *,
    clutch_file: str | None,
    vm_name: str,
    session_id: str | None = None,
) -> list[dict[str, str]]:
    """Return resolved guest env rows (reserved base + Clutch user) for VM details."""
    from lib import guest_env as guest_env_lib

    user_entries = []
    vm = _vm_from_clutch_source(
        session_id=session_id,
        clutch_file=clutch_file,
        vm_name=vm_name,
    )
    if vm is not None:
        user_entries = list(vm.environment or [])
    try:
        user_env = guest_env_lib.entries_to_process_map(user_entries)
        merged = guest_env_lib.merge_guest_environment(
            guest_env_lib.reserved_environment(guest_os),
            user_env,
        )
    except ValueError:
        return []
    reserved = set(guest_env_lib.RESERVED_BASE)
    rows: list[dict[str, str]] = []
    for key, value in merged.items():
        if key in reserved:
            rows.append(
                {
                    "name": key,
                    "value": value,
                    "source": "reserved",
                    "scope": "machine",
                    "persist": "yes",
                    "mode": "replace",
                }
            )
            continue
        entry = next((e for e in user_entries if e.name == key), None)
        rows.append(
            {
                "name": key,
                "value": value,
                "source": "clutch",
                "scope": (
                    entry.scope.value if entry and hasattr(entry.scope, "value") else "machine"
                ),
                "persist": "yes" if (entry is None or entry.persist) else "no",
                "mode": (entry.mode.value if entry and hasattr(entry.mode, "value") else "replace"),
            }
        )
    for item in guest_env_lib.reserved_env_catalog(guest_os):
        if item.get("mode") == "append":
            rows.append(
                {
                    "name": item["name"],
                    "value": item["value"],
                    "source": "reserved",
                    "scope": "machine",
                    "persist": "yes",
                    "mode": "append",
                }
            )
            continue
        if item["scope"] == "software":
            rows.append(
                {
                    "name": item["name"],
                    "value": item["value"],
                    "source": "software",
                    "scope": "",
                    "persist": "job",
                    "mode": "",
                }
            )
    return rows


def _clutch_vm_create_policy(
    *,
    clutch_file: str | None,
    vm_name: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Return firmware/tpm from the Clutch VM when available."""
    out: dict[str, Any] = {"firmware": None, "tpm": None}
    vm = _vm_from_clutch_source(
        session_id=session_id,
        clutch_file=clutch_file,
        vm_name=vm_name,
    )
    if vm is None:
        return out
    out["firmware"] = vm.firmware.value if vm.firmware else None
    out["tpm"] = vm.tpm
    return out


def _as_vm_id(value: Any) -> str | None:
    """Return a string VM UUID, or None for missing/non-string values."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _resolve_nest_storage_path(
    provider: Any,
    *,
    vm_id: str | None,
) -> str | None:
    """Return ``{nest_storage}/{vm_id}`` when root and uuid are known (#587 / #600).

    Does not query Hyper-V host defaults during inventory (avoid Nest chatter).
    """
    if not vm_id:
        return None
    nest_storage = getattr(provider, "nest_storage", None)
    provider_default = None
    default_fn = getattr(provider, "_provider_default_storage_root", None)
    if callable(default_fn):
        try:
            provider_default = default_fn()
        except Exception:
            provider_default = None
    root = resolve_nest_storage_root(
        nest_storage=nest_storage,
        provider_default=provider_default,
    )
    if root is None:
        return None
    return str(vm_nest_dir(root, vm_id))


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

    # Transport / hypervisor failures must not 500 the page: treat like
    # provider unavailable so cross-Nest inventory can skip this Nest.
    try:
        vms = provider.list_vms()
    except Exception as exc:
        raise NestProviderUnavailableError(str(exc)) from exc
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
            "firmware": None,
            "tpm": None,
            "vm_id": None,
            "nest_storage_path": None,
            "environment": [],
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
            try:
                record["vm_id"] = _as_vm_id(provider.get_vm_uuid(name))
            except Exception:
                pass
            record["nest_storage_path"] = _resolve_nest_storage_path(
                provider,
                vm_id=record.get("vm_id"),
            )
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
                record["vm_id"] = _as_vm_id(db_row.get("libvirt_uuid"))
                guest_os = db_row.get("guest_os")
                if guest_os:
                    record["os"] = guest_os
                    record["environment"] = _resolved_environment(
                        guest_os,
                        clutch_file=record.get("clutch_file"),
                        vm_name=name,
                        session_id=sid,
                    )
                policy = _clutch_vm_create_policy(
                    clutch_file=record.get("clutch_file"),
                    vm_name=name,
                    session_id=sid,
                )
                record["firmware"] = policy.get("firmware")
                record["tpm"] = policy.get("tpm")
            scripts = hatch_lib.get_vm_scripts(sid, name)
            last_events = hatch_lib.get_last_script_event_messages(sid, name)
            for script in scripts:
                script["last_event"] = last_events.get(script["script_name"])
                _enrich_script_reboot_source(script)
            record["scripts"] = scripts

        if not record.get("vm_id"):
            try:
                record["vm_id"] = _as_vm_id(provider.get_vm_uuid(name))
            except Exception:
                pass
        record["nest_storage_path"] = _resolve_nest_storage_path(
            provider,
            vm_id=record.get("vm_id"),
        )

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
        except Exception:
            # Belt-and-suspenders: never fail the whole inventory for one Nest.
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
