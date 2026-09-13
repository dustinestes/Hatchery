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
    preflight,
    preflight_clutch,
    verify_local,
)
from lib.nest_transport import NestConnectionConfig, NestSshConfig


def _clutch_with_media(**kwargs) -> Clutch:
    vm = VMConfig(
        name="dc01",
        os="win11",
        vcpus=2,
        ram_gb=4,
        disk_gb=60,
        os_media="win11.iso",
        virtio_drivers=kwargs.get("virtio_drivers"),
        os_config=kwargs.get("os_config"),
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
                os_config="unattend.xml",
                automations=["setup.ps1"],
            )
        )
        kinds = {a.kind for a in arts}
        assert kinds == {
            "media/iso",
            "media/virtio",
            "automation/os_config",
            "automation/scripts",
        }

    def test_dedupes_shared_iso_across_vms(self):
        vms = [
            VMConfig(name="a", os="win11", vcpus=2, ram_gb=4, disk_gb=40, os_media="win11.iso"),
            VMConfig(name="b", os="win11", vcpus=2, ram_gb=4, disk_gb=40, os_media="win11.iso"),
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
