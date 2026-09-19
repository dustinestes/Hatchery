"""Tests for Library API adapter registry and Artifactory plugin (#255)."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from lib import library as library_lib
from lib.library_api import artifactory as af
from lib.library_api import register_builtins
from lib.library_api.artifactory import ArtifactoryAdapter
from lib.library_api.registry import all_providers, clear_registry, get_adapter


@pytest.fixture(autouse=True)
def _registry():
    clear_registry()
    register_builtins()
    yield
    clear_registry()


class TestRegistry:
    def test_artifactory_registered(self):
        assert get_adapter("artifactory") is not None
        ids = [p.id for p in all_providers()]
        assert "artifactory" in ids

    def test_unknown_provider(self):
        assert get_adapter("nexus") is None


class TestParseApi:
    def test_api_requires_provider(self):
        with pytest.raises(ValueError, match="needs a provider"):
            library_lib.parse_connections(
                [
                    {
                        "id": "a1",
                        "label": "AF",
                        "type": "api",
                        "base_uri": "https://af.example/artifactory",
                        "kinds": ["media"],
                    }
                ]
            )

    def test_api_unknown_provider(self):
        with pytest.raises(ValueError, match="unknown API provider"):
            library_lib.parse_connections(
                [
                    {
                        "id": "a1",
                        "label": "AF",
                        "type": "api",
                        "provider": "not-a-real-vendor",
                        "base_uri": "https://af.example/artifactory",
                        "kinds": ["media"],
                    }
                ]
            )

    def test_api_ok(self):
        conns = library_lib.parse_connections(
            [
                {
                    "id": "a1",
                    "label": "AF",
                    "type": "api",
                    "provider": "artifactory",
                    "base_uri": "https://af.example/artifactory",
                    "token": "t",
                    "kinds": ["media"],
                }
            ]
        )
        assert conns[0]["provider"] == "artifactory"
        assert conns[0]["type"] == "api"

    def test_path_clears_provider(self):
        conns = library_lib.parse_connections(
            [
                {
                    "id": "p1",
                    "label": "Share",
                    "type": "path",
                    "provider": "artifactory",
                    "base_uri": "/tmp",
                    "kinds": ["scripts"],
                }
            ]
        )
        assert conns[0]["provider"] == ""


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


class TestArtifactory:
    def test_parse_filter(self):
        assert af._parse_filter("media-isos/**/*.iso") == ("media-isos", "**/*.iso")
        assert af._parse_filter("scripts") == ("scripts", "**/*")

    def test_ping_ok(self):
        adapter = ArtifactoryAdapter()
        conn = {
            "id": "a1",
            "base_uri": "https://af.example/artifactory",
            "token": "tok",
            "provider": "artifactory",
        }
        with patch(
            "lib.library_api.artifactory.urlopen",
            side_effect=_mock_urlopen_factory({"/api/system/ping": (200, b"OK", {})}),
        ):
            result = adapter.test(conn)
        assert result["ok"] is True
        assert "Artifactory OK" in result["message"]

    def test_list_via_aql(self):
        adapter = ArtifactoryAdapter()
        conn = {
            "id": "a1",
            "base_uri": "https://af.example/artifactory",
            "token": "",
            "provider": "artifactory",
        }
        payload = {
            "results": [
                {
                    "repo": "media-isos",
                    "path": ".",
                    "name": "win11.iso",
                    "actual_sha2": "abc123",
                }
            ]
        }
        with patch(
            "lib.library_api.artifactory.urlopen",
            side_effect=_mock_urlopen_factory(
                {"/api/search/aql": (200, json.dumps(payload).encode(), {})}
            ),
        ):
            hits = adapter.list_hits(
                conn, "media-isos/*.iso", extensions=frozenset({".iso"}), limit=10
            )
        assert len(hits) == 1
        assert hits[0]["name"] == "win11.iso"
        assert hits[0]["relative_path"] == "media-isos/win11.iso"
        assert hits[0]["sha256"] == "abc123"
        assert hits[0]["source_type"] == "api"

    def test_pull_uses_checksum_header(self, tmp_path):
        adapter = ArtifactoryAdapter()
        conn = {
            "id": "a1",
            "base_uri": "https://af.example/artifactory",
            "token": "t",
            "provider": "artifactory",
        }
        dest = tmp_path / "win11.iso"

        def factory(req, timeout=None):  # noqa: ARG001
            resp = MagicMock()
            resp.status = 200
            resp.getcode.return_value = 200
            resp.headers = {"X-Checksum-Sha256": "deadbeef"}
            resp.read.side_effect = [b"iso-bytes", b""]
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("lib.library_api.artifactory.urlopen", side_effect=factory):
            result = adapter.pull_file(conn, "media-isos/win11.iso", dest)
        assert dest.read_bytes() == b"iso-bytes"
        assert result["sha256"] == "deadbeef"
        assert result["name"] == "win11.iso"

    def test_library_dispatch(self):
        conn = {
            "id": "a1",
            "label": "AF",
            "type": "api",
            "provider": "artifactory",
            "base_uri": "https://af.example/artifactory",
            "token": "",
            "kinds": ["media"],
        }
        with patch(
            "lib.library_api.artifactory.urlopen",
            side_effect=_mock_urlopen_factory({"/api/system/ping": (200, b"OK", {})}),
        ):
            result = library_lib.test_connection(conn)
        assert result["ok"] is True
