"""``hatchery media`` - list Controller data-dir media (ISO / VirtIO)."""

from __future__ import annotations

import argparse

from lib.cli import bootstrap
from lib.cli import output as cli_out

_MEDIA_TYPES = ("iso", "virtio")


def register(sub: argparse._SubParsersAction) -> None:
    media = sub.add_parser(
        "media",
        help="List local media files under the Controller data dir",
    )
    bootstrap.add_data_dir_argument(media)
    media_sub = media.add_subparsers(dest="media_command", required=True)

    listing = media_sub.add_parser("list", help="List ISO and/or VirtIO media files")
    listing.add_argument(
        "--type",
        choices=_MEDIA_TYPES,
        default=None,
        metavar="KIND",
        help="Limit to iso or virtio (default: both)",
    )


def run(args: argparse.Namespace) -> int:
    """Dispatch ``media`` subcommands."""
    try:
        bootstrap.bootstrap(args, create=False)
    except bootstrap.DataDirMissingError as exc:
        bootstrap.print_err(str(exc))
        return 1
    as_json = cli_out.use_json(args)
    cmd = args.media_command
    if cmd == "list":
        return _list_media(args.type, as_json=as_json)
    bootstrap.print_err(f"unknown media command: {cmd}")
    return 2


def _list_media(media_type: str | None, *, as_json: bool) -> int:
    from lib import media_inspect as media_inspect_lib

    kinds = (media_type,) if media_type else _MEDIA_TYPES
    rows: list[dict] = []
    for kind in kinds:
        for item in media_inspect_lib.scan_media_dir(kind):
            rows.append(
                {
                    "type": kind,
                    "name": item["name"],
                    "size_bytes": item["size_bytes"],
                    "modified_at": item["modified_at"],
                    "relative_path": item["relative_path"],
                }
            )

    if as_json:
        cli_out.emit_json({"media": rows})
        return 0
    if not rows:
        scope = media_type or "iso/virtio"
        print(f"No media files ({scope}).")
        return 0
    print(f"{'TYPE':<8} {'NAME':<40} {'SIZE':>12} MODIFIED")
    for r in rows:
        print(f"{r['type']:<8} {r['name']:<40} {r['size_bytes']:>12} {r['modified_at']}")
    return 0
