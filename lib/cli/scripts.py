"""``hatchery scripts`` - list Controller automation scripts."""

from __future__ import annotations

import argparse
from pathlib import Path

from lib.cli import bootstrap
from lib.cli import output as cli_out

_SCRIPT_LANGUAGES = {
    ".ps1": "PowerShell",
    ".sh": "Shell",
    ".bash": "Shell",
    ".py": "Python",
    ".bat": "Batch",
    ".cmd": "Batch",
}


def register(sub: argparse._SubParsersAction) -> None:
    scripts = sub.add_parser(
        "scripts",
        help="List local automation scripts under the Controller data dir",
    )
    bootstrap.add_data_dir_argument(scripts)
    scripts_sub = scripts.add_subparsers(dest="scripts_command", required=True)
    scripts_sub.add_parser("list", help="List files in automation/scripts/")


def run(args: argparse.Namespace) -> int:
    """Dispatch ``scripts`` subcommands."""
    try:
        bootstrap.bootstrap(args, create=False)
    except bootstrap.DataDirMissingError as exc:
        bootstrap.print_err(str(exc))
        return 1
    as_json = cli_out.use_json(args)
    cmd = args.scripts_command
    if cmd == "list":
        return _list_scripts(as_json=as_json)
    bootstrap.print_err(f"unknown scripts command: {cmd}")
    return 2


def _script_language(name: str) -> str:
    ext = Path(name).suffix.lower()
    if not ext:
        return "Unknown"
    return _SCRIPT_LANGUAGES.get(ext, ext.lstrip(".").upper() or "Unknown")


def _list_scripts(*, as_json: bool) -> int:
    from lib import config as cfg

    root = cfg.data_dir() / "automation" / "scripts"
    rows: list[dict] = []
    if root.is_dir():
        for f in sorted(root.iterdir()):
            if not f.is_file():
                continue
            rows.append(
                {
                    "name": f.name,
                    "language": _script_language(f.name),
                    "relative_path": f"automation/scripts/{f.name}",
                }
            )

    if as_json:
        cli_out.emit_json({"scripts": rows})
        return 0
    if not rows:
        print("No scripts.")
        return 0
    print(f"{'NAME':<40} LANGUAGE")
    for r in rows:
        print(f"{r['name']:<40} {r['language']}")
    return 0
