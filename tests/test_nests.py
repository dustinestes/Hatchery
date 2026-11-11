"""Nest connection registry (#207)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import lib.config as config
import lib.db as db_module
import lib.nests as nests_lib


@pytest.fixture(autouse=True)
def isolate_db(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    db_module.init_db(data / "hatchery.db")
    monkeypatch.setattr(config, "nest_ssh_identities", lambda: [])
    monkeypatch.setattr(config, "get", lambda: {"nest_ssh_identities": [], "data_dir": str(data)})
    monkeypatch.setattr(config, "save", lambda _c: None)
    yield
    db_module._db_path = None


class TestSeedAndList:
    def test_fresh_registry_empty(self):
        assert nests_lib.list_nests() == []
        assert nests_lib.default_nest_id() is None

    def test_ensure_local_seeds(self):
        nest = nests_lib.ensure_local_nest()
        assert nest["id"] == "local"
        assert nest["location"] == "local"
        assert nest["provider_type"] == "libvirt"
        assert nest["name"] == "Local"
        assert nests_lib.default_nest_id() == "local"

    def test_ensure_local_idempotent(self):
        nests_lib.ensure_local_nest()
        nests_lib.ensure_local_nest()
        assert len(nests_lib.list_nests()) == 1


class TestReplaceNests:
    def test_remote_nest_rejected(self):
        nests_lib.ensure_local_nest()
        local = nests_lib.get_nest("local")
        with pytest.raises(ValueError, match="#620"):
            nests_lib.replace_nests(
                [
                    local,
                    {
                        "id": "lab1",
                        "name": "Lab",
                        "provider_type": "libvirt",
                        "location": "remote",
                        "transport": "ssh",
                        "host": "nest.example",
                    },
                ]
            )
        assert [n["id"] for n in nests_lib.list_nests()] == ["local"]

    def test_can_remove_local_and_empty_registry(self):
        nests_lib.ensure_local_nest()
        nests_lib.replace_nests([])
        assert nests_lib.list_nests() == []
        assert nests_lib.default_nest_id() is None

    def test_local_must_stay_local(self):
        with pytest.raises(ValueError, match="#620"):
            nests_lib.replace_nests(
                [
                    {
                        "id": "local",
                        "name": "Local",
                        "provider_type": "libvirt",
                        "location": "remote",
                        "host": "x.example",
                    }
                ]
            )

    def test_non_local_id_rejected(self):
        with pytest.raises(ValueError, match="not allowed on free HEAD"):
            nests_lib.replace_nests(
                [
                    {
                        "id": "lab1",
                        "name": "Lab",
                        "provider_type": "libvirt",
                        "location": "local",
                    }
                ]
            )

    def test_removing_nest_resolves_scoped_alerts(self):
        import lib.alerts as alerts_lib

        nests_lib.ensure_local_nest()
        local = nests_lib.get_nest("local")
        alerts_lib.record_alert("Nest reachability: 'Local' (local): endpoint not reachable")
        alerts_lib.record_alert("Nest capability: 'Local' (local): 'virsh' is not available - x")
        assert alerts_lib.count_active_alerts() == 2
        nests_lib.replace_nests([])
        assert nests_lib.list_nests() == []
        assert alerts_lib.count_active_alerts() == 0
        history = alerts_lib.list_recent()
        assert len(history) == 2
        assert all(r["resolved"] == 1 for r in history)
        assert local["id"] == "local"

    def test_local_has_no_transport(self):
        nests_lib.ensure_local_nest()
        cfg = nests_lib.to_connection_config(nests_lib.get_nest("local"))
        assert cfg.location == "local"
        with (
            patch("lib.requirements.check_nest", return_value=[]),
            patch(
                "lib.nest_health._gather_resources_local",
                return_value={"cpu": None, "memory": None, "disks": []},
            ),
        ):
            nests_lib.ensure_local_nest()
            result = nests_lib.test_connection(nests_lib.get_nest("local"))
        assert result["ok"] is True
        assert "nest health" in result["message"].lower()

    def test_draft_remote_rejected(self):
        """Remote Nest drafts fail Test Nest connection on free HEAD (#620)."""
        draft = {
            "id": "draft-xyz",
            "name": "Draft",
            "provider_type": "libvirt",
            "location": "remote",
            "transport": "ssh",
            "host": "nowhere.example",
            "port": 22,
        }
        with (
            patch("lib.nest_reachability.record_probe") as record,
            patch("lib.nest_reachability.sync_alert_for_probe") as sync_alert,
        ):
            result = nests_lib.test_connection(draft)
        assert result["ok"] is False
        assert "#620" in result["message"]
        record.assert_not_called()
        sync_alert.assert_not_called()

    def test_saved_local_updates_snapshot_and_alerts(self):
        """Saved Local Nest Health updates snapshot and syncs reachability Alerts (#538)."""
        from lib.nest_types import NestHealthCheckResult

        nests_lib.ensure_local_nest()
        nest = nests_lib.get_nest("local")
        ok = NestHealthCheckResult(ok=True, detail="Local Nest - co-located")
        with (
            patch("lib.nest_reachability.probe_nest", return_value=ok),
            patch("lib.nest_reachability.record_probe") as record,
            patch("lib.nest_reachability.sync_alert_for_probe") as sync_alert,
            patch("lib.requirements.check_nest", return_value=[]),
            patch(
                "lib.nest_health._gather_resources",
                return_value={"cpu": None, "memory": None, "disks": []},
            ),
        ):
            result = nests_lib.test_connection(nest)
        assert result["ok"] is True
        record.assert_called_once()
        sync_alert.assert_called_once()

    def test_to_connection_config_local_only(self):
        local = nests_lib.normalize_nest(
            {"id": "local", "name": "Local", "provider_type": "libvirt", "location": "local"}
        )
        cfg = nests_lib.to_connection_config(local)
        assert cfg.location == "local"
        with pytest.raises(ValueError, match="#620"):
            nests_lib.to_connection_config({"id": "r1", "location": "remote"})

    def test_parse_rejects_bad_provider_and_duplicate(self):
        with pytest.raises(ValueError, match="unsupported provider_type"):
            nests_lib.normalize_nest(
                {
                    "id": "x",
                    "name": "X",
                    "provider_type": "vmware",
                    "location": "local",
                }
            )
        with pytest.raises(ValueError, match="duplicate"):
            nests_lib.parse_nests(
                [
                    {
                        "id": "local",
                        "name": "Local",
                        "provider_type": "libvirt",
                        "location": "local",
                    },
                    {
                        "id": "local",
                        "name": "Dup",
                        "provider_type": "libvirt",
                        "location": "local",
                    },
                ]
            )

    def test_remote_rejected(self):
        with pytest.raises(ValueError, match="#620"):
            nests_lib.normalize_nest(
                {
                    "id": "r",
                    "name": "R",
                    "provider_type": "libvirt",
                    "location": "remote",
                    "host": "r.example",
                }
            )

    def test_identities_for_expiry_empty(self):
        nests_lib.ensure_local_nest()
        assert nests_lib.identities_for_expiry() == []

    def test_rejects_second_local(self):
        nests_lib.ensure_local_nest()
        local = nests_lib.get_nest("local")
        with pytest.raises(ValueError, match="not allowed on free HEAD"):
            nests_lib.replace_nests(
                [
                    local,
                    {
                        "id": "other",
                        "name": "Other local",
                        "provider_type": "libvirt",
                        "location": "local",
                    },
                ]
            )

    def test_migrate_legacy_identity_bindings_noop(self):
        assert nests_lib.migrate_legacy_identity_bindings() == 0


class TestNormalizeHelpers:
    def test_parse_expires_at(self):
        assert nests_lib._parse_expires_at("", label="x") is None
        assert nests_lib._parse_expires_at("2026-12-01", label="x").startswith("2026-12-01")
        assert nests_lib._parse_expires_at("2026-12-01T10:00:00Z", label="x").startswith(
            "2026-12-01T10:00:00"
        )
        assert nests_lib._parse_expires_at("2026-12-01T10:00:00", label="x").endswith("+00:00")
        with pytest.raises(ValueError, match="identity expiry"):
            nests_lib._parse_expires_at("not-a-date", label="x")

    def test_optional_int(self):
        assert nests_lib._optional_int(None, label="port") is None
        assert nests_lib._optional_int("", label="port") is None
        assert nests_lib._optional_int("22", label="port") == 22
        with pytest.raises(ValueError, match="integer"):
            nests_lib._optional_int("x", label="port")
        with pytest.raises(ValueError, match="between"):
            nests_lib._optional_int("70000", label="port")


class TestMigrateLegacySshIdentities:
    def test_noop_when_empty(self):
        assert nests_lib.migrate_legacy_ssh_identities() is False

    def test_clears_settings_list(self, monkeypatch):
        cleared: list[dict] = []
        raw = [{"id": "k1", "identity_file": "~/.ssh/k1"}]
        monkeypatch.setattr(config, "nest_ssh_identities", lambda: raw)
        monkeypatch.setattr(
            config, "get", lambda: {"nest_ssh_identities": raw, "data_dir": "unused"}
        )
        monkeypatch.setattr(config, "update_settings", lambda patch: cleared.append(patch))
        nests_lib.ensure_local_nest()
        assert nests_lib.migrate_legacy_ssh_identities() is True
        assert cleared == [{"nest_ssh_identities": []}]
