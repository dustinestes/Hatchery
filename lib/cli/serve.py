"""``hatchery serve`` - start the Hatchery Controller HTTP server."""

from __future__ import annotations

import argparse
from typing import Any


def register(sub: argparse._SubParsersAction) -> None:
    serve = sub.add_parser(
        "serve",
        help="Start the Hatchery Controller HTTP server",
    )
    serve.add_argument(
        "--data-dir",
        default=None,
        metavar="PATH",
        help="Session-only data directory override (never written to Settings)",
    )
    serve.add_argument(
        "--nest-local",
        action="store_true",
        help=(
            "Session-only: register this Controller as Local Nest id 'local' "
            "if missing (idempotent; ADR-0014)"
        ),
    )
    serve.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind address (default: 0.0.0.0)",
    )
    serve.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Bind port (default: 5000)",
    )


def _run_with_gunicorn(application: Any, options: dict) -> None:
    """Start gunicorn for ``application`` (isolated for tests / Windows import quirks)."""
    from gunicorn.app.base import BaseApplication

    class _App(BaseApplication):
        def __init__(self, app, opts: dict):
            self.application = app
            self.options = opts
            super().__init__()

        def load_config(self) -> None:
            for key, value in self.options.items():
                if value is None:
                    continue
                self.cfg.set(key.lower(), value)

        def load(self):
            return self.application

    _App(application, options).run()


def run(args: argparse.Namespace) -> int:
    """Apply session overrides, then run gunicorn against ``hatchery:app``.

    Background hatch/validator services start in the worker via ``post_fork`` so the
    gunicorn arbiter never holds a competing Settings writer (#366).
    """
    from lib import config as cfg

    if args.data_dir:
        cfg.set_runtime_data_dir(args.data_dir)
    if args.nest_local:
        cfg.set_runtime_nest_local(True)

    # Import after overrides so module-level config.load() / Nest registration see them.
    import hatchery

    def post_fork(server, worker) -> None:  # noqa: ARG001
        hatchery.start_runtime_services()

    options = {
        "bind": f"{args.host}:{args.port}",
        "workers": 1,
        # Sync worker matches contributor docs / single-process Controller expectations.
        "worker_class": "sync",
        "post_fork": post_fork,
    }
    _run_with_gunicorn(hatchery.app, options)
    return 0
