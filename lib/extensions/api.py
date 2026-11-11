"""Extension API passed to ``hatchery_enterprise.register`` (ADR-0043)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from lib.extensions.entitlements import Entitlements, free_entitlements

CliRegistrar = Callable[[Any], None]
FlaskHook = Callable[[Any], None]


class ExtensionApi:
    """Narrow registration surface for the commercial package."""

    def __init__(self) -> None:
        self._entitlements = free_entitlements()
        self._cli_registrars: list[CliRegistrar] = []
        self._flask_hooks: list[FlaskHook] = []

    def entitlements(self) -> Entitlements:
        return self._entitlements

    def set_entitlements(self, entitlements: Entitlements) -> None:
        self._entitlements = entitlements

    def register_cli(self, registrar: CliRegistrar) -> None:
        """``registrar(subparsers)`` - same shape as ``lib.cli.*.register``."""
        self._cli_registrars.append(registrar)

    def register_flask(self, hook: FlaskHook) -> None:
        """``hook(app)`` - attach blueprints / routes when UI packs land."""
        self._flask_hooks.append(hook)

    def register_validator(self, validator: Any) -> Any:
        """Delegate to the public validator registry."""
        from lib.validators.registry import register

        return register(validator)

    def apply_cli(self, subparsers: Any) -> None:
        for registrar in self._cli_registrars:
            registrar(subparsers)

    def apply_flask(self, app: Any) -> None:
        for hook in self._flask_hooks:
            hook(app)


_api = ExtensionApi()


def get_api() -> ExtensionApi:
    return _api


def reset_api_for_tests() -> ExtensionApi:
    """Replace the process-wide API (tests only)."""
    global _api
    _api = ExtensionApi()
    return _api
