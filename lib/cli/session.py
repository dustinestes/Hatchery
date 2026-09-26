"""``hatchery session`` - inspect hatch sessions (operator)."""

from __future__ import annotations

import argparse

from lib.cli import bootstrap
from lib.cli import output as cli_out

_EVENT_CAP = 10


def register(sub: argparse._SubParsersAction) -> None:
    session = sub.add_parser(
        "session",
        help="Inspect hatch sessions (list / show) and retry failed VMs",
    )
    bootstrap.add_data_dir_argument(session)
    session_sub = session.add_subparsers(dest="session_command", required=True)

    listing = session_sub.add_parser("list", help="List active hatch sessions")
    listing.add_argument(
        "--nest",
        default=None,
        metavar="ID",
        help="Limit to one Nest id (default: all registered Nests)",
    )

    show = session_sub.add_parser("show", help="Show a hatch session and recent events")
    show.add_argument("session_id", metavar="SESSION", help="Hatch session id")

    retry = session_sub.add_parser(
        "retry",
        help="Retry provisioning for a failed VM in a hatch session",
    )
    retry.add_argument("session_id", metavar="SESSION", help="Hatch session id")
    retry.add_argument("vm_name", metavar="VM", help="VM name in the session")


def run(args: argparse.Namespace) -> int:
    """Dispatch ``session`` subcommands."""
    try:
        bootstrap.bootstrap(args, create=False)
    except bootstrap.DataDirMissingError as exc:
        bootstrap.print_err(str(exc))
        return 1
    as_json = cli_out.use_json(args)
    cmd = args.session_command
    if cmd == "list":
        return _list_sessions(args.nest, as_json=as_json)
    if cmd == "show":
        return _show_session(args.session_id, as_json=as_json)
    if cmd == "retry":
        return _retry_vm(args.session_id, args.vm_name)
    bootstrap.print_err(f"unknown session command: {cmd}")
    return 2


def _collect_sessions(nest_arg: str | None) -> list[dict]:
    from lib import hatch as hatch_lib
    from lib import nests as nests_lib

    nest_id = (nest_arg or "").strip()
    if nest_id:
        return hatch_lib.list_sessions(nest_id)
    sessions: list[dict] = []
    for nest in nests_lib.list_nests():
        sessions.extend(hatch_lib.list_sessions(nest["id"]))
    if not nests_lib.list_nests():
        sessions = hatch_lib.list_sessions("local")
    return sessions


def _list_sessions(nest_arg: str | None, *, as_json: bool = False) -> int:
    sessions = _collect_sessions(nest_arg)
    if as_json:
        cli_out.emit_json(
            [
                {
                    "id": s.get("id"),
                    "nest": s.get("nest"),
                    "status": s.get("status"),
                    "clutch_file": s.get("clutch_file"),
                    "clutch_name": s.get("clutch_name"),
                    "hatched_at": s.get("hatched_at"),
                }
                for s in sessions
            ]
        )
        return 0
    if not sessions:
        print("No active hatch sessions.")
        return 0

    print(f"{'ID':<38} {'NEST':<12} {'STATUS':<12} {'CLUTCH':<24} HATCHED")
    for s in sessions:
        sid = (s.get("id") or "")[:36]
        nest = (s.get("nest") or "-")[:12]
        status = (s.get("status") or "-")[:12]
        clutch = (s.get("clutch_file") or s.get("clutch_name") or "-")[:24]
        hatched = s.get("hatched_at") or "-"
        print(f"{sid:<38} {nest:<12} {status:<12} {clutch:<24} {hatched}")
    return 0


def _show_session(session_id: str, *, as_json: bool = False) -> int:
    from lib import hatch as hatch_lib

    detail = hatch_lib.get_session_detail(session_id)
    if detail is None:
        bootstrap.print_err(f"Session not found: {session_id}")
        return 1

    vms_out = []
    for vm in detail.get("vms") or []:
        name = vm.get("vm_name") or "?"
        events = hatch_lib.get_events(session_id, name)
        recent = events[-_EVENT_CAP:] if events else []
        vms_out.append(
            {
                "vm_name": name,
                "status": vm.get("status"),
                "error": vm.get("error"),
                "events": recent,
            }
        )

    if as_json:
        cli_out.emit_json(
            {
                "id": detail.get("id"),
                "nest": detail.get("nest"),
                "clutch_file": detail.get("clutch_file"),
                "clutch_name": detail.get("clutch_name"),
                "status": detail.get("status"),
                "hatched_at": detail.get("hatched_at"),
                "archived_at": detail.get("archived_at"),
                "vms": vms_out,
            }
        )
        return 0

    print(f"id: {detail.get('id')}")
    print(f"nest: {detail.get('nest') or '-'}")
    print(f"clutch: {detail.get('clutch_file') or '-'} ({detail.get('clutch_name') or '-'})")
    print(f"status: {detail.get('status') or '-'}")
    print(f"hatched_at: {detail.get('hatched_at') or '-'}")
    if detail.get("archived_at"):
        print(f"archived_at: {detail['archived_at']}")
    print("vms:")
    if not vms_out:
        print("  (none)")
        return 0

    for vm in vms_out:
        name = vm["vm_name"]
        print(f"  - {name}: {vm.get('status') or '-'}")
        if vm.get("error"):
            print(f"      error: {vm['error']}")
        recent = vm.get("events") or []
        if not recent:
            print("      events: (none)")
            continue
        print(f"      events (last {len(recent)}):")
        for ev in recent:
            ts = ev.get("received_at") or "-"
            level = ev.get("level") or "-"
            msg = (ev.get("message") or "").replace("\n", " ")
            print(f"        [{ts}] {level}: {msg}")
    return 0


def _retry_vm(session_id: str, vm_name: str) -> int:
    from lib import hatch_lifecycle as hatch_lifecycle_lib

    try:
        result = hatch_lifecycle_lib.retry_failed_vm(session_id, vm_name)
    except hatch_lifecycle_lib.RetryError as exc:
        bootstrap.print_err(str(exc))
        return 1

    if result["queued"]:
        print(f"Retry queued for '{vm_name}' in session {session_id}.")
        return 0
    msg = result.get("message") or "not queued"
    print(f"Retry recorded for '{vm_name}' in session {session_id}: {msg}")
    return 0
