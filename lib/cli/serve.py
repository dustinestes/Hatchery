"""``hatchery serve`` - start the Hatchery Controller HTTP server."""

from __future__ import annotations

import argparse


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


def run(args: argparse.Namespace) -> int:
    """Apply session overrides, then run gunicorn against ``hatchery:app``."""
    from lib import config as cfg

    if args.data_dir:
        cfg.set_runtime_data_dir(args.data_dir)

    # Import after overrides so module-level config.load() sees the session data_dir.
    import hatchery  # noqa: F401

    from gunicorn.app.base import BaseApplication

    class _App(BaseApplication):
        def __init__(self, application, options: dict):
            self.application = application
            self.options = options
            super().__init__()

        def load_config(self) -> None:
            for key, value in self.options.items():
                if value is None:
                    continue
                self.cfg.set(key.lower(), value)

        def load(self):
            return self.application

    options = {
        "bind": f"{args.host}:{args.port}",
        "workers": 1,
        # Sync worker matches contributor docs / single-process Controller expectations.
        "worker_class": "sync",
    }
    _App(hatchery.app, options).run()
    return 0
