"""Shared Library status cue vocabulary (#387)."""

from __future__ import annotations

from lib import library_status_cues as cues


class TestLibraryStatusCues:
    def test_local(self):
        r = cues.resolve(drift_state="local")
        assert r["cue"] == "local"
        assert r["short"] == ""
        assert r["can_sync"] is False
        assert r["show_rail_icon"] is False

    def test_synced(self):
        r = cues.resolve(source_status="ok", sync_state="in_sync")
        assert r["cue"] == "synced"
        assert r["short"] == "synced"
        assert r["severity"] == "ok"
        assert r["can_sync"] is False

    def test_out_of_sync(self):
        r = cues.resolve(source_status="ok", sync_state="out_of_sync", cache_name="a.ps1")
        assert r["cue"] == "out_of_sync"
        assert r["can_sync"] is True
        assert r["can_reattach"] is False
        assert "Sync" in r["header_aria"]

    def test_missing(self):
        r = cues.resolve(source_status="missing", sync_state="unevaluated")
        assert r["cue"] == "missing"
        assert r["short"] == "source missing"
        assert r["can_reattach"] is True
        assert r["can_sync"] is False

    def test_communication_rollup(self):
        r = cues.resolve(source_status="rate_limited", sync_state="unevaluated")
        assert r["cue"] == "communication"
        assert "communication" in r["filter_keys"]
        r2 = cues.resolve(source_status="unreachable", sync_state="unevaluated")
        assert r2["cue"] == "communication"

    def test_legacy_drift_compat(self):
        r = cues.resolve(drift_state="out_of_sync")
        assert r["source_status"] == "ok"
        assert r["sync_state"] == "out_of_sync"
        assert r["can_sync"] is True

    def test_attach_to_inventory(self):
        item = {
            "name": "x.ps1",
            "drift_state": "in_sync",
            "source_status": "ok",
            "sync_state": "in_sync",
            "source_status_message": "",
            "orphan": False,
        }
        cues.attach_to_inventory_item(item)
        assert item["library_cue"] == "synced"
        assert item["library_cue_short"] == "synced"
        assert item["library_can_sync"] is False
