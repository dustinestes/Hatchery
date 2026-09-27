from lib import answerfile
from lib.clutch import GuestOS


class TestRenderWin10:
    def test_returns_string(self):
        result = answerfile.render(GuestOS.WIN10, "myvm", "admin", "pass1")
        assert isinstance(result, str)

    def test_contains_computer_name(self):
        xml = answerfile.render(GuestOS.WIN10, "devbox", "admin", "pass1")
        assert "<ComputerName>devbox</ComputerName>" in xml

    def test_contains_admin_username(self):
        xml = answerfile.render(GuestOS.WIN10, "vm", "alice", "secret")
        assert "alice" in xml

    def test_contains_admin_password(self):
        xml = answerfile.render(GuestOS.WIN10, "vm", "admin", "MyP@ss!")
        assert "MyP@ss!" in xml

    def test_bios_single_partition(self):
        xml = answerfile.render(GuestOS.WIN10, "vm", "admin", "pass")
        assert "<PartitionID>1</PartitionID>" in xml
        assert "<Active>true</Active>" in xml

    def test_no_edition_selection(self):
        xml = answerfile.render(GuestOS.WIN10, "vm", "admin", "pass")
        assert "SERVERSTANDARD" not in xml
        assert "InstallFrom" not in xml

    def test_single_firstlogon_command(self):
        xml = answerfile.render(GuestOS.WIN10, "vm", "admin", "pass")
        assert xml.count("<SynchronousCommand") == 1
        assert "hatchery-setup.ps1" in xml

    def test_name_truncated_to_15_chars(self):
        xml = answerfile.render(GuestOS.WIN10, "a" * 20, "admin", "pass")
        assert f"<ComputerName>{'a' * 15}</ComputerName>" in xml

    def test_name_exactly_15_not_truncated(self):
        xml = answerfile.render(GuestOS.WIN10, "a" * 15, "admin", "pass")
        assert f"<ComputerName>{'a' * 15}</ComputerName>" in xml

    def test_password_xml_escaped(self):
        xml = answerfile.render(GuestOS.WIN10, "vm", "admin", 'p<a>ss&"end')
        assert 'p<a>ss&"end' not in xml
        assert "p&lt;a&gt;ss&amp;" in xml

    def test_username_xml_escaped(self):
        xml = answerfile.render(GuestOS.WIN10, "vm", "us<er>", "pass")
        assert "us<er>" not in xml
        assert "us&lt;er&gt;" in xml

    def test_is_valid_xml(self):
        import xml.etree.ElementTree as ET

        xml = answerfile.render(GuestOS.WIN10, "vm", "admin", "pass")
        ET.fromstring(xml)  # raises if invalid


class TestRenderWin11:
    def test_uefi_gpt_partitions(self):
        xml = answerfile.render(GuestOS.WIN11, "vm", "admin", "pass")
        assert "EFI" in xml
        assert "MSR" in xml

    def test_install_to_partition_3(self):
        xml = answerfile.render(GuestOS.WIN11, "vm", "admin", "pass")
        assert "<PartitionID>3</PartitionID>" in xml

    def test_no_edition_selection(self):
        xml = answerfile.render(GuestOS.WIN11, "vm", "admin", "pass")
        assert "SERVERSTANDARD" not in xml

    def test_single_firstlogon_command(self):
        xml = answerfile.render(GuestOS.WIN11, "vm", "admin", "pass")
        assert xml.count("<SynchronousCommand") == 1
        assert "hatchery-setup.ps1" in xml

    def test_is_valid_xml(self):
        import xml.etree.ElementTree as ET

        xml = answerfile.render(GuestOS.WIN11, "vm", "admin", "pass")
        ET.fromstring(xml)


class TestRenderServer2022:
    def test_edition_selection_present(self):
        xml = answerfile.render(GuestOS.SERVER2022, "vm", "admin", "pass")
        assert "Windows Server 2022 SERVERSTANDARD" in xml

    def test_bios_single_partition(self):
        xml = answerfile.render(GuestOS.SERVER2022, "vm", "admin", "pass")
        assert "<Active>true</Active>" in xml

    def test_install_to_partition_1(self):
        xml = answerfile.render(GuestOS.SERVER2022, "vm", "admin", "pass")
        assert "<PartitionID>1</PartitionID>" in xml

    def test_single_firstlogon_command(self):
        xml = answerfile.render(GuestOS.SERVER2022, "vm", "admin", "pass")
        assert xml.count("<SynchronousCommand") == 1
        assert "hatchery-setup.ps1" in xml

    def test_is_valid_xml(self):
        import xml.etree.ElementTree as ET

        xml = answerfile.render(GuestOS.SERVER2022, "vm", "admin", "pass")
        ET.fromstring(xml)


class TestRenderServer2025:
    def test_edition_selection_present(self):
        xml = answerfile.render(GuestOS.SERVER2025, "vm", "admin", "pass")
        assert "Windows Server 2025 SERVERSTANDARD" in xml

    def test_uefi_gpt_partitions(self):
        xml = answerfile.render(GuestOS.SERVER2025, "vm", "admin", "pass")
        assert "EFI" in xml
        assert "MSR" in xml

    def test_install_to_partition_3(self):
        xml = answerfile.render(GuestOS.SERVER2025, "vm", "admin", "pass")
        assert "<PartitionID>3</PartitionID>" in xml

    def test_single_firstlogon_command(self):
        xml = answerfile.render(GuestOS.SERVER2025, "vm", "admin", "pass")
        assert xml.count("<SynchronousCommand") == 1
        assert "hatchery-setup.ps1" in xml

    def test_is_valid_xml(self):
        import xml.etree.ElementTree as ET

        xml = answerfile.render(GuestOS.SERVER2025, "vm", "admin", "pass")
        ET.fromstring(xml)


class TestRenderSetupScript:
    def test_returns_string(self):
        assert isinstance(answerfile.render_setup_script(), str)

    def test_contains_all_setup_steps(self):
        script = answerfile.render_setup_script()
        assert "Enable-PSRemoting" in script
        assert "LocalAccountTokenFilterPolicy" in script
        assert "5985" in script
        assert "OpenSSH.Server" in script
        assert "hatchery-ready" in script

    def test_contains_window_title(self):
        assert "Hatchery - First Boot Setup" in answerfile.render_setup_script()

    def test_log_uses_hatch_event_format(self):
        script = answerfile.render_setup_script()
        assert "[HATCH:" in script
        assert 'Write-Log "INFO"' in script
        assert 'Write-Log "ERROR"' in script

    def test_log_path_is_hatchery_dir(self):
        script = answerfile.render_setup_script()
        assert r"C:\Program Files\Hatchery" in script
        assert r"hatchery-setup.log" in script

    def test_script_name_constant(self):
        assert answerfile.SETUP_SCRIPT_NAME == "hatchery-setup.ps1"


_SAMPLE_FRONTMATTER = """\
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
<body>{{ input_locale }}</body>
"""


class TestParseFrontmatter:
    def test_parses_hatchery_block(self):
        hatchery, body = answerfile.parse_frontmatter(_SAMPLE_FRONTMATTER)
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
        params = answerfile.declared_parameters(_SAMPLE_FRONTMATTER)
        names = [p["name"] for p in params]
        assert names == ["input_locale", "system_locale"]

    def test_filters_reserved_system_tokens(self):
        params = answerfile.declared_parameters(_SAMPLE_FRONTMATTER)
        names = {p["name"] for p in params}
        assert names.isdisjoint(answerfile.RESERVED_SYSTEM_TOKENS)

    def test_shape_matches_script_params(self):
        params = answerfile.declared_parameters(_SAMPLE_FRONTMATTER)
        p = params[0]
        assert p["name"] == "input_locale"
        assert p["type"] == "String"
        assert p["mandatory"] is False
        assert p["default"] == "en-US"
        assert p["help"] == "Input locale"
        assert p["label"] == "Input locale"

    def test_mandatory_true_when_set(self):
        params = answerfile.declared_parameters(_SAMPLE_FRONTMATTER)
        by_name = {p["name"]: p for p in params}
        assert by_name["system_locale"]["mandatory"] is True

    def test_no_frontmatter_returns_empty(self):
        assert answerfile.declared_parameters("<unattend/>") == []

    def test_malformed_returns_empty(self):
        assert answerfile.declared_parameters("---\nhatchery: [\nbad\n---\nx\n") == []

    def test_accepts_path(self, tmp_path):
        path = tmp_path / "win11.xml.j2"
        path.write_text(_SAMPLE_FRONTMATTER)
        params = answerfile.declared_parameters(path)
        assert [p["name"] for p in params] == ["input_locale", "system_locale"]

    def test_reserved_constant(self):
        assert answerfile.RESERVED_SYSTEM_TOKENS == frozenset(
            {"vm_name", "admin_username", "admin_password"}
        )
