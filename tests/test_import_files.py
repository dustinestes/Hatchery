"""Tests for lib.import_files — create-only uploads into the data directory."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest

import lib.alerts as alerts_lib
import lib.config as cfg
import lib.db as db_module
import lib.import_files as import_files_lib


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path):
    db_module.init_db(tmp_path / "hatchery.db")
    yield
    db_module._db_path = None


class TestImportUploads:
    def test_imports_yaml_into_clutches(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        upload = SimpleNamespace(filename="lab.yaml", stream=BytesIO(b"name: lab\nvms: []\n"))

        result = import_files_lib.import_uploads("clutches", [upload])

        assert result["imported"] == ["lab.yaml"]
        assert result["errors"] == []
        assert (tmp_path / "clutches" / "lab.yaml").read_bytes().startswith(b"name:")

        rows = alerts_lib.list_recent(10)
        assert any(
            r["message"].startswith("Import finished:")
            and r["resolved"] == 1
            and r["tier"] == "info"
            for r in rows
        )
        assert not any(
            r["resolved"] == 0 and r["message"].startswith("Import in progress:") for r in rows
        )

    def test_refuses_overwrite(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        dest = tmp_path / "media" / "iso"
        dest.mkdir(parents=True)
        existing = dest / "win.iso"
        existing.write_bytes(b"ORIGINAL")

        upload = SimpleNamespace(filename="win.iso", stream=BytesIO(b"NEW"))
        result = import_files_lib.import_uploads("media/iso", [upload])

        assert result["imported"] == []
        assert result["errors"] == [
            {"name": "win.iso", "reason": "already exists (refuse overwrite)"}
        ]
        assert existing.read_bytes() == b"ORIGINAL"

    def test_rejects_bad_extension(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        upload = SimpleNamespace(filename="notes.txt", stream=BytesIO(b"hi"))

        result = import_files_lib.import_uploads("automation/scripts", [upload])

        assert result["imported"] == []
        assert len(result["errors"]) == 1
        assert "unsupported file type" in result["errors"][0]["reason"]
        assert not (tmp_path / "automation" / "scripts" / "notes.txt").exists()

    def test_sanitizes_path_traversal_basename(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        upload = SimpleNamespace(
            filename="../escape.ps1",
            stream=BytesIO(b"Write-Host hi"),
        )

        result = import_files_lib.import_uploads("automation/scripts", [upload])

        assert result["imported"] == ["escape.ps1"]
        assert (tmp_path / "automation" / "scripts" / "escape.ps1").is_file()
        assert not (tmp_path / "escape.ps1").exists()

    def test_partial_batch_imports_ok_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "media" / "virtio").mkdir(parents=True)
        (tmp_path / "media" / "virtio" / "taken.iso").write_bytes(b"old")

        uploads = [
            SimpleNamespace(filename="taken.iso", stream=BytesIO(b"nope")),
            SimpleNamespace(filename="fresh.iso", stream=BytesIO(b"yes")),
        ]
        result = import_files_lib.import_uploads("media/virtio", uploads)

        assert result["imported"] == ["fresh.iso"]
        assert result["errors"][0]["name"] == "taken.iso"
        assert (tmp_path / "media" / "virtio" / "fresh.iso").read_bytes() == b"yes"

    def test_rejects_empty_filename_and_unknown_kind(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        empty = SimpleNamespace(filename="", stream=BytesIO(b"x"))
        result = import_files_lib.import_uploads("clutches", [empty])
        assert result["imported"] == []
        assert result["errors"][0]["reason"] == "invalid filename"

        with pytest.raises(ValueError, match="unsupported import kind"):
            import_files_lib.import_uploads("nope", [])

        assert "clutches" in import_files_lib.known_kinds()

    def test_write_oserror_reports_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)

        def boom(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(import_files_lib, "_write_create_only", boom)
        upload = SimpleNamespace(filename="x.iso", stream=BytesIO(b"data"))
        result = import_files_lib.import_uploads("media/iso", [upload])
        assert result["imported"] == []
        assert result["errors"][0]["reason"] == "disk full"
        rows = alerts_lib.list_recent(5)
        assert any("with errors" in r["message"] for r in rows)
