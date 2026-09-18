"""Runtime context passed into each validator run."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lib import alerts as alerts_lib
from lib import config

_TIER_RANK = {"info": 0, "warning": 1, "alert": 2}


@dataclass
class ValidatorContext:
    """Helpers available to ``BaseValidator.run``."""

    nest_id: str | None = None
    trigger: str = "schedule"  # schedule | manual | connection
    winrm_password: str | None = None
    findings_count: int = 0
    max_finding_tier: str = "info"
    _finding_tiers: list[str] = field(default_factory=list, repr=False)

    def data_dir(self) -> Path:
        return config.data_dir()

    def note_finding(self, tier: str = "alert") -> None:
        """Record that this run detected a problem (may or may not open a new Alert)."""
        normalized = alerts_lib.normalize_tier(tier)
        self.findings_count += 1
        self._finding_tiers.append(normalized)
        if _TIER_RANK.get(normalized, 0) > _TIER_RANK.get(self.max_finding_tier, 0):
            self.max_finding_tier = normalized

    def note_findings(self, count: int, tier: str = "alert") -> None:
        for _ in range(max(0, int(count))):
            self.note_finding(tier)

    def record_alert(self, message: str, tier: str = "alert") -> int:
        self.note_finding(tier)
        return alerts_lib.record_alert(message, tier=tier)

    def resolve_alerts_by_prefix(self, prefix: str) -> None:
        alerts_lib.resolve_alerts_by_prefix(prefix)

    def has_active_alert(self, message: str) -> bool:
        return alerts_lib.has_active_alert(message)
