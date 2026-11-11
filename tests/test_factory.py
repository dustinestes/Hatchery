"""Tests for Nest id → BaseProvider factory."""

from __future__ import annotations

import pytest

from lib import config as cfg
from lib import nests as nests_lib
from lib.providers.factory import (
    NoNestSelectedError,
    UnknownNestError,
    UnsupportedProviderError,
    get_provider,
)
from lib.providers.hyperv import HyperVProvider
from lib.providers.libvirt import LibvirtProvider


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
    from lib import db

    db.init_db(tmp_path / "hatchery.db")
    yield


class TestGetProvider:
    def test_empty_registry_raises(self):
        with pytest.raises(NoNestSelectedError):
            get_provider()

    def test_sole_nest_is_default(self, tmp_path):
        nests_lib.ensure_local_nest()
        provider = get_provider()
        assert isinstance(provider, LibvirtProvider)
        assert provider.iso_dir == tmp_path / "media" / "iso"

    def test_explicit_local_id(self, tmp_path):
        nests_lib.ensure_local_nest()
        provider = get_provider("local")
        assert isinstance(provider, LibvirtProvider)
        assert provider.automation_dir == tmp_path / "automation" / "answerfiles"

    def test_local_nest_cache_ignores_stale_override(self, tmp_path):
        nests_lib.ensure_local_nest()
        override = tmp_path / "alt-nest-cache"
        override.mkdir()
        nests_lib.update_nest_extra("local", {"nest_cache": str(override)})
        provider = get_provider("local")
        assert isinstance(provider, LibvirtProvider)
        assert provider.nest_cache == tmp_path
        assert provider.iso_dir == tmp_path / "media" / "iso"
        assert provider.virtio_dir == tmp_path / "media" / "virtio"

    def test_unknown_nest_raises(self):
        with pytest.raises(UnknownNestError) as exc:
            get_provider("no-such-nest")
        assert "no-such-nest" in str(exc.value)

    def test_remote_nest_cannot_be_registered(self):
        nests_lib.ensure_local_nest()
        with pytest.raises(ValueError, match="#620"):
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

    def test_utm_local_unsupported(self):
        nests_lib.ensure_local_nest()
        local = nests_lib.get_nest("local")
        assert local is not None
        local["provider_type"] = "utm"
        nests_lib.replace_nests([local])
        with pytest.raises(UnsupportedProviderError) as exc:
            get_provider("local")
        assert "utm" in str(exc.value)

    def test_hyperv_local(self):
        nests_lib.ensure_local_nest()
        local = nests_lib.get_nest("local")
        assert local is not None
        local["provider_type"] = "hyperv"
        nests_lib.replace_nests([local])
        provider = get_provider("local")
        assert isinstance(provider, HyperVProvider)
        assert provider.nest_id == "local"
        assert provider._transport is None
        assert provider.iso_dir.name == "iso"
        assert provider.automation_dir.name == "answerfiles"

    @pytest.mark.parametrize("provider_type", ["libvirt", "hyperv"])
    def test_remote_location_rejected(self, monkeypatch, provider_type):
        monkeypatch.setattr(
            nests_lib,
            "get_nest",
            lambda nid: {
                "id": nid,
                "name": "Remote",
                "provider_type": provider_type,
                "location": "remote",
                "extra": {},
            },
        )
        with pytest.raises(UnsupportedProviderError, match="#620"):
            get_provider("remote1")
