import textwrap

import pytest

import lib.clutch as clutch
from lib.clutch import Clutch, GuestOS, VMConfig


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
        assert vm.automations == ["install-chocolatey.ps1", "install-dev-tools.ps1"]
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
