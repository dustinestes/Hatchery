"""``hatchery hatch`` - Hatch a Clutch onto a Nest (operator mutate)."""

from __future__ import annotations

import argparse
from pathlib import Path

from lib.cli import bootstrap
from lib.cli.bootstrap import NestResolveError


def register(sub: argparse._SubParsersAction) -> None:
    hatch = sub.add_parser(
        "hatch",
        help="Hatch a Clutch onto a Nest (create + provision)",
    )
    bootstrap.add_data_dir_argument(hatch)
    hatch.add_argument(
        "--clutch",
        required=True,
        metavar="FILE",
        help="Clutch filename under data_dir/clutches (bare name)",
    )
    hatch.add_argument(
        "--nest",
        default=None,
        metavar="ID",
        help="Nest id (required unless exactly one Nest is registered)",
    )
    hatch.add_argument(
        "--password",
        action="append",
        default=[],
        metavar="VM=SECRET",
        help="Admin password for a VM (repeatable). Required when the Clutch sets admin_username.",
    )
    hatch.add_argument(
        "--ensure-cache",
        action="store_true",
        help="Run Nest cache ensure during preflight (local = verify)",
    )
    hatch.add_argument(
        "--no-wait",
        action="store_true",
        help="Return after VM create starts; do not poll until fledged/failed",
    )


def run(args: argparse.Namespace) -> int:
    """Dispatch ``hatch``."""
    try:
        bootstrap.bootstrap(args, create=True)
    except bootstrap.DataDirMissingError as exc:
        bootstrap.print_err(str(exc))
        return 1
    return _hatch(args)


def _parse_passwords(entries: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in entries:
        if "=" not in raw:
            raise ValueError(f"Invalid --password value (expected VM=SECRET): {raw}")
        name, _, secret = raw.partition("=")
        name = name.strip()
        if not name:
            raise ValueError(f"Invalid --password value (empty VM name): {raw}")
        out[name] = secret
    return out


def _hatch(args: argparse.Namespace) -> int:
    from lib import clutch as clutch_lib
    from lib import config
    from lib import hatch_lifecycle as hatch_lifecycle_lib
    from lib import nest_cache as nest_cache_lib
    from lib import nests as nests_lib
    from lib.providers.factory import (
        NoNestSelectedError,
        UnknownNestError,
        UnsupportedProviderError,
        get_provider,
    )

    try:
        passwords = _parse_passwords(args.password)
    except ValueError as exc:
        bootstrap.print_err(str(exc))
        return 2

    try:
        nest_id = bootstrap.resolve_nest_id(args.nest)
    except NestResolveError as exc:
        bootstrap.print_err(str(exc))
        return 1

    nest_row = nests_lib.get_nest(nest_id)
    if nest_row is None:
        bootstrap.print_err(f"Unknown Nest id: {nest_id}")
        return 1

    filename = Path(args.clutch).name
    clutch_path = config.data_dir() / "clutches" / filename
    try:
        clutch_obj = clutch_lib.load(clutch_path)
    except FileNotFoundError:
        bootstrap.print_err(f"Clutch file '{filename}' not found.")
        return 1
    except Exception as exc:
        bootstrap.print_err(str(exc))
        return 1

    missing = hatch_lifecycle_lib.missing_passwords(clutch_obj.vms, passwords)
    if missing:
        bootstrap.print_err(f"Password required for: {', '.join(missing)}")
        bootstrap.print_err("Pass --password VM=SECRET for each (repeatable).")
        return 1

    try:
        get_provider(nest_id)
    except (NoNestSelectedError, UnknownNestError, UnsupportedProviderError) as exc:
        bootstrap.print_err(str(exc))
        return 1

    try:
        nest_result = nest_cache_lib.preflight_clutch(
            clutch_obj,
            nest=nests_lib.to_connection_config(nest_row),
            run_ensure=bool(args.ensure_cache),
        )
    except nest_cache_lib.NestCacheError as exc:
        bootstrap.print_err(str(exc))
        return 1
    if not nest_result.ok:
        bootstrap.print_err(nest_result.error_message())
        return 1

    # Fill None for VMs that need no password so create_vm still gets a key.
    full_passwords = {vm.name: passwords.get(vm.name) for vm in clutch_obj.vms}

    print(f"Hatching '{clutch_obj.name}' ({filename}) on Nest '{nest_id}'...")
    session_id = hatch_lifecycle_lib.create_and_start_hatch(
        clutch_file=filename,
        clutch_obj=clutch_obj,
        nest_id=nest_id,
        passwords=full_passwords,
        background=False,
    )
    print(f"Session {session_id}: VM create finished.")

    if args.no_wait:
        print("Not waiting for fledged (--no-wait).")
        return 0

    def _tick(session: dict) -> None:
        vms = session.get("vms") or []
        parts = [f"{v.get('vm_name')}={v.get('status')}" for v in vms]
        print("  " + ", ".join(parts), flush=True)

    print("Polling hatch status until terminal...")
    session = hatch_lifecycle_lib.poll_session_until_terminal(session_id, on_tick=_tick)
    vms = session.get("vms") or []
    failed = [v for v in vms if v.get("status") == "failed"]
    if failed:
        names = ", ".join(v.get("vm_name", "?") for v in failed)
        bootstrap.print_err(f"Hatch finished with failures: {names}")
        return 1
    print(f"Hatch complete (session {session_id}).")
    return 0
