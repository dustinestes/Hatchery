import textwrap

import pytest

import lib.clutch as clutch
from lib.clutch import AutomationScript, Clutch, GuestOS, VMConfig


# ── Fixtures ──────────────────────────────────────────────────────────────────


def write_clutch(tmp_path, content: str):
    """Write a YAML string to a temp file and return its path."""
    p = tmp_path / "test.yaml"
    p.write_text(textwrap.dedent(content))
    return p


MINIMAL_VM = """\
    name: test-lab
    vms:
      - name: vm1
        os: win11
        vcpus: 2
        ram_gb: 4
        disk_gb: 40
        os_media: win11.iso
"""

FULL_VM = """\
    name: full-lab
    description: Full example
    vms:
      - name: vm1
        os: win11
        vcpus: 4
        ram_gb: 8
        disk_gb: 80
        os_media: Win11_24H2.iso
        virtio_drivers: virtio-win.iso
        os_config: win11-unattend.xml.j2
        automations:
          - install-chocolatey.ps1
          - install-dev-tools.ps1
        depends_on: []
"""


# ── Valid Clutch files ────────────────────────────────────────────────────────


class TestValidSingleVM:
    def test_loads_successfully(self, tmp_path):
        result = clutch.load(write_clutch(tmp_path, MINIMAL_VM))
        assert isinstance(result, Clutch)

    def test_clutch_name(self, tmp_path):
        result = clutch.load(write_clutch(tmp_path, MINIMAL_VM))
        assert result.name == "test-lab"

    def test_vm_fields(self, tmp_path):
        result = clutch.load(write_clutch(tmp_path, MINIMAL_VM))
        vm = result.vms[0]
        assert vm.name == "vm1"
        assert vm.os == GuestOS.WIN11
        assert vm.vcpus == 2
        assert vm.ram_gb == 4
        assert vm.disk_gb == 40
        assert vm.os_media == "win11.iso"

    def test_optional_fields_default(self, tmp_path):
        result = clutch.load(write_clutch(tmp_path, MINIMAL_VM))
        vm = result.vms[0]
        assert vm.virtio_drivers is None
        assert vm.os_config is None
        assert vm.automations == []
        assert vm.depends_on == []

    def test_full_vm_loads(self, tmp_path):
        result = clutch.load(write_clutch(tmp_path, FULL_VM))
        vm = result.vms[0]
        assert vm.virtio_drivers == "virtio-win.iso"
        assert vm.os_config == "win11-unattend.xml.j2"
        assert [s.name for s in vm.automations] == [
            "install-chocolatey.ps1",
            "install-dev-tools.ps1",
        ]
        assert all(not s.reboot_after for s in vm.automations)
        assert result.description == "Full example"

    def test_all_os_types_accepted(self, tmp_path):
        for os_val in ("win10", "win11", "server2022", "server2025"):
            content = MINIMAL_VM.replace("os: win11", f"os: {os_val}")
            result = clutch.load(write_clutch(tmp_path, content))
            assert result.vms[0].os == GuestOS(os_val)


class TestValidMultiVM:
    MULTI = """\
        name: ad-lab
        vms:
          - name: dc01
            os: server2022
            vcpus: 2
            ram_gb: 4
            disk_gb: 60
            os_media: server2022.iso
          - name: client01
            os: win11
            vcpus: 4
            ram_gb: 8
            disk_gb: 80
            os_media: win11.iso
            depends_on:
              - dc01
    """

    def test_loads_two_vms(self, tmp_path):
        result = clutch.load(write_clutch(tmp_path, self.MULTI))
        assert len(result.vms) == 2

    def test_depends_on_resolved(self, tmp_path):
        result = clutch.load(write_clutch(tmp_path, self.MULTI))
        assert result.vms[1].depends_on == ["dc01"]


# ── Validation errors ─────────────────────────────────────────────────────────


class TestMissingRequiredFields:
    def test_missing_name(self, tmp_path):
        content = MINIMAL_VM.replace("name: test-lab\n", "")
        with pytest.raises(ValueError, match="name"):
            clutch.load(write_clutch(tmp_path, content))

    def test_missing_os(self, tmp_path):
        content = MINIMAL_VM.replace("        os: win11\n", "")
        with pytest.raises(ValueError, match="os"):
            clutch.load(write_clutch(tmp_path, content))

    def test_missing_os_media(self, tmp_path):
        content = MINIMAL_VM.replace("        os_media: win11.iso\n", "")
        with pytest.raises(ValueError, match="os_media"):
            clutch.load(write_clutch(tmp_path, content))

    def test_missing_vcpus(self, tmp_path):
        content = MINIMAL_VM.replace("        vcpus: 2\n", "")
        with pytest.raises(ValueError, match="vcpus"):
            clutch.load(write_clutch(tmp_path, content))


class TestInvalidFieldValues:
    def test_unknown_os_type(self, tmp_path):
        content = MINIMAL_VM.replace("os: win11", "os: windows-xp")
        with pytest.raises(ValueError, match="os"):
            clutch.load(write_clutch(tmp_path, content))

    def test_vcpus_zero(self, tmp_path):
        content = MINIMAL_VM.replace("vcpus: 2", "vcpus: 0")
        with pytest.raises(ValueError, match="vcpus"):
            clutch.load(write_clutch(tmp_path, content))

    def test_ram_gb_zero(self, tmp_path):
        content = MINIMAL_VM.replace("ram_gb: 4", "ram_gb: 0")
        with pytest.raises(ValueError, match="ram_gb"):
            clutch.load(write_clutch(tmp_path, content))

    def test_disk_gb_zero(self, tmp_path):
        content = MINIMAL_VM.replace("disk_gb: 40", "disk_gb: 0")
        with pytest.raises(ValueError, match="disk_gb"):
            clutch.load(write_clutch(tmp_path, content))


class TestCrossVMValidation:
    def test_empty_vms_list(self, tmp_path):
        content = "name: empty-lab\nvms: []\n"
        with pytest.raises(ValueError, match="at least one VM"):
            clutch.load(write_clutch(tmp_path, content))

    def test_duplicate_vm_names(self, tmp_path):
        content = (
            MINIMAL_VM
            + "      - name: vm1\n        os: win10\n        vcpus: 1\n        ram_gb: 2\n        disk_gb: 20\n        os_media: win10.iso\n"
        )  # noqa: E501
        with pytest.raises(ValueError, match="duplicate"):
            clutch.load(write_clutch(tmp_path, content))

    def test_depends_on_unknown_vm(self, tmp_path):
        content = MINIMAL_VM.replace("depends_on: []", "").replace(
            "os_media: win11.iso",
            "os_media: win11.iso\n        depends_on:\n          - nonexistent",
        )
        with pytest.raises(ValueError, match="unknown VM"):
            clutch.load(write_clutch(tmp_path, content))

    def test_depends_on_self(self, tmp_path):
        content = MINIMAL_VM.replace(
            "os_media: win11.iso", "os_media: win11.iso\n        depends_on:\n          - vm1"
        )
        with pytest.raises(ValueError, match="cannot depend on itself"):
            clutch.load(write_clutch(tmp_path, content))

    def test_direct_cycle_rejected(self, tmp_path):
        content = textwrap.dedent("""\
            name: cycle-lab
            vms:
              - name: vm-a
                os: win11
                vcpus: 2
                ram_gb: 4
                disk_gb: 40
                os_media: win11.iso
                depends_on: [vm-b]
              - name: vm-b
                os: win11
                vcpus: 2
                ram_gb: 4
                disk_gb: 40
                os_media: win11.iso
                depends_on: [vm-a]
        """)
        with pytest.raises(ValueError, match="Circular dependency"):
            clutch.load(write_clutch(tmp_path, content))

    def test_three_node_cycle_rejected(self, tmp_path):
        content = textwrap.dedent("""\
            name: three-cycle
            vms:
              - name: vm-a
                os: win11
                vcpus: 2
                ram_gb: 4
                disk_gb: 40
                os_media: win11.iso
                depends_on: [vm-b]
              - name: vm-b
                os: win11
                vcpus: 2
                ram_gb: 4
                disk_gb: 40
                os_media: win11.iso
                depends_on: [vm-c]
              - name: vm-c
                os: win11
                vcpus: 2
                ram_gb: 4
                disk_gb: 40
                os_media: win11.iso
                depends_on: [vm-a]
        """)
        with pytest.raises(ValueError, match="Circular dependency"):
            clutch.load(write_clutch(tmp_path, content))

    def test_cycle_error_includes_node_names(self, tmp_path):
        content = textwrap.dedent("""\
            name: cycle-lab
            vms:
              - name: dc01
                os: win11
                vcpus: 2
                ram_gb: 4
                disk_gb: 40
                os_media: win11.iso
                depends_on: [client01]
              - name: client01
                os: win11
                vcpus: 2
                ram_gb: 4
                disk_gb: 40
                os_media: win11.iso
                depends_on: [dc01]
        """)
        with pytest.raises(ValueError, match="dc01") as exc_info:
            clutch.load(write_clutch(tmp_path, content))
        assert "client01" in str(exc_info.value)

    def test_valid_chain_not_rejected(self, tmp_path):
        content = textwrap.dedent("""\
            name: chain-lab
            vms:
              - name: vm-a
                os: win11
                vcpus: 2
                ram_gb: 4
                disk_gb: 40
                os_media: win11.iso
              - name: vm-b
                os: win11
                vcpus: 2
                ram_gb: 4
                disk_gb: 40
                os_media: win11.iso
                depends_on: [vm-a]
              - name: vm-c
                os: win11
                vcpus: 2
                ram_gb: 4
                disk_gb: 40
                os_media: win11.iso
                depends_on: [vm-b]
        """)
        result = clutch.load(write_clutch(tmp_path, content))
        assert len(result.vms) == 3


class TestLoadRaw:
    CIRCULAR = textwrap.dedent("""\
        name: cycle-lab
        vms:
          - name: vm-a
            os: win11
            vcpus: 2
            ram_gb: 4
            disk_gb: 40
            os_media: win11.iso
            depends_on: [vm-b]
          - name: vm-b
            os: win11
            vcpus: 2
            ram_gb: 4
            disk_gb: 40
            os_media: win11.iso
            depends_on: [vm-a]
    """)

    def test_returns_vms_despite_cycle(self, tmp_path):
        result = clutch.load_raw(write_clutch(tmp_path, self.CIRCULAR))
        assert len(result["vms"]) == 2

    def test_preserves_depends_on(self, tmp_path):
        result = clutch.load_raw(write_clutch(tmp_path, self.CIRCULAR))
        vm_a = next(v for v in result["vms"] if v["name"] == "vm-a")
        assert vm_a["depends_on"] == ["vm-b"]

    def test_preserves_clutch_name(self, tmp_path):
        result = clutch.load_raw(write_clutch(tmp_path, self.CIRCULAR))
        assert result["name"] == "cycle-lab"

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            clutch.load_raw(tmp_path / "missing.yaml")

    def test_valid_clutch_also_works(self, tmp_path):
        result = clutch.load_raw(write_clutch(tmp_path, MINIMAL_VM))
        assert result["name"] == "test-lab"
        assert len(result["vms"]) == 1


class TestFileErrors:
    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="not found"):
            clutch.load(tmp_path / "missing.yaml")

    def test_malformed_yaml(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("name: test\nvms:\n  - [invalid: yaml: here")
        with pytest.raises(ValueError, match="Invalid YAML"):
            clutch.load(p)

    def test_non_mapping_yaml(self, tmp_path):
        p = tmp_path / "list.yaml"
        p.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            clutch.load(p)


# ── Model unit tests ──────────────────────────────────────────────────────────


class TestVMConfigModel:
    def test_valid_construction(self):
        vm = VMConfig(name="vm1", os="win11", vcpus=2, ram_gb=4, disk_gb=40, os_media="win11.iso")
        assert vm.os == GuestOS.WIN11

    def test_negative_vcpus_rejected(self):
        with pytest.raises(Exception):
            VMConfig(name="vm1", os="win11", vcpus=-1, ram_gb=4, disk_gb=40, os_media="win11.iso")


# ── Export ────────────────────────────────────────────────────────────────────


def make_clutch(name="my-lab"):
    vm = VMConfig(name="vm1", os="win11", vcpus=2, ram_gb=4, disk_gb=40, os_media="win11.iso")
    return clutch.Clutch(name=name, vms=[vm])


class TestExport:
    def test_creates_file(self, tmp_path):
        c = make_clutch()
        path = clutch.export(c, "my-lab", tmp_path)
        assert path.exists()

    def test_adds_yaml_extension(self, tmp_path):
        c = make_clutch()
        path = clutch.export(c, "my-lab", tmp_path)
        assert path.name == "my-lab.yaml"

    def test_preserves_existing_yaml_extension(self, tmp_path):
        c = make_clutch()
        path = clutch.export(c, "my-lab.yaml", tmp_path)
        assert path.name == "my-lab.yaml"

    def test_raises_if_file_exists(self, tmp_path):
        c = make_clutch()
        clutch.export(c, "my-lab", tmp_path)
        with pytest.raises(FileExistsError, match="my-lab.yaml"):
            clutch.export(c, "my-lab", tmp_path)

    def test_written_file_is_valid_clutch(self, tmp_path):
        c = make_clutch()
        path = clutch.export(c, "exported", tmp_path)
        loaded = clutch.load(path)
        assert loaded.name == "my-lab"
        assert loaded.vms[0].name == "vm1"


class TestSave:
    def test_creates_file(self, tmp_path):
        c = make_clutch()
        path = clutch.save(c, tmp_path / "new.yaml")
        assert path.exists()

    def test_overwrites_existing_file(self, tmp_path):
        c = make_clutch()
        path = tmp_path / "existing.yaml"
        path.write_text("old content")
        clutch.save(c, path)
        loaded = clutch.load(path)
        assert loaded.name == "my-lab"

    def test_written_file_is_valid_clutch(self, tmp_path):
        c = make_clutch()
        path = clutch.save(c, tmp_path / "saved.yaml")
        loaded = clutch.load(path)
        assert loaded.vms[0].name == "vm1"


class TestAppendVM:
    def test_appends_vm(self, tmp_path):
        c = make_clutch()
        path = clutch.export(c, "lab", tmp_path)
        vm2 = VMConfig(name="vm2", os="win10", vcpus=1, ram_gb=2, disk_gb=20, os_media="win10.iso")
        updated = clutch.append_vm(vm2, path)
        assert len(updated.vms) == 2
        assert updated.vms[1].name == "vm2"

    def test_persists_appended_vm(self, tmp_path):
        c = make_clutch()
        path = clutch.export(c, "lab", tmp_path)
        vm2 = VMConfig(name="vm2", os="win10", vcpus=1, ram_gb=2, disk_gb=20, os_media="win10.iso")
        clutch.append_vm(vm2, path)
        loaded = clutch.load(path)
        assert len(loaded.vms) == 2

    def test_raises_on_duplicate_name(self, tmp_path):
        c = make_clutch()
        path = clutch.export(c, "lab", tmp_path)
        vm_dup = VMConfig(
            name="vm1", os="win10", vcpus=1, ram_gb=2, disk_gb=20, os_media="win10.iso"
        )
        with pytest.raises(ValueError, match="already exists"):
            clutch.append_vm(vm_dup, path)

    def test_raises_if_target_missing(self, tmp_path):
        vm = VMConfig(name="vm1", os="win10", vcpus=1, ram_gb=2, disk_gb=20, os_media="win10.iso")
        with pytest.raises(FileNotFoundError):
            clutch.append_vm(vm, tmp_path / "missing.yaml")


# ── AutomationScript ──────────────────────────────────────────────────────────


class TestAutomationScript:
    def test_coerce_from_string(self):
        s = AutomationScript.coerce("setup.ps1")
        assert s.name == "setup.ps1"
        assert s.reboot_after is False

    def test_coerce_from_dict(self):
        s = AutomationScript.coerce({"name": "setup.ps1", "reboot_after": True})
        assert s.name == "setup.ps1"
        assert s.reboot_after is True

    def test_reboot_after_defaults_false(self):
        s = AutomationScript(name="a.ps1")
        assert s.reboot_after is False

    def test_vmconfig_accepts_string_list(self):
        vm = VMConfig(
            name="dc01",
            os="win10",
            vcpus=1,
            ram_gb=2,
            disk_gb=20,
            os_media="win10.iso",
            automations=["a.ps1", "b.ps1"],
        )
        assert len(vm.automations) == 2
        assert all(isinstance(s, AutomationScript) for s in vm.automations)
        assert vm.automations[0].name == "a.ps1"

    def test_vmconfig_accepts_mixed_list(self):
        vm = VMConfig(
            name="dc01",
            os="win10",
            vcpus=1,
            ram_gb=2,
            disk_gb=20,
            os_media="win10.iso",
            automations=["a.ps1", {"name": "b.ps1", "reboot_after": True}],
        )
        assert vm.automations[0].reboot_after is False
        assert vm.automations[1].reboot_after is True

    def test_yaml_round_trip_plain_string(self, tmp_path):
        """Scripts with reboot_after=False are written as plain strings in YAML."""
        vm = VMConfig(
            name="dc01",
            os="win10",
            vcpus=1,
            ram_gb=2,
            disk_gb=20,
            os_media="win10.iso",
            automations=["setup.ps1"],
        )
        c = Clutch(name="lab", vms=[vm])
        path = tmp_path / "lab.yaml"
        clutch.save(c, path)
        raw = path.read_text()
        assert "- setup.ps1" in raw
        assert "reboot_after" not in raw

    def test_yaml_round_trip_reboot_after_true(self, tmp_path):
        """Scripts with reboot_after=True are written as a mapping in YAML."""
        vm = VMConfig(
            name="dc01",
            os="win10",
            vcpus=1,
            ram_gb=2,
            disk_gb=20,
            os_media="win10.iso",
            automations=[{"name": "setup.ps1", "reboot_after": True}],
        )
        c = Clutch(name="lab", vms=[vm])
        path = tmp_path / "lab.yaml"
        clutch.save(c, path)
        raw = path.read_text()
        assert "reboot_after: true" in raw

    def test_parallel_false_omitted_from_yaml(self, tmp_path):
        vm = VMConfig(
            name="dc01",
            os="win10",
            vcpus=1,
            ram_gb=2,
            disk_gb=20,
            os_media="win10.iso",
        )
        c = Clutch(name="lab", vms=[vm])
        path = tmp_path / "lab.yaml"
        clutch.save(c, path)
        assert "parallel" not in path.read_text()

    def test_load_backward_compat_string_automations(self, tmp_path):
        """Existing clutch files with plain string automations still load correctly."""
        content = textwrap.dedent("""
            name: lab
            vms:
              - name: dc01
                os: win10
                vcpus: 1
                ram_gb: 2
                disk_gb: 20
                os_media: win10.iso
                automations:
                  - setup.ps1
                  - configure.ps1
        """)
        result = clutch.load(write_clutch(tmp_path, content))
        assert [s.name for s in result.vms[0].automations] == ["setup.ps1", "configure.ps1"]
