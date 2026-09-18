"""Scheduler and on-demand runner for registered validators."""

from __future__ import annotations

import atexit
import logging
import threading
import time
from datetime import datetime, timezone

from lib.validators.context import ValidatorContext
from lib.validators.registry import all_validators, get_validator
from lib.validators.runs import record_run
from lib.validators.settings import get_validator_config, list_validator_configs

logger = logging.getLogger(__name__)

_TICK_CAP_SECONDS = 5.0
_last_run_monotonic: dict[str, float] = {}
_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None


def run_validator(
    validator_id: str,
    *,
    nest_id: str | None = None,
    trigger: str = "manual",
    winrm_password: str | None = None,
) -> dict:
    """Run one validator and persist a ``validator_runs`` row. Returns run summary dict."""
    validator = get_validator(validator_id)
    if validator is None:
        raise KeyError(f"Unknown validator: {validator_id}")

    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    started_mono = time.monotonic()
    ctx = ValidatorContext(nest_id=nest_id, trigger=trigger, winrm_password=winrm_password)
    try:
        summary = validator.run(ctx) or "Completed"
        findings = int(ctx.findings_count)
        if findings > 0:
            status = "findings"
            tier = ctx.max_finding_tier or "alert"
        else:
            status = "ok"
            tier = "info"
        detail = None
        message = str(summary)
    except Exception as exc:
        logger.exception("validator %s failed", validator_id)
        status = "error"
        tier = "alert"
        findings = 0
        message = f"Validator error: {exc}"
        detail = str(exc)
        summary = message

    finished = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = record_run(
        validator_id=validator_id,
        status=status,
        message=message,
        trigger=trigger,
        tier=tier,
        detail=detail,
        nest_id=nest_id,
        findings_count=findings,
        started_at=started,
        finished_at=finished,
    )
    _last_run_monotonic[validator_id] = started_mono
    return {
        "id": run_id,
        "validator_id": validator_id,
        "status": status,
        "tier": tier,
        "findings_count": findings,
        "message": message,
        "started_at": started,
        "finished_at": finished,
    }


def _seconds_until_due(validator_id: str, interval: int) -> float:
    last = _last_run_monotonic.get(validator_id)
    if last is None:
        return 0.0
    elapsed = time.monotonic() - last
    return max(0.0, float(interval) - elapsed)


def _scheduler_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            configs = {c["id"]: c for c in list_validator_configs()}
            next_wake = _TICK_CAP_SECONDS
            for v in all_validators():
                cfg = configs.get(v.id) or get_validator_config(v.id)
                if not cfg.get("enabled", True):
                    continue
                if getattr(v, "stub", False):
                    continue
                interval = int(cfg.get("interval_seconds") or v.default_interval_seconds)
                due_in = _seconds_until_due(v.id, interval)
                if due_in <= 0:
                    try:
                        run_validator(v.id, trigger="schedule")
                    except Exception:
                        logger.exception("scheduled run failed for %s", v.id)
                    due_in = float(interval)
                next_wake = min(next_wake, due_in)
            stop.wait(max(0.5, min(_TICK_CAP_SECONDS, next_wake)))
        except Exception:
            logger.exception("validator scheduler tick failed")
            stop.wait(_TICK_CAP_SECONDS)


def start_scheduler() -> threading.Event:
    """Start the background validator scheduler (idempotent)."""
    global _stop_event, _thread
    if _thread is not None and _thread.is_alive():
        return _stop_event  # type: ignore[return-value]
    stop = threading.Event()
    _stop_event = stop
    t = threading.Thread(target=_scheduler_loop, args=(stop,), daemon=True, name="validators")
    _thread = t
    t.start()
    atexit.register(stop.set)
    return stop


def stop_scheduler() -> None:
    """Stop the scheduler thread (tests)."""
    global _stop_event, _thread
    if _stop_event is not None:
        _stop_event.set()
    _stop_event = None
    _thread = None
