"""Shared CLI stdout helpers (text tables vs ``--json``)."""

from __future__ import annotations

import json
from typing import Any


def use_json(args) -> bool:
    """Return True when the global ``--json`` flag is set."""
    return bool(getattr(args, "json", False))


def emit_json(payload: Any) -> None:
    """Print ``payload`` as JSON on stdout."""
    print(json.dumps(payload, indent=2, default=str))
