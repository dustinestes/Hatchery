"""Unit tests for lib.library — path connections, list, pull, identity."""

import os
import shutil
import subprocess
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

    def test_parse_enabled_defaults_true(self):
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
        assert conns[0]["enabled"] is True
        binds = library.parse_script_bindings(
            [{"id": "b1", "connection_id": "a", "filter": "*"}], conns
        )
        assert binds[0]["enabled"] is True

    def test_parse_enabled_false(self):
        conns = library.parse_connections(
            [
                {
                    "id": "a",
                    "label": "A",
                    "type": "path",
                    "base_uri": "/tmp",
                    "expires_at": "",
                    "kinds": ["scripts"],
                    "enabled": False,
                }
            ]
        )
        assert conns[0]["enabled"] is False
        binds = library.parse_script_bindings(
            [{"id": "b1", "connection_id": "a", "filter": "*", "enabled": "0"}], conns
        )
        assert binds[0]["enabled"] is False

    def test_binding_effective_requires_connection_and_binding(self):
        conns = [
            {"id": "a", "label": "A", "enabled": True},
            {"id": "b", "label": "B", "enabled": False},
        ]
        by_id = {c["id"]: c for c in conns}
        assert library.binding_is_effective(
            {"connection_id": "a", "enabled": True}, by_id
        )
        assert not library.binding_is_effective(
            {"connection_id": "a", "enabled": False}, by_id
        )
        assert not library.binding_is_effective(
            {"connection_id": "b", "enabled": True}, by_id
        )
        # Cascade does not rewrite stored binding.enabled — only effective state.
        assert library.binding_is_enabled({"enabled": True})

    def test_catalog_skips_disabled_and_cascaded(self, script_share):
        on = _path_conn(script_share, conn_id="on")
        off = {**_path_conn(script_share, conn_id="off"), "enabled": False}
        bindings = [
            {
                "id": "b-on",
                "connection_id": "on",
                "filter": "*",
                "domain": "scripts",
                "enabled": True,
            },
            {
                "id": "b-off",
                "connection_id": "on",
                "filter": "*",
                "domain": "scripts",
                "enabled": False,
            },
            {
                "id": "b-cascade",
                "connection_id": "off",
                "filter": "*",
                "domain": "scripts",
                "enabled": True,
            },
        ]
        items = library.catalog_scripts([on, off], bindings)
        assert len(items) >= 1
        assert all(i["binding_id"] == "b-on" for i in items)


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


class TestClutchLibrary:
    @pytest.fixture
    def clutch_share(self, tmp_path: Path) -> Path:
        root = tmp_path / "clutch-share"
        (root / "nested").mkdir(parents=True)
        (root / "lab.yaml").write_text("name: lab\n", encoding="utf-8")
        (root / "nested" / "prod.yaml").write_text("name: prod\n", encoding="utf-8")
        (root / "notes.txt").write_text("skip\n", encoding="utf-8")
        return root

    def _clutch_conn(self, root: Path) -> dict:
        return {
            "id": "c1",
            "label": "Clutch share",
            "type": "path",
            "base_uri": str(root),
            "token": "",
            "expires_at": None,
            "kinds": ["clutches"],
        }

    def test_parse_clutch_bindings_requires_clutches_kind(self, clutch_share):
        conn = {
            "id": "a",
            "label": "Scripts only",
            "type": "path",
            "base_uri": str(clutch_share),
            "token": "",
            "expires_at": None,
            "kinds": ["scripts"],
        }
        with pytest.raises(ValueError, match="does not serve clutches"):
            library.parse_clutch_bindings(
                [{"id": "b1", "connection_id": "a", "filter": "*"}],
                [conn],
            )

    def test_list_pull_and_catalog(self, clutch_share, tmp_path, monkeypatch):
        conn = self._clutch_conn(clutch_share)
        hits = library.list_clutch_hits(conn, "*")
        assert {h["name"] for h in hits} == {"lab.yaml", "prod.yaml"}

        sample = library.test_filter(conn, "*.yaml", domain="clutches")
        assert sample["ok"] is True
        assert len(sample["hits"]) >= 1

        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path / "data")
        (tmp_path / "data" / "clutches").mkdir(parents=True)
        pulled = library.pull_clutch(conn, "lab.yaml")
        assert pulled["name"] == "lab.yaml"
        assert (tmp_path / "data" / "clutches" / "lab.yaml").is_file()

        with pytest.raises(FileExistsError):
            library.pull_clutch(conn, "lab.yaml")

        bindings = [
            {"id": "b1", "connection_id": "c1", "filter": "*", "domain": "clutches"},
            {"id": "b2", "connection_id": "c1", "filter": "lab.yaml", "domain": "clutches"},
        ]
        items = library.catalog_clutches([conn], bindings)
        names = [i["name"] for i in items]
        assert names.count("lab.yaml") == 1
        assert "prod.yaml" in names


class TestGitLibrary:
    @pytest.fixture
    def git_remote(self, tmp_path: Path) -> Path:
        if not shutil.which("git"):
            pytest.skip("git not installed")
        repo = tmp_path / "remote.git-work"
        (repo / "nested").mkdir(parents=True)
        (repo / "hello.ps1").write_text("Write-Host hi\n", encoding="utf-8")
        (repo / "nested" / "setup.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
        (repo / "lab.yaml").write_text("name: lab\n", encoding="utf-8")
        (repo / "readme.txt").write_text("ignore\n", encoding="utf-8")
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, env=env)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo,
            check=True,
            capture_output=True,
            env=env,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo,
            check=True,
            capture_output=True,
            env=env,
        )
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, env=env)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo,
            check=True,
            capture_output=True,
            env=env,
        )
        return repo

    def _git_conn(self, root: Path, *, conn_id: str = "g1") -> dict:
        return {
            "id": conn_id,
            "label": "Ops git",
            "type": "git",
            "base_uri": str(root),
            "token": "",
            "expires_at": None,
            "kinds": ["scripts", "clutches"],
        }

    def test_remote_url_embeds_token_for_https(self):
        url = library.git_remote_url("https://github.com/org/repo.git", "sekret")
        assert url.startswith("https://x-access-token:")
        assert "sekret" in url
        assert "@github.com/org/repo.git" in url
        gitlab = library.git_remote_url("https://gitlab.example/g/r.git", "tok")
        assert gitlab.startswith("https://oauth2:")

    def test_remote_url_ignores_token_for_ssh_and_path(self, tmp_path):
        assert library.git_remote_url("git@github.com:org/repo.git", "tok") == (
            "git@github.com:org/repo.git"
        )
        local = str(tmp_path / "repo")
        assert library.git_remote_url(local, "tok") == local

    def test_connection_ok(self, git_remote):
        result = library.test_connection(self._git_conn(git_remote))
        assert result["ok"] is True
        assert "Git remote OK" in result["message"]

    def test_connection_missing(self, tmp_path):
        if not shutil.which("git"):
            pytest.skip("git not installed")
        result = library.test_connection(self._git_conn(tmp_path / "missing-repo"))
        assert result["ok"] is False

    def test_list_filter_and_pull(self, git_remote, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path / "data")
        (tmp_path / "data" / "automation" / "scripts").mkdir(parents=True)
        conn = self._git_conn(git_remote)
        hits = library.list_script_hits(conn, "*", limit=None)
        names = {h["name"] for h in hits}
        assert names == {"hello.ps1", "setup.sh"}
        assert all(h["source_type"] == "git" for h in hits)
        assert all(h["sha256"] for h in hits)

        sample = library.test_filter(conn, "*.ps1")
        assert sample["ok"] is True
        assert len(sample["hits"]) == 1

        pulled = library.pull_script(conn, "hello.ps1")
        assert pulled["name"] == "hello.ps1"
        dest = tmp_path / "data" / "automation" / "scripts" / "hello.ps1"
        assert dest.is_file()
        assert pulled["sha256"] == library.sha256_file(dest)

        with pytest.raises(FileExistsError):
            library.pull_script(conn, "hello.ps1")

        clutch_hits = library.list_clutch_hits(conn, "*")
        assert {h["name"] for h in clutch_hits} == {"lab.yaml"}


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
