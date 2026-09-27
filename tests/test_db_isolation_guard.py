"""Guard that the pytest suite never keeps the operator Controller DB bound (#460)."""

from __future__ import annotations

from pathlib import Path

import lib.config as cfg
import lib.db as db_module


def test_bound_db_is_never_operator_data_dir():
    """Library pulls write provenance to whatever ``db._db_path`` is.

    ``hatchery`` import binds the operator DB; ``conftest`` must clear it, and
    tests that pull must use an isolated temp DB - never ``~/.local/share/...``.
    """
    operator_db = (Path(cfg.data_dir()) / "hatchery.db").resolve()
    bound = db_module._db_path
    if bound is None:
        return
    assert Path(bound).resolve() != operator_db
