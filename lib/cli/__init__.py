"""Hatchery Controller CLI package (ADR-0013)."""

from __future__ import annotations

import argparse
from typing import Sequence

from lib.cli import serve as serve_cmd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hatchery",
        description="Hatchery Controller CLI - launch and (later) Nest-scoped operator commands.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve_cmd.register(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "serve":
        return serve_cmd.run(args)
    parser.error(f"unknown command: {args.command}")
    return 2


__all__ = ["build_parser", "main"]
