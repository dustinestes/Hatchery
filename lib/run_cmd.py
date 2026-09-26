"""Portable Nest-tool subprocess helpers (Controller-side provider adapters).

Providers (libvirt / UTM / Hyper-V) should prefer ``run_cmd`` for mutate and
inspect calls so stderr/stdout are captured and operator surfaces can show the
tool's own message instead of a bare exit-code string.

Capture does **not** silence the Controller console: on failure, Nest tool
streams are echoed once to stderr (the way inherited fds used to appear before
capture). Operator UI / CLI still receive the same text via
``format_process_error``.

Not Nest-transport SSH — that lives in ``lib/nest_transport.py``.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import Any


def format_process_error(exc: BaseException) -> str:
    """Operator-facing detail from a failed Nest tool invocation.

    Prefers stderr, then stdout. Falls back to a short command + exit summary
    (never the Python ``CalledProcessError`` list-repr alone).
    """
    if isinstance(exc, subprocess.CalledProcessError):
        detail = _decode_stream(exc.stderr) or _decode_stream(exc.stdout)
        if detail:
            return detail
        cmd = _format_cmd(exc.cmd)
        return f"Command failed (exit {exc.returncode}): {cmd}"
    return str(exc).strip() or exc.__class__.__name__


def run_cmd(
    cmd: Sequence[str],
    *,
    check: bool = True,
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
    echo_failure: bool = True,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Run a Nest-local tool with stdout/stderr captured as text.

    On failure with ``check=True``, raises ``CalledProcessError`` with
    ``stdout`` / ``stderr`` populated so ``format_process_error`` can surface
    the tool message on any Controller OS. When ``echo_failure`` is true
    (default), the same Nest tool output is also written once to Controller
    stderr so server consoles still show it.
    """
    argv = list(cmd)
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        **kwargs,
    )
    if check and result.returncode != 0:
        if echo_failure:
            _echo_failure(argv, result)
        raise subprocess.CalledProcessError(
            result.returncode,
            argv,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def _echo_failure(cmd: Sequence[str], result: subprocess.CompletedProcess[str]) -> None:
    """Re-emit captured Nest tool streams so capture does not hide console output.

    Writes once to stderr only (not also via logging) so gunicorn / CLI consoles
    do not show the same block twice.
    """
    detail = _decode_stream(result.stderr) or _decode_stream(result.stdout)
    header = f"Nest tool failed (exit {result.returncode}): {_format_cmd(cmd)}"
    if detail:
        line = f"{header}\n{detail}"
    else:
        line = header
    print(line, file=sys.stderr, flush=True)


def _decode_stream(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = value
    return text.strip()


def _format_cmd(cmd: Any) -> str:
    if isinstance(cmd, (list, tuple)):
        return " ".join(shlex.quote(str(c)) for c in cmd)
    return str(cmd)
