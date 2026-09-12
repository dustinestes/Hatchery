"""Unit tests for lib.media_inspect."""

from unittest.mock import MagicMock, patch

import lib.clutch as clutch_lib
import lib.config as cfg
from lib import media_inspect
from lib.clutch import Clutch, VMConfig


class TestScanMediaDir:
    def test_lists_files_with_metadata(self, tmp_path, monkeypatch):
        iso = tmp_path / "media" / "iso"
        iso.mkdir(parents=True)
        f = iso / "a.iso"
        f.write_bytes(b"abc")
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        items = media_inspect.scan_media_dir("iso")
        assert len(items) == 1
        assert items[0]["name"] == "a.iso"
        assert items[0]["relative_path"] == "media/iso/a.iso"
        assert items[0]["size_bytes"] == 3
        assert items[0]["modified_at"].endswith("Z")

    def test_missing_dir_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        assert media_inspect.scan_media_dir("iso") == []


class TestResolveMediaPath:
    def test_basename_only_stays_under_subdir(self, tmp_path, monkeypatch):
        (tmp_path / "media" / "iso").mkdir(parents=True)
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        resolved = media_inspect.resolve_media_path("iso", "../x.iso")
        assert resolved == (tmp_path / "media" / "iso" / "x.iso").resolve()


class TestMediaUsedBy:
    def test_maps_os_media_and_virtio(self, tmp_path, monkeypatch):
        clutches = tmp_path / "clutches"
        clutches.mkdir(parents=True)
        clutch_lib.save(
            Clutch(
                name="Lab",
                vms=[
                    VMConfig(
                        name="dc01",
                        os="win11",
                        vcpus=2,
                        ram_gb=4,
                        disk_gb=40,
                        os_media="win11.iso",
                        virtio_drivers="virtio-win.iso",
                    )
                ],
            ),
            clutches / "lab.yaml",
        )
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        assert media_inspect.media_used_by("os_media")["win11.iso"][0]["vm"] == "dc01"
        assert media_inspect.media_used_by("virtio_drivers")["virtio-win.iso"][0]["vm"] == "dc01"


class TestProbeIso:
    def test_missing_file(self, tmp_path):
        result = media_inspect.probe_iso(tmp_path / "missing.iso")
        assert result["available"] is False
        assert result["error"] == "not found"

    def test_parses_pycdlib_pvd_and_eltorito(self, tmp_path):
        f = tmp_path / "a.iso"
        f.write_bytes(b"x")

        pvd = MagicMock()
        pvd.volume_identifier = b"TEST_VOL"
        pvd.publisher_identifier = MagicMock(text=b"MICROSOFT CORPORATION")
        pvd.application_identifier = MagicMock(text=b"CDIMAGE 2.56")
        created = MagicMock(year=2025, month=9, dayofmonth=16, hour=0, minute=0, second=0)
        pvd.volume_creation_date = created

        validation = MagicMock(platform_id=0)
        section = MagicMock(platform_id=0xEF)
        catalog = MagicMock(
            validation_entry=validation,
            initial_entry=MagicMock(boot_indicator=0x88),
            sections=[section],
        )

        iso = MagicMock()
        iso.pvd = pvd
        iso.eltorito_boot_catalog = catalog

        fake_mod = MagicMock()
        fake_mod.PyCdlib.return_value = iso

        with patch.dict("sys.modules", {"pycdlib": fake_mod}):
            # Re-import path uses import inside probe_iso
            result = media_inspect.probe_iso(f)

        assert result["available"] is True
        assert result["backend"] == "pycdlib"
        assert result["volume_id"] == "TEST_VOL"
        assert result["publisher"] == "MICROSOFT CORPORATION"
        assert result["app_id"] == "CDIMAGE 2.56"
        assert result["created_at"] == "2025-09-16 00:00:00"
        assert result["boot"] == "BIOS, UEFI"

    def test_no_eltorito_catalog_reports_none(self, tmp_path):
        f = tmp_path / "a.iso"
        f.write_bytes(b"x")

        pvd = MagicMock()
        pvd.volume_identifier = b"virtio-win-0.1.285"
        pvd.publisher_identifier = MagicMock(text=b" " * 20)
        pvd.application_identifier = MagicMock(text=b"GENISOIMAGE")
        created = MagicMock(year=2025, month=9, dayofmonth=12, hour=11, minute=6, second=55)
        pvd.volume_creation_date = created

        iso = MagicMock()
        iso.pvd = pvd
        iso.eltorito_boot_catalog = None

        fake_mod = MagicMock()
        fake_mod.PyCdlib.return_value = iso

        with patch.dict("sys.modules", {"pycdlib": fake_mod}):
            result = media_inspect.probe_iso(f)

        assert result["boot"] == "None"
        assert result["publisher"] is None
        assert result["created_at"] == "2025-09-12 11:06:55"

    def test_open_failure_returns_unavailable(self, tmp_path):
        f = tmp_path / "a.iso"
        f.write_bytes(b"x")
        fake_mod = MagicMock()
        fake_mod.PyCdlib.return_value.open.side_effect = OSError("bad iso")
        with patch.dict("sys.modules", {"pycdlib": fake_mod}):
            result = media_inspect.probe_iso(f)
        assert result["available"] is False
        assert "bad iso" in result["error"]
