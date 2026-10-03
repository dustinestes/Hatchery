import pytest

from lib import answerfile
from lib.clutch import GuestOS, VMConfig


_SAMPLE = """\
---
hatchery:
  kind: windows_unattend
  guest_os: [win11]
  companions:
    - hatchery-setup.ps1
  parameters:
    - name: input_locale
      label: Input locale
      default: en-US
    - name: vm_name
      label: Should be skipped
    - name: admin_username
    - name: admin_password
    - name: system_locale
      label: System locale
      default: en-US
      mandatory: true
    - label: Missing name skipped
      default: x
---
<body>{{ input_locale }} {{ vm_name }} {{ admin_username }}</body>
"""


class TestParseFrontmatter:
    def test_parses_hatchery_block(self):
        hatchery, body = answerfile.parse_frontmatter(_SAMPLE)
        assert hatchery is not None
        assert hatchery["kind"] == "windows_unattend"
        assert "companions" in hatchery
        assert body.startswith("<body>")

    def test_no_frontmatter_returns_none(self):
        text = "<unattend>{{ vm_name }}</unattend>"
        hatchery, body = answerfile.parse_frontmatter(text)
        assert hatchery is None
        assert body == text

    def test_malformed_yaml_returns_none(self):
        text = "---\nhatchery: [\nbad\n---\nbody\n"
        hatchery, body = answerfile.parse_frontmatter(text)
        assert hatchery is None
        assert body == text

    def test_missing_closing_delimiter_returns_none(self):
        text = "---\nhatchery:\n  kind: windows_unattend\nbody without close\n"
        hatchery, body = answerfile.parse_frontmatter(text)
        assert hatchery is None
        assert body == text

    def test_missing_hatchery_key_returns_none(self):
        text = "---\nother: true\n---\nbody\n"
        hatchery, body = answerfile.parse_frontmatter(text)
        assert hatchery is None
        assert body == text


class TestDeclaredParameters:
    def test_returns_user_params(self):
        params = answerfile.declared_parameters(_SAMPLE)
        names = [p["name"] for p in params]
        assert names == ["input_locale", "system_locale"]

    def test_filters_reserved_system_tokens(self):
        params = answerfile.declared_parameters(_SAMPLE)
        names = {p["name"] for p in params}
        assert names.isdisjoint(answerfile.RESERVED_SYSTEM_TOKENS)

    def test_shape_matches_script_params(self):
        params = answerfile.declared_parameters(_SAMPLE)
        p = params[0]
        assert p["name"] == "input_locale"
        assert p["type"] == "String"
        assert p["mandatory"] is False
        assert p["default"] == "en-US"
        assert p["help"] == "Input locale"
        assert p["label"] == "Input locale"

    def test_mandatory_true_when_set(self):
        params = answerfile.declared_parameters(_SAMPLE)
        by_name = {p["name"]: p for p in params}
        assert by_name["system_locale"]["mandatory"] is True

    def test_no_frontmatter_returns_empty(self):
        assert answerfile.declared_parameters("<unattend/>") == []

    def test_malformed_returns_empty(self):
        assert answerfile.declared_parameters("---\nhatchery: [\nbad\n---\nx\n") == []

    def test_accepts_path(self, tmp_path):
        path = tmp_path / "win11.xml.j2"
        path.write_text(_SAMPLE)
        params = answerfile.declared_parameters(path)
        assert [p["name"] for p in params] == ["input_locale", "system_locale"]

    def test_reserved_constant(self):
        assert answerfile.RESERVED_SYSTEM_TOKENS == frozenset(
            {"vm_name", "admin_username", "admin_password"}
        )


class TestRenderUserAnswerFile:
    def test_renders_system_and_user_tokens(self, tmp_path):
        path = tmp_path / "win11.xml.j2"
        path.write_text(_SAMPLE, encoding="utf-8")
        xml, companions = answerfile.render_user_answer_file(
            path,
            vm_name="devbox",
            admin_username="alice",
            admin_password="secret",
            user_params={"input_locale": "en-GB", "system_locale": "en-GB"},
        )
        assert "en-GB" in xml
        assert "devbox" in xml
        assert "alice" in xml
        assert companions == ["hatchery-setup.ps1"]

    def test_truncates_vm_name_to_15(self, tmp_path):
        path = tmp_path / "t.xml.j2"
        path.write_text("{{ vm_name }}", encoding="utf-8")
        xml, _ = answerfile.render_user_answer_file(path, vm_name="a" * 20)
        assert xml == "a" * 15

    def test_xml_escapes_special_chars(self, tmp_path):
        path = tmp_path / "t.xml.j2"
        path.write_text("<x>{{ admin_password }}</x>", encoding="utf-8")
        xml, _ = answerfile.render_user_answer_file(
            path, vm_name="vm", admin_password='p<a>ss&"end'
        )
        assert 'p<a>ss&"end' not in xml
        assert "p&lt;a&gt;ss&amp;" in xml

    def test_missing_jinja_var_raises(self, tmp_path):
        path = tmp_path / "t.xml.j2"
        path.write_text("{{ missing_token }}", encoding="utf-8")
        with pytest.raises(answerfile.AnswerFileError, match="missing_token"):
            answerfile.render_user_answer_file(path, vm_name="vm")

    def test_plain_file_no_frontmatter(self, tmp_path):
        path = tmp_path / "plain.xml"
        path.write_text("<unattend/>\n", encoding="utf-8")
        xml, companions = answerfile.render_user_answer_file(path, vm_name="vm")
        assert "<unattend/>" in xml
        assert companions == []


class TestValidateVmAnswerFile:
    def test_requires_answer_file_for_windows(self, tmp_path):
        vm = VMConfig(name="dc01", os="windows", vcpus=2, ram_gb=4, disk_gb=40, os_media="win11.iso")
        errors = answerfile.validate_vm_answer_file(vm, automation_dir=tmp_path)
        assert any("Answer File is required" in e for e in errors)

    def test_missing_file(self, tmp_path):
        vm = VMConfig(
            name="dc01",
            os="windows",
            vcpus=2,
            ram_gb=4,
            disk_gb=40,
            os_media="win11.iso",
            answer_file="missing.xml.j2",
        )
        errors = answerfile.validate_vm_answer_file(vm, automation_dir=tmp_path)
        assert any("not found" in e for e in errors)

    def test_missing_mandatory_param(self, tmp_path):
        path = tmp_path / "win11.xml.j2"
        path.write_text(
            "---\n"
            "hatchery:\n"
            "  parameters:\n"
            "    - name: region\n"
            "      mandatory: true\n"
            "---\n"
            "{{ region }}\n",
            encoding="utf-8",
        )
        vm = VMConfig(
            name="dc01",
            os="windows",
            vcpus=2,
            ram_gb=4,
            disk_gb=40,
            os_media="win11.iso",
            answer_file="win11.xml.j2",
        )
        errors = answerfile.validate_vm_answer_file(vm, automation_dir=tmp_path)
        assert any("parameter 'region' is required" in e for e in errors)

    def test_missing_companion(self, tmp_path):
        path = tmp_path / "win11.xml.j2"
        path.write_text(
            "---\nhatchery:\n  companions:\n    - hatchery-setup.ps1\n---\n<unattend/>\n",
            encoding="utf-8",
        )
        vm = VMConfig(
            name="dc01",
            os="windows",
            vcpus=2,
            ram_gb=4,
            disk_gb=40,
            os_media="win11.iso",
            answer_file="win11.xml.j2",
        )
        errors = answerfile.validate_vm_answer_file(vm, automation_dir=tmp_path)
        assert any("companion 'hatchery-setup.ps1'" in e for e in errors)

    def test_ok_when_complete(self, tmp_path):
        (tmp_path / "win11.xml.j2").write_text(_SAMPLE, encoding="utf-8")
        (tmp_path / "hatchery-setup.ps1").write_text("# setup\n", encoding="utf-8")
        vm = VMConfig(
            name="dc01",
            os="windows",
            vcpus=2,
            ram_gb=4,
            disk_gb=40,
            os_media="win11.iso",
            answer_file="win11.xml.j2",
            answer_file_parameters={"system_locale": "en-GB"},
        )
        assert answerfile.validate_vm_answer_file(vm, automation_dir=tmp_path) == []

    def test_requires_answer_file_helper(self):
        assert answerfile.requires_answer_file(GuestOS.WINDOWS) is True
        assert answerfile.requires_answer_file("win10") is True

    def test_needs_windows_hatch_fields_matches_answer_file_set(self):
        for os_val in answerfile.windows_hatch_os_values():
            assert answerfile.needs_windows_hatch_fields(os_val) is True
        assert answerfile.needs_windows_hatch_fields("linux") is False
        assert answerfile.windows_hatch_os_values() == ("windows",)


class TestCompanionNames:
    def test_rejects_path_separators(self):
        assert answerfile.companion_names({"companions": ["ok.ps1", "../x", "a/b"]}) == ["ok.ps1"]
