"""Shared pytest fixtures.

The app starts a hatch status poller and a validator scheduler on the first
request (and at import under some entrypoints). Stop both when the suite loads
and between tests so long CI runs (especially Windows) do not race host checks
or bootstrap writes into isolated config fixtures.

Importing ``hatchery`` binds SQLite to the operator ``data_dir`` from config.
Clear that binding immediately so Library pull/provenance tests cannot write
into the real Controller DB (#460).
"""

from __future__ import annotations

import pytest

import hatchery as app_module
import lib.db as db_module

app_module.stop_runtime_services()
# hatchery.py init_db(config.data_dir() / "hatchery.db") at import - unbind.
db_module._db_path = None


@pytest.fixture(autouse=True)
def _isolate_runtime_services():
    """Keep the hatch poller / validator scheduler from racing later modules."""
    app_module.stop_runtime_services()
    yield
    app_module.stop_runtime_services()
