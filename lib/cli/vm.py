"""``hatchery vm`` - Nest-scoped VM inventory (inspect slice)."""

from __future__ import annotations

import argparse

from lib.cli import bootstrap
from lib.cli.bootstrap import NestResolveError


def register(sub: argparse._SubParsersAction) -> None:
    vm = sub.add_parser(
        "vm",
        help="Nest-scoped VM inventory and (later) lifecycle",
    )
    bootstrap.add_data_dir_argument(vm)
    vm_sub = vm.add_subparsers(dest="vm_command", required=True)

    listing = vm_sub.add_parser("list", help="List VMs on a Nest (live hypervisor inventory)")
    listing.add_argument(
        "--nest",
        default=None,
        metavar="ID",
        help="Nest id (required unless exactly one Nest is registered)",
    )


def run(args: argparse.Namespace) -> int:
    """Dispatch ``vm`` subcommands."""
    bootstrap.bootstrap(args)
    cmd = args.vm_command
    if cmd == "list":
        return _list_vms(args.nest)
    bootstrap.print_err(f"unknown vm command: {cmd}")
    return 2


def _list_vms(nest_arg: str | None) -> int:
    from lib.providers.factory import (
        NoNestSelectedError,
        UnknownNestError,
        UnsupportedProviderError,
        get_provider,
    )

    try:
        nest_id = bootstrap.resolve_nest_id(nest_arg)
    except NestResolveError as exc:
        bootstrap.print_err(str(exc))
        return 1

    try:
        provider = get_provider(nest_id)
    except NoNestSelectedError as exc:
        bootstrap.print_err(str(exc))
        return 1
    except UnknownNestError as exc:
        bootstrap.print_err(str(exc))
        return 1
    except UnsupportedProviderError as exc:
        bootstrap.print_err(str(exc))
        return 1

    vms = provider.list_vms()
    if not vms:
        print(f"No VMs on Nest '{nest_id}'.")
        return 0
    print(f"{'NAME':<40} STATUS")
    for vm in vms:
        print(f"{vm.get('name', ''):<40} {vm.get('status', '')}")
    return 0
