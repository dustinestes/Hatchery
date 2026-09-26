"""``hatchery vm`` - Nest-scoped VM inventory and lifecycle (operator)."""

from __future__ import annotations

import argparse
import subprocess

from lib.cli import bootstrap
from lib.cli.bootstrap import NestResolveError


def register(sub: argparse._SubParsersAction) -> None:
    vm = sub.add_parser(
        "vm",
        help="Nest-scoped VM inventory and lifecycle",
    )
    bootstrap.add_data_dir_argument(vm)
    vm_sub = vm.add_subparsers(dest="vm_command", required=True)

    listing = vm_sub.add_parser("list", help="List VMs on a Nest (live hypervisor inventory)")
    _add_nest_arg(listing)

    for name, help_text in (
        ("start", "Power on a VM"),
        ("stop", "Gracefully shut down a VM"),
        ("force-stop", "Forcibly power off a VM"),
        ("destroy", "Destroy a VM and remove its storage"),
        ("health", "Guest health: IP + WinRM TCP reachability"),
    ):
        p = vm_sub.add_parser(name, help=help_text)
        _add_nest_arg(p)
        p.add_argument("name", metavar="VM", help="VM name on the Nest")

    snap = vm_sub.add_parser(
        "snap",
        help="VM state snapshot (Hyper-V calls this a checkpoint)",
    )
    snap_sub = snap.add_subparsers(dest="snap_command", required=True)

    take = snap_sub.add_parser("take", help="Capture current VM state")
    _add_nest_arg(take)
    take.add_argument("name", metavar="VM", help="VM name")
    take.add_argument(
        "--label",
        required=True,
        metavar="ID",
        help="Snapshot label / id",
    )

    snap_list = snap_sub.add_parser("list", help="List snapshot labels for a VM")
    _add_nest_arg(snap_list)
    snap_list.add_argument("name", metavar="VM", help="VM name")

    apply_p = snap_sub.add_parser("apply", help="Restore a VM to a snapshot")
    _add_nest_arg(apply_p)
    apply_p.add_argument("name", metavar="VM", help="VM name")
    apply_p.add_argument("label", metavar="ID", help="Snapshot label / id")

    delete_p = snap_sub.add_parser("delete", help="Delete a snapshot")
    _add_nest_arg(delete_p)
    delete_p.add_argument("name", metavar="VM", help="VM name")
    delete_p.add_argument("label", metavar="ID", help="Snapshot label / id")


def _add_nest_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--nest",
        default=None,
        metavar="ID",
        help="Nest id (required unless exactly one Nest is registered)",
    )


def run(args: argparse.Namespace) -> int:
    """Dispatch ``vm`` subcommands."""
    try:
        bootstrap.bootstrap(args, create=False)
    except bootstrap.DataDirMissingError as exc:
        bootstrap.print_err(str(exc))
        return 1
    cmd = args.vm_command
    if cmd == "list":
        return _list_vms(args.nest)
    if cmd == "snap":
        return _snap(args)
    if cmd in ("start", "stop", "force-stop", "destroy", "health"):
        return _power_or_health(cmd, args.nest, args.name)
    bootstrap.print_err(f"unknown vm command: {cmd}")
    return 2


def _with_provider(nest_arg: str | None):
    """Resolve Nest and return ``(nest_id, provider)`` or raise / print errors via caller."""
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
        return None, None

    try:
        provider = get_provider(nest_id)
    except NoNestSelectedError as exc:
        bootstrap.print_err(str(exc))
        return None, None
    except UnknownNestError as exc:
        bootstrap.print_err(str(exc))
        return None, None
    except UnsupportedProviderError as exc:
        bootstrap.print_err(str(exc))
        return None, None
    return nest_id, provider


def _list_vms(nest_arg: str | None) -> int:
    nest_id, provider = _with_provider(nest_arg)
    if provider is None:
        return 1

    vms = provider.list_vms()
    if not vms:
        print(f"No VMs on Nest '{nest_id}'.")
        return 0
    print(f"{'NAME':<40} STATUS")
    for vm in vms:
        print(f"{vm.get('name', ''):<40} {vm.get('status', '')}")
    return 0


def _run_provider(action, *, ok_msg: str) -> int:
    try:
        action()
    except subprocess.CalledProcessError as exc:
        detail = (
            (exc.stderr or exc.stdout or str(exc)).strip() if hasattr(exc, "stderr") else str(exc)
        )
        bootstrap.print_err(detail or str(exc))
        return 1
    except Exception as exc:
        bootstrap.print_err(str(exc))
        return 1
    print(ok_msg)
    return 0


def _power_or_health(cmd: str, nest_arg: str | None, name: str) -> int:
    from lib.guest_health import guest_health

    nest_id, provider = _with_provider(nest_arg)
    if provider is None:
        return 1

    if cmd == "start":
        return _run_provider(
            lambda: provider.start_vm(name),
            ok_msg=f"Started '{name}' on Nest '{nest_id}'.",
        )
    if cmd == "stop":
        return _run_provider(
            lambda: provider.stop_vm(name),
            ok_msg=f"Stopped '{name}' on Nest '{nest_id}'.",
        )
    if cmd == "force-stop":
        return _run_provider(
            lambda: provider.force_stop_vm(name),
            ok_msg=f"Force-stopped '{name}' on Nest '{nest_id}'.",
        )
    if cmd == "destroy":
        return _run_provider(
            lambda: provider.destroy_vm(name),
            ok_msg=f"Destroyed '{name}' on Nest '{nest_id}'.",
        )
    if cmd == "health":
        try:
            result = guest_health(provider, name)
        except Exception as exc:
            bootstrap.print_err(str(exc))
            return 1
        ip = result["ip"] or "-"
        winrm = "ok" if result["winrm"] else "unreachable"
        print(f"VM '{name}' on Nest '{nest_id}': ip={ip} winrm={winrm}")
        return 0 if result["reachable"] else 1
    bootstrap.print_err(f"unknown vm command: {cmd}")
    return 2


def _snap(args: argparse.Namespace) -> int:
    nest_id, provider = _with_provider(args.nest)
    if provider is None:
        return 1
    sub = args.snap_command
    name = args.name

    if sub == "list":
        try:
            labels = provider.list_snapshots(name)
        except Exception as exc:
            bootstrap.print_err(str(exc))
            return 1
        if not labels:
            print(f"No snapshots for '{name}' on Nest '{nest_id}'.")
            return 0
        print(f"{'LABEL':<40}")
        for label in labels:
            print(f"{label:<40}")
        return 0

    if sub == "take":
        label = args.label
        return _run_provider(
            lambda: provider.create_snapshot(name, label),
            ok_msg=f"Snapshot '{label}' taken for '{name}' on Nest '{nest_id}'.",
        )
    if sub == "apply":
        label = args.label
        return _run_provider(
            lambda: provider.revert_snapshot(name, label),
            ok_msg=f"Applied snapshot '{label}' to '{name}' on Nest '{nest_id}'.",
        )
    if sub == "delete":
        label = args.label
        return _run_provider(
            lambda: provider.delete_snapshot(name, label),
            ok_msg=f"Deleted snapshot '{label}' for '{name}' on Nest '{nest_id}'.",
        )
    bootstrap.print_err(f"unknown snap command: {sub}")
    return 2
