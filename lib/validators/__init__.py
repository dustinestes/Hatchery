"""Pluggable background validators — Host-plane health checks (#268)."""

from __future__ import annotations

from lib.validators.base import BaseValidator, ValidatorScope
from lib.validators.registry import all_validators, get_validator, register
from lib.validators.runs import latest_by_validator, list_runs
from lib.validators.scheduler import run_validator, start_scheduler, stop_scheduler
from lib.validators.settings import (
    get_run_retention,
    get_validator_config,
    list_validator_configs,
    migrate_bg_interval,
    save_validator_configs,
    cleaned_validator_settings,
)

__all__ = [
    "BaseValidator",
    "ValidatorScope",
    "all_validators",
    "get_validator",
    "register",
    "run_validator",
    "start_scheduler",
    "stop_scheduler",
    "list_runs",
    "latest_by_validator",
    "get_validator_config",
    "list_validator_configs",
    "save_validator_configs",
    "cleaned_validator_settings",
    "get_run_retention",
    "migrate_bg_interval",
]
