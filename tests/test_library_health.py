"""Library connection health Alerts (#254)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from lib import alerts as alerts_lib
from lib import config as cfg
from lib import db
from lib import library_health as lh
from lib.validators import builtins as builtins_mod
from lib.validators.registry import clear_registry, get_validator
from lib.validators.scheduler import run_validator


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.yaml")
    db.init_db(tmp_path / "hatchery.db")
    cfg.load()
    cfg.bind_db()
    clear_registry()
    builtins_mod.register_builtins()
    yield


def _enable_library(connections: list[dict]) -> None:
    c = cfg.get()
    c["library_enabled"] = True
    c["library_connections"] = connections
    cfg.save(c)


class TestTokenExpiry:
    def test_expires_inside_window_alerts(self):
        expires = (date.today() + timedelta(days=5)).isoformat()
        conn = {
            "id": "conn1",
            "label": "Share",
            "type": "path",
            "base_uri": "/tmp",
            "token": "t",
            "expires_at": expires,
            "kinds": ["scripts"],
        }
        recorded = lh.sync_token_expiry_alerts([conn])
        assert len(recorded) == 1
        assert recorded[0].startswith(lh.TOKEN_EXPIRY_ALERT_PREFIX)
        assert alerts_lib.count_active_by_prefixes(lh.LIBRARY_SCOPED_ALERT_PREFIXES) == 1

    def test_expiry_past_all_windows_resolves(self):
        expires = (date.today() + timedelta(days=90)).isoformat()
        conn = {
            "id": "conn1",
            "label": "Share",
            "type": "path",
            "base_uri": "/tmp",
            "token": "",
            "expires_at": expires,
            "kinds": ["scripts"],
        }
        # Seed an active alert, then sync with far expiry → resolve.
        alerts_lib.record_alert(
            lh.token_expiry_alert_message(conn, date.today() + timedelta(days=3), 3),
            tier="warning",
        )
        recorded = lh.sync_token_expiry_alerts([conn])
        assert recorded == []
        assert alerts_lib.count_active_by_prefixes((lh.TOKEN_EXPIRY_ALERT_PREFIX,)) == 0

    def test_empty_expires_at_no_alert(self):
        conn = {
            "id": "conn1",
            "label": "Share",
            "type": "path",
            "base_uri": "/tmp",
            "token": "",
            "expires_at": None,
            "kinds": ["scripts"],
        }
        assert lh.sync_token_expiry_alerts([conn]) == []
        assert alerts_lib.count_active_by_prefixes((lh.TOKEN_EXPIRY_ALERT_PREFIX,)) == 0


class TestConnectionProbe:
    def test_unreachable_path_alerts(self, tmp_path):
        missing = tmp_path / "nope"
        conn = {
            "id": "conn2",
            "label": "Missing",
            "type": "path",
            "base_uri": str(missing),
            "token": "",
            "expires_at": None,
            "kinds": ["scripts"],
        }
        stats = lh.sync_connection_alerts([conn])
        assert stats["down"] == 1
        assert alerts_lib.count_active_by_prefixes((lh.CONNECTION_ALERT_PREFIX,)) == 1

    def test_reachable_resolves(self, tmp_path):
        share = tmp_path / "share"
        share.mkdir()
        conn = {
            "id": "conn2",
            "label": "Share",
            "type": "path",
            "base_uri": str(share),
            "token": "",
            "expires_at": None,
            "kinds": ["scripts"],
        }
        alerts_lib.record_alert(
            lh.connection_alert_message(conn, "old"),
            tier="alert",
        )
        stats = lh.sync_connection_alerts([conn])
        assert stats["down"] == 0
        assert alerts_lib.count_active_by_prefixes((lh.CONNECTION_ALERT_PREFIX,)) == 0

    def test_git_unreachable_alerts(self, monkeypatch):
        monkeypatch.setattr(
            "lib.library.test_connection",
            lambda _conn: {"ok": False, "message": "git ls-remote failed: denied"},
        )
        conn = {
            "id": "git1",
            "label": "Repo",
            "type": "git",
            "base_uri": "https://example.com/r.git",
            "token": "",
            "expires_at": None,
            "kinds": ["scripts"],
        }
        stats = lh.sync_connection_alerts([conn])
        assert stats["checked"] == 1
        assert stats["down"] == 1
        assert alerts_lib.count_active_by_prefixes((lh.CONNECTION_ALERT_PREFIX,)) == 1


class TestValidator:
    def test_library_connections_active(self):
        v = get_validator("library_connections")
        assert v is not None
        assert getattr(v, "stub", False) is False

    def test_disabled_resolves_alerts(self, tmp_path):
        share = tmp_path / "missing"
        _enable_library(
            [
                {
                    "id": "c1",
                    "label": "X",
                    "type": "path",
                    "base_uri": str(share),
                    "token": "",
                    "expires_at": None,
                    "kinds": ["scripts"],
                }
            ]
        )
        run_validator("library_connections", trigger="manual")
        assert alerts_lib.count_active_by_prefixes(lh.LIBRARY_SCOPED_ALERT_PREFIXES) >= 1

        c = cfg.get()
        c["library_enabled"] = False
        cfg.save(c)
        run_validator("library_connections", trigger="manual")
        assert alerts_lib.count_active_by_prefixes(lh.LIBRARY_SCOPED_ALERT_PREFIXES) == 0

    def test_disabled_connection_skipped_and_alerts_resolved(self, tmp_path):
        share = tmp_path / "missing"
        _enable_library(
            [
                {
                    "id": "c1",
                    "label": "X",
                    "type": "path",
                    "base_uri": str(share),
                    "token": "",
                    "expires_at": None,
                    "kinds": ["scripts"],
                    "enabled": True,
                }
            ]
        )
        run_validator("library_connections", trigger="manual")
        assert alerts_lib.count_active_by_prefixes(lh.LIBRARY_SCOPED_ALERT_PREFIXES) >= 1

        c = cfg.get()
        c["library_connections"] = [
            {
                "id": "c1",
                "label": "X",
                "type": "path",
                "base_uri": str(share),
                "token": "",
                "expires_at": None,
                "kinds": ["scripts"],
                "enabled": False,
            }
        ]
        cfg.save(c)
        run_validator("library_connections", trigger="manual")
        assert alerts_lib.count_active_by_prefixes(lh.LIBRARY_SCOPED_ALERT_PREFIXES) == 0

    def test_prune_removed_connection(self):
        alerts_lib.record_alert(
            "Library connection: 'Gone' (gone1) - Path does not exist: /x",
            tier="alert",
        )
        lh.prune_alerts_for_removed_connections({"still-here"})
        assert alerts_lib.count_active_by_prefixes((lh.CONNECTION_ALERT_PREFIX,)) == 0
