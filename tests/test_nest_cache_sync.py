"""Tests for Nest-reported nest_cache sync (#608)."""

from __future__ import annotations

import pytest

from lib import config as config_lib
from lib import db
from lib import nest_cache as nest_cache_lib
from lib import nest_cache_sync as sync_lib
from lib import nests as nests_lib


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config_lib, "data_dir", lambda: tmp_path)
    db.init_db(tmp_path / "hatchery.db")
    config_lib.update_settings({"nest_cache_sync": {}})
    yield


def _add_remote(extra=None):
    nests_lib.ensure_local_nest()
    nests_lib.replace_nests(
        [
            nests_lib.get_nest("local"),
            {
                "id": "remote1",
                "name": "Remote",
                "provider_type": "libvirt",
                "location": "remote",
                "host": "nest.example",
                "port": 22,
                "transport": "ssh",
                "extra": extra or {"nest_cache": "/var/lib/hatchery"},
            },
        ]
    )
    return nests_lib.get_nest("remote1")


class TestLocalCheck:
    def test_unevaluated_before_check(self, tmp_path):
        nests_lib.ensure_local_nest()
        nest = nests_lib.get_nest("local")
        status = nest_cache_lib.nest_cache_status(nest)
        assert status["sync"]["sync_state"] == "unevaluated"
        assert status["sync"]["content"] == []

    def test_local_check_lists_content(self, tmp_path):
        nests_lib.ensure_local_nest()
        iso = tmp_path / "media" / "iso"
        iso.mkdir(parents=True)
        (iso / "win11.iso").write_bytes(b"iso-bytes")
        scripts = tmp_path / "automation" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "setup.ps1").write_text("Write-Host hi\n", encoding="utf-8")

        nest = nests_lib.get_nest("local")
        report = sync_lib.run_check(nest)
        assert report["sync_state"] == "in_sync"
        assert report["source"] == "local_verify"
        assert "content" in report["message"].lower()
        paths = {i["path"] for i in report["content"]}
        assert "media/iso/win11.iso" in paths
        assert "automation/scripts/setup.ps1" in paths
        win = next(i for i in report["content"] if i["path"] == "media/iso/win11.iso")
        assert win["size_bytes"] == len(b"iso-bytes")
        assert win["kind"] == "media/iso"
        assert win["state"] == "present"

        status = nest_cache_lib.nest_cache_status(nest)
        assert status["sync"]["sync_state"] == "in_sync"
        assert len(status["sync"]["content"]) == 2


class TestRemoteCheck:
    def test_remote_check_unavailable(self):
        nest = _add_remote()
        report = sync_lib.run_check(nest)
        assert report["sync_state"] == "unavailable"
        assert "#609" in (report.get("message") or "")
        assert report["content"] == []

    def test_remote_check_preserves_nest_report_content(self):
        nest = _add_remote()
        sync_lib.record_report(
            "remote1",
            {
                "sync_state": "out_of_sync",
                "source": "nest_report",
                "message": "missing iso",
                "content": [
                    {
                        "kind": "media/iso",
                        "basename": "win11.iso",
                        "path": "media/iso/win11.iso",
                        "state": "missing",
                    }
                ],
            },
        )
        report = sync_lib.run_check(nest)
        assert report["sync_state"] == "unavailable"
        assert report["source"] == "nest_report"
        assert len(report["content"]) == 1
        assert report["content"][0]["basename"] == "win11.iso"


class TestIngest:
    def test_record_report_validates_state(self):
        nests_lib.ensure_local_nest()
        with pytest.raises(sync_lib.NestCacheSyncError, match="invalid sync_state"):
            sync_lib.record_report("local", {"sync_state": "nope"})

    def test_ingest_nest_report(self):
        nest = _add_remote()
        report = sync_lib.record_report(
            nest["id"],
            {
                "sync_state": "in_sync",
                "source": "nest_report",
                "content": [{"path": "media/iso/a.iso", "state": "present"}],
            },
        )
        assert report["sync_state"] == "in_sync"
        assert sync_lib.get_sync("remote1")["content"][0]["path"] == "media/iso/a.iso"


class TestPrune:
    def test_prune_removed_nests(self):
        _add_remote()
        sync_lib.record_report(
            "remote1",
            {"sync_state": "in_sync", "source": "nest_report", "content": []},
        )
        assert sync_lib.get_sync("remote1") is not None
        nests_lib.replace_nests([nests_lib.get_nest("local")])
        assert sync_lib.get_sync("remote1") is None


class TestValidator:
    def test_run_as_validator_local(self, tmp_path):
        nests_lib.ensure_local_nest()
        (tmp_path / "media" / "iso").mkdir(parents=True)
        (tmp_path / "media" / "iso" / "x.iso").write_bytes(b"x")

        class Ctx:
            nest_id = None

        summary = sync_lib.run_as_validator(Ctx())
        assert "local:in_sync" in summary
