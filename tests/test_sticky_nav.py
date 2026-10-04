"""Sticky submenu helper (#525 / ADR-0031)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STICKY_TEST = ROOT / "tests" / "js" / "sticky_nav.test.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node required for sticky_nav.js tests")
def test_sticky_nav_js_unit():
    proc = subprocess.run(
        ["node", "--test", str(STICKY_TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
