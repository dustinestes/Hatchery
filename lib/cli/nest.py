"""``hatchery nest`` - inspect Nest registry / Test Nest connection / Nest Health."""

from __future__ import annotations

import argparse

from lib.cli import bootstrap
from lib.cli import output as cli_out


def register(sub: argparse._SubParsersAction) -> None:
    nest = sub.add_parser(
        "nest",
        help="Inspect registered Nests, Nest Health, and Test Nest connection",
    )
    bootstrap.add_data_dir_argument(nest)
    nest_sub = nest.add_subparsers(dest="nest_command", required=True)

    nest_sub.add_parser("list", help="List Nests in the Controller registry")

    test = nest_sub.add_parser("test", help="Test Nest connection (reachability / capability)")
    test.add_argument("nest_id", metavar="ID", help="Nest id to test")

    health = nest_sub.add_parser(
        "health",
        help="Run Nest Health (reachability gate + host resources / prerequisites)",
    )
    health.add_argument("nest_id", metavar="ID", help="Nest id to check")

    cache_sync = nest_sub.add_parser(
        "cache-sync",
        help="Run nest_cache sync check (Local content scan / Remote unavailable stub)",
    )
    cache_sync.add_argument("nest_id", metavar="ID", help="Nest id to check")

    events = nest_sub.add_parser(
        "events",
        help="List Nest Events transcript for one Nest (newest first)",
    )
    events.add_argument("nest_id", metavar="ID", help="Nest id")
    events.add_argument("--topic", default="", help="Filter by topic (health, transport, …)")
    events.add_argument("--level", default="", help="Filter by level (INFO, WARN, ERROR)")
    events.add_argument("-q", "--query", default="", help="Search message / component / ref")
    events.add_argument("--limit", type=int, default=100, help="Max rows (default 100)")


def run(args: argparse.Namespace) -> int:
    """Dispatch ``nest`` subcommands."""
    try:
        bootstrap.bootstrap(args, create=False)
    except bootstrap.DataDirMissingError as exc:
        bootstrap.print_err(str(exc))
        return 1
    as_json = cli_out.use_json(args)
    cmd = args.nest_command
    if cmd == "list":
        return _list_nests(as_json=as_json)
    if cmd == "test":
        return _test_nest(args.nest_id, as_json=as_json)
    if cmd == "health":
        return _nest_health(args.nest_id, as_json=as_json)
    if cmd == "cache-sync":
        return _nest_cache_sync(args.nest_id, as_json=as_json)
    if cmd == "events":
        return _nest_events(
            args.nest_id,
            topic=getattr(args, "topic", "") or "",
            level=getattr(args, "level", "") or "",
            query=getattr(args, "query", "") or "",
            limit=int(getattr(args, "limit", 100) or 100),
            as_json=as_json,
        )
    bootstrap.print_err(f"unknown nest command: {cmd}")
    return 2


def _list_nests(*, as_json: bool) -> int:
    from lib import nests as nests_lib

    rows = nests_lib.list_nests()
    if as_json:
        cli_out.emit_json(
            [
                {
                    "id": n["id"],
                    "name": n["name"],
                    "provider_type": n["provider_type"],
                    "location": n["location"],
                    "host": n.get("host"),
                }
                for n in rows
            ]
        )
        return 0
    if not rows:
        print("No Nests registered.")
        return 0
    print(f"{'ID':<16} {'NAME':<24} {'PROVIDER':<10} {'LOCATION':<8} HOST")
    for n in rows:
        host = n.get("host") or "-"
        print(f"{n['id']:<16} {n['name']:<24} {n['provider_type']:<10} {n['location']:<8} {host}")
    return 0


def _test_nest(nest_id: str, *, as_json: bool) -> int:
    from lib import nests as nests_lib

    nid = (nest_id or "").strip()
    nest = nests_lib.get_nest(nid)
    if nest is None:
        bootstrap.print_err(f"Unknown Nest id: {nid}")
        return 1
    result = nests_lib.test_connection(nest)
    ok = bool(result.get("ok"))
    message = result.get("message") or ("OK" if ok else "Test failed")
    if as_json:
        cli_out.emit_json({"ok": ok, "message": message, "nest_id": nid})
        return 0 if ok else 1
    print(message)
    return 0 if ok else 1


def _nest_health(nest_id: str, *, as_json: bool) -> int:
    from lib import nest_health as nest_health_lib
    from lib import nests as nests_lib

    nid = (nest_id or "").strip()
    nest = nests_lib.get_nest(nid)
    if nest is None:
        bootstrap.print_err(f"Unknown Nest id: {nid}")
        return 1
    result = nest_health_lib.run_health(nest, persist=True, sync_alerts=True)
    ok = bool(result.get("ok"))
    if as_json:
        cli_out.emit_json(result)
        return 0 if ok else 1
    gate = result.get("gate") or {}
    print(gate.get("detail") or ("Nest Health OK" if ok else "Nest Health failed"))
    if result.get("deeper_ran"):
        cpu = result.get("cpu") or {}
        mem = result.get("memory") or {}
        if cpu.get("count") is not None:
            print(f"CPU: {cpu['count']} logical")
        if mem.get("total_bytes") is not None:
            print(
                f"Memory: {mem.get('used_bytes')} used / {mem.get('total_bytes')} total "
                f"(free {mem.get('free_bytes')})"
            )
        disks = result.get("disks") or []
        print(f"Disks: {len(disks)} volume(s)")
        missing = [p["name"] for p in (result.get("prerequisites") or []) if not p.get("present")]
        if missing:
            print("Missing prerequisites: " + ", ".join(missing))
        else:
            print("Prerequisites: OK")
    return 0 if ok else 1


def _nest_cache_sync(nest_id: str, *, as_json: bool) -> int:
    from lib import nest_cache as nest_cache_lib
    from lib import nest_cache_sync as nest_cache_sync_lib
    from lib import nests as nests_lib

    nid = (nest_id or "").strip()
    nest = nests_lib.get_nest(nid)
    if nest is None:
        bootstrap.print_err(f"Unknown Nest id: {nid}")
        return 1
    try:
        report = nest_cache_sync_lib.run_check(nest)
    except nest_cache_sync_lib.NestCacheSyncError as exc:
        bootstrap.print_err(str(exc))
        return 1
    status = nest_cache_lib.nest_cache_status(nest)
    if as_json:
        cli_out.emit_json(status)
        return 0
    state = report.get("sync_state") or "unevaluated"
    checked = report.get("checked_at") or "-"
    content = report.get("content") or []
    print(f"Sync: {state}")
    print(f"Checked: {checked}")
    if report.get("message"):
        print(report["message"])
    print(f"Content: {len(content)} item(s)")
    for item in content[:50]:
        path = item.get("path") or item.get("basename") or "?"
        size = item.get("size_bytes")
        size_s = f" ({size} bytes)" if size is not None else ""
        print(f"  {path}{size_s}")
    if len(content) > 50:
        print(f"  … and {len(content) - 50} more")
    return 0


def _nest_events(
    nest_id: str,
    *,
    topic: str,
    level: str,
    query: str,
    limit: int,
    as_json: bool,
) -> int:
    from lib import nest_events as nest_events_lib
    from lib import nests as nests_lib

    nid = (nest_id or "").strip()
    nest = nests_lib.get_nest(nid)
    if nest is None:
        bootstrap.print_err(f"Unknown Nest id: {nid}")
        return 1
    try:
        page = nest_events_lib.query_events(
            nest["id"],
            topic=topic.strip() or None,
            level=level.strip() or None,
            q=query.strip() or None,
            limit=limit,
            offset=0,
        )
    except nest_events_lib.NestEventsError as exc:
        bootstrap.print_err(str(exc))
        return 1
    if as_json:
        cli_out.emit_json(page)
        return 0
    events = page.get("events") or []
    total = page.get("total") or 0
    print(f"Showing {len(events)} of {total} (newest first)")
    for ev in events:
        ts = ev.get("received_at") or "-"
        lvl = ev.get("level") or "?"
        top = ev.get("topic") or "?"
        src = ev.get("source") or "?"
        msg = ev.get("message") or ""
        print(f"{ts}  {lvl:<5}  {top:<12}  {src:<10}  {msg}")
    return 0
