"""Tests for Nest cache ensure and hatch preflight (#245)."""

from __future__ import annotations

import pytest

from lib.clutch import Clutch, VMConfig
from lib.library import sha256_file
from lib.nest_cache import (
    CacheArtifact,
    NestCacheError,
    collect_clutch_artifacts,
    ensure,
    get_nest_cache_override,
    nest_cache_status,
    preflight,
    preflight_clutch,
    resolve_nest_cache,
    resolve_nest_cache_for_provider,
    set_nest_cache,
    verify_local,
)
from lib.nest_transport import NestConnectionConfig, NestSshConfig


def _clutch_with_media(**kwargs) -> Clutch:
    vm = VMConfig(
        name="dc01",
        os="windows",
        vcpus=2,
        ram_gb=4,
        disk_gb=60,
        os_media="win11.iso",
        virtio_drivers=kwargs.get("virtio_drivers"),
        answer_file=kwargs.get("answer_file", kwargs.get("os_config")),
        automations=kwargs.get("automations") or [],
    )
    return Clutch(name="lab", vms=[vm])


class TestCollectArtifacts:
    def test_collects_os_media(self):
        arts = collect_clutch_artifacts(_clutch_with_media())
        assert len(arts) == 1
        assert arts[0].kind == "media/iso"
        assert arts[0].basename == "win11.iso"
        assert arts[0].relative_path == "media/iso/win11.iso"

    def test_collects_optional_paths_and_scripts(self):
        arts = collect_clutch_artifacts(
            _clutch_with_media(
                virtio_drivers="virtio.iso",
                answer_file="unattend.xml",
                automations=[{"type": "script", "name": "setup.ps1"}],
            )
        )
        kinds = {a.kind for a in arts}
        assert kinds == {
            "media/iso",
            "media/virtio",
            "automation/answerfiles",
            "automation/scripts",
        }

    def test_collects_software_package_dirs(self):
        arts = collect_clutch_artifacts(
            _clutch_with_media(
                automations=[
                    {"type": "script", "name": "setup.ps1"},
                    {"type": "software", "name": "Hatchery.SoftwareExample.1.0.0"},
                ],
            )
        )
        by_kind = {}
        for a in arts:
            by_kind.setdefault(a.kind, []).append(a.basename)
        assert by_kind.get("automation/scripts") == ["setup.ps1"]
        assert by_kind.get("automation/software") == ["Hatchery.SoftwareExample.1.0.0"]

    def test_verify_software_package_directory(self, tmp_path):
        pkg = tmp_path / "automation" / "software" / "Hatchery.SoftwareExample.1.0.0"
        pkg.mkdir(parents=True)
        (pkg / "software.yaml").write_text("hatchery: {}\nplatforms: {}\n", encoding="utf-8")
        arts = collect_clutch_artifacts(
            _clutch_with_media(
                automations=[{"type": "software", "name": "Hatchery.SoftwareExample.1.0.0"}],
            )
        )
        # Drop ISO so we only assert software verify (ISO still required by collect)
        soft = [a for a in arts if a.kind == "automation/software"]
        result = verify_local(soft, nest_root=tmp_path)
        assert result.ok

    def test_dedupes_shared_iso_across_vms(self):
        vms = [
            VMConfig(name="a", os="windows", vcpus=2, ram_gb=4, disk_gb=40, os_media="win11.iso"),
            VMConfig(name="b", os="windows", vcpus=2, ram_gb=4, disk_gb=40, os_media="win11.iso"),
        ]
        arts = collect_clutch_artifacts(Clutch(name="lab", vms=vms))
        assert len(arts) == 1


class TestVerifyLocal:
    def test_missing_iso(self, tmp_path):
        art = CacheArtifact(kind="media/iso", basename="win11.iso")
        result = verify_local([art], nest_root=tmp_path)
        assert not result.ok
        assert result.issues[0].reason == "missing"
        assert "Nest cache missing: media/iso/win11.iso" in result.error_message()

    def test_present_iso(self, tmp_path):
        iso = tmp_path / "media" / "iso"
        iso.mkdir(parents=True)
        (iso / "win11.iso").write_bytes(b"iso")
        art = CacheArtifact(kind="media/iso", basename="win11.iso")
        result = verify_local([art], nest_root=tmp_path)
        assert result.ok

    def test_checksum_mismatch(self, tmp_path):
        iso = tmp_path / "media" / "iso"
        iso.mkdir(parents=True)
        path = iso / "win11.iso"
        path.write_bytes(b"iso")
        art = CacheArtifact(kind="media/iso", basename="win11.iso", sha256="0" * 64)
        result = verify_local([art], nest_root=tmp_path)
        assert not result.ok
        assert result.issues[0].reason == "checksum_mismatch"

    def test_checksum_match(self, tmp_path):
        iso = tmp_path / "media" / "iso"
        iso.mkdir(parents=True)
        path = iso / "win11.iso"
        path.write_bytes(b"iso")
        digest = sha256_file(path)
        art = CacheArtifact(kind="media/iso", basename="win11.iso", sha256=digest)
        assert verify_local([art], nest_root=tmp_path).ok

    def test_absolute_path_local(self, tmp_path):
        outside = tmp_path / "shared" / "win11.iso"
        outside.parent.mkdir(parents=True)
        outside.write_bytes(b"iso")
        art = CacheArtifact(
            kind="media/iso",
            basename="win11.iso",
            absolute_path=str(outside),
        )
        assert verify_local([art], nest_root=tmp_path / "data").ok


class TestRemoteStub:
    def test_preflight_remote_raises(self):
        nest = NestConnectionConfig(
            location="remote",
            transport="ssh",
            ssh=NestSshConfig(host="nest.example"),
        )
        art = CacheArtifact(kind="media/iso", basename="win11.iso")
        with pytest.raises(NestCacheError, match="Remote Nest cache ensure"):
            preflight([art], nest=nest)

    def test_ensure_remote_raises(self):
        nest = NestConnectionConfig(
            location="remote",
            transport="ssh",
            ssh=NestSshConfig(host="nest.example"),
        )
        art = CacheArtifact(kind="media/iso", basename="win11.iso")
        with pytest.raises(NestCacheError, match="not available yet"):
            ensure([art], nest=nest)

    def test_remote_refuses_absolute_operator_paths(self):
        nest = NestConnectionConfig(
            location="remote",
            transport="ssh",
            ssh=NestSshConfig(host="nest.example"),
        )
        art = CacheArtifact(
            kind="media/iso",
            basename="win11.iso",
            absolute_path="/home/op/data/media/iso/win11.iso",
        )
        result = preflight([art], nest=nest)
        assert not result.ok
        assert result.issues[0].reason == "absolute_path_remote"


class TestPreflightClutch:
    def test_local_ok(self, tmp_path):
        iso = tmp_path / "media" / "iso"
        iso.mkdir(parents=True)
        (iso / "win11.iso").write_bytes(b"x")
        result = preflight_clutch(_clutch_with_media(), nest_root=tmp_path)
        assert result.ok

    def test_ensure_local_is_verify(self, tmp_path):
        result = preflight_clutch(_clutch_with_media(), nest_root=tmp_path, run_ensure=True)
        assert not result.ok


class TestResolveNestCache:
    def test_local_always_data_dir(self, tmp_path, monkeypatch):
        from lib import config as config_lib

        monkeypatch.setattr(config_lib, "data_dir", lambda: tmp_path)
        nest = {"id": "local", "location": "local", "extra": {}}
        assert resolve_nest_cache(nest) == tmp_path
        assert get_nest_cache_override(nest) is None
        status = nest_cache_status(nest)
        assert status["is_default"] is True
        assert status["editable"] is False
        assert status["resolved"] == str(tmp_path)

    def test_local_ignores_stale_override(self, tmp_path, monkeypatch):
        from lib import config as config_lib

        monkeypatch.setattr(config_lib, "data_dir", lambda: tmp_path)
        override = tmp_path / "nest-cache"
        nest = {
            "id": "local",
            "location": "local",
            "extra": {"nest_cache": str(override)},
        }
        assert resolve_nest_cache(nest) == tmp_path
        status = nest_cache_status(nest)
        assert status["override"] is None
        assert status["is_default"] is True
        assert status["editable"] is False

    def test_remote_requires_path(self):
        nest = {"id": "remote1", "location": "remote", "extra": {}}
        with pytest.raises(NestCacheError, match="no nest_cache path"):
            resolve_nest_cache(nest)
        fallback = resolve_nest_cache_for_provider(nest, data_dir="/tmp/controller")
        assert str(fallback).replace("\\", "/") == "/tmp/controller"

    def test_remote_set_and_clear(self, tmp_path, monkeypatch):
        from lib import config as config_lib
        from lib import db
        from lib import nests as nests_lib

        monkeypatch.setattr(config_lib, "data_dir", lambda: tmp_path)
        db.init_db(tmp_path / "hatchery.db")
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
                    "extra": {},
                },
            ]
        )
        override = tmp_path / "remote-cache"
        status = set_nest_cache("remote1", str(override))
        assert status["override"] == str(override)
        assert status["resolved"] == str(override)
        assert status["editable"] is True
        cleared = set_nest_cache("remote1", None)
        assert cleared["override"] is None
        assert cleared["resolved"] is None
        assert cleared["error"]

    def test_local_refuses_set_path(self, tmp_path, monkeypatch):
        from lib import config as config_lib
        from lib import db
        from lib import nests as nests_lib

        monkeypatch.setattr(config_lib, "data_dir", lambda: tmp_path)
        db.init_db(tmp_path / "hatchery.db")
        nests_lib.ensure_local_nest()
        with pytest.raises(NestCacheError, match="cannot be overridden"):
            set_nest_cache("local", str(tmp_path / "alt-cache"))
        cleared = set_nest_cache("local", None)
        assert cleared["resolved"] == str(tmp_path)
        assert cleared["editable"] is False
