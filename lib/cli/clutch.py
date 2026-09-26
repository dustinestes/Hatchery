"""``hatchery clutch`` - list/show Clutch files under the Controller data dir."""

from __future__ import annotations

import argparse
from pathlib import Path

from lib.cli import bootstrap
from lib.cli import output as cli_out


def register(sub: argparse._SubParsersAction) -> None:
    clutch = sub.add_parser(
        "clutch",
        help="List and show Clutch files under the Controller data dir",
    )
    bootstrap.add_data_dir_argument(clutch)
    clutch_sub = clutch.add_subparsers(dest="clutch_command", required=True)

    clutch_sub.add_parser("list", help="List Clutch YAML files")

    show = clutch_sub.add_parser("show", help="Show a Clutch file summary")
    show.add_argument("file", metavar="FILE", help="Clutch filename (e.g. lab.yaml)")


def run(args: argparse.Namespace) -> int:
    """Dispatch ``clutch`` subcommands."""
    try:
        bootstrap.bootstrap(args, create=False)
    except bootstrap.DataDirMissingError as exc:
        bootstrap.print_err(str(exc))
        return 1
    as_json = cli_out.use_json(args)
    cmd = args.clutch_command
    if cmd == "list":
        return _list_clutches(as_json=as_json)
    if cmd == "show":
        return _show_clutch(args.file, as_json=as_json)
    bootstrap.print_err(f"unknown clutch command: {cmd}")
    return 2


def _clutches_dir() -> Path:
    from lib import config as cfg

    return cfg.data_dir() / "clutches"


def _list_clutches(*, as_json: bool) -> int:
    root = _clutches_dir()
    files: list[str] = []
    if root.is_dir():
        files = sorted(p.name for p in root.glob("*.yaml") if p.is_file())
    if as_json:
        cli_out.emit_json({"clutches": files})
        return 0
    if not files:
        print("No Clutch files.")
        return 0
    for name in files:
        print(name)
    return 0


def _show_clutch(filename: str, *, as_json: bool) -> int:
    from lib import clutch as clutch_lib

    safe = Path(filename).name
    path = _clutches_dir() / safe
    try:
        clutch = clutch_lib.load(path)
    except FileNotFoundError:
        bootstrap.print_err(f"Clutch file not found: {safe}")
        return 1
    except ValueError as exc:
        bootstrap.print_err(str(exc))
        return 1

    payload = {
        "name": clutch.name,
        "description": clutch.description,
        "file": safe,
        "vms": [
            {
                "name": vm.name,
                "os": vm.os,
                "vcpus": vm.vcpus,
                "ram_gb": vm.ram_gb,
            }
            for vm in clutch.vms
        ],
    }
    if as_json:
        cli_out.emit_json(payload)
        return 0

    print(f"name: {clutch.name}")
    if clutch.description:
        print(f"description: {clutch.description}")
    print(f"vms: {len(clutch.vms)}")
    for vm in clutch.vms:
        print(f"  - {vm.name} ({vm.os}, {vm.vcpus} vCPU, {vm.ram_gb} GB RAM)")
    return 0
