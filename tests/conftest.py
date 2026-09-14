"""Shared pytest fixtures.

The app starts a background sync thread at import (requirements, clutches, hatch
status). Slow multi-OS CI runs — especially Windows — can exceed ``bg_interval``
(60s) and race real host checks into the isolated test DB. Stop that thread as
soon as the test suite loads; unit tests that need the loop call it directly.
"""

from __future__ import annotations

import hatchery as app_module

if app_module._bg_stop_event is not None:
    app_module._bg_stop_event.set()
