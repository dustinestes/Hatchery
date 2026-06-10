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

    def test_winrm_quickconfig_present(self):
        xml = answerfile.render(GuestOS.WIN10, "vm", "admin", "pass")
        assert "winrm quickconfig" in xml

    def test_winrm_firewall_rule_present(self):
        xml = answerfile.render(GuestOS.WIN10, "vm", "admin", "pass")
        assert "5985" in xml

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

    def test_winrm_present(self):
        xml = answerfile.render(GuestOS.WIN11, "vm", "admin", "pass")
        assert "winrm quickconfig" in xml

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

    def test_winrm_present(self):
        xml = answerfile.render(GuestOS.SERVER2022, "vm", "admin", "pass")
        assert "winrm quickconfig" in xml

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

    def test_winrm_present(self):
        xml = answerfile.render(GuestOS.SERVER2025, "vm", "admin", "pass")
        assert "winrm quickconfig" in xml

    def test_is_valid_xml(self):
        import xml.etree.ElementTree as ET

        xml = answerfile.render(GuestOS.SERVER2025, "vm", "admin", "pass")
        ET.fromstring(xml)
