"""Tests for Library disable / excise (#407 / ADR-0019)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hatchery import app as flask_app
from lib import config as cfg
from lib import db
from lib import library as library_lib
from lib import library_excise as excise
from lib import library_provenance as prov
from lib import library_registry as registry


@pytest.fixture
def data_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr("lib.config.data_dir", lambda: data)
    db.init_db(data / "hatchery.db")
    yield data
    db._db_path = None


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def live_cfg(tmp_path, monkeypatch):
    """Isolated config + DB so /api/library/disable can update_settings."""
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(cfg, "DEFAULT_DATA_DIR", tmp_path / "data")
    cfg._config = {}
    cfg._db_bound = False
    cfg._pending_yaml_settings = {}
    cfg.set_runtime_data_dir(None)
    data = tmp_path / "data"
    data.mkdir()
    cfg.load()
    db.init_db(data / "hatchery.db")
    cfg.bind_db()
    cfg.save({**cfg.get(), "data_dir": str(data), "library_enabled": True})
    yield cfg
    db._db_path = None
    cfg._config = {}
    cfg._db_bound = False


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


def _seed_linked_script(data_env: Path, share: Path, *, conn_id: str = "c1") -> Path:
    (share / "hello.ps1").write_text("Write-Host hi\n", encoding="utf-8")
    registry.upsert_connection(_path_conn(share, conn_id=conn_id))
    library_lib.pull_script(_path_conn(share, conn_id=conn_id), "hello.ps1", binding_id="b1")
    dest = data_env / "automation" / "scripts" / "hello.ps1"
    assert dest.is_file()
    assert prov.get_for_cache("scripts", "hello.ps1") is not None
    return dest


class TestApplyDisableExcise:
    def test_mutex_raises(self, data_env):
        with pytest.raises(ValueError, match="mutually exclusive"):
            excise.apply_disable_excise(
                clear_connections=False,
                clear_content=True,
                clear_links=True,
                data_dir=data_env,
            )

    def test_clear_links_keeps_file_drops_provenance(self, data_env, tmp_path):
        share = tmp_path / "share"
        share.mkdir()
        dest = _seed_linked_script(data_env, share)
        counts = excise.apply_disable_excise(
            clear_connections=False,
            clear_content=False,
            clear_links=True,
            data_dir=data_env,
        )
        assert counts["links_cleared"] == 1
        assert counts["files_deleted"] == 0
        assert dest.is_file()
        assert prov.get_for_cache("scripts", "hello.ps1") is None
        assert prov.list_all() == []

    def test_clear_content_deletes_file_and_provenance(self, data_env, tmp_path):
        share = tmp_path / "share"
        share.mkdir()
        dest = _seed_linked_script(data_env, share)
        local_only = data_env / "automation" / "scripts" / "local.ps1"
        local_only.parent.mkdir(parents=True, exist_ok=True)
        local_only.write_text("local\n", encoding="utf-8")

        counts = excise.apply_disable_excise(
            clear_connections=False,
            clear_content=True,
            clear_links=False,
            data_dir=data_env,
        )
        assert counts["files_deleted"] == 1
        assert counts["links_cleared"] == 0
        assert not dest.exists()
        assert local_only.is_file()
        assert prov.get_for_cache("scripts", "hello.ps1") is None

    def test_clear_connections_empties_registry(self, data_env, tmp_path):
        share = tmp_path / "share"
        share.mkdir()
        _seed_linked_script(data_env, share)
        registry.upsert_binding(
            {
                "id": "b1",
                "connection_id": "c1",
                "filter": "*",
                "domain": "scripts",
                "enabled": True,
            }
        )
        counts = excise.apply_disable_excise(
            clear_connections=True,
            clear_content=False,
            clear_links=False,
            data_dir=data_env,
        )
        assert counts["connections_deleted"] == 1
        assert registry.list_connections() == []
        assert registry.list_bindings() == []
        # Soft on content/links: file + provenance remain
        assert (data_env / "automation" / "scripts" / "hello.ps1").is_file()
        assert prov.get_for_cache("scripts", "hello.ps1") is not None


class TestApiLibraryDisable:
    def test_soft_disable_sets_library_enabled_false(self, client, live_cfg):
        assert live_cfg.library_enabled() is True

        resp = client.post(
            "/api/library/disable",
            json={
                "clear_connections": False,
                "clear_content": False,
                "clear_links": False,
            },
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["connections_deleted"] == 0
        assert body["files_deleted"] == 0
        assert body["links_cleared"] == 0
        assert live_cfg.library_enabled() is False

    def test_rejects_content_and_links_both_true(self, client, live_cfg):
        assert live_cfg.library_enabled() is True
        resp = client.post(
            "/api/library/disable",
            json={
                "clear_connections": False,
                "clear_content": True,
                "clear_links": True,
            },
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["ok"] is False
        assert "mutually exclusive" in (body.get("error") or "")
        assert live_cfg.library_enabled() is True
