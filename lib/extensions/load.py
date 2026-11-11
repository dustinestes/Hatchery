"""Load optional ``hatchery_enterprise`` into the Controller (ADR-0043)."""

from __future__ import annotations

import logging

from lib.extensions.api import ExtensionApi, get_api

log = logging.getLogger(__name__)

_LOADED = False


def load_extensions(*, force: bool = False) -> ExtensionApi:
    """Try-import the commercial package and call ``register(api)``.

    Idempotent. Absent package leaves free entitlements.
    Public CI never requires the private package. Dev free-mode and
    entitlement toggles are owned by the Enterprise package, not here.
    """
    global _LOADED
    api = get_api()
    if _LOADED and not force:
        return api
    try:
        import hatchery_enterprise
    except ImportError:
        _LOADED = True
        return api
    register = getattr(hatchery_enterprise, "register", None)
    if not callable(register):
        log.warning("hatchery_enterprise has no register(); ignoring package")
        _LOADED = True
        return api
    register(api)
    _LOADED = True
    return api


def reset_load_state_for_tests() -> None:
    """Allow tests to call ``load_extensions(force=True)`` from a clean slate."""
    global _LOADED
    _LOADED = False
