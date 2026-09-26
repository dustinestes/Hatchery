"""``hatchery settings`` - get/set exportable Controller Settings (operator)."""

from __future__ import annotations

import argparse
import json
from typing import Any

from lib.cli import bootstrap
from lib.cli import output as cli_out


def register(sub: argparse._SubParsersAction) -> None:
    settings = sub.add_parser(
        "settings",
        help="Get or set Controller Settings (persist to SQLite)",
    )
    bootstrap.add_data_dir_argument(settings)
    settings_sub = settings.add_subparsers(dest="settings_command", required=True)

    get_p = settings_sub.add_parser("get", help="Show one or more Settings keys")
    get_p.add_argument(
        "keys",
        nargs="*",
        metavar="KEY",
        help="Keys to show (default: all exportable keys)",
    )

    set_p = settings_sub.add_parser("set", help="Persist one Settings key")
    set_p.add_argument("key", metavar="KEY", help="Exportable Settings key")
    set_p.add_argument(
        "value",
        metavar="VALUE",
        help="Value (true/false, integer, string, or JSON for maps/lists)",
    )


def run(args: argparse.Namespace) -> int:
    """Dispatch ``settings`` subcommands."""
    cmd = args.settings_command
    create = cmd == "set"
    try:
        bootstrap.bootstrap(args, create=create)
    except bootstrap.DataDirMissingError as exc:
        bootstrap.print_err(str(exc))
        return 1
    as_json = cli_out.use_json(args)
    if cmd == "get":
        return _get(args.keys, as_json=as_json)
    if cmd == "set":
        return _set(args.key, args.value, as_json=as_json)
    bootstrap.print_err(f"unknown settings command: {cmd}")
    return 2


def _snapshot(keys: list[str] | None) -> dict[str, Any]:
    from lib import config as cfg

    exportable = sorted(cfg.exportable_setting_keys())
    wanted = list(keys) if keys else exportable
    live = cfg.get()
    out: dict[str, Any] = {}
    for key in wanted:
        if key not in cfg.exportable_setting_keys():
            raise KeyError(key)
        out[key] = live.get(key, cfg.default_for(key))
    return out


def _get(keys: list[str], *, as_json: bool) -> int:
    try:
        payload = _snapshot(keys or None)
    except KeyError as exc:
        bootstrap.print_err(f"Unknown or non-exportable settings key: {exc.args[0]}")
        return 1
    if as_json:
        cli_out.emit_json(payload)
        return 0
    width = max((len(k) for k in payload), default=8)
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, sort_keys=True)
        elif isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        print(f"{key:<{width}}  {rendered}")
    return 0


def _set(key: str, raw_value: str, *, as_json: bool) -> int:
    from lib import settings_io as settings_io_lib

    try:
        settings_io_lib.assert_exportable_key(key)
        parsed = settings_io_lib.parse_cli_value(key, raw_value)
        normalized = settings_io_lib.set_exportable_setting(key, parsed)
    except settings_io_lib.SettingError as exc:
        bootstrap.print_err(str(exc))
        return 1
    except ValueError as exc:
        bootstrap.print_err(str(exc))
        return 1
    if as_json:
        cli_out.emit_json({"key": key, "value": normalized})
        return 0
    if isinstance(normalized, (dict, list)):
        rendered = json.dumps(normalized, sort_keys=True)
    elif isinstance(normalized, bool):
        rendered = "true" if normalized else "false"
    else:
        rendered = str(normalized)
    print(f"Set {key}={rendered}")
    return 0
