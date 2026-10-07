"""Tests for Software definition schema (#471)."""

from __future__ import annotations

import pytest

import lib.config as cfg
import lib.software as software_lib

_VALID_WINDOWS = """\
hatchery:
  kind: software
  publisher: Acme
  product: Widget
  version: "1.0.0"
platforms:
  windows:
    x64:
      pre_install:
        - command: 'echo prep'
      install:
        command: '.\\Setup.exe /S'
        success_exit_codes: [0]
        reboot_after: false
      post_install:
        - script: '.\\hooks\\post.ps1'
          success_exit_codes: [0, 3010]
      uninstall:
        command: 'msiexec /x {GUID} /qn'
      detect:
        command: 'powershell -NoProfile -Command "exit 0"'
"""


class TestSoftwareDefinitionSchema:
    def test_load_valid_windows_x64(self, tmp_path):
        path = tmp_path / "software.yaml"
        path.write_text(_VALID_WINDOWS)
        defn = software_lib.load_definition(path)
        assert defn.hatchery.publisher == "Acme"
        assert defn.architecture_labels() == ["x64"]
        win = defn.platforms["windows"]["x64"]
        assert win.install.command.startswith(".\\Setup.exe")
        assert win.pre_install[0].command == "echo prep"
        assert win.post_install[0].script == ".\\hooks\\post.ps1"
        assert defn.payload_relpath("windows", "x64") == "windows/x64"
        assert defn.resolve_unit("windows", "x64")[0] == "x64"
        assert defn.any_install_reboot_after() is False

    def test_any_install_reboot_after(self, tmp_path):
        path = tmp_path / "software.yaml"
        path.write_text(_VALID_WINDOWS.replace("reboot_after: false", "reboot_after: true"))
        defn = software_lib.load_definition(path)
        assert defn.any_install_reboot_after() is True

    def test_install_retry_defaults_and_validation(self, tmp_path):
        path = tmp_path / "software.yaml"
        path.write_text(
            _VALID_WINDOWS.replace(
                "reboot_after: false",
                "reboot_after: false\n        retry: {}\n",
            )
        )
        defn = software_lib.load_definition(path)
        retry = defn.platforms["windows"]["x64"].install.retry
        assert retry is not None
        assert retry.max_attempts == 3
        assert retry.delay_seconds == 15
        assert retry.on_null_exit is True

        path.write_text(
            _VALID_WINDOWS.replace(
                "reboot_after: false",
                "reboot_after: false\n        retry:\n          max_attempts: 0\n",
            )
        )
        with pytest.raises(ValueError, match="max_attempts"):
            software_lib.load_definition(path)

        path.write_text(
            _VALID_WINDOWS.replace(
                "reboot_after: false",
                "reboot_after: false\n        retry:\n          delay_seconds: -1\n",
            )
        )
        with pytest.raises(ValueError, match="delay_seconds"):
            software_lib.load_definition(path)

        # Omitted retry stays None (single attempt).
        path.write_text(_VALID_WINDOWS)
        assert software_lib.load_definition(path).platforms["windows"]["x64"].install.retry is None

    def test_uninstall_may_declare_retry(self, tmp_path):
        path = tmp_path / "software.yaml"
        path.write_text(
            "hatchery:\n"
            "  kind: software\n"
            "  publisher: Acme\n"
            "  product: Widget\n"
            "  version: '1.0.0'\n"
            "platforms:\n"
            "  windows:\n"
            "    x64:\n"
            "      install: {command: '.\\Setup.exe'}\n"
            "      uninstall:\n"
            "        command: 'u'\n"
            "        retry: {max_attempts: 2, delay_seconds: 5}\n"
            "      detect: {command: 'd'}\n"
        )
        defn = software_lib.load_definition(path)
        assert defn.platforms["windows"]["x64"].uninstall.retry is not None
        assert defn.platforms["windows"]["x64"].uninstall.retry.max_attempts == 2

    def test_multi_arch_and_any_exclusive(self, tmp_path):
        path = tmp_path / "software.yaml"
        path.write_text(
            "hatchery:\n"
            "  kind: software\n"
            "  publisher: Acme\n"
            "  product: Widget\n"
            "  version: '1.0.0'\n"
            "platforms:\n"
            "  windows:\n"
            "    x86:\n"
            "      install: {command: '.\\a-x86.msi'}\n"
            "      uninstall: {command: 'u'}\n"
            "      detect: {command: 'd'}\n"
            "    x64:\n"
            "      install: {command: '.\\a-x64.msi'}\n"
            "      uninstall: {command: 'u'}\n"
            "      detect: {command: 'd'}\n"
            "    arm64:\n"
            "      install: {command: '.\\a-arm64.msi'}\n"
            "      uninstall: {command: 'u'}\n"
            "      detect: {command: 'd'}\n"
        )
        defn = software_lib.load_definition(path)
        assert defn.architecture_labels() == ["arm64", "x64", "x86"]

        path.write_text(
            "hatchery:\n"
            "  kind: software\n"
            "  publisher: Acme\n"
            "  product: Widget\n"
            "  version: '1.0.0'\n"
            "platforms:\n"
            "  windows:\n"
            "    any:\n"
            "      install: {command: '.\\multi.msi'}\n"
            "      uninstall: {command: 'u'}\n"
            "      detect: {command: 'd'}\n"
        )
        any_defn = software_lib.load_definition(path)
        assert any_defn.resolve_unit("windows", "x64")[0] == "any"
        assert any_defn.payload_relpath("windows", "arm64") == "windows/any"

        path.write_text(
            "hatchery:\n"
            "  kind: software\n"
            "  publisher: Acme\n"
            "  product: Widget\n"
            "  version: '1.0.0'\n"
            "platforms:\n"
            "  windows:\n"
            "    any:\n"
            "      install: {command: '.\\multi.msi'}\n"
            "      uninstall: {command: 'u'}\n"
            "      detect: {command: 'd'}\n"
            "    x64:\n"
            "      install: {command: '.\\a.msi'}\n"
            "      uninstall: {command: 'u'}\n"
            "      detect: {command: 'd'}\n"
        )
        with pytest.raises(ValueError, match="any.*cannot be combined"):
            software_lib.load_definition(path)

    def test_defaults_success_exit_codes_and_reboot(self, tmp_path):
        path = tmp_path / "software.yaml"
        path.write_text(
            "hatchery:\n"
            "  kind: software\n"
            "  publisher: Acme\n"
            "  product: Widget\n"
            "  version: '1.0.0'\n"
            "platforms:\n"
            "  windows:\n"
            "    x64:\n"
            "      install:\n"
            "        command: '.\\a.exe'\n"
            "      uninstall:\n"
            "        command: 'msiexec /x {G}'\n"
            "      detect:\n"
            "        command: 'exit 1'\n"
        )
        defn = software_lib.load_definition(path)
        win = defn.platforms["windows"]["x64"]
        assert win.install.success_exit_codes == [0]
        assert win.install.reboot_after is False
        assert win.pre_install == []

    def test_rejects_hook_with_both_command_and_script(self, tmp_path):
        path = tmp_path / "software.yaml"
        path.write_text(
            "hatchery:\n"
            "  kind: software\n"
            "  publisher: Acme\n"
            "  product: Widget\n"
            "  version: '1.0.0'\n"
            "platforms:\n"
            "  windows:\n"
            "    x64:\n"
            "      pre_install:\n"
            "        - command: 'echo a'\n"
            "          script: '.\\a.ps1'\n"
            "      install:\n"
            "        command: '.\\a.exe'\n"
            "      uninstall:\n"
            "        command: 'u'\n"
            "      detect:\n"
            "        command: 'd'\n"
        )
        with pytest.raises(ValueError, match="exactly one of command or script"):
            software_lib.load_definition(path)

    def test_rejects_unknown_os_arch_and_hatchery_architecture(self, tmp_path):
        path = tmp_path / "software.yaml"
        path.write_text(
            "hatchery:\n"
            "  kind: software\n"
            "  publisher: Acme\n"
            "  product: Widget\n"
            "  version: '1.0.0'\n"
            "platforms:\n"
            "  solaris:\n"
            "    x64:\n"
            "      install: {command: './a'}\n"
            "      uninstall: {command: 'u'}\n"
            "      detect: {command: 'd'}\n"
        )
        with pytest.raises(ValueError, match="unknown platform"):
            software_lib.load_definition(path)

        path.write_text(
            "hatchery:\n"
            "  kind: software\n"
            "  publisher: Acme\n"
            "  product: Widget\n"
            "  version: '1.0.0'\n"
            "platforms:\n"
            "  windows:\n"
            "    amd64:\n"
            "      install: {command: '.\\a.exe'}\n"
            "      uninstall: {command: 'u'}\n"
            "      detect: {command: 'd'}\n"
        )
        with pytest.raises(ValueError, match="unknown architecture"):
            software_lib.load_definition(path)

        path.write_text(
            "hatchery:\n"
            "  kind: software\n"
            "  publisher: Acme\n"
            "  product: Widget\n"
            "  version: '1.0.0'\n"
            "  architecture: x64\n"
            "platforms:\n"
            "  windows:\n"
            "    x64:\n"
            "      install: {command: '.\\a.exe'}\n"
            "      uninstall: {command: 'u'}\n"
            "      detect: {command: 'd'}\n"
        )
        with pytest.raises(ValueError, match="architecture|Extra"):
            software_lib.load_definition(path)

    def test_rejects_wrong_kind_and_empty_publisher(self, tmp_path):
        path = tmp_path / "software.yaml"
        path.write_text(
            "hatchery:\n"
            "  kind: script\n"
            "  publisher: Acme\n"
            "  product: Widget\n"
            "  version: '1.0.0'\n"
            "platforms:\n"
            "  windows:\n"
            "    x64:\n"
            "      install: {command: '.\\a.exe'}\n"
            "      uninstall: {command: 'u'}\n"
            "      detect: {command: 'd'}\n"
        )
        with pytest.raises(ValueError):
            software_lib.load_definition(path)

        path.write_text(
            "hatchery:\n"
            "  kind: software\n"
            "  publisher: '  '\n"
            "  product: Widget\n"
            "  version: '1.0.0'\n"
            "platforms:\n"
            "  windows:\n"
            "    x64:\n"
            "      install: {command: '.\\a.exe'}\n"
            "      uninstall: {command: 'u'}\n"
            "      detect: {command: 'd'}\n"
        )
        with pytest.raises(ValueError, match="must not be empty"):
            software_lib.load_definition(path)

    def test_try_load_returns_error_string(self, tmp_path):
        path = tmp_path / "software.yaml"
        path.write_text("not: a software definition\n")
        defn, err = software_lib.try_load_definition(path)
        assert defn is None
        assert err is not None
        assert "Invalid Software definition" in err
        assert "pydantic" not in err.lower()

    def test_scan_inventory_includes_definition_valid(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        pkg = tmp_path / "automation" / "software" / "Acme.Widget.1.0.0"
        pkg.mkdir(parents=True)
        (pkg / "software.yaml").write_text(_VALID_WINDOWS)
        items = software_lib.scan_inventory()
        assert len(items) == 1
        assert items[0]["definition_valid"] is True
        assert items[0]["architecture"] == "x64"
        assert items[0]["definition_error"] == ""

        (pkg / "software.yaml").write_text("hatchery: {}\n")
        items = software_lib.scan_inventory()
        assert items[0]["definition_valid"] is False
        assert "Invalid Software definition" in items[0]["definition_error"]

    def test_rejects_empty_platforms_and_empty_command(self, tmp_path):
        path = tmp_path / "software.yaml"
        path.write_text(
            "hatchery:\n"
            "  kind: software\n"
            "  publisher: Acme\n"
            "  product: Widget\n"
            "  version: '1.0.0'\n"
            "platforms: {}\n"
        )
        with pytest.raises(ValueError, match="at least one OS"):
            software_lib.load_definition(path)

        path.write_text(
            "hatchery:\n"
            "  kind: software\n"
            "  publisher: Acme\n"
            "  product: Widget\n"
            "  version: '1.0.0'\n"
            "platforms:\n"
            "  windows:\n"
            "    x64:\n"
            "      install:\n"
            "        command: '  '\n"
            "      uninstall:\n"
            "        command: 'u'\n"
            "      detect:\n"
            "        command: 'd'\n"
        )
        with pytest.raises(ValueError, match="must not be empty"):
            software_lib.load_definition(path)

    def test_load_rejects_empty_and_non_mapping_yaml(self, tmp_path):
        path = tmp_path / "software.yaml"
        path.write_text("")
        with pytest.raises(ValueError, match="empty"):
            software_lib.load_definition(path)
        path.write_text("- just a list\n")
        with pytest.raises(ValueError, match="mapping"):
            software_lib.load_definition(path)
        missing = tmp_path / "missing.yaml"
        with pytest.raises(ValueError, match="Cannot read"):
            software_lib.load_definition(missing)

    def test_display_subtitle_fallbacks(self):
        assert software_lib.display_subtitle(
            {"publisher": "A", "product": "B", "version": "1"}
        ) == ("A · B 1")
        assert (
            software_lib.display_subtitle({"publisher": "A", "product": "", "version": ""}) == "A"
        )
        assert (
            software_lib.display_subtitle({"publisher": "", "product": "", "version": "9"}) == "9"
        )
        assert software_lib.display_subtitle({}) == "Software"

    def test_scan_empty_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "data_dir", lambda: tmp_path)
        assert software_lib.scan_inventory() == []
