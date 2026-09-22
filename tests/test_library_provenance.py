"""Tests for Library cache provenance + bidirectional drift (#308)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from lib import alerts as alerts_lib
from lib import db
from lib import library as library_lib
from lib import library_drift as drift
from lib import library_provenance as prov
from lib.validators.builtins import LibraryCacheDriftValidator
from lib.validators.context import ValidatorContext


@pytest.fixture
def data_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr("lib.config.data_dir", lambda: data)
    db.init_db(data / "hatchery.db")
    yield data
    db._db_path = None


def _path_conn(root: Path, *, conn_id: str = "c1") -> dict:
    return {
        "id": conn_id,
        "label": "Share",
        "type": "path",
        "base_uri": str(root),
        "token": "",
        "expires_at": None,
        "kinds": ["scripts", "clutches", "media"],
        "enabled": True,
        "provider": "",
    }


class TestProvenancePull:
    def test_pull_writes_provenance_and_create_only(self, data_env, tmp_path):
        share = tmp_path / "share"
        share.mkdir()
        (share / "hello.ps1").write_text("Write-Host hi\n", encoding="utf-8")
        conn = _path_conn(share)
        result = library_lib.pull_script(conn, "hello.ps1", binding_id="b1")
        assert result["name"] == "hello.ps1"
        row = prov.get_for_cache("scripts", "hello.ps1")
        assert row is not None
        assert row["connection_id"] == "c1"
        assert row["binding_id"] == "b1"
        assert row["source_digest_kind"] == "size_mtime"
        assert row["source_digest"]
        assert row["source_digest_synced"] == row["source_digest"]
        assert row["cache_sha256"]
        assert row["cache_sha256_synced"] == row["cache_sha256"]
        assert row["drift_state"] == "in_sync"
        with pytest.raises(FileExistsError):
            library_lib.pull_script(conn, "hello.ps1")

    def test_sync_then_evaluate_promotes_anchors(self, data_env, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        src = share / "hello.ps1"
        src.write_text("v1\n", encoding="utf-8")
        conn = _path_conn(share)
        library_lib.pull_script(conn, "hello.ps1")
        src.write_text("v2-longer\n", encoding="utf-8")
        row = prov.get_for_cache("scripts", "hello.ps1")
        tip = library_lib.resolve_source_digest(conn, "hello.ps1")
        assert tip is not None
        assert tip[1] != row["source_digest_synced"]

        monkeypatch.setattr(drift, "connection_by_id", lambda: {"c1": conn})
        monkeypatch.setattr(drift, "connection_and_binding_ids", lambda: ({"c1"}, set()))
        summary = drift.sync_row(row, {"c1": conn})
        assert summary is not None
        assert summary["drift_state"] == "in_sync"
        assert (data_env / "automation" / "scripts" / "hello.ps1").read_text(
            encoding="utf-8"
        ) == "v2-longer\n"
        row2 = prov.get_for_cache("scripts", "hello.ps1")
        assert row2["source_digest_synced"] == tip[1]
        assert row2["cache_sha256_synced"] == row2["cache_sha256"]
        assert row2["cache_sha256"] == summary["cache_sha256"]

    def test_media_pull_provenance(self, data_env, tmp_path):
        share = tmp_path / "share"
        share.mkdir()
        (share / "win.iso").write_bytes(b"iso-bytes")
        conn = _path_conn(share)
        library_lib.pull_media(conn, "win.iso", target="iso")
        tip = library_lib.resolve_source_digest(conn, "win.iso")
        row = prov.get_for_cache("media", "win.iso", media_target="iso")
        assert row is not None
        assert row["source_digest_kind"] == "size_mtime"
        assert tip and row["source_digest_synced"] == tip[1]


class TestCascadeAndOrphan:
    def test_delete_attributed_files(self, data_env, tmp_path):
        share = tmp_path / "share"
        share.mkdir()
        (share / "hello.ps1").write_text("x\n", encoding="utf-8")
        conn = _path_conn(share)
        library_lib.pull_script(conn, "hello.ps1")
        dest = data_env / "automation" / "scripts" / "hello.ps1"
        assert dest.is_file()
        deleted = prov.delete_attributed_cache_files(
            prov.rows_for_connection("c1"), data_dir=data_env
        )
        assert "hello.ps1" in deleted
        assert not dest.exists()
        assert prov.get_for_cache("scripts", "hello.ps1") is None

    def test_orphan_annotation(self, data_env, tmp_path):
        share = tmp_path / "share"
        share.mkdir()
        (share / "hello.ps1").write_text("x\n", encoding="utf-8")
        library_lib.pull_script(_path_conn(share), "hello.ps1")
        items = prov.enrich_inventory(
            [{"name": "hello.ps1"}],
            domain="scripts",
            connection_ids=set(),
            binding_ids=set(),
        )
        assert items[0]["orphan"] is True
        assert items[0]["drift_state"] == "orphan"
        assert items[0]["orphan_reason"] == "Library connection missing"

    def test_reattach(self, data_env, tmp_path):
        share = tmp_path / "share"
        share.mkdir()
        (share / "hello.ps1").write_text("x\n", encoding="utf-8")
        library_lib.pull_script(_path_conn(share, conn_id="old"), "hello.ps1")
        tip = library_lib.resolve_source_digest(_path_conn(share, conn_id="new"), "hello.ps1")
        assert tip
        row = prov.reattach(
            domain="scripts",
            cache_name="hello.ps1",
            connection_id="new",
            relative_path="hello.ps1",
            source_type="path",
            source_digest=tip[1],
            source_digest_kind=tip[0],
            binding_id="bind-new",
        )
        assert row["connection_id"] == "new"
        assert row["binding_id"] == "bind-new"
        assert row["drift_state"] == "unknown"

    def test_reattach_binding_cascade_delete(self, data_env, tmp_path):
        """Orphan → reattach with binding_id → binding cascade deletes the file (#357)."""
        share = tmp_path / "share"
        share.mkdir()
        (share / "hello.ps1").write_text("x\n", encoding="utf-8")
        conn = _path_conn(share)
        library_lib.pull_script(conn, "hello.ps1", binding_id="bind-old")
        dest = data_env / "automation" / "scripts" / "hello.ps1"
        assert dest.is_file()
        # Simulate orphan recovery onto a new binding id for the same connection.
        tip = library_lib.resolve_source_digest(conn, "hello.ps1")
        assert tip
        row = prov.reattach(
            domain="scripts",
            cache_name="hello.ps1",
            connection_id="c1",
            relative_path="hello.ps1",
            source_type="path",
            source_digest=tip[1],
            source_digest_kind=tip[0],
            binding_id="bind-new",
        )
        assert row["binding_id"] == "bind-new"
        assert prov.rows_for_binding("bind-old") == []
        deleted = prov.delete_attributed_cache_files(
            prov.rows_for_binding("bind-new"), data_dir=data_env
        )
        assert "hello.ps1" in deleted
        assert not dest.exists()
        assert prov.get_for_cache("scripts", "hello.ps1") is None

    def test_reattach_without_binding_misses_binding_cascade(self, data_env, tmp_path):
        """Low-level reattach with null binding_id skips cascade (API forbids this; #363)."""
        share = tmp_path / "share"
        share.mkdir()
        (share / "hello.ps1").write_text("x\n", encoding="utf-8")
        conn = _path_conn(share)
        library_lib.pull_script(conn, "hello.ps1", binding_id="bind-1")
        tip = library_lib.resolve_source_digest(conn, "hello.ps1")
        assert tip
        prov.reattach(
            domain="scripts",
            cache_name="hello.ps1",
            connection_id="c1",
            relative_path="hello.ps1",
            source_type="path",
            source_digest=tip[1],
            source_digest_kind=tip[0],
            binding_id=None,
        )
        assert prov.rows_for_binding("bind-1") == []
        deleted = prov.delete_attributed_cache_files(
            prov.rows_for_binding("bind-1"), data_dir=data_env
        )
        assert deleted == []
        assert (data_env / "automation" / "scripts" / "hello.ps1").is_file()


class TestBidirectionalDrift:
    def test_source_only_drift(self, data_env, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        src = share / "hello.ps1"
        src.write_text("v1\n", encoding="utf-8")
        conn = _path_conn(share)
        library_lib.pull_script(conn, "hello.ps1")
        src.write_text("v2\n", encoding="utf-8")
        monkeypatch.setattr(drift, "connection_by_id", lambda: {"c1": conn})
        monkeypatch.setattr(drift, "connection_and_binding_ids", lambda: ({"c1"}, set()))
        row = prov.get_for_cache("scripts", "hello.ps1")
        summary = drift.evaluate_row(row, connections={"c1": conn}, binding_ids=set())
        assert summary["drift_state"] == "out_of_sync"
        assert summary["source_drifted"] is True
        assert summary["cache_drifted"] is False

    def test_cache_only_drift(self, data_env, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        src = share / "hello.ps1"
        src.write_text("v1\n", encoding="utf-8")
        conn = _path_conn(share)
        library_lib.pull_script(conn, "hello.ps1")
        dest = data_env / "automation" / "scripts" / "hello.ps1"
        dest.write_text("edited locally\n", encoding="utf-8")
        monkeypatch.setattr(drift, "connection_by_id", lambda: {"c1": conn})
        monkeypatch.setattr(drift, "connection_and_binding_ids", lambda: ({"c1"}, set()))
        row = prov.get_for_cache("scripts", "hello.ps1")
        summary = drift.evaluate_row(row, connections={"c1": conn}, binding_ids=set())
        assert summary["drift_state"] == "out_of_sync"
        assert summary["cache_drifted"] is True
        assert summary["source_drifted"] is False

    def test_live_mismatch_sha256(self, data_env, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        src = share / "hello.ps1"
        src.write_text("v1\n", encoding="utf-8")
        conn = _path_conn(share)
        library_lib.pull_script(conn, "hello.ps1")
        dest = data_env / "automation" / "scripts" / "hello.ps1"
        fake_tip = "a" * 64
        # Corrupt: both anchors "agree" on tip, but cache bytes are not that tip.
        prov.upsert_on_pull(
            domain="scripts",
            cache_name="hello.ps1",
            connection_id="c1",
            relative_path="hello.ps1",
            source_type="path",
            cache_sha256=library_lib.sha256_file(dest),
            source_digest=fake_tip,
            source_digest_kind="sha256",
        )
        monkeypatch.setattr(
            library_lib,
            "resolve_source_digest",
            lambda *_a, **_k: ("sha256", fake_tip),
        )
        row = prov.get_for_cache("scripts", "hello.ps1")
        summary = drift.evaluate_row(row, connections={"c1": conn}, binding_ids=set())
        assert summary["drift_state"] == "out_of_sync"
        assert summary["live_mismatch"] is True

    def test_out_of_sync_alert_once_per_domain(self, data_env, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        src = share / "hello.ps1"
        src.write_text("v1\n", encoding="utf-8")
        conn = _path_conn(share)
        library_lib.pull_script(conn, "hello.ps1")
        src.write_text("v2\n", encoding="utf-8")
        monkeypatch.setattr(drift, "connection_by_id", lambda: {"c1": conn})
        monkeypatch.setattr(drift, "connection_and_binding_ids", lambda: ({"c1"}, set()))
        monkeypatch.setattr("lib.config.library_enabled", lambda: True)
        alerts_lib.resolve_alerts_by_prefix("Library cache drift:")
        summary = drift.run_drift_pass(auto_sync=False)
        assert summary["out_of_sync"] == 1
        active = [a for a in alerts_lib.list_recent(50) if not a.get("resolved")]
        msgs = [a["message"] for a in active]
        assert sum(1 for m in msgs if m.startswith("Library cache drift: Scripts")) == 1
        drift.run_drift_pass(auto_sync=False)
        active2 = [
            a
            for a in alerts_lib.list_recent(50)
            if not a.get("resolved") and a["message"].startswith("Library cache drift: Scripts")
        ]
        assert len(active2) == 1

    def test_auto_sync_skips_alerts(self, data_env, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        src = share / "hello.ps1"
        src.write_text("v1\n", encoding="utf-8")
        conn = _path_conn(share)
        library_lib.pull_script(conn, "hello.ps1")
        src.write_text("v2\n", encoding="utf-8")
        monkeypatch.setattr(drift, "connection_by_id", lambda: {"c1": conn})
        monkeypatch.setattr(drift, "connection_and_binding_ids", lambda: ({"c1"}, set()))
        monkeypatch.setattr("lib.config.library_enabled", lambda: True)
        alerts_lib.resolve_alerts_by_prefix("Library cache drift:")
        summary = drift.run_drift_pass(auto_sync=True)
        assert summary["synced"] == 1
        active = [
            a
            for a in alerts_lib.list_recent(50)
            if not a.get("resolved") and "Library cache drift:" in a["message"]
        ]
        assert active == []
        assert (data_env / "automation" / "scripts" / "hello.ps1").read_text(
            encoding="utf-8"
        ) == "v2\n"

    def test_sync_refuses_stale_tip_mismatch(self, data_env, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        src = share / "hello.ps1"
        src.write_text("v1\n", encoding="utf-8")
        conn = _path_conn(share)
        library_lib.pull_script(conn, "hello.ps1")
        src.write_text("v2-remote\n", encoding="utf-8")
        result = {
            "name": "hello.ps1",
            "sha256": library_lib.sha256_file(data_env / "automation" / "scripts" / "hello.ps1"),
            "dest": str(data_env / "automation" / "scripts" / "hello.ps1"),
        }
        with pytest.raises(ValueError, match="does not match Library tip"):
            monkeypatch.setattr(
                library_lib,
                "resolve_source_digest",
                lambda *_a, **_k: ("sha256", library_lib.sha256_file(src)),
            )
            library_lib.assert_pulled_matches_tip(
                Path(result["dest"]),
                ("sha256", library_lib.sha256_file(src)),
                content_sha256=result["sha256"],
            )

    def test_forge_digest_no_raw_download(self, data_env):
        conn = {
            "id": "f1",
            "type": "forge",
            "provider": "github",
            "base_uri": "https://github.com/acme/widgets",
            "token": "",
        }

        class _Adapter:
            def source_digest_one(self, _c, _rel):
                return None

            def tip_index(self, _c):
                return {"scripts/hello.ps1": ("git_blob", "abc123")}

            def source_digest(self, _c, rel):
                return self.tip_index(_c).get(rel)

        with patch("lib.library._forge_adapter", return_value=_Adapter()):
            tip = library_lib.resolve_source_digest(
                conn, "scripts/hello.ps1", tip_index={"scripts/hello.ps1": ("git_blob", "abc123")}
            )
            assert tip == ("git_blob", "abc123")

    def test_tip_index_one_trees_per_pass(self, data_env, tmp_path, monkeypatch):
        share = tmp_path / "share"
        share.mkdir()
        (share / "a.ps1").write_text("a\n", encoding="utf-8")
        (share / "b.ps1").write_text("b\n", encoding="utf-8")
        # Use forge-shaped rows with a mocked tip_index
        conn = {
            "id": "f1",
            "type": "forge",
            "provider": "github",
            "base_uri": "https://github.com/acme/widgets",
            "token": "t",
            "enabled": True,
            "kinds": ["scripts"],
            "label": "GH",
            "expires_at": None,
        }
        for name in ("a.ps1", "b.ps1"):
            dest = data_env / "automation" / "scripts" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(name + "\n", encoding="utf-8")
            sha = library_lib.sha256_file(dest)
            blob = library_lib.git_blob_sha_file(dest)
            prov.upsert_on_pull(
                domain="scripts",
                cache_name=name,
                connection_id="f1",
                relative_path=name,
                source_type="forge",
                cache_sha256=sha,
                source_digest=blob,
                source_digest_kind="git_blob",
            )

        calls = {"n": 0}

        def fake_index(_c):
            calls["n"] += 1
            return {
                "a.ps1": (
                    "git_blob",
                    library_lib.git_blob_sha_file(data_env / "automation" / "scripts" / "a.ps1"),
                ),
                "b.ps1": (
                    "git_blob",
                    library_lib.git_blob_sha_file(data_env / "automation" / "scripts" / "b.ps1"),
                ),
            }

        monkeypatch.setattr(drift, "connection_by_id", lambda: {"f1": conn})
        monkeypatch.setattr(drift, "connection_and_binding_ids", lambda: ({"f1"}, set()))
        monkeypatch.setattr("lib.config.library_enabled", lambda: True)
        with patch("lib.library.tip_index_for_connection", side_effect=fake_index):
            summary = drift.run_drift_pass(auto_sync=False)
        assert calls["n"] == 1
        assert summary["checked"] == 2
        assert summary["in_sync"] == 2

    def test_validator_message(self, data_env, monkeypatch):
        # Call the validator instance directly — do not clear_registry() here;
        # that would wipe builtins and break later Nest connection tests.
        monkeypatch.setattr("lib.config.library_enabled", lambda: True)
        monkeypatch.setattr(
            "lib.validators.settings.get_validator_config",
            lambda _id: {"auto_sync": False},
        )
        monkeypatch.setattr(
            "lib.library_drift.run_drift_pass",
            lambda auto_sync: {
                "checked": 2,
                "out_of_sync": 1,
                "synced": 0,
                "orphan": 0,
                "rate_limited": 0,
                "in_sync": 1,
                "unknown": 0,
                "by_domain": {"scripts": 1, "clutches": 0, "media": 0},
            },
        )
        ctx = ValidatorContext(trigger="manual")
        msg = LibraryCacheDriftValidator().run(ctx)
        assert "1 out of sync" in msg
