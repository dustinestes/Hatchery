"""Tests for Library forge adapter registry and GitHub plugin (#307)."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from lib import library as library_lib
from lib.library_forge import github as gh
from lib.library_forge import register_builtins
from lib.library_forge.github import GitHubAdapter
from lib.library_forge.registry import all_providers, clear_registry, get_adapter


@pytest.fixture(autouse=True)
def _registry():
    clear_registry()
    register_builtins()
    yield
    clear_registry()


class TestRegistry:
    def test_github_registered(self):
        assert get_adapter("github") is not None
        ids = [p.id for p in all_providers()]
        assert "github" in ids

    def test_unknown_provider(self):
        assert get_adapter("gitlab") is None


class TestParseForge:
    def test_forge_requires_provider(self):
        with pytest.raises(ValueError, match="needs a provider"):
            library_lib.parse_connections(
                [
                    {
                        "id": "f1",
                        "label": "GH",
                        "type": "forge",
                        "base_uri": "https://github.com/org/repo",
                        "kinds": ["scripts"],
                    }
                ]
            )

    def test_forge_unknown_provider(self):
        with pytest.raises(ValueError, match="unknown forge provider"):
            library_lib.parse_connections(
                [
                    {
                        "id": "f1",
                        "label": "GH",
                        "type": "forge",
                        "provider": "not-a-real-vendor",
                        "base_uri": "https://github.com/org/repo",
                        "kinds": ["scripts"],
                    }
                ]
            )

    def test_forge_ok(self):
        conns = library_lib.parse_connections(
            [
                {
                    "id": "f1",
                    "label": "GH",
                    "type": "forge",
                    "provider": "github",
                    "base_uri": "https://github.com/org/repo",
                    "token": "t",
                    "kinds": ["scripts"],
                }
            ]
        )
        assert conns[0]["provider"] == "github"
        assert conns[0]["type"] == "forge"

    def test_path_clears_provider(self):
        conns = library_lib.parse_connections(
            [
                {
                    "id": "p1",
                    "label": "Share",
                    "type": "path",
                    "provider": "github",
                    "base_uri": "/tmp",
                    "kinds": ["scripts"],
                }
            ]
        )
        assert conns[0]["provider"] == ""


class TestParseGithubRepo:
    def test_https_and_owner_repo(self):
        assert gh.parse_github_repo("https://github.com/acme/widgets.git") == (
            "acme",
            "widgets",
        )
        assert gh.parse_github_repo("acme/widgets") == ("acme", "widgets")

    def test_rejects_non_github_host(self):
        with pytest.raises(ValueError, match="github.com"):
            gh.parse_github_repo("https://gitlab.com/acme/widgets")


def _mock_urlopen_factory(responses: dict[str, tuple[int, bytes, dict]]):
    """Map URL substring → (code, body, headers)."""

    def factory(req, timeout=None):  # noqa: ARG001
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for key, (code, body, headers) in responses.items():
            if key in url:
                if code >= 400:
                    raise HTTPError(url, code, "err", hdrs=None, fp=io.BytesIO(body))
                resp = MagicMock()
                resp.status = code
                resp.getcode.return_value = code
                resp.read.side_effect = [body, b""]
                resp.headers = headers or {}
                resp.__enter__ = lambda s: s
                resp.__exit__ = MagicMock(return_value=False)
                return resp
        raise AssertionError(f"unexpected URL: {url}")

    return factory


def _forge_conn(**overrides) -> dict:
    base = {
        "id": "f1",
        "label": "GH scripts",
        "type": "forge",
        "provider": "github",
        "base_uri": "https://github.com/acme/widgets",
        "token": "tok",
        "expires_at": None,
        "kinds": ["scripts"],
        "enabled": True,
    }
    base.update(overrides)
    return base


class TestGitHub:
    def test_ping_ok(self):
        adapter = GitHubAdapter()
        payload = {"full_name": "acme/widgets", "default_branch": "main"}
        with patch(
            "lib.library_forge.github.urlopen",
            side_effect=_mock_urlopen_factory(
                {"/repos/acme/widgets": (200, json.dumps(payload).encode(), {})}
            ),
        ):
            result = adapter.test(_forge_conn())
        assert result["ok"] is True
        assert "acme/widgets" in result["message"]
        assert "main" in result["message"]

    def test_list_via_tree(self):
        adapter = GitHubAdapter()
        repo = {"default_branch": "main"}
        tree = {
            "truncated": False,
            "tree": [
                {"type": "blob", "path": "scripts/hello.ps1", "sha": "blobsha1"},
                {"type": "blob", "path": "scripts/setup.sh", "sha": "blobsha2"},
                {"type": "blob", "path": "README.md", "sha": "blobsha3"},
                {"type": "tree", "path": "scripts", "sha": "treesha"},
            ],
        }
        with patch(
            "lib.library_forge.github.urlopen",
            side_effect=_mock_urlopen_factory(
                {
                    "/repos/acme/widgets/git/trees/": (
                        200,
                        json.dumps(tree).encode(),
                        {},
                    ),
                    "/repos/acme/widgets": (200, json.dumps(repo).encode(), {}),
                }
            ),
        ):
            hits = adapter.list_hits(
                _forge_conn(),
                "scripts/*.ps1",
                extensions=frozenset({".ps1", ".sh"}),
                limit=10,
            )
        assert len(hits) == 1
        assert hits[0]["name"] == "hello.ps1"
        assert hits[0]["relative_path"] == "scripts/hello.ps1"
        assert hits[0]["sha256"] is None
        assert hits[0]["source_type"] == "forge"
        assert hits[0]["connection_id"] == "f1"

    def test_pull_computes_sha256(self, tmp_path: Path):
        adapter = GitHubAdapter()
        dest = tmp_path / "hello.ps1"
        body = b"Write-Host hi"
        expected = hashlib.sha256(body).hexdigest()
        repo = {"default_branch": "main"}

        def factory(req, timeout=None):  # noqa: ARG001
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "api.github.com" in url:
                payload = json.dumps(repo).encode()
                resp = MagicMock()
                resp.status = 200
                resp.getcode.return_value = 200
                resp.read.side_effect = [payload, b""]
                resp.headers = {}
                resp.__enter__ = lambda s: s
                resp.__exit__ = MagicMock(return_value=False)
                return resp
            if "raw.githubusercontent.com" in url:
                resp = MagicMock()
                resp.status = 200
                resp.getcode.return_value = 200
                resp.read.side_effect = [body, b""]
                resp.headers = {}
                resp.__enter__ = lambda s: s
                resp.__exit__ = MagicMock(return_value=False)
                return resp
            raise AssertionError(f"unexpected URL: {url}")

        with patch("lib.library_forge.github.urlopen", side_effect=factory):
            result = adapter.pull_file(_forge_conn(), "scripts/hello.ps1", dest)
        assert dest.read_bytes() == body
        assert result["sha256"] == expected
        assert result["name"] == "hello.ps1"

    def test_library_dispatch_and_no_git_cache(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("lib.config.data_dir", lambda: tmp_path / "data")
        (tmp_path / "data" / "automation" / "scripts").mkdir(parents=True)
        conn = _forge_conn()
        repo = {"default_branch": "main", "full_name": "acme/widgets"}
        tree = {
            "truncated": False,
            "tree": [
                {"type": "blob", "path": "hello.ps1", "sha": "blobsha1"},
            ],
        }
        body = b"# forge script"

        def factory(req, timeout=None):  # noqa: ARG001
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "/git/trees/" in url:
                payload = json.dumps(tree).encode()
            elif "raw.githubusercontent.com" in url:
                payload = body
            elif "/repos/acme/widgets" in url:
                payload = json.dumps(repo).encode()
            else:
                raise AssertionError(f"unexpected URL: {url}")
            resp = MagicMock()
            resp.status = 200
            resp.getcode.return_value = 200
            resp.read.side_effect = [payload, b""]
            resp.headers = {}
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("lib.library_forge.github.urlopen", side_effect=factory):
            result = library_lib.test_connection(conn)
            assert result["ok"] is True
            hits = library_lib.list_script_hits(conn, "*", limit=None)
            assert len(hits) == 1
            assert hits[0]["source_type"] == "forge"
            assert hits[0]["sha256"] is None
            pulled = library_lib.pull_script(conn, "hello.ps1")

        dest = tmp_path / "data" / "automation" / "scripts" / "hello.ps1"
        assert dest.is_file()
        assert dest.read_bytes() == body
        assert pulled["sha256"] == hashlib.sha256(body).hexdigest()
        git_cache = tmp_path / "data" / "library" / "git"
        assert not git_cache.exists()
