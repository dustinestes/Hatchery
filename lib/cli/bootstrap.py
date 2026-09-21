"""Shared Controller runtime bootstrap for operator CLI commands (ADR-0013).

Does not import ``hatchery`` (avoids Flask / background threads).
"""

from __future__ import annotations

import argparse
import sys

from lib import config as cfg
from lib import db as db_module
from lib import nests as nests_lib


class NestResolveError(RuntimeError):
    """Raised when a Nest id cannot be resolved for an operator command."""


def add_data_dir_argument(parser: argparse.ArgumentParser) -> None:
    """Add session-only ``--data-dir`` (never written to Settings)."""
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="PATH",
        help="Session-only data directory override (never written to Settings)",
    )


def apply_data_dir(path: str | None) -> None:
    """Apply a session-only data_dir override when ``path`` is set."""
    if path:
        cfg.set_runtime_data_dir(path)


def init_controller_runtime() -> None:
    """Load config, ensure data dir, open SQLite, bind Settings (no Flask)."""
    cfg.load()
    cfg.init_data_dir()
    db_module.init_db(cfg.data_dir() / "hatchery.db")
    cfg.bind_db()


def bootstrap(args: argparse.Namespace) -> None:
    """Apply ``--data-dir`` from ``args`` (if present) and init Controller runtime."""
    apply_data_dir(getattr(args, "data_dir", None))
    init_controller_runtime()


def resolve_nest_id(explicit: str | None) -> str:
    """Return an explicit Nest id or the sole registered Nest (ADR-0014).

    Raises:
        NestResolveError: zero or many Nests when id omitted, or empty explicit id.
    """
    nid = (explicit or "").strip()
    if nid:
        return nid
    sole = nests_lib.default_nest_id()
    if sole:
        return sole
    registered = nests_lib.list_nests()
    if not registered:
        raise NestResolveError(
            "No Nests registered — add one under Settings → Nests, "
            "or pass --nest <id> after registering"
        )
    raise NestResolveError(
        "Multiple Nests registered — pass --nest <id> "
        f"(have: {', '.join(n['id'] for n in registered)})"
    )


def print_err(message: str) -> None:
    """Write ``message`` to stderr."""
    print(message, file=sys.stderr)
