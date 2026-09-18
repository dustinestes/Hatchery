"""Shared pytest fixtures.

The app starts a hatch status poller and a validator scheduler at import.
Stop both as soon as the test suite loads so long CI runs do not race host
checks into the isolated test DB. Unit tests that need them call them directly.
"""

from __future__ import annotations

import hatchery as app_module

if app_module._bg_stop_event is not None:
    app_module._bg_stop_event.set()

from lib.validators.scheduler import stop_scheduler

stop_scheduler()
