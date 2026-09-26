"""Hatchery Controller CLI package (ADR-0013)."""

from __future__ import annotations

import argparse
from typing import Sequence

from lib.cli import clutch as clutch_cmd
from lib.cli import hatch as hatch_cmd
from lib.cli import media as media_cmd
from lib.cli import nest as nest_cmd
from lib.cli import scripts as scripts_cmd
from lib.cli import serve as serve_cmd
from lib.cli import session as session_cmd
from lib.cli import vm as vm_cmd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hatchery",
        description="Hatchery Controller CLI - launch and Nest-scoped operator commands.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable JSON on stdout for inspect/list/show commands",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve_cmd.register(sub)
    nest_cmd.register(sub)
    clutch_cmd.register(sub)
    vm_cmd.register(sub)
    hatch_cmd.register(sub)
    session_cmd.register(sub)
    media_cmd.register(sub)
    scripts_cmd.register(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "serve":
        return serve_cmd.run(args)
    if args.command == "nest":
        return nest_cmd.run(args)
    if args.command == "clutch":
        return clutch_cmd.run(args)
    if args.command == "vm":
        return vm_cmd.run(args)
    if args.command == "hatch":
        return hatch_cmd.run(args)
    if args.command == "session":
        return session_cmd.run(args)
    if args.command == "media":
        return media_cmd.run(args)
    if args.command == "scripts":
        return scripts_cmd.run(args)
    parser.error(f"unknown command: {args.command}")
    return 2


__all__ = ["build_parser", "main"]
