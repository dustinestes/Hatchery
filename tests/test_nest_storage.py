"""Nest nest_storage volumes (#538)."""

from __future__ import annotations

import pytest

import lib.config as config
import lib.db as db_module
from lib import nest_storage as ns
from lib import nests as nests_lib


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


class TestNestStorageVolumes:
    def test_add_remove_and_primary_sync(self):
        nests_lib.ensure_local_nest()
        vol = ns.add_storage_volume("local", "/var/lib/libvirt/images", primary=True)
        assert vol["path"] == "/var/lib/libvirt/images"
        assert vol["primary"] is True
        nest = nests_lib.get_nest("local")
        assert nest is not None
        assert nest["extra"].get("nest_storage") == "/var/lib/libvirt/images"
        volumes = ns.list_storage_volumes(nest)
        assert len(volumes) == 1

        second = ns.add_storage_volume("local", "/mnt/bulk", primary=True)
        nest = nests_lib.get_nest("local")
        assert nest["extra"].get("nest_storage") == "/mnt/bulk"
        volumes = ns.list_storage_volumes(nest)
        assert len(volumes) == 2
        assert sum(1 for v in volumes if v["primary"]) == 1
        assert second["primary"] is True

        ns.remove_storage_volume("local", vol["id"])
        nest = nests_lib.get_nest("local")
        volumes = ns.list_storage_volumes(nest)
        assert len(volumes) == 1
        assert volumes[0]["path"] == "/mnt/bulk"
        assert nest["extra"].get("nest_storage") == "/mnt/bulk"

        ns.remove_storage_volume("local", second["id"])
        nest = nests_lib.get_nest("local")
        assert nest["extra"].get("nest_storage") is None
        assert ns.list_storage_volumes(nest) == []

    def test_legacy_single_path(self):
        nests_lib.ensure_local_nest()
        nests_lib.update_nest_extra("local", {"nest_storage": "/legacy/path"})
        nest = nests_lib.get_nest("local")
        volumes = ns.list_storage_volumes(nest)
        assert len(volumes) == 1
        assert volumes[0]["path"] == "/legacy/path"
        assert volumes[0]["primary"] is True

    def test_duplicate_path_rejected(self):
        nests_lib.ensure_local_nest()
        ns.add_storage_volume("local", "/data/vms")
        with pytest.raises(ns.NestStorageError, match="already registered"):
            ns.add_storage_volume("local", "/data/vms")

    def test_set_primary(self):
        nests_lib.ensure_local_nest()
        a = ns.add_storage_volume("local", "/a", primary=True)
        b = ns.add_storage_volume("local", "/b", primary=False)
        ns.set_primary_storage_volume("local", b["id"])
        nest = nests_lib.get_nest("local")
        assert nest["extra"]["nest_storage"] == "/b"
        volumes = ns.list_storage_volumes(nest)
        assert next(v for v in volumes if v["id"] == b["id"])["primary"] is True
        assert next(v for v in volumes if v["id"] == a["id"])["primary"] is False

    def test_unknown_nest(self):
        with pytest.raises(ns.NestStorageError, match="Unknown Nest"):
            ns.add_storage_volume("missing", "/x")

    def test_update_path_and_primary(self):
        nests_lib.ensure_local_nest()
        a = ns.add_storage_volume("local", "/a", primary=True)
        ns.add_storage_volume("local", "/b", primary=False)
        updated = ns.update_storage_volume("local", a["id"], path="/a2", primary=False)
        assert updated["path"] == "/a2"
        nest = nests_lib.get_nest("local")
        volumes = ns.list_storage_volumes(nest)
        assert next(v for v in volumes if v["id"] == a["id"])["path"] == "/a2"
        assert nest["extra"]["nest_storage"] == "/b"
        ns.update_storage_volume("local", a["id"], primary=True)
        nest = nests_lib.get_nest("local")
        assert nest["extra"]["nest_storage"] == "/a2"
        with pytest.raises(ns.NestStorageError, match="already registered"):
            ns.update_storage_volume("local", a["id"], path="/b")

    def test_skips_malformed_volume_entries(self):
        nests_lib.ensure_local_nest()
        nests_lib.update_nest_extra(
            "local",
            {
                "nest_storage_volumes": [
                    "skip-me",
                    {"id": "", "path": "/x"},
                    {"id": "ok", "path": "/ok", "primary": True},
                    {"id": "two", "path": "/two", "primary": True},
                ]
            },
        )
        nest = nests_lib.get_nest("local")
        volumes = ns.list_storage_volumes(nest)
        assert [v["path"] for v in volumes] == ["/ok", "/two"]
        assert sum(1 for v in volumes if v["primary"]) == 1
        assert volumes[0]["primary"] is True

    def test_empty_path_rejected(self):
        nests_lib.ensure_local_nest()
        with pytest.raises(ns.NestStorageError, match="path"):
            ns.add_storage_volume("local", "  ")
