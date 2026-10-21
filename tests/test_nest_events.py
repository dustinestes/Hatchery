"""Tests for Nest Events transcript (#611)."""

from __future__ import annotations

import pytest

from lib import config as config_lib
from lib import db
from lib import nest_cache_sync as sync_lib
from lib import nest_events as nest_events_lib
from lib import nest_health as nest_health_lib
from lib import nests as nests_lib


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config_lib, "data_dir", lambda: tmp_path)
    db.init_db(tmp_path / "hatchery.db")
    yield


class TestNestEventsStore:
    def test_add_and_query_newest_first(self):
        nests_lib.ensure_local_nest()
        nest_events_lib.add_event(
            "local",
            source="controller",
            topic="health",
            level="INFO",
            message="first",
        )
        nest_events_lib.add_event(
            "local",
            source="controller",
            topic="cache_sync",
            level="WARN",
            message="second",
        )
        page = nest_events_lib.query_events("local", limit=10)
        assert page["total"] == 2
        assert [e["message"] for e in page["events"]] == ["second", "first"]

    def test_filters_topic_level_q(self):
        nests_lib.ensure_local_nest()
        nest_events_lib.add_event(
            "local",
            source="controller",
            topic="health",
            level="INFO",
            message="gate ok",
            component="nest_health",
        )
        nest_events_lib.add_event(
            "local",
            source="nest",
            topic="job",
            level="ERROR",
            message="pull failed",
            ref="job-1",
        )
        page = nest_events_lib.query_events("local", topic="job", level="ERROR")
        assert page["total"] == 1
        assert page["events"][0]["ref"] == "job-1"
        qpage = nest_events_lib.query_events("local", q="nest_health")
        assert qpage["total"] == 1
        assert qpage["events"][0]["topic"] == "health"

    def test_reject_bad_enums(self):
        nests_lib.ensure_local_nest()
        with pytest.raises(nest_events_lib.NestEventsError):
            nest_events_lib.add_event(
                "local",
                source="guest",
                topic="health",
                level="INFO",
                message="nope",
            )

    def test_batch_ingest(self):
        nests_lib.ensure_local_nest()
        rows = nest_events_lib.add_events(
            "local",
            [
                {
                    "source": "nest",
                    "topic": "cache_sync",
                    "level": "INFO",
                    "message": "a",
                },
                {
                    "source": "nest",
                    "topic": "general",
                    "level": "WARN",
                    "message": "b",
                },
            ],
        )
        assert len(rows) == 2
        assert nest_events_lib.query_events("local")["total"] == 2

    def test_prune_on_nest_remove(self):
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
                    "extra": {"nest_cache": "/var/lib/hatchery"},
                },
            ]
        )
        nest_events_lib.add_event(
            "remote1",
            source="controller",
            topic="transport",
            level="INFO",
            message="remote line",
        )
        nest_events_lib.add_event(
            "local",
            source="controller",
            topic="health",
            level="INFO",
            message="local line",
        )
        nests_lib.replace_nests([nests_lib.get_nest("local")])
        assert nest_events_lib.query_events("remote1")["total"] == 0
        assert nest_events_lib.query_events("local")["total"] == 1


class TestWriters:
    def test_health_writes_event(self, monkeypatch):
        nests_lib.ensure_local_nest()
        nest = nests_lib.get_nest("local")

        class _Probe:
            ok = True
            detail = "Local Nest OK"
            failure_class = None

        monkeypatch.setattr(
            "lib.nest_reachability.probe_nest",
            lambda *a, **k: _Probe(),
        )
        monkeypatch.setattr("lib.nest_reachability.record_probe", lambda *a, **k: None)
        monkeypatch.setattr("lib.nest_reachability.sync_alert_for_probe", lambda *a, **k: None)
        monkeypatch.setattr(
            nest_health_lib,
            "_gather_resources",
            lambda *a, **k: {"cpu": None, "memory": None, "disks": []},
        )
        monkeypatch.setattr(
            "lib.requirements.check_nest",
            lambda *a, **k: [],
        )
        nest_health_lib.run_health(nest, persist=True, sync_alerts=False)
        page = nest_events_lib.query_events("local", topic="health")
        assert page["total"] >= 1
        assert page["events"][0]["source"] == "controller"
        assert "OK" in page["events"][0]["message"]

    def test_cache_sync_writes_event(self):
        nests_lib.ensure_local_nest()
        nest = nests_lib.get_nest("local")
        sync_lib.run_check(nest)
        page = nest_events_lib.query_events("local", topic="cache_sync")
        assert page["total"] >= 1
        assert page["events"][0]["component"] == "nest_cache_sync"
