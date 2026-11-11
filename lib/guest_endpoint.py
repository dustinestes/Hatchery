"""Guest remoting known-endpoint bind (#621).

Authenticated guest SSH/WinRM must target a VM UUID that exists on this
Controller's Nest registry, with a live Nest IP matching the remoting address.
Prevents hierarchy-lite via smuggled credentials / arbitrary guest IPs.
"""

from __future__ import annotations

from dataclasses import dataclass


class GuestUnknownEndpointError(RuntimeError):
    """Raised when guest remoting targets an unbound or foreign endpoint (#621)."""


@dataclass(frozen=True)
class KnownGuest:
    """Nest-proven guest remoting target."""

    vm_id: str
    nest_id: str
    name: str
    host: str


def _normalize_host(host: str) -> str:
    return (host or "").strip().lower()


def _hatch_status_for_uuid(vm_id: str) -> str | None:
    """Return hatch_vm_status.status for this UUID when a row exists."""
    from lib import db as db_module

    if not db_module.is_initialized():
        return None
    conn = db_module.get_connection()
    try:
        row = conn.execute(
            """
            SELECT status FROM hatch_vm_status
            WHERE libvirt_uuid = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (vm_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return str(row["status"] or "").strip() or None


def resolve_known_guest(
    *,
    vm_id: str,
    nest_id: str | None = None,
) -> KnownGuest:
    """Resolve ``vm_id`` to a Nest-local name and live guest IP on this Controller."""
    alias = (vm_id or "").strip()
    if not alias:
        raise GuestUnknownEndpointError("Guest remoting requires a VM UUID (vm_id).")

    status = _hatch_status_for_uuid(alias)
    if status == "destroyed":
        raise GuestUnknownEndpointError(f"Refusing guest remoting to destroyed VM UUID {alias}.")

    from lib import nests as nests_lib
    from lib.providers import factory as factory_lib

    nests = nests_lib.list_nests()
    if nest_id:
        nests = [n for n in nests if n.get("id") == nest_id]
        if not nests:
            raise GuestUnknownEndpointError(
                f"Nest id {nest_id!r} is not registered on this Controller."
            )

    last_error: str | None = None
    for nest in nests:
        nid = str(nest.get("id") or "").strip()
        if not nid:
            continue
        try:
            provider = factory_lib.get_provider(nid)
        except (
            factory_lib.UnknownNestError,
            factory_lib.UnsupportedProviderError,
            factory_lib.NoNestSelectedError,
        ) as exc:
            last_error = str(exc)
            continue
        name = provider.get_vm_name_by_uuid(alias)
        if not name:
            continue
        live_ip = provider.get_vm_ip(name)
        if not live_ip or not str(live_ip).strip():
            raise GuestUnknownEndpointError(
                f"VM UUID {alias} has no guest IP yet; remoting deferred."
            )
        return KnownGuest(
            vm_id=alias,
            nest_id=nid,
            name=str(name),
            host=str(live_ip).strip(),
        )

    if last_error:
        raise GuestUnknownEndpointError(
            f"VM UUID {alias} is not known on this Controller's Nests ({last_error})."
        )
    raise GuestUnknownEndpointError(f"VM UUID {alias} is not known on this Controller's Nests.")


def assert_guest_host_bound(
    *,
    host: str,
    vm_id: str,
    nest_id: str | None = None,
) -> KnownGuest:
    """Verify ``host`` matches the live Nest IP for ``vm_id`` on this Controller."""
    known = resolve_known_guest(vm_id=vm_id, nest_id=nest_id)
    wanted = _normalize_host(host)
    expected = _normalize_host(known.host)
    if not wanted:
        raise GuestUnknownEndpointError("Guest host is required")
    if wanted != expected:
        raise GuestUnknownEndpointError(
            f"Guest address {host} does not match Nest IP for VM UUID {known.vm_id} "
            f"(expected {known.host})."
        )
    return known
