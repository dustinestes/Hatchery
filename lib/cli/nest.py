"""``hatchery nest`` - inspect Nest registry / Test Nest connection."""

from __future__ import annotations

import argparse

from lib.cli import bootstrap


def register(sub: argparse._SubParsersAction) -> None:
    nest = sub.add_parser(
        "nest",
        help="Inspect registered Nests and Test Nest connection",
    )
    bootstrap.add_data_dir_argument(nest)
    nest_sub = nest.add_subparsers(dest="nest_command", required=True)

    nest_sub.add_parser("list", help="List Nests in the Controller registry")

    test = nest_sub.add_parser("test", help="Test Nest connection (reachability / capability)")
    test.add_argument("nest_id", metavar="ID", help="Nest id to test")


def run(args: argparse.Namespace) -> int:
    """Dispatch ``nest`` subcommands."""
    bootstrap.bootstrap(args)
    cmd = args.nest_command
    if cmd == "list":
        return _list_nests()
    if cmd == "test":
        return _test_nest(args.nest_id)
    bootstrap.print_err(f"unknown nest command: {cmd}")
    return 2


def _list_nests() -> int:
    from lib import nests as nests_lib

    rows = nests_lib.list_nests()
    if not rows:
        print("No Nests registered.")
        return 0
    print(f"{'ID':<16} {'NAME':<24} {'PROVIDER':<10} {'LOCATION':<8} HOST")
    for n in rows:
        host = n.get("host") or "-"
        print(f"{n['id']:<16} {n['name']:<24} {n['provider_type']:<10} {n['location']:<8} {host}")
    return 0


def _test_nest(nest_id: str) -> int:
    from lib import nests as nests_lib

    nid = (nest_id or "").strip()
    nest = nests_lib.get_nest(nid)
    if nest is None:
        bootstrap.print_err(f"Unknown Nest id: {nid}")
        return 1
    result = nests_lib.test_connection(nest)
    ok = bool(result.get("ok"))
    message = result.get("message") or ("OK" if ok else "Test failed")
    print(message)
    return 0 if ok else 1
