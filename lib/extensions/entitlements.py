"""Free-tier and commercial entitlement claims (ADR-0043)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Entitlements:
    """Capability packs and Nest capacity for this Controller install.

    Free edition defaults: one Nest, no commercial feature packs.
    The Enterprise package may replace this object via ``ExtensionApi.set_entitlements``.
    """

    max_nests: int = 1
    features: frozenset[str] = field(default_factory=frozenset)

    def has(self, feature: str) -> bool:
        return feature in self.features


def free_entitlements() -> Entitlements:
    """Artifactory-OSS-shaped free defaults (Local Nest capacity only)."""
    return Entitlements(max_nests=1, features=frozenset())
