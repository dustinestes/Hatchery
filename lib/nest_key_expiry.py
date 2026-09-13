"""Nest SSH identity expiry checks and alerts (#219).

Plain OpenSSH keys have no in-file expiry — operators set ``expires_at``.
OpenSSH certificates may expose ``Valid before`` via ``ssh-keygen -L``.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from lib import alerts as alerts_lib

ALERT_PREFIX = "Nest SSH identity expiry:"
ExpiresSource = Literal["manual", "cert"]


@dataclass(frozen=True)
class NestKeyAlertTier:
    days_before: int
    alerts_per_day: int

    def __post_init__(self) -> None:
        if self.days_before < 0:
            raise ValueError("days_before must be >= 0")
        if self.alerts_per_day < 1:
            raise ValueError("alerts_per_day must be >= 1")


@dataclass(frozen=True)
class NestSshIdentity:
    """Tracked Nest SSH identity for expiry alerting (key reference + policy date)."""

    id: str
    label: str | None = None
    identity_file: str | None = None
    cert_path: str | None = None
    expires_at: datetime | None = None
    expires_source: ExpiresSource = "manual"

    def __post_init__(self) -> None:
        if not self.id or not str(self.id).strip():
            raise ValueError("Nest SSH identity id is required")


DEFAULT_ALERT_TIERS: list[NestKeyAlertTier] = [
    NestKeyAlertTier(days_before=30, alerts_per_day=1),
    NestKeyAlertTier(days_before=7, alerts_per_day=2),
]


def parse_tiers(raw: Any) -> list[NestKeyAlertTier]:
    """Parse config list of ``{days_before, alerts_per_day}`` into tiers."""
    if raw is None:
        return list(DEFAULT_ALERT_TIERS)
    if not isinstance(raw, list) or not raw:
        return list(DEFAULT_ALERT_TIERS)
    tiers: list[NestKeyAlertTier] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tiers.append(
            NestKeyAlertTier(
                days_before=int(item["days_before"]),
                alerts_per_day=int(item.get("alerts_per_day", 1)),
            )
        )
    return tiers or list(DEFAULT_ALERT_TIERS)


def parse_identities(raw: Any) -> list[NestSshIdentity]:
    """Parse config list of Nest SSH identity dicts."""
    if not isinstance(raw, list):
        return []
    out: list[NestSshIdentity] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        expires_at = _parse_iso_datetime(item.get("expires_at"))
        source = item.get("expires_source") or "manual"
        if source not in ("manual", "cert"):
            source = "manual"
        out.append(
            NestSshIdentity(
                id=str(item["id"]).strip(),
                label=(str(item["label"]).strip() if item.get("label") else None),
                identity_file=item.get("identity_file"),
                cert_path=item.get("cert_path"),
                expires_at=expires_at,
                expires_source=source,  # type: ignore[arg-type]
            )
        )
    return out


def _parse_iso_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_openssh_cert_valid_before(path: str | Path) -> datetime | None:
    """Return Valid-before from an OpenSSH certificate, or None if not a cert / unreadable."""
    cert = Path(path).expanduser()
    if not cert.is_file():
        return None
    try:
        result = subprocess.run(
            ["ssh-keygen", "-L", "-f", str(cert)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    # Typical line: "        Valid: from 2024-01-01T00:00:00 to 2026-12-31T23:59:59"
    match = re.search(
        r"Valid:\s*from\s+\S+\s+to\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})",
        result.stdout,
    )
    if not match:
        return None
    try:
        dt = datetime.fromisoformat(match.group(1))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_expires_at(identity: NestSshIdentity) -> tuple[datetime | None, ExpiresSource]:
    """Return effective expiry: explicit ``expires_at``, else cert Valid-before when path set."""
    if identity.expires_at is not None:
        return identity.expires_at, identity.expires_source
    paths: list[Path] = []
    if identity.cert_path:
        paths.append(Path(identity.cert_path).expanduser())
    if identity.identity_file:
        key = Path(identity.identity_file).expanduser()
        paths.append(key.parent / f"{key.name}-cert.pub")
    for path in paths:
        parsed = parse_openssh_cert_valid_before(path)
        if parsed is not None:
            return parsed, "cert"
    return None, identity.expires_source


def matching_tier(days_left: int, tiers: list[NestKeyAlertTier]) -> NestKeyAlertTier | None:
    """Return the tightest tier whose ``days_before`` window includes ``days_left``."""
    applicable = [t for t in tiers if days_left <= t.days_before]
    if not applicable:
        return None
    return min(applicable, key=lambda t: t.days_before)


def alert_message(identity: NestSshIdentity, expires_at: datetime, days_left: int) -> str:
    label = identity.label or identity.id
    date_s = expires_at.date().isoformat()
    if days_left < 0:
        return f"{ALERT_PREFIX} '{label}' ({identity.id}) expired on {date_s}"
    return f"{ALERT_PREFIX} '{label}' ({identity.id}) expires in {days_left} day(s) ({date_s})"


def should_fire_alert(
    identity_id: str, alerts_per_day: int, *, now: datetime | None = None
) -> bool:
    """True if fewer than ``alerts_per_day`` alerts for this Nest id were filed in the last 24h."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=24)).isoformat()
    pattern = f"{ALERT_PREFIX} %{identity_id}%"
    count = alerts_lib.count_alerts_since(pattern, since, like=True)
    return count < alerts_per_day


def sync_nest_key_expiry_alerts(
    identities: list[NestSshIdentity],
    tiers: list[NestKeyAlertTier],
    *,
    now: datetime | None = None,
) -> list[str]:
    """Evaluate identities and record/resolve alerts. Returns messages that were recorded."""
    now = now or datetime.now(timezone.utc)
    recorded: list[str] = []

    for identity in identities:
        expires_at, _source = resolve_expires_at(identity)
        if expires_at is None:
            _resolve_for_identity(identity.id)
            continue

        days_left = (expires_at.date() - now.astimezone(timezone.utc).date()).days
        tier = matching_tier(days_left, tiers)
        if tier is None:
            _resolve_for_identity(identity.id)
            continue

        msg = alert_message(identity, expires_at, days_left)
        if not should_fire_alert(identity.id, tier.alerts_per_day, now=now):
            continue
        if alerts_lib.has_active_alert(msg):
            continue
        _resolve_for_identity(identity.id)
        alerts_lib.record_alert(msg, tier="warning" if days_left >= 0 else "alert")
        recorded.append(msg)

    return recorded


def _resolve_for_identity(identity_id: str) -> None:
    """Resolve active expiry alerts that mention this Nest identity id."""
    from lib import db

    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    try:
        conn.execute(
            """
            UPDATE alerts SET resolved = 1, resolved_at = ?
            WHERE resolved = 0 AND message LIKE ? AND message LIKE ?
            """,
            (now, f"{ALERT_PREFIX}%", f"%({identity_id})%"),
        )
        conn.commit()
    finally:
        conn.close()
