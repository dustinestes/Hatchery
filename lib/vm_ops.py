"""Nest-scoped VM lifecycle helpers shared by UI routes and CLI.

Wraps Nest factory + provider mutate / health / snap. Does not require Flask.
"""

from __future__ import annotations

import subprocess
from typing import Any, Callable

from lib.guest_health import guest_health
from lib.providers.factory import (
    NoNestSelectedError,
    UnknownNestError,
    UnsupportedProviderError,
    get_provider,
)
from lib.run_cmd import format_process_error


class VmOpsError(Exception):
    """Operator-facing VM action failure."""

    def __init__(self, message: str, *, code: str = "error") -> None:
        super().__init__(message)
        self.code = code


class NestResolveError(VmOpsError):
    def __init__(self, message: str, *, code: str = "not_found") -> None:
        super().__init__(message, code=code)


class ProviderActionError(VmOpsError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="provider")


def _resolve_provider(nest_id: str):
    try:
        return get_provider(nest_id)
    except UnknownNestError as exc:
        raise NestResolveError(str(exc), code="not_found") from exc
    except NoNestSelectedError as exc:
        raise NestResolveError(str(exc), code="not_found") from exc
    except UnsupportedProviderError as exc:
        raise NestResolveError(str(exc), code="unavailable") from exc


def _run(action: Callable[[], Any]) -> None:
    try:
        action()
    except subprocess.CalledProcessError as exc:
        raise ProviderActionError(format_process_error(exc)) from exc
    except VmOpsError:
        raise
    except Exception as exc:
        raise ProviderActionError(format_process_error(exc)) from exc


def start_vm(nest_id: str, name: str) -> None:
    provider = _resolve_provider(nest_id)
    _run(lambda: provider.start_vm(name))


def stop_vm(nest_id: str, name: str) -> None:
    provider = _resolve_provider(nest_id)
    _run(lambda: provider.stop_vm(name))


def force_stop_vm(nest_id: str, name: str) -> None:
    provider = _resolve_provider(nest_id)
    _run(lambda: provider.force_stop_vm(name))


def pause_vm(nest_id: str, name: str) -> None:
    provider = _resolve_provider(nest_id)
    _run(lambda: provider.pause_vm(name))


def resume_vm(nest_id: str, name: str) -> None:
    provider = _resolve_provider(nest_id)
    _run(lambda: provider.resume_vm(name))


def protect_media_basenames_for_destroy(provider, name: str) -> frozenset[str] | None:
    """Clutch-snapshot OS/VirtIO basenames for Destroy media protect (#601).

    Returns a frozenset (possibly empty) when a hatch session tag and clutch
    snapshot VM row exist. Returns ``None`` when there is no snapshot so the
    provider falls back to catalog-root eject (``iso_dir`` / ``virtio_dir``).
    """
    from pathlib import Path

    try:
        tag = provider.get_vm_session_tag(name)
    except Exception:
        return None
    if not isinstance(tag, dict):
        return None
    session_id = tag.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    try:
        from lib import hatch as hatch_lib

        vm = hatch_lib.load_session_vm_config(session_id.strip(), name)
    except Exception:
        return None
    if vm is None:
        return None
    names: set[str] = set()
    os_media = getattr(vm, "os_media", None) or ""
    virtio = getattr(vm, "virtio_drivers", None) or ""
    if os_media:
        names.add(Path(str(os_media)).name)
    if virtio:
        names.add(Path(str(virtio)).name)
    return frozenset(names)


def destroy_vm(nest_id: str, name: str) -> None:
    from lib import guest_transport as gt

    provider = _resolve_provider(nest_id)
    vm_id: str | None = None
    try:
        raw = provider.get_vm_uuid(name)
        vm_id = raw if isinstance(raw, str) else None
    except Exception:
        vm_id = None
    protect = protect_media_basenames_for_destroy(provider, name)
    _run(lambda: provider.destroy_vm(name, protect_media_basenames=protect))
    # Best-effort prune HostKeyAlias after Nest destroy (#593).
    gt.remove_guest_known_host(vm_id)


def health_vm(nest_id: str, name: str) -> dict[str, Any]:
    provider = _resolve_provider(nest_id)
    try:
        return guest_health(provider, name)
    except Exception as exc:
        raise ProviderActionError(format_process_error(exc)) from exc


def list_snapshots(nest_id: str, name: str) -> list[str]:
    provider = _resolve_provider(nest_id)
    try:
        return list(provider.list_snapshots(name))
    except Exception as exc:
        raise ProviderActionError(format_process_error(exc)) from exc


def take_snapshot(nest_id: str, name: str, label: str) -> None:
    provider = _resolve_provider(nest_id)
    _run(lambda: provider.create_snapshot(name, label))


def apply_snapshot(nest_id: str, name: str, label: str) -> None:
    provider = _resolve_provider(nest_id)
    _run(lambda: provider.revert_snapshot(name, label))


def delete_snapshot(nest_id: str, name: str, label: str) -> None:
    provider = _resolve_provider(nest_id)
    _run(lambda: provider.delete_snapshot(name, label))
