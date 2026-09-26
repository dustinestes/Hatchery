"""``hatchery library`` - enable, connections/bindings, content list/test/pull."""

from __future__ import annotations

import argparse
from typing import Any

from lib.cli import bootstrap
from lib.cli import output as cli_out


def register(sub: argparse._SubParsersAction) -> None:
    library = sub.add_parser(
        "library",
        help="Library enable, connections/bindings, and content list/pull",
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
    test_c = conn_sub.add_parser("test", help="Test Library connection reachability")
    test_c.add_argument("connection_id", metavar="ID")

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

    content = lib_sub.add_parser("content", help="Library Content catalog and pull")
    content_sub = content.add_subparsers(dest="content_command", required=True)
    list_ct = content_sub.add_parser(
        "list",
        help="List Available Content from bindings (consume catalog)",
    )
    list_ct.add_argument(
        "--domain",
        required=True,
        choices=("scripts", "clutches", "media"),
        metavar="DOMAIN",
        help="Content domain: scripts | clutches | media",
    )
    list_ct.add_argument(
        "--connection",
        default=None,
        dest="connection_id",
        metavar="ID",
        help="Limit to one connection id",
    )
    list_ct.add_argument(
        "--target",
        choices=("iso", "virtio"),
        default=None,
        metavar="TARGET",
        help="Media only: filter catalog by iso | virtio",
    )
    pull_ct = content_sub.add_parser(
        "pull",
        help="Pull one file into the operator cache (create-only; ADR-0011)",
    )
    pull_ct.add_argument(
        "--domain",
        required=True,
        choices=("scripts", "clutches", "media"),
        metavar="DOMAIN",
    )
    pull_ct.add_argument(
        "--connection",
        required=True,
        dest="connection_id",
        metavar="ID",
    )
    pull_ct.add_argument(
        "--path",
        required=True,
        dest="relative_path",
        metavar="REL",
        help="Relative path within the connection (from content list)",
    )
    pull_ct.add_argument(
        "--binding-id",
        default=None,
        dest="binding_id",
        metavar="ID",
        help="Optional binding id for provenance attribution",
    )
    pull_ct.add_argument(
        "--target",
        choices=("iso", "virtio"),
        default=None,
        metavar="TARGET",
        help="Required when --domain media: iso | virtio",
    )
    rem_ct = content_sub.add_parser(
        "remove",
        help="Remove one Library-linked cache file and its provenance (UI trash)",
    )
    rem_ct.add_argument(
        "--domain",
        required=True,
        choices=("scripts", "clutches", "media"),
        metavar="DOMAIN",
    )
    rem_ct.add_argument(
        "--name",
        required=True,
        metavar="NAME",
        help="Cached basename (operator cache filename, not forge relative_path)",
    )
    rem_ct.add_argument(
        "--target",
        choices=("iso", "virtio"),
        default=None,
        metavar="TARGET",
        help="Required when --domain media: iso | virtio",
    )


def run(args: argparse.Namespace) -> int:
    """Dispatch ``library`` subcommands."""
    cmd = args.library_command
    mutate = cmd in ("enable", "disable") or (
        cmd in ("connection", "binding")
        and getattr(args, f"{cmd}_command", None) in ("add", "remove")
    )
    if cmd == "content" and getattr(args, "content_command", None) in ("pull", "remove"):
        mutate = True
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
    if cmd == "content":
        return _content(args, as_json=as_json)
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
    from lib import library_health
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

    if sub == "test":
        if not _require_library_enabled():
            return 1
        row = registry.get_connection(args.connection_id)
        if row is None:
            bootstrap.print_err(f"Connection not found: {args.connection_id}")
            return 1
        result = library_lib.test_connection(row)
        library_health.apply_manual_test_result(row, result, registered=True)
        payload = {
            "connection_id": row["id"],
            "ok": bool(result.get("ok")),
            "message": str(result.get("message") or ""),
        }
        if as_json:
            cli_out.emit_json(payload)
            return 0 if payload["ok"] else 1
        status = "ok" if payload["ok"] else "failed"
        print(f"Connection '{row['id']}': {status} - {payload['message']}")
        return 0 if payload["ok"] else 1

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


def _cached_basenames(domain: str, *, target: str | None = None) -> set[str]:
    """Basenames already in the operator cache for annotate_cached."""
    from lib import config as cfg

    root = cfg.data_dir()
    if domain == "scripts":
        directory = root / "automation" / "scripts"
        if not directory.is_dir():
            return set()
        return {p.name for p in directory.iterdir() if p.is_file()}
    if domain == "clutches":
        directory = root / "clutches"
        if not directory.is_dir():
            return set()
        return {p.name for p in directory.iterdir() if p.is_file() and p.suffix == ".yaml"}
    if domain == "media":
        names: set[str] = set()
        targets = [target] if target in ("iso", "virtio") else ["iso", "virtio"]
        for t in targets:
            directory = root / "media" / t
            if not directory.is_dir():
                continue
            names.update(p.name for p in directory.iterdir() if p.is_file())
        return names
    return set()


def _catalog_items(
    domain: str,
    *,
    connection_id: str | None = None,
    target: str | None = None,
) -> list[dict]:
    from lib import library as library_lib
    from lib import library_registry as registry

    raw_connections = registry.list_connections()
    raw_bindings = registry.list_bindings(domain=domain)
    if connection_id:
        raw_bindings = [b for b in raw_bindings if b.get("connection_id") == connection_id]
    connections = library_lib.connections_for_bindings(raw_connections, raw_bindings)
    parsers = {
        "scripts": library_lib.parse_script_bindings,
        "clutches": library_lib.parse_clutch_bindings,
        "media": library_lib.parse_media_bindings,
    }
    bindings = parsers[domain](raw_bindings, connections)
    if domain == "scripts":
        items = library_lib.catalog_scripts(connections, bindings)
    elif domain == "clutches":
        items = library_lib.catalog_clutches(connections, bindings)
    else:
        items = library_lib.catalog_media(connections, bindings, target=target)
    return library_lib.annotate_cached(items, _cached_basenames(domain, target=target))


def _content(args: argparse.Namespace, *, as_json: bool) -> int:
    from lib import library as library_lib
    from lib import library_registry as registry

    if not _require_library_enabled():
        return 1

    sub = args.content_command
    if sub == "list":
        try:
            items = _catalog_items(
                args.domain,
                connection_id=args.connection_id,
                target=args.target,
            )
        except ValueError as exc:
            bootstrap.print_err(str(exc))
            return 1
        if as_json:
            cli_out.emit_json({"domain": args.domain, "items": items})
            return 0
        if not items:
            print(f"No Available Content for domain '{args.domain}'.")
            return 0
        print(f"{'NAME':<28} {'CACHED':<8} {'CONNECTION':<20} PATH")
        for item in items:
            cached = "yes" if item.get("cached") else "no"
            print(
                f"{item.get('name', ''):<28} {cached:<8} "
                f"{item.get('connection_id', ''):<20} {item.get('relative_path', '')}"
            )
        return 0

    if sub == "pull":
        if args.domain == "media" and args.target not in ("iso", "virtio"):
            bootstrap.print_err("content pull --domain media requires --target iso|virtio")
            return 1
        row = registry.get_connection(args.connection_id)
        if row is None:
            bootstrap.print_err(f"Connection not found: {args.connection_id}")
            return 1
        try:
            if args.domain == "scripts":
                result = library_lib.pull_script(
                    row,
                    args.relative_path,
                    binding_id=args.binding_id,
                )
            elif args.domain == "clutches":
                result = library_lib.pull_clutch(
                    row,
                    args.relative_path,
                    binding_id=args.binding_id,
                )
            else:
                result = library_lib.pull_media(
                    row,
                    args.relative_path,
                    target=args.target,
                    binding_id=args.binding_id,
                )
        except FileExistsError as exc:
            bootstrap.print_err(str(exc))
            return 1
        except FileNotFoundError as exc:
            bootstrap.print_err(str(exc))
            return 1
        except ValueError as exc:
            bootstrap.print_err(str(exc))
            return 1
        except OSError as exc:
            bootstrap.print_err(str(exc))
            return 1
        payload = {
            "domain": args.domain,
            "imported": [result["name"]],
            "sha256": result.get("sha256"),
            "dest": str(result.get("dest") or ""),
        }
        if as_json:
            cli_out.emit_json(payload)
            return 0
        print(f"Pulled '{result['name']}' -> {result.get('dest')}")
        return 0

    if sub == "remove":
        from lib import config as cfg
        from lib import library_provenance as prov

        if args.domain == "media" and args.target not in ("iso", "virtio"):
            bootstrap.print_err("content remove --domain media requires --target iso|virtio")
            return 1
        name = str(args.name or "").strip()
        if not name:
            bootstrap.print_err("name is required")
            return 1
        row = prov.get_for_cache(args.domain, name, media_target=args.target)
        if row is None:
            bootstrap.print_err(f"No Library provenance for cached file: {name}")
            return 1
        deleted = prov.delete_attributed_cache_files([row], data_dir=cfg.data_dir())
        payload = {
            "ok": True,
            "domain": args.domain,
            "name": name,
            "deleted": deleted,
        }
        if as_json:
            cli_out.emit_json(payload)
            return 0
        if deleted:
            print(f"Removed '{name}' from operator cache and cleared Library provenance.")
        else:
            print(f"Cleared Library provenance for '{name}' (cache file was already missing).")
        return 0

    bootstrap.print_err(f"unknown content command: {sub}")
    return 2
