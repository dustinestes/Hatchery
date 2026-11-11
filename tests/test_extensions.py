"""Controller extension load (ADR-0043 / #619)."""

from __future__ import annotations

import sys
import types

import pytest

from lib.extensions import (
    Entitlements,
    free_entitlements,
    load_extensions,
    reset_api_for_tests,
    reset_load_state_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_extensions():
    reset_api_for_tests()
    reset_load_state_for_tests()
    # Ensure no real commercial package leaks into public tests.
    sys.modules.pop("hatchery_enterprise", None)
    yield
    reset_api_for_tests()
    reset_load_state_for_tests()
    sys.modules.pop("hatchery_enterprise", None)


def test_free_entitlements_defaults():
    e = free_entitlements()
    assert e.max_nests == 1
    assert e.features == frozenset()
    assert not e.has("nest_agent")


def test_load_absent_package_keeps_free():
    api = load_extensions(force=True)
    assert api.entitlements().max_nests == 1
    assert not api.entitlements().has("nest_agent")


def test_load_calls_register_once(monkeypatch):
    calls: list[object] = []

    def register(api):
        calls.append(api)
        api.set_entitlements(Entitlements(max_nests=3, features=frozenset({"nest_agent"})))

    fake = types.ModuleType("hatchery_enterprise")
    fake.register = register
    monkeypatch.setitem(sys.modules, "hatchery_enterprise", fake)

    api = load_extensions(force=True)
    assert len(calls) == 1
    assert calls[0] is api
    assert api.entitlements().max_nests == 3
    assert api.entitlements().has("nest_agent")

    load_extensions()  # idempotent
    assert len(calls) == 1


def test_register_cli_applied_to_subparsers(monkeypatch):
    seen: list[object] = []

    def register(api):
        def add_cmd(sub):
            seen.append(sub)
            p = sub.add_parser("enterprise-probe")
            p.set_defaults(run=lambda _args: 0)

        api.register_cli(add_cmd)

    fake = types.ModuleType("hatchery_enterprise")
    fake.register = register
    monkeypatch.setitem(sys.modules, "hatchery_enterprise", fake)

    from lib.cli import build_parser

    reset_load_state_for_tests()
    parser = build_parser()
    assert seen
    args = parser.parse_args(["enterprise-probe"])
    assert args.command == "enterprise-probe"
    assert callable(args.run)
