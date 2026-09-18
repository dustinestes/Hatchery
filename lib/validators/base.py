"""Validator base types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from lib.validators.context import ValidatorContext

ValidatorScope = Literal["controller", "nest", "content"]


class BaseValidator(ABC):
    """Registered health / content check run by the validator scheduler."""

    id: str
    title: str
    description: str
    scope: ValidatorScope
    default_interval_seconds: int = 60
    default_enabled: bool = True

    @abstractmethod
    def run(self, ctx: ValidatorContext) -> str:
        """Execute the check. Return a short human summary for ``validator_runs.message``.

        Record/resolve Alerts via ``ctx`` for findings. Raise only on unexpected failure
        (scheduler records ``status=error``).
        """
