"""Tests for Nest SSH identity expiry alerts (#219)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import lib.alerts as alerts_lib
import lib.db as db_module
import lib.nest_key_expiry as nke


@pytest.fixture(autouse=True)
def isolate_db(tmp_path):
    db_module.init_db(tmp_path / "hatchery.db")
    yield
    db_module._db_path = None


class TestParseTiers:
    def test_defaults_when_empty(self):
        tiers = nke.parse_tiers(None)
        assert len(tiers) == 2
        assert tiers[0].days_before == 30

    def test_parses_list(self):
        tiers = nke.parse_tiers([{"days_before": 14, "alerts_per_day": 3}])
        assert tiers == [nke.NestKeyAlertTier(14, 3)]


class TestMatchingTier:
    def test_picks_tightest_window(self):
        tiers = nke.parse_tiers(None)
        assert nke.matching_tier(40, tiers) is None
        assert nke.matching_tier(20, tiers).days_before == 30
        assert nke.matching_tier(5, tiers).days_before == 7
        assert nke.matching_tier(-1, tiers).days_before == 7


class TestCertParse:
    def test_parse_valid_before(self, tmp_path):
        out = (
            "nest_ed25519-cert.pub:\n"
            "        Type: ethill@openssh.com user certificate\n"
            "        Valid: from 2024-01-01T00:00:00 to 2026-12-31T23:59:59\n"
        )
        path = tmp_path / "nest-cert.pub"
        path.write_text("placeholder")
        with patch("lib.nest_key_expiry.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout=out, stderr="")
            dt = nke.parse_openssh_cert_valid_before(path)
        assert dt == datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    def test_parse_returns_none_when_not_cert(self, tmp_path):
        path = tmp_path / "key.pub"
        path.write_text("ssh-ed25519 AAAA")
        with patch("lib.nest_key_expiry.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="not a cert listing\n", stderr="")
            assert nke.parse_openssh_cert_valid_before(path) is None


class TestSyncAlerts:
    def test_fires_when_inside_tier(self):
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        expires = now + timedelta(days=10)
        identities = [nke.NestSshIdentity(id="nest-a", label="Lab Nest", expires_at=expires)]
        recorded = nke.sync_nest_key_expiry_alerts(identities, nke.parse_tiers(None), now=now)
        assert len(recorded) == 1
        assert "nest-a" in recorded[0]
        assert alerts_lib.has_active_alert(recorded[0])

    def test_resolves_when_outside_tiers(self):
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        expires = now + timedelta(days=90)
        identities = [nke.NestSshIdentity(id="nest-a", expires_at=expires)]
        # Seed an old alert
        alerts_lib.record_alert(nke.alert_message(identities[0], expires, 5), tier="warning")
        nke.sync_nest_key_expiry_alerts(identities, nke.parse_tiers(None), now=now)
        active = [a for a in alerts_lib.list_recent() if a["resolved"] == 0]
        assert not any("nest-a" in a["message"] for a in active)

    def test_rate_limits_alerts_per_day(self):
        now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        expires = now + timedelta(days=5)
        identity = nke.NestSshIdentity(id="nest-b", expires_at=expires)
        tiers = [nke.NestKeyAlertTier(days_before=7, alerts_per_day=1)]
        first = nke.sync_nest_key_expiry_alerts([identity], tiers, now=now)
        assert len(first) == 1
        second = nke.sync_nest_key_expiry_alerts([identity], tiers, now=now)
        assert second == []
