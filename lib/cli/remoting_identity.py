"""``hatchery remoting-identity`` - Controller remoting identity catalog (ADR-0030 / #522)."""

from __future__ import annotations

import argparse

from lib.cli import bootstrap
from lib.cli import output as cli_out


def register(sub: argparse._SubParsersAction) -> None:
    root = sub.add_parser(
        "remoting-identity",
        help="Manage Controller remoting identities (Nest + Guest SSH keys)",
    )
    bootstrap.add_data_dir_argument(root)
    ri_sub = root.add_subparsers(dest="remoting_identity_command", required=True)

    ri_sub.add_parser("list", help="List remoting identities in the catalog")

    show = ri_sub.add_parser("show", help="Show one remoting identity")
    show.add_argument("identity_id", metavar="ID")

    ri_sub.add_parser(
        "generate",
        help="Create the Hatchery-managed key if missing (id: hatchery)",
    )
    ri_sub.add_parser(
        "rotate",
        help="Replace the Hatchery-managed keypair (id: hatchery)",
    )

    add = ri_sub.add_parser(
        "add-path",
        help="Register an operator private-key path (never stores key bytes)",
    )
    add.add_argument("--id", required=True, dest="identity_id", metavar="ID")
    add.add_argument(
        "--identity-file",
        required=True,
        dest="identity_file",
        metavar="PATH",
        help="Private key path on the Controller",
    )
    add.add_argument("--name", default="", metavar="TEXT", help="Display label")
    add.add_argument(
        "--cert-path",
        default="",
        dest="cert_path",
        metavar="PATH",
        help="Optional OpenSSH certificate path",
    )
    add.add_argument(
        "--expires-at",
        default="",
        dest="expires_at",
        metavar="ISO8601",
        help="Optional operator policy expiry",
    )

    rem = ri_sub.add_parser(
        "remove", help="Remove a path identity (or Hatchery with --delete-files)"
    )
    rem.add_argument("identity_id", metavar="ID")
    rem.add_argument(
        "--delete-files",
        action="store_true",
        help="Also delete Hatchery-managed key files under data_dir/remoting",
    )

    check = ri_sub.add_parser("check", help="Validate identity files exist, perms, and pubkey")
    check.add_argument(
        "identity_id",
        nargs="?",
        default=None,
        metavar="ID",
        help="Optional identity id (default: all)",
    )


def run(args: argparse.Namespace) -> int:
    """Dispatch ``remoting-identity`` subcommands."""
    cmd = args.remoting_identity_command
    mutate = cmd in ("generate", "rotate", "add-path", "remove")
    try:
        bootstrap.bootstrap(args, create=mutate)
    except bootstrap.DataDirMissingError as exc:
        bootstrap.print_err(str(exc))
        return 1
    as_json = cli_out.use_json(args)
    if cmd == "list":
        return _list(as_json=as_json)
    if cmd == "show":
        return _show(args.identity_id, as_json=as_json)
    if cmd == "generate":
        return _generate(as_json=as_json)
    if cmd == "rotate":
        return _rotate(as_json=as_json)
    if cmd == "add-path":
        return _add_path(args, as_json=as_json)
    if cmd == "remove":
        return _remove(args.identity_id, delete_files=args.delete_files, as_json=as_json)
    if cmd == "check":
        return _check(args.identity_id, as_json=as_json)
    bootstrap.print_err(f"unknown remoting-identity command: {cmd}")
    return 2


def _list(*, as_json: bool) -> int:
    from lib import remoting_identities as ri

    rows = [ri.to_dict(i) for i in ri.list_identities()]
    if as_json:
        cli_out.emit_json({"identities": rows})
        return 0
    if not rows:
        print("No remoting identities. Run: hatchery remoting-identity generate")
        return 0
    print(f"{'ID':<16} {'KIND':<10} {'NAME':<20} IDENTITY_FILE")
    for r in rows:
        print(f"{r['id']:<16} {r['kind']:<10} {r['name']:<20} {r['identity_file']}")
    return 0


def _show(identity_id: str, *, as_json: bool) -> int:
    from lib import remoting_identities as ri

    ident = ri.get_identity(identity_id)
    if ident is None:
        bootstrap.print_err(f"unknown remoting identity: {identity_id}")
        return 1
    payload = ri.to_dict(ident)
    if as_json:
        cli_out.emit_json(payload)
        return 0
    for key, value in payload.items():
        print(f"{key}: {value}")
    return 0


def _generate(*, as_json: bool) -> int:
    from lib import remoting_identities as ri

    try:
        ident = ri.ensure_hatchery_identity()
    except ri.RemotingIdentityError as exc:
        bootstrap.print_err(str(exc))
        return 1
    payload = ri.to_dict(ident)
    if as_json:
        cli_out.emit_json(payload)
        return 0
    print(f"Hatchery-managed identity ready: {ident.id} -> {payload['resolved_path']}")
    return 0


def _rotate(*, as_json: bool) -> int:
    from lib import remoting_identities as ri

    try:
        ident = ri.rotate_hatchery_identity()
    except ri.RemotingIdentityError as exc:
        bootstrap.print_err(str(exc))
        return 1
    payload = ri.to_dict(ident)
    if as_json:
        cli_out.emit_json(payload)
        return 0
    print(f"Rotated Hatchery-managed identity: {payload['resolved_path']}")
    return 0


def _add_path(args: argparse.Namespace, *, as_json: bool) -> int:
    from lib import remoting_identities as ri

    try:
        ident = ri.add_path_identity(
            identity_id=args.identity_id,
            identity_file=args.identity_file,
            name=args.name or None,
            cert_path=args.cert_path or None,
            identity_expires_at=args.expires_at or None,
        )
    except ri.RemotingIdentityError as exc:
        bootstrap.print_err(str(exc))
        return 1
    payload = ri.to_dict(ident)
    if as_json:
        cli_out.emit_json(payload)
        return 0
    print(f"Registered path identity '{ident.id}' -> {payload['resolved_path']}")
    return 0


def _remove(identity_id: str, *, delete_files: bool, as_json: bool) -> int:
    from lib import remoting_identities as ri

    try:
        ri.remove_identity(identity_id, delete_files=delete_files)
    except ri.RemotingIdentityError as exc:
        bootstrap.print_err(str(exc))
        return 1
    if as_json:
        cli_out.emit_json({"removed": identity_id, "delete_files": delete_files})
        return 0
    print(f"Removed remoting identity '{identity_id}'.")
    return 0


def _check(identity_id: str | None, *, as_json: bool) -> int:
    from lib import remoting_identities as ri

    if identity_id:
        ident = ri.get_identity(identity_id)
        if ident is None:
            bootstrap.print_err(f"unknown remoting identity: {identity_id}")
            return 1
        checks = [ri.check_identity(ident)]
    else:
        checks = ri.check_all_identities()
    payload = [{"id": c.identity_id, "ok": c.ok, "detail": c.detail} for c in checks]
    failed = [c for c in checks if not c.ok]
    if as_json:
        cli_out.emit_json({"checks": payload})
        return 0 if not failed else 1
    if not checks:
        print("No remoting identities to check.")
        return 0
    for c in checks:
        status = "ok" if c.ok else "FAIL"
        print(f"{c.identity_id}: {status} - {c.detail}")
    return 0 if not failed else 1
