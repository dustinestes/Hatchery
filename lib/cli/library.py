"""``hatchery library`` - enable flag + connection/binding CRUD (operator)."""

from __future__ import annotations

import argparse
from typing import Any

from lib.cli import bootstrap
from lib.cli import output as cli_out


def register(sub: argparse._SubParsersAction) -> None:
    library = sub.add_parser(
        "library",
        help="Library enable/disable and connection/binding CRUD",
    )
    bootstrap.add_data_dir_argument(library)
    lib_sub = library.add_subparsers(dest="library_command", required=True)

    lib_sub.add_parser("enable", help="Persist library_enabled=true (Settings)")
    lib_sub.add_parser("disable", help="Persist library_enabled=false (Settings)")

    conn = lib_sub.add_parser("connection", help="Library connections")
    conn_sub = conn.add_subparsers(dest="connection_command", required=True)
    conn_sub.add_parser("list", help="List Library connections")
    show_c = conn_sub.add_parser("show", help="Show one connection")
    show_c.add_argument("connection_id", metavar="ID")
    add_c = conn_sub.add_parser(
        "add",
        help="Upsert a Library connection (see docs/cli/library.md for accepted values)",
    )
    add_c.add_argument(
        "--id",
        default="",
        dest="conn_id",
        metavar="ID",
        help="Connection id (optional; auto-generated if omitted; pass to upsert/restore)",
    )
    add_c.add_argument("--label", default="", metavar="TEXT")
    add_c.add_argument(
        "--type",
        required=True,
        dest="conn_type",
        choices=("path", "https", "api", "forge"),
        metavar="TYPE",
        help="Connection type: path | https | api | forge",
    )
    add_c.add_argument(
        "--base-uri",
        required=True,
        dest="base_uri",
        metavar="URI",
        help="Filesystem path (path) or HTTPS URL (https/api/forge)",
    )
    add_c.add_argument(
        "--provider",
        default="",
        metavar="NAME",
        help="Required for api/forge (e.g. github, artifactory); omit for path/https",
    )
    add_c.add_argument(
        "--kinds",
        required=True,
        metavar="LIST",
        help="Comma-separated: scripts,clutches,media,packages",
    )
    add_c.add_argument("--token", default="", metavar="TOKEN")
    rem_c = conn_sub.add_parser("remove", help="Delete a connection (cascades bindings)")
    rem_c.add_argument("connection_id", metavar="ID")

    bind = lib_sub.add_parser("binding", help="Library bindings")
    bind_sub = bind.add_subparsers(dest="binding_command", required=True)
    list_b = bind_sub.add_parser("list", help="List Library bindings")
    list_b.add_argument(
        "--domain",
        choices=("scripts", "clutches", "media"),
        default=None,
        metavar="DOMAIN",
    )
    show_b = bind_sub.add_parser("show", help="Show one binding")
    show_b.add_argument("binding_id", metavar="ID")
    add_b = bind_sub.add_parser(
        "add",
        help="Upsert a Library binding (see docs/cli/library.md for accepted values)",
    )
    add_b.add_argument(
        "--id",
        default="",
        dest="bind_id",
        metavar="ID",
        help="Binding id (optional; auto-generated if omitted; pass to upsert/restore)",
    )
    add_b.add_argument("--connection-id", required=True, dest="connection_id", metavar="ID")
    add_b.add_argument(
        "--domain",
        required=True,
        choices=("scripts", "clutches", "media"),
        metavar="DOMAIN",
        help="Binding domain: scripts | clutches | media",
    )
    add_b.add_argument(
        "--filter",
        required=True,
        dest="filt",
        metavar="GLOB",
        help="Glob under the connection (e.g. *.ps1 or clutches/*.yaml)",
    )
    add_b.add_argument("--label", default="", metavar="TEXT")
    add_b.add_argument(
        "--target",
        choices=("iso", "virtio"),
        default="iso",
        metavar="TARGET",
        help="Media cache target when --domain media: iso | virtio (default iso)",
    )
    rem_b = bind_sub.add_parser("remove", help="Delete a binding")
    rem_b.add_argument("binding_id", metavar="ID")


def run(args: argparse.Namespace) -> int:
    """Dispatch ``library`` subcommands."""
    cmd = args.library_command
    mutate = cmd in ("enable", "disable") or (
        cmd in ("connection", "binding")
        and getattr(args, f"{cmd}_command", None) in ("add", "remove")
    )
    try:
        bootstrap.bootstrap(args, create=mutate)
    except bootstrap.DataDirMissingError as exc:
        bootstrap.print_err(str(exc))
        return 1
    as_json = cli_out.use_json(args)
    if cmd == "enable":
        return _set_enabled(True, as_json=as_json)
    if cmd == "disable":
        return _set_enabled(False, as_json=as_json)
    if cmd == "connection":
        return _connection(args, as_json=as_json)
    if cmd == "binding":
        return _binding(args, as_json=as_json)
    bootstrap.print_err(f"unknown library command: {cmd}")
    return 2


def _set_enabled(enabled: bool, *, as_json: bool) -> int:
    from lib import settings_io as settings_io_lib

    try:
        settings_io_lib.set_exportable_setting("library_enabled", enabled)
    except settings_io_lib.SettingError as exc:
        bootstrap.print_err(str(exc))
        return 1
    if as_json:
        cli_out.emit_json({"library_enabled": enabled})
        return 0
    print(f"Library {'enabled' if enabled else 'disabled'}.")
    return 0


def _require_library_enabled() -> bool:
    from lib import config as cfg

    if cfg.library_enabled():
        return True
    bootstrap.print_err("Library is disabled - run: hatchery library enable")
    return False


def _public_connection(row: dict) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "label": row.get("label"),
        "type": row.get("type"),
        "provider": row.get("provider") or None,
        "base_uri": row.get("base_uri"),
        "kinds": list(row.get("kinds") or []),
        "enabled": bool(row.get("enabled", True)),
        "expires_at": row.get("expires_at"),
        "has_token": bool(row.get("token")),
    }


def _public_binding(row: dict) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "connection_id": row.get("connection_id"),
        "domain": row.get("domain"),
        "label": row.get("label"),
        "filter": row.get("filter"),
        "target": row.get("media_target") or row.get("target") or None,
        "enabled": bool(row.get("enabled", True)),
    }


def _connection(args: argparse.Namespace, *, as_json: bool) -> int:
    from lib import library as library_lib
    from lib import library_registry as registry

    sub = args.connection_command
    if sub == "list":
        rows = [_public_connection(c) for c in registry.list_connections()]
        if as_json:
            cli_out.emit_json({"connections": rows})
            return 0
        if not rows:
            print("No Library connections.")
            return 0
        print(f"{'ID':<20} {'TYPE':<8} {'KINDS':<24} LABEL")
        for r in rows:
            kinds = ",".join(r["kinds"])
            print(f"{r['id']:<20} {r['type']:<8} {kinds:<24} {r['label']}")
        return 0

    if sub == "show":
        row = registry.get_connection(args.connection_id)
        if row is None:
            bootstrap.print_err(f"Connection not found: {args.connection_id}")
            return 1
        payload = _public_connection(row)
        if as_json:
            cli_out.emit_json(payload)
            return 0
        for key, value in payload.items():
            print(f"{key}: {value if not isinstance(value, list) else ','.join(value)}")
        return 0

    if sub == "add":
        if not _require_library_enabled():
            return 1
        raw = {
            "id": args.conn_id or None,
            "label": args.label or args.conn_id or "connection",
            "type": args.conn_type,
            "base_uri": args.base_uri,
            "provider": args.provider,
            "kinds": [k.strip() for k in args.kinds.split(",") if k.strip()],
            "token": args.token,
            "enabled": True,
        }
        try:
            parsed = library_lib.parse_connections([raw], enforce_expiry_future=False)[0]
            row = registry.upsert_connection(parsed)
        except ValueError as exc:
            bootstrap.print_err(str(exc))
            return 1
        if as_json:
            cli_out.emit_json(_public_connection(row))
            return 0
        print(f"Upserted connection '{row['id']}'.")
        return 0

    if sub == "remove":
        if not _require_library_enabled():
            return 1
        if not registry.delete_connection(args.connection_id):
            bootstrap.print_err(f"Connection not found: {args.connection_id}")
            return 1
        if as_json:
            cli_out.emit_json({"removed": args.connection_id})
            return 0
        print(f"Removed connection '{args.connection_id}'.")
        return 0

    bootstrap.print_err(f"unknown connection command: {sub}")
    return 2


def _binding(args: argparse.Namespace, *, as_json: bool) -> int:
    from lib import library as library_lib
    from lib import library_registry as registry

    sub = args.binding_command
    if sub == "list":
        rows = [_public_binding(b) for b in registry.list_bindings(domain=args.domain)]
        if as_json:
            cli_out.emit_json({"bindings": rows})
            return 0
        if not rows:
            print("No Library bindings.")
            return 0
        print(f"{'ID':<20} {'DOMAIN':<10} {'CONNECTION':<20} FILTER")
        for r in rows:
            print(f"{r['id']:<20} {r['domain']:<10} {r['connection_id']:<20} {r['filter']}")
        return 0

    if sub == "show":
        matches = [b for b in registry.list_bindings() if b["id"] == args.binding_id]
        if not matches:
            bootstrap.print_err(f"Binding not found: {args.binding_id}")
            return 1
        payload = _public_binding(matches[0])
        if as_json:
            cli_out.emit_json(payload)
            return 0
        for key, value in payload.items():
            print(f"{key}: {value}")
        return 0

    if sub == "add":
        if not _require_library_enabled():
            return 1
        raw = {
            "id": args.bind_id or None,
            "connection_id": args.connection_id,
            "domain": args.domain,
            "filter": args.filt,
            "label": args.label or args.filt,
            "enabled": True,
        }
        if args.domain == "media":
            raw["target"] = args.target
        parsers = {
            "scripts": library_lib.parse_script_bindings,
            "clutches": library_lib.parse_clutch_bindings,
            "media": library_lib.parse_media_bindings,
        }
        try:
            connections = registry.list_connections()
            parsed = parsers[args.domain]([raw], connections)[0]
            row = registry.upsert_binding(parsed)
        except ValueError as exc:
            bootstrap.print_err(str(exc))
            return 1
        if as_json:
            cli_out.emit_json(_public_binding(row))
            return 0
        print(f"Upserted binding '{row['id']}'.")
        return 0

    if sub == "remove":
        if not _require_library_enabled():
            return 1
        if not registry.delete_binding(args.binding_id):
            bootstrap.print_err(f"Binding not found: {args.binding_id}")
            return 1
        if as_json:
            cli_out.emit_json({"removed": args.binding_id})
            return 0
        print(f"Removed binding '{args.binding_id}'.")
        return 0

    bootstrap.print_err(f"unknown binding command: {sub}")
    return 2
