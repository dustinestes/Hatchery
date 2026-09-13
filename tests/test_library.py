"""Unit tests for lib.library — path connections, list, pull, identity."""

from datetime import date, timedelta
from pathlib import Path

import pytest

import lib.library as library


@pytest.fixture
def script_share(tmp_path: Path) -> Path:
    root = tmp_path / "share"
    (root / "nested").mkdir(parents=True)
    (root / "hello.ps1").write_text("Write-Host hi\n", encoding="utf-8")
    (root / "nested" / "setup.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    (root / "readme.txt").write_text("ignore\n", encoding="utf-8")
    return root


def _path_conn(root: Path, *, conn_id: str = "c1") -> dict:
    return {
        "id": conn_id,
        "label": "Share",
        "type": "path",
        "base_uri": str(root),
        "token": "",
        "expires_at": None,
        "kinds": ["scripts"],
    }


class TestParse:
    def test_parse_connections_requires_artifact_type(self):
        with pytest.raises(ValueError, match="at least one artifact type"):
            library.parse_connections(
                [
                    {
                        "id": "a",
                        "label": "A",
                        "type": "path",
                        "base_uri": "/tmp",
                        "expires_at": (date.today() + timedelta(days=30)).isoformat(),
                        "kinds": [],
                    }
                ]
            )

    def test_parse_connections_allows_empty_expiry(self):
        conns = library.parse_connections(
            [
                {
                    "id": "a",
                    "label": "A",
                    "type": "path",
                    "base_uri": "/tmp",
                    "expires_at": "",
                    "kinds": ["scripts"],
                }
            ]
        )
        assert conns[0]["expires_at"] is None

    def test_parse_connections_rejects_expiry_not_after_today(self):
        with pytest.raises(ValueError, match="on or after"):
            library.parse_connections(
                [
                    {
                        "id": "a",
                        "label": "A",
                        "type": "path",
                        "base_uri": "/tmp",
                        "expires_at": date.today().isoformat(),
                        "kinds": ["scripts"],
                    }
                ]
            )

    def test_parse_script_bindings_requires_scripts_kind(self):
        conns = library.parse_connections(
            [
                {
                    "id": "a",
                    "label": "Media only",
                    "type": "path",
                    "base_uri": "/tmp",
                    "expires_at": (date.today() + timedelta(days=7)).isoformat(),
                    "kinds": ["media"],
                }
            ]
        )
        with pytest.raises(ValueError, match="does not serve scripts"):
            library.parse_script_bindings(
                [{"id": "b1", "connection_id": "a", "filter": "*"}], conns
            )


class TestPathLibrary:
    def test_connection(self, script_share):
        result = library.test_connection(_path_conn(script_share))
        assert result["ok"] is True

    def test_connection_missing(self, tmp_path):
        result = library.test_connection(_path_conn(tmp_path / "missing"))
        assert result["ok"] is False

    def test_list_and_filter(self, script_share):
        conn = _path_conn(script_share)
        hits = library.list_script_hits(conn, "*", limit=None)
        names = {h["name"] for h in hits}
        assert names == {"hello.ps1", "setup.sh"}
        assert all(h["sha256"] for h in hits)

        sample = library.test_filter(conn, "*.ps1")
        assert sample["ok"] is True
        assert len(sample["hits"]) == 1
        assert sample["hits"][0]["name"] == "hello.ps1"

    def test_pull_create_only(self, script_share, tmp_path, monkeypatch):
        dest = tmp_path / "data" / "automation" / "scripts"
        dest.mkdir(parents=True)
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path / "data")
        conn = _path_conn(script_share)
        result = library.pull_script(conn, "hello.ps1")
        assert result["name"] == "hello.ps1"
        assert (dest / "hello.ps1").is_file()
        assert result["sha256"] == library.sha256_file(dest / "hello.ps1")

        with pytest.raises(FileExistsError):
            library.pull_script(conn, "hello.ps1")

    def test_connections_for_bindings_skips_unreferenced(self, script_share):
        script = _path_conn(script_share)
        media = {
            "id": "media1",
            "label": "Artifactory",
            "type": "https",
            "base_uri": "https://example.invalid/",
            "token": "x",
            "expires_at": "",
            "kinds": ["media"],
        }
        parsed = library.connections_for_bindings(
            [media, script],
            [{"id": "b1", "connection_id": "c1", "filter": "*"}],
        )
        assert len(parsed) == 1
        assert parsed[0]["id"] == "c1"

    def test_catalog_dedupes_by_name(self, script_share):
        conn = _path_conn(script_share)
        bindings = [
            {"id": "b1", "connection_id": "c1", "filter": "*", "domain": "scripts"},
            {"id": "b2", "connection_id": "c1", "filter": "*.ps1", "domain": "scripts"},
        ]
        items = library.catalog_scripts([conn], bindings)
        names = [i["name"] for i in items]
        assert names.count("hello.ps1") == 1
        assert "setup.sh" in names


class TestMediaLibrary:
    @pytest.fixture
    def media_share(self, tmp_path: Path) -> Path:
        root = tmp_path / "media-share"
        root.mkdir()
        (root / "win11.iso").write_bytes(b"iso-bytes")
        (root / "virtio.iso").write_bytes(b"virtio-bytes")
        (root / "notes.txt").write_text("skip\n", encoding="utf-8")
        return root

    def _media_conn(self, root: Path) -> dict:
        return {
            "id": "m1",
            "label": "Media share",
            "type": "path",
            "base_uri": str(root),
            "token": "",
            "expires_at": None,
            "kinds": ["media"],
        }

    def test_parse_media_bindings_require_target(self, media_share):
        conn = self._media_conn(media_share)
        with pytest.raises(ValueError, match="target must be one of"):
            library.parse_media_bindings(
                [{"id": "b1", "connection_id": "m1", "filter": "*", "target": "vhd"}],
                [conn],
            )

    def test_list_pull_and_catalog_by_target(self, media_share, tmp_path, monkeypatch):
        conn = self._media_conn(media_share)
        hits = library.list_media_hits(conn, "*.iso")
        assert {h["name"] for h in hits} == {"win11.iso", "virtio.iso"}

        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path / "data")
        (tmp_path / "data" / "media" / "iso").mkdir(parents=True)
        pulled = library.pull_media(conn, "win11.iso", target="iso")
        assert pulled["name"] == "win11.iso"
        assert (tmp_path / "data" / "media" / "iso" / "win11.iso").is_file()

        bindings = [
            {
                "id": "b-iso",
                "connection_id": "m1",
                "filter": "win11.iso",
                "domain": "media",
                "target": "iso",
            },
            {
                "id": "b-virtio",
                "connection_id": "m1",
                "filter": "virtio.iso",
                "domain": "media",
                "target": "virtio",
            },
        ]
        iso_items = library.catalog_media([conn], bindings, target="iso")
        assert [i["name"] for i in iso_items] == ["win11.iso"]
        virtio_items = library.catalog_media([conn], bindings, target="virtio")
        assert [i["name"] for i in virtio_items] == ["virtio.iso"]
