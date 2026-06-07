import subprocess
from unittest.mock import MagicMock, patch

import pytest

from lib.clutch import VMConfig
from lib.providers.libvirt import LibvirtProvider


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def provider(tmp_path):
    media = tmp_path / "media"
    automation = tmp_path / "automation"
    media.mkdir()
    automation.mkdir()
    return LibvirtProvider(media_dir=media, automation_dir=automation)


# ── create_vm ─────────────────────────────────────────────────────────────────


class TestCreateVM:
    def test_calls_virt_install(self, tmp_path, provider):
        iso = provider.media_dir / "win11.iso"
        iso.touch()
        vm = VMConfig(
            name="test-vm", os="win11", vcpus=2, ram_gb=4, disk_gb=40, os_media="win11.iso"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            provider.create_vm(vm)
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "virt-install"
        assert "--name" in cmd
        assert "test-vm" in cmd

    def test_sets_memory_from_ram_gb(self, tmp_path, provider):
        iso = provider.media_dir / "win11.iso"
        iso.touch()
        vm = VMConfig(
            name="test-vm", os="win11", vcpus=2, ram_gb=8, disk_gb=40, os_media="win11.iso"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            provider.create_vm(vm)
        cmd = mock_run.call_args[0][0]
        idx = cmd.index("--memory")
        assert cmd[idx + 1] == "8192"

    def test_win11_adds_uefi_and_tpm(self, tmp_path, provider):
        iso = provider.media_dir / "win11.iso"
        iso.touch()
        vm = VMConfig(
            name="test-vm", os="win11", vcpus=2, ram_gb=4, disk_gb=40, os_media="win11.iso"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            provider.create_vm(vm)
        cmd = mock_run.call_args[0][0]
        assert "--boot" in cmd
        assert "uefi" in cmd
        assert "--tpm" in cmd

    def test_win10_no_uefi(self, tmp_path, provider):
        iso = provider.media_dir / "win10.iso"
        iso.touch()
        vm = VMConfig(
            name="test-vm", os="win10", vcpus=2, ram_gb=4, disk_gb=40, os_media="win10.iso"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            provider.create_vm(vm)
        cmd = mock_run.call_args[0][0]
        assert "--boot" not in cmd
        assert "--tpm" not in cmd

    def test_server2025_adds_uefi_and_tpm(self, tmp_path, provider):
        iso = provider.media_dir / "server2025.iso"
        iso.touch()
        vm = VMConfig(
            name="srv", os="server2025", vcpus=2, ram_gb=4, disk_gb=60, os_media="server2025.iso"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            provider.create_vm(vm)
        cmd = mock_run.call_args[0][0]
        assert "--boot" in cmd
        assert "--tpm" in cmd

    def test_virtio_adds_cdrom(self, tmp_path, provider):
        iso = provider.media_dir / "win11.iso"
        virtio = provider.media_dir / "virtio-win.iso"
        iso.touch()
        virtio.touch()
        vm = VMConfig(
            name="test-vm",
            os="win11",
            vcpus=2,
            ram_gb=4,
            disk_gb=40,
            os_media="win11.iso",
            virtio_drivers="virtio-win.iso",
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            provider.create_vm(vm)
        cmd = mock_run.call_args[0][0]
        assert any("virtio-win.iso" in arg and "cdrom" in arg for arg in cmd)

    def test_os_config_creates_floppy(self, tmp_path, provider):
        iso = provider.media_dir / "win11.iso"
        iso.touch()
        answer = provider.automation_dir / "win11.xml"
        answer.write_text("<Autounattend/>")
        img_path = tmp_path / "fake.img"
        img_path.touch()
        vm = VMConfig(
            name="test-vm",
            os="win11",
            vcpus=2,
            ram_gb=4,
            disk_gb=40,
            os_media="win11.iso",
            os_config="win11.xml",
        )
        with patch.object(provider, "_create_answer_image", return_value=img_path) as mock_img:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                provider.create_vm(vm)
        mock_img.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert any("floppy" in arg for arg in cmd)

    def test_floppy_cleaned_up_on_success(self, tmp_path, provider):
        iso = provider.media_dir / "win11.iso"
        iso.touch()
        answer = provider.automation_dir / "win11.xml"
        answer.write_text("<Autounattend/>")
        img_path = tmp_path / "fake.img"
        img_path.touch()
        vm = VMConfig(
            name="test-vm",
            os="win11",
            vcpus=2,
            ram_gb=4,
            disk_gb=40,
            os_media="win11.iso",
            os_config="win11.xml",
        )
        with patch.object(provider, "_create_answer_image", return_value=img_path):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                provider.create_vm(vm)
        assert not img_path.exists()

    def test_floppy_cleaned_up_on_failure(self, tmp_path, provider):
        iso = provider.media_dir / "win11.iso"
        iso.touch()
        answer = provider.automation_dir / "win11.xml"
        answer.write_text("<Autounattend/>")
        img_path = tmp_path / "fake.img"
        img_path.touch()
        vm = VMConfig(
            name="test-vm",
            os="win11",
            vcpus=2,
            ram_gb=4,
            disk_gb=40,
            os_media="win11.iso",
            os_config="win11.xml",
        )
        with patch.object(provider, "_create_answer_image", return_value=img_path):
            with patch(
                "subprocess.run", side_effect=subprocess.CalledProcessError(1, "virt-install")
            ):
                with pytest.raises(subprocess.CalledProcessError):
                    provider.create_vm(vm)
        assert not img_path.exists()

    def test_missing_egg_raises(self, tmp_path, provider):
        vm = VMConfig(
            name="test-vm", os="win11", vcpus=2, ram_gb=4, disk_gb=40, os_media="missing.iso"
        )
        with pytest.raises(FileNotFoundError, match="missing.iso"):
            provider.create_vm(vm)

    def test_missing_automation_raises(self, tmp_path, provider):
        iso = provider.media_dir / "win11.iso"
        iso.touch()
        vm = VMConfig(
            name="test-vm",
            os="win11",
            vcpus=2,
            ram_gb=4,
            disk_gb=40,
            os_media="win11.iso",
            os_config="missing.xml",
        )
        with pytest.raises(FileNotFoundError, match="missing.xml"):
            provider.create_vm(vm)


# ── Power state ───────────────────────────────────────────────────────────────


class TestPowerState:
    def test_start_vm(self, provider):
        with patch("subprocess.run") as mock_run:
            provider.start_vm("myvm")
        mock_run.assert_called_once_with(["virsh", "start", "myvm"], check=True)

    def test_stop_vm(self, provider):
        with patch("subprocess.run") as mock_run:
            provider.stop_vm("myvm")
        mock_run.assert_called_once_with(["virsh", "shutdown", "myvm"], check=True)

    def test_force_stop_vm(self, provider):
        with patch("subprocess.run") as mock_run:
            provider.force_stop_vm("myvm")
        mock_run.assert_called_once_with(["virsh", "destroy", "myvm"], check=True)

    def test_destroy_vm(self, provider):
        with patch("subprocess.run") as mock_run:
            provider.destroy_vm("myvm")
        mock_run.assert_called_once_with(
            ["virsh", "undefine", "myvm", "--remove-all-storage"], check=True
        )


# ── Inventory ─────────────────────────────────────────────────────────────────


class TestInventory:
    def test_list_vms_returns_names_and_status(self, provider):
        list_result = MagicMock(stdout="vm1\nvm2\n")
        status_result = MagicMock(stdout="running\n")
        with patch("subprocess.run", side_effect=[list_result, status_result, status_result]):
            vms = provider.list_vms()
        assert len(vms) == 2
        assert vms[0]["name"] == "vm1"
        assert vms[0]["status"] == "running"

    def test_list_vms_empty(self, provider):
        result = MagicMock(stdout="\n")
        with patch("subprocess.run", return_value=result):
            vms = provider.list_vms()
        assert vms == []

    def test_get_status(self, provider):
        result = MagicMock(stdout="shut off\n")
        with patch("subprocess.run", return_value=result):
            status = provider.get_status("myvm")
        assert status == "shut off"


# ── Snapshots ─────────────────────────────────────────────────────────────────


class TestSnapshots:
    def test_create_snapshot(self, provider):
        with patch("subprocess.run") as mock_run:
            provider.create_snapshot("myvm", "snap1")
        mock_run.assert_called_once_with(
            ["virsh", "snapshot-create-as", "myvm", "--name", "snap1"], check=True
        )

    def test_list_snapshots(self, provider):
        result = MagicMock(stdout="snap1\nsnap2\n")
        with patch("subprocess.run", return_value=result):
            snaps = provider.list_snapshots("myvm")
        assert snaps == ["snap1", "snap2"]

    def test_list_snapshots_empty(self, provider):
        result = MagicMock(stdout="\n")
        with patch("subprocess.run", return_value=result):
            snaps = provider.list_snapshots("myvm")
        assert snaps == []

    def test_revert_snapshot(self, provider):
        with patch("subprocess.run") as mock_run:
            provider.revert_snapshot("myvm", "snap1")
        mock_run.assert_called_once_with(["virsh", "snapshot-revert", "myvm", "snap1"], check=True)

    def test_delete_snapshot(self, provider):
        with patch("subprocess.run") as mock_run:
            provider.delete_snapshot("myvm", "snap1")
        mock_run.assert_called_once_with(["virsh", "snapshot-delete", "myvm", "snap1"], check=True)


# ── Path resolution ───────────────────────────────────────────────────────────


class TestPathResolution:
    def test_resolve_media_relative(self, provider):
        f = provider.media_dir / "test.iso"
        f.touch()
        assert provider._resolve_media("test.iso") == f

    def test_resolve_media_absolute(self, tmp_path, provider):
        f = tmp_path / "elsewhere.iso"
        f.touch()
        assert provider._resolve_media(str(f)) == f

    def test_resolve_media_missing_relative_raises(self, provider):
        with pytest.raises(FileNotFoundError, match="media directory"):
            provider._resolve_media("nope.iso")

    def test_resolve_media_missing_absolute_raises(self, tmp_path, provider):
        with pytest.raises(FileNotFoundError):
            provider._resolve_media(str(tmp_path / "nope.iso"))

    def test_resolve_automation_relative(self, provider):
        f = provider.automation_dir / "answer.xml"
        f.touch()
        assert provider._resolve_automation("answer.xml") == f

    def test_resolve_automation_absolute(self, tmp_path, provider):
        f = tmp_path / "answer.xml"
        f.touch()
        assert provider._resolve_automation(str(f)) == f

    def test_resolve_automation_missing_raises(self, provider):
        with pytest.raises(FileNotFoundError, match="Automation pane"):
            provider._resolve_automation("missing.xml")

    def test_resolve_automation_absolute_missing_raises(self, tmp_path, provider):
        with pytest.raises(FileNotFoundError, match="Automation file not found"):
            provider._resolve_automation(str(tmp_path / "nope.xml"))
