"""Shared Nest types used by Local Nest health / reachability / registry.

Remote Nest transport lived in ``lib.nest_transport`` and was removed from free
HEAD (#620). Enterprise Remote Nest uses Nest Agent (#345), not Nest SSH on free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class NestConnectionConfig:
    """Nest control-plane connection. Free HEAD is Local Nest only (#620)."""

    location: Literal["local"] = "local"
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.location != "local":
            raise ValueError("Remote Nest connection configs are not available on free HEAD (#620)")


@dataclass(frozen=True)
class NestHealthCheckResult:
    """Result of a Nest connectivity check (UI: Test Nest connection).

    ``failure_class`` (when ``ok`` is False):

    - ``endpoint`` - host:port not reachable (nothing listening / filtered / wrong address)
    - ``transport`` - endpoint accepts TCP but Nest transport session failed (auth, protocol, …)
    - ``config`` - Nest row / client setup cannot run a probe (missing password, invalid fields)
    """

    ok: bool
    detail: str
    failure_class: str | None = None
