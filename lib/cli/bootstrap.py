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


class DataDirMissingError(RuntimeError):
    """Raised when an inspect command targets a data directory that does not exist."""


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


def init_controller_runtime(*, create: bool = True) -> None:
    """Load config and open Controller state.

    When ``create`` is True (launch / mutate paths), ensure the data directory
    tree and SQLite database exist. When False (inspect), require an existing
    data directory and open ``hatchery.db`` only if it already exists — never
    mkdir or create a new database.
    """
    cfg.load()
    root = cfg.data_dir()
    if create:
        cfg.init_data_dir()
        db_module.init_db(root / "hatchery.db")
        cfg.bind_db()
        return

    if not root.is_dir():
        raise DataDirMissingError(
            f"Data directory does not exist: {root}\n"
            "Pass an existing Controller data dir, or create one with "
            "`hatchery serve --data-dir ...`."
        )
    db_path = root / "hatchery.db"
    if db_path.is_file():
        db_module.init_db(db_path)
        cfg.bind_db()


def bootstrap(args: argparse.Namespace, *, create: bool = True) -> None:
    """Apply ``--data-dir`` from ``args`` (if present) and init Controller runtime."""
    apply_data_dir(getattr(args, "data_dir", None))
    init_controller_runtime(create=create)


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
            "No Nests registered - add one under Settings → Nests, "
            "or pass --nest <id> after registering"
        )
    raise NestResolveError(
        "Multiple Nests registered - pass --nest <id> "
        f"(have: {', '.join(n['id'] for n in registered)})"
    )


def print_err(message: str) -> None:
    """Write ``message`` to stderr."""
    print(message, file=sys.stderr)
