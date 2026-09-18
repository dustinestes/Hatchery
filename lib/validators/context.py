"""Runtime context passed into each validator run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lib import alerts as alerts_lib
from lib import config


@dataclass
class ValidatorContext:
    """Helpers available to ``BaseValidator.run``."""

    nest_id: str | None = None
    trigger: str = "schedule"  # schedule | manual | connection

    def data_dir(self) -> Path:
        return config.data_dir()

    def record_alert(self, message: str, tier: str = "alert") -> int:
        return alerts_lib.record_alert(message, tier=tier)

    def resolve_alerts_by_prefix(self, prefix: str) -> int:
        return alerts_lib.resolve_alerts_by_prefix(prefix)

    def has_active_alert(self, message: str) -> bool:
        return alerts_lib.has_active_alert(message)
