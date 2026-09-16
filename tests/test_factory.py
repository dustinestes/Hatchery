"""Tests for Nest id → BaseProvider factory."""

from __future__ import annotations

import pytest

from lib import config as cfg
from lib import nests as nests_lib
from lib.providers.factory import (
    UnknownNestError,
    UnsupportedProviderError,
    get_provider,
)
from lib.providers.libvirt import LibvirtProvider


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
    from lib import db

    db.init_db(tmp_path / "hatchery.db")
    nests_lib.ensure_local_nest()
    yield


class TestGetProvider:
    def test_default_local_libvirt(self, tmp_path):
        provider = get_provider()
        assert isinstance(provider, LibvirtProvider)
        assert provider.iso_dir == tmp_path / "media" / "iso"

    def test_explicit_local_id(self, tmp_path):
        provider = get_provider("local")
        assert isinstance(provider, LibvirtProvider)
        assert provider.automation_dir == tmp_path / "automation" / "os_config"

    def test_unknown_nest_raises(self):
        with pytest.raises(UnknownNestError) as exc:
            get_provider("no-such-nest")
        assert "no-such-nest" in str(exc.value)

    def test_remote_nest_unsupported(self):
        nests_lib.replace_nests(
            [
                nests_lib.get_nest("local"),
                {
                    "id": "remote1",
                    "name": "Remote",
                    "provider_type": "libvirt",
                    "location": "remote",
                    "host": "r.example",
                },
            ]
        )
        with pytest.raises(UnsupportedProviderError) as exc:
            get_provider("remote1")
        assert "remote1" in str(exc.value)

    def test_utm_local_unsupported(self):
        local = nests_lib.get_nest("local")
        assert local is not None
        local["provider_type"] = "utm"
        nests_lib.replace_nests([local])
        with pytest.raises(UnsupportedProviderError) as exc:
            get_provider("local")
        assert "utm" in str(exc.value)
