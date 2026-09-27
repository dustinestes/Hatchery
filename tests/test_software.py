"""Tests for lib.software inventory helpers (#469)."""

from __future__ import annotations

import lib.config as cfg
import lib.software as software_lib


class TestSoftwareInventory:
    def test_scan_reads_yaml_display_meta(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        pkg = tmp_path / "automation" / "software" / "Acme.Widget.1.0.0"
        pkg.mkdir(parents=True)
        (pkg / "software.yaml").write_text(
            "hatchery:\n"
            "  kind: software\n"
            "  publisher: Acme\n"
            "  product: Widget\n"
            "  version: '1.0.0'\n"
            "  architecture: x64\n"
        )

        items = software_lib.scan_inventory()
        assert len(items) == 1
        item = items[0]
        assert item["name"] == "Acme.Widget.1.0.0"
        assert item["publisher"] == "Acme"
        assert item["product"] == "Widget"
        assert item["version"] == "1.0.0"
        assert item["architecture"] == "x64"
        assert "Acme" in item["subtitle"]
        assert item["has_definition"] is True
        assert item["relative_path"] == "automation/software/Acme.Widget.1.0.0"

    def test_scan_tolerates_missing_yaml(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        pkg = tmp_path / "automation" / "software" / "Bare.Pkg.0.1.0"
        pkg.mkdir(parents=True)

        items = software_lib.scan_inventory()
        assert len(items) == 1
        assert items[0]["publisher"] == ""
        assert items[0]["subtitle"] == "Software"
        assert items[0]["has_definition"] is False

    def test_resolve_rejects_traversal(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        (tmp_path / "automation" / "software").mkdir(parents=True)
        # Basename-only: "../etc" becomes "etc" under the software root (not escaped).
        resolved = software_lib.resolve_package_path("../etc")
        assert resolved is not None
        assert resolved.name == "etc"
        assert software_lib.resolve_package_path("..") is None
        assert software_lib.resolve_package_path(".") is None
        assert software_lib.resolve_package_path("") is None

    def test_delete_package_tree(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        pkg = tmp_path / "automation" / "software" / "Acme.Widget.1.0.0"
        pkg.mkdir(parents=True)
        (pkg / "software.yaml").write_text("hatchery: {}\n")
        (pkg / "windows").mkdir()
        (pkg / "windows" / "setup.exe").write_bytes(b"x")

        ok, err = software_lib.delete_package("Acme.Widget.1.0.0")
        assert ok is True
        assert err == ""
        assert not pkg.exists()
