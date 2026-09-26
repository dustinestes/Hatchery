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


def destroy_vm(nest_id: str, name: str) -> None:
    provider = _resolve_provider(nest_id)
    _run(lambda: provider.destroy_vm(name))


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
