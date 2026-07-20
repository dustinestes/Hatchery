import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from lib.clutch import VMConfig
from lib.providers.libvirt import LibvirtProvider, _check_media_accessible, _qemu_user, _system_env


# ── _system_env ───────────────────────────────────────────────────────────────


class TestSystemEnv:
    def test_strips_venv_bin_from_path(self, monkeypatch):
        monkeypatch.setenv("VIRTUAL_ENV", "/home/user/.venv")
        monkeypatch.setenv("PATH", "/home/user/.venv/bin:/usr/local/bin:/usr/bin")
        env = _system_env()
        path_parts = env["PATH"].split(os.pathsep)
        assert "/home/user/.venv/bin" not in path_parts
        assert "/usr/local/bin" in path_parts

    def test_noop_when_virtual_env_not_set(self, monkeypatch):
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
        env = _system_env()
        assert env["PATH"] == "/usr/local/bin:/usr/bin"

    def test_returns_copy_not_os_environ(self, monkeypatch):
        monkeypatch.setenv("VIRTUAL_ENV", "/home/user/.venv")
        monkeypatch.setenv("PATH", "/home/user/.venv/bin:/usr/bin")
        env = _system_env()
        assert env is not os.environ
        assert "/home/user/.venv/bin" in os.environ["PATH"]


# ── _qemu_user ────────────────────────────────────────────────────────────────


class TestQemuUser:
    def test_returns_libvirt_qemu_when_file_missing(self, tmp_path, monkeypatch):
        import lib.providers.libvirt as libvirt_mod

        monkeypatch.setattr(libvirt_mod, "_QEMU_CONF", tmp_path / "nonexistent.conf")
        assert _qemu_user() == "libvirt-qemu"

    def test_returns_configured_user(self, tmp_path, monkeypatch):
        import lib.providers.libvirt as libvirt_mod

        conf = tmp_path / "qemu.conf"
        conf.write_text('user = "dustin"\n')
        monkeypatch.setattr(libvirt_mod, "_QEMU_CONF", conf)
        assert _qemu_user() == "dustin"

    def test_ignores_commented_lines(self, tmp_path, monkeypatch):
        import lib.providers.libvirt as libvirt_mod

        conf = tmp_path / "qemu.conf"
        conf.write_text('# user = "root"\nuser = "myuser"\n')
        monkeypatch.setattr(libvirt_mod, "_QEMU_CONF", conf)
        assert _qemu_user() == "myuser"

    def test_returns_libvirt_qemu_when_no_user_setting(self, tmp_path, monkeypatch):
        import lib.providers.libvirt as libvirt_mod

        conf = tmp_path / "qemu.conf"
        conf.write_text('# various settings\ngroup = "kvm"\n')
        monkeypatch.setattr(libvirt_mod, "_QEMU_CONF", conf)
        assert _qemu_user() == "libvirt-qemu"

    def test_returns_none_when_file_permission_denied(self, tmp_path, monkeypatch):
        import lib.providers.libvirt as libvirt_mod

        conf = tmp_path / "qemu.conf"
        conf.write_text('user = "dustin"\n')
        conf.chmod(0o000)
        monkeypatch.setattr(libvirt_mod, "_QEMU_CONF", conf)
        assert _qemu_user() is None


# ── _check_media_accessible ───────────────────────────────────────────────────


class TestCheckMediaAccessible:
    @pytest.fixture(autouse=True)
    def _default_qemu_user(self, monkeypatch):
        # Simulate default libvirt-qemu so world-permission checks run in all tests
        monkeypatch.setattr("lib.providers.libvirt._qemu_user", lambda: "libvirt-qemu")

    def test_noop_when_file_does_not_exist(self, tmp_path):
        _check_media_accessible(tmp_path / "does-not-exist.iso")

    def test_raises_when_file_not_world_readable(self, tmp_path):
        f = tmp_path / "win11.iso"
        f.touch()
        f.chmod(0o640)
        with pytest.raises(PermissionError, match="world-readable"):
            _check_media_accessible(f)

    def test_file_error_includes_chmod_command(self, tmp_path):
        f = tmp_path / "win11.iso"
        f.touch()
        f.chmod(0o640)
        with pytest.raises(PermissionError, match=r"chmod o\+r"):
            _check_media_accessible(f)

    def test_raises_when_parent_dir_not_world_executable(self, tmp_path):
        media_dir = tmp_path / "media"
        media_dir.mkdir()
        media_dir.chmod(0o750)
        f = media_dir / "win11.iso"
        f.touch()
        f.chmod(0o644)
        with pytest.raises(PermissionError, match=r"chmod o\+x"):
            _check_media_accessible(f)

    def test_error_references_getting_started(self, tmp_path):
        f = tmp_path / "win11.iso"
        f.touch()
        f.chmod(0o640)
        with pytest.raises(PermissionError, match="Getting Started"):
            _check_media_accessible(f)

    def test_noop_when_qemu_runs_as_current_user(self, tmp_path, monkeypatch):
        import getpass

        monkeypatch.setattr("lib.providers.libvirt._qemu_user", getpass.getuser)
        f = tmp_path / "win11.iso"
        f.touch()
        f.chmod(0o600)  # not world-readable — irrelevant when qemu == current user
        _check_media_accessible(f)  # should not raise

    def test_noop_when_qemu_runs_as_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.providers.libvirt._qemu_user", lambda: "root")
        f = tmp_path / "win11.iso"
        f.touch()
        f.chmod(0o600)
        _check_media_accessible(f)  # should not raise

    def test_noop_when_qemu_conf_unreadable(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.providers.libvirt._qemu_user", lambda: None)
        f = tmp_path / "win11.iso"
        f.touch()
        f.chmod(0o600)
        _check_media_accessible(f)  # should not raise


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def provider(tmp_path):
    iso_dir = tmp_path / "media" / "iso"
    virtio_dir = tmp_path / "media" / "virtio"
    automation = tmp_path / "automation"
    iso_dir.mkdir(parents=True)
    virtio_dir.mkdir(parents=True)
    automation.mkdir()
    return LibvirtProvider(iso_dir=iso_dir, virtio_dir=virtio_dir, automation_dir=automation)


# ── create_vm ─────────────────────────────────────────────────────────────────


class TestCreateVM:
    @pytest.fixture(autouse=True)
    def _skip_access_check(self, monkeypatch):
        monkeypatch.setattr("lib.providers.libvirt._check_media_accessible", lambda _: None)

    def test_calls_virt_install(self, tmp_path, provider):
        iso = provider.iso_dir / "win11.iso"
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
        iso = provider.iso_dir / "win11.iso"
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
        iso = provider.iso_dir / "win11.iso"
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
        iso = provider.iso_dir / "win10.iso"
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
        iso = provider.iso_dir / "server2025.iso"
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
        iso = provider.iso_dir / "win11.iso"
        virtio = provider.virtio_dir / "virtio-win.iso"
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
        iso = provider.iso_dir / "win11.iso"
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

    def test_floppy_persists_on_success(self, tmp_path, provider):
        iso = provider.iso_dir / "win11.iso"
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
        assert img_path.exists()

    def test_floppy_cleaned_up_on_failure(self, tmp_path, provider):
        iso = provider.iso_dir / "win11.iso"
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
        iso = provider.iso_dir / "win11.iso"
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

    def test_credentials_renders_answer_file(self, tmp_path, provider):
        iso = provider.iso_dir / "win10.iso"
        iso.touch()
        img_path = tmp_path / "fake.img"
        img_path.touch()
        vm = VMConfig(
            name="test-vm",
            os="win10",
            vcpus=2,
            ram_gb=4,
            disk_gb=40,
            os_media="win10.iso",
            admin_username="alice",
        )
        with patch.object(provider, "_create_answer_image", return_value=img_path) as mock_img:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                provider.create_vm(vm, admin_password="secret")
        xml_arg, _vm_name, setup_script = mock_img.call_args[0]
        assert "alice" in xml_arg
        assert "secret" in xml_arg
        assert "Enable-PSRemoting" in setup_script
        cmd = mock_run.call_args[0][0]
        assert any("floppy" in arg for arg in cmd)

    def test_credentials_skipped_when_no_password(self, tmp_path, provider):
        iso = provider.iso_dir / "win10.iso"
        iso.touch()
        vm = VMConfig(
            name="test-vm",
            os="win10",
            vcpus=2,
            ram_gb=4,
            disk_gb=40,
            os_media="win10.iso",
            admin_username="alice",
        )
        with patch.object(provider, "_create_answer_image") as mock_img:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                provider.create_vm(vm, admin_password=None)
        mock_img.assert_not_called()

    def test_credentials_skipped_when_no_username(self, tmp_path, provider):
        iso = provider.iso_dir / "win10.iso"
        iso.touch()
        vm = VMConfig(
            name="test-vm",
            os="win10",
            vcpus=2,
            ram_gb=4,
            disk_gb=40,
            os_media="win10.iso",
        )
        with patch.object(provider, "_create_answer_image") as mock_img:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                provider.create_vm(vm, admin_password="secret")
        mock_img.assert_not_called()


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

    def test_destroy_vm_removes_floppy_if_present(self, tmp_path, provider, monkeypatch):
        monkeypatch.setattr(provider, "_floppy_path", lambda name: tmp_path / f"{name}.img")
        floppy = tmp_path / "myvm.img"
        floppy.touch()
        with patch("subprocess.run"):
            provider.destroy_vm("myvm")
        assert not floppy.exists()

    def test_destroy_vm_noop_when_no_floppy(self, provider):
        with patch("subprocess.run"):
            provider.destroy_vm("myvm")  # no floppy file — should not raise


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


# ── Fledged detection ─────────────────────────────────────────────────────────


class TestGetVmIp:
    def test_returns_ipv4_address(self, provider):
        output = (
            " Name       MAC address          Protocol     Address\n"
            "-------------------------------------------------------------------------------\n"
            " vnet1      52:54:00:7b:b8:c7    ipv4         192.168.122.40/24\n"
        )
        result = MagicMock(returncode=0, stdout=output)
        with patch("subprocess.run", return_value=result):
            ip = provider.get_vm_ip("myvm")
        assert ip == "192.168.122.40"

    def test_returns_none_when_no_ip_yet(self, provider):
        output = (
            " Name       MAC address          Protocol     Address\n"
            "-------------------------------------------------------------------------------\n"
        )
        result = MagicMock(returncode=0, stdout=output)
        with patch("subprocess.run", return_value=result):
            ip = provider.get_vm_ip("myvm")
        assert ip is None

    def test_returns_none_on_nonzero_exit(self, provider):
        result = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=result):
            ip = provider.get_vm_ip("myvm")
        assert ip is None

    def test_strips_prefix_length(self, provider):
        output = (
            " Name       MAC address          Protocol     Address\n"
            "-------------------------------------------------------------------------------\n"
            " vnet0      52:54:00:00:00:01    ipv4         10.0.0.5/16\n"
        )
        result = MagicMock(returncode=0, stdout=output)
        with patch("subprocess.run", return_value=result):
            ip = provider.get_vm_ip("myvm")
        assert ip == "10.0.0.5"

    def test_uses_first_ipv4_when_multiple(self, provider):
        output = (
            " Name       MAC address          Protocol     Address\n"
            "-------------------------------------------------------------------------------\n"
            " vnet0      52:54:00:00:00:01    ipv4         10.0.0.5/16\n"
            " vnet0      52:54:00:00:00:01    ipv4         10.0.0.6/16\n"
        )
        result = MagicMock(returncode=0, stdout=output)
        with patch("subprocess.run", return_value=result):
            ip = provider.get_vm_ip("myvm")
        assert ip == "10.0.0.5"

    def test_ignores_ipv6_lines(self, provider):
        output = (
            " Name       MAC address          Protocol     Address\n"
            "-------------------------------------------------------------------------------\n"
            " vnet0      52:54:00:00:00:01    ipv6         fe80::1/64\n"
        )
        result = MagicMock(returncode=0, stdout=output)
        with patch("subprocess.run", return_value=result):
            ip = provider.get_vm_ip("myvm")
        assert ip is None


# ── Session metadata ───────────────────────────────────────────────────────────


class TestTagVmSession:
    def test_calls_virsh_metadata_set(self, provider):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            provider.tag_vm_session("myvm", "sess-uuid", "lab.yaml")
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "virsh"
        assert cmd[1] == "metadata"
        assert cmd[2] == "myvm"
        assert "--set" in cmd
        assert "--live" in cmd
        assert "--config" in cmd

    def test_set_payload_contains_session_id(self, provider):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            provider.tag_vm_session("myvm", "sess-uuid", "lab.yaml")
        cmd = mock_run.call_args[0][0]
        set_value = cmd[cmd.index("--set") + 1]
        assert "sess-uuid" in set_value

    def test_set_payload_contains_clutch_file(self, provider):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            provider.tag_vm_session("myvm", "sess-uuid", "lab.yaml")
        cmd = mock_run.call_args[0][0]
        set_value = cmd[cmd.index("--set") + 1]
        assert "lab.yaml" in set_value


class TestGetVmSessionTag:
    _XML = "<hatchery><session_id>s1</session_id><clutch_file>lab.yaml</clutch_file></hatchery>"

    def test_returns_session_and_clutch_file(self, provider):
        result = MagicMock(returncode=0, stdout=self._XML)
        with patch("subprocess.run", return_value=result):
            tag = provider.get_vm_session_tag("myvm")
        assert tag == {"session_id": "s1", "clutch_file": "lab.yaml"}

    def test_returns_none_when_no_metadata(self, provider):
        result = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=result):
            tag = provider.get_vm_session_tag("myvm")
        assert tag is None

    def test_returns_none_on_invalid_xml(self, provider):
        result = MagicMock(returncode=0, stdout="not xml")
        with patch("subprocess.run", return_value=result):
            tag = provider.get_vm_session_tag("myvm")
        assert tag is None

    def test_returns_none_when_fields_missing(self, provider):
        result = MagicMock(returncode=0, stdout="<hatchery></hatchery>")
        with patch("subprocess.run", return_value=result):
            tag = provider.get_vm_session_tag("myvm")
        assert tag is None


# ── send_key ──────────────────────────────────────────────────────────────────


class TestSendKey:
    def test_calls_virsh_send_key(self, provider):
        with patch("subprocess.run") as mock_run:
            provider.send_key("myvm", "KEY_ENTER")
        cmd = mock_run.call_args[0][0]
        assert cmd == ["virsh", "send-key", "myvm", "KEY_ENTER"]

    def test_passes_arbitrary_key(self, provider):
        with patch("subprocess.run") as mock_run:
            provider.send_key("myvm", "KEY_SPACE")
        cmd = mock_run.call_args[0][0]
        assert "KEY_SPACE" in cmd

    def test_raises_on_failure(self, provider):
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "virsh")):
            with pytest.raises(subprocess.CalledProcessError):
                provider.send_key("myvm", "KEY_ENTER")


# ── VM UUID ───────────────────────────────────────────────────────────────────


class TestGetVmUuid:
    _UUID = "aabbccdd-1234-5678-abcd-000000000001"

    def test_returns_uuid_string(self, provider):
        result = MagicMock(returncode=0, stdout=f"{self._UUID}\n")
        with patch("subprocess.run", return_value=result):
            assert provider.get_vm_uuid("myvm") == self._UUID

    def test_returns_none_on_nonzero_exit(self, provider):
        result = MagicMock(returncode=1, stdout="error: failed to get domain 'myvm'\n")
        with patch("subprocess.run", return_value=result):
            assert provider.get_vm_uuid("myvm") is None

    def test_returns_none_on_empty_output(self, provider):
        result = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", return_value=result):
            assert provider.get_vm_uuid("myvm") is None

    def test_strips_trailing_newline(self, provider):
        result = MagicMock(returncode=0, stdout=f"{self._UUID}\n\n")
        with patch("subprocess.run", return_value=result):
            assert provider.get_vm_uuid("myvm") == self._UUID

    def test_calls_virsh_domuuid(self, provider):
        result = MagicMock(returncode=0, stdout=f"{self._UUID}\n")
        with patch("subprocess.run", return_value=result) as mock_run:
            provider.get_vm_uuid("myvm")
        assert mock_run.call_args[0][0] == ["virsh", "domuuid", "myvm"]


class TestGetVmNameByUuid:
    _UUID = "aabbccdd-1234-5678-abcd-000000000001"

    def test_returns_vm_name(self, provider):
        result = MagicMock(returncode=0, stdout="dc01\n")
        with patch("subprocess.run", return_value=result):
            assert provider.get_vm_name_by_uuid(self._UUID) == "dc01"

    def test_returns_none_on_nonzero_exit(self, provider):
        result = MagicMock(returncode=1, stdout="error: failed to get domain\n")
        with patch("subprocess.run", return_value=result):
            assert provider.get_vm_name_by_uuid(self._UUID) is None

    def test_returns_none_on_empty_output(self, provider):
        result = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", return_value=result):
            assert provider.get_vm_name_by_uuid(self._UUID) is None

    def test_strips_trailing_newline(self, provider):
        result = MagicMock(returncode=0, stdout="dc01\n")
        with patch("subprocess.run", return_value=result):
            assert provider.get_vm_name_by_uuid(self._UUID) == "dc01"

    def test_calls_virsh_domname(self, provider):
        result = MagicMock(returncode=0, stdout="dc01\n")
        with patch("subprocess.run", return_value=result) as mock_run:
            provider.get_vm_name_by_uuid(self._UUID)
        assert mock_run.call_args[0][0] == ["virsh", "domname", self._UUID]


# ── Poweroff action ───────────────────────────────────────────────────────────


class TestSetPoweroffAction:
    def test_calls_set_lifecycle_action_live(self, provider):
        with patch("subprocess.run") as mock_run:
            provider.set_poweroff_action("myvm", "restart")
        cmd = mock_run.call_args[0][0]
        assert cmd == ["virsh", "set-lifecycle-action", "myvm", "poweroff", "restart", "--live"]

    def test_passes_destroy_action(self, provider):
        with patch("subprocess.run") as mock_run:
            provider.set_poweroff_action("myvm", "destroy")
        assert "destroy" in mock_run.call_args[0][0]

    def test_does_not_pass_config_flag(self, provider):
        with patch("subprocess.run") as mock_run:
            provider.set_poweroff_action("myvm", "restart")
        assert "--config" not in mock_run.call_args[0][0]

    def test_raises_on_virsh_failure(self, provider):
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "virsh")):
            with pytest.raises(subprocess.CalledProcessError):
                provider.set_poweroff_action("myvm", "restart")


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


# ── create_command_description ────────────────────────────────────────────────


class TestCreateCommandDescription:
    def test_returns_virt_install_command(self, provider):
        vm = VMConfig(name="dc01", os="win10", vcpus=2, ram_gb=4, disk_gb=40, os_media="win10.iso")
        desc = provider.create_command_description(vm)
        assert desc.startswith("virt-install")

    def test_includes_vm_name(self, provider):
        vm = VMConfig(name="dc01", os="win10", vcpus=2, ram_gb=4, disk_gb=40, os_media="win10.iso")
        desc = provider.create_command_description(vm)
        assert "dc01" in desc

    def test_includes_memory(self, provider):
        vm = VMConfig(name="vm", os="win10", vcpus=2, ram_gb=8, disk_gb=40, os_media="win10.iso")
        desc = provider.create_command_description(vm)
        assert "8192" in desc

    def test_win11_includes_uefi(self, provider):
        vm = VMConfig(name="vm", os="win11", vcpus=2, ram_gb=4, disk_gb=40, os_media="win11.iso")
        desc = provider.create_command_description(vm)
        assert "--boot uefi" in desc

    def test_win10_no_uefi(self, provider):
        vm = VMConfig(name="vm", os="win10", vcpus=2, ram_gb=4, disk_gb=40, os_media="win10.iso")
        desc = provider.create_command_description(vm)
        assert "--boot uefi" not in desc

    def test_virtio_included_in_command(self, provider):
        vm = VMConfig(
            name="vm",
            os="win10",
            vcpus=2,
            ram_gb=4,
            disk_gb=40,
            os_media="win10.iso",
            virtio_drivers="virtio.iso",
        )
        desc = provider.create_command_description(vm)
        assert "virtio.iso" in desc

    def test_no_extra_cdrom_when_no_virtio(self, provider):
        vm = VMConfig(name="vm", os="win10", vcpus=2, ram_gb=4, disk_gb=40, os_media="win10.iso")
        desc = provider.create_command_description(vm)
        assert "device=cdrom" not in desc

    def test_os_media_path_included(self, provider):
        vm = VMConfig(name="vm", os="win10", vcpus=2, ram_gb=4, disk_gb=40, os_media="win10.iso")
        desc = provider.create_command_description(vm)
        assert "win10.iso" in desc

    def test_absolute_os_media_used_as_is(self, tmp_path, provider):
        iso = tmp_path / "custom" / "win10.iso"
        vm = VMConfig(name="vm", os="win10", vcpus=2, ram_gb=4, disk_gb=40, os_media=str(iso))
        desc = provider.create_command_description(vm)
        assert str(iso) in desc


# ── Path resolution ───────────────────────────────────────────────────────────


class TestPathResolution:
    def test_resolve_media_relative(self, provider):
        f = provider.iso_dir / "test.iso"
        f.touch()
        assert provider._resolve_media("test.iso", provider.iso_dir) == f

    def test_resolve_media_absolute(self, tmp_path, provider):
        f = tmp_path / "elsewhere.iso"
        f.touch()
        assert provider._resolve_media(str(f), provider.iso_dir) == f

    def test_resolve_media_missing_relative_raises(self, provider):
        with pytest.raises(FileNotFoundError, match="Media file not found"):
            provider._resolve_media("nope.iso", provider.iso_dir)

    def test_resolve_media_missing_absolute_raises(self, tmp_path, provider):
        with pytest.raises(FileNotFoundError):
            provider._resolve_media(str(tmp_path / "nope.iso"), provider.iso_dir)

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


# ── storage_path ──────────────────────────────────────────────────────────────


class TestStoragePath:
    @pytest.fixture(autouse=True)
    def _skip_access_check(self, monkeypatch):
        monkeypatch.setattr("lib.providers.libvirt._check_media_accessible", lambda _: None)

    def test_uses_pool_when_no_storage_path(self, provider):
        iso = provider.iso_dir / "win10.iso"
        iso.touch()
        vm = VMConfig(name="vm", os="win10", vcpus=2, ram_gb=4, disk_gb=40, os_media="win10.iso")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            provider.create_vm(vm)
        cmd = " ".join(mock_run.call_args[0][0])
        assert "pool=default" in cmd
        assert "path=" not in cmd.split("--disk")[1].split("--disk")[0]

    def test_uses_path_when_storage_path_set(self, provider, tmp_path):
        iso = provider.iso_dir / "win10.iso"
        iso.touch()
        storage = tmp_path / "vms"
        storage.mkdir()
        vm = VMConfig(name="vm", os="win10", vcpus=2, ram_gb=4, disk_gb=40, os_media="win10.iso")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            provider.create_vm(vm, storage_path=str(storage))
        cmd = " ".join(mock_run.call_args[0][0])
        assert "pool=" not in cmd
        assert str(storage) in cmd
        assert "vm.qcow2" in cmd

    def test_disk_path_includes_vm_name(self, provider, tmp_path):
        iso = provider.iso_dir / "win10.iso"
        iso.touch()
        storage = tmp_path / "vms"
        storage.mkdir()
        vm = VMConfig(name="myvm", os="win10", vcpus=2, ram_gb=4, disk_gb=40, os_media="win10.iso")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            provider.create_vm(vm, storage_path=str(storage))
        cmd = " ".join(mock_run.call_args[0][0])
        assert "myvm.qcow2" in cmd

    def test_disk_size_preserved_with_storage_path(self, provider, tmp_path):
        iso = provider.iso_dir / "win10.iso"
        iso.touch()
        storage = tmp_path / "vms"
        storage.mkdir()
        vm = VMConfig(name="vm", os="win10", vcpus=2, ram_gb=4, disk_gb=80, os_media="win10.iso")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            provider.create_vm(vm, storage_path=str(storage))
        cmd = " ".join(mock_run.call_args[0][0])
        assert "size=80" in cmd

    def test_missing_storage_path_raises_before_virt_install(self, provider, tmp_path):
        iso = provider.iso_dir / "win10.iso"
        iso.touch()
        vm = VMConfig(name="vm", os="win10", vcpus=2, ram_gb=4, disk_gb=40, os_media="win10.iso")
        with patch("subprocess.run") as mock_run:
            with pytest.raises(FileNotFoundError, match="Storage path does not exist"):
                provider.create_vm(vm, storage_path="/nonexistent/path")
        mock_run.assert_not_called()

    def test_create_command_description_uses_storage_path(self, provider, tmp_path):
        vm = VMConfig(name="vm", os="win10", vcpus=2, ram_gb=4, disk_gb=40, os_media="win10.iso")
        desc = provider.create_command_description(vm, storage_path="/mnt/nvme/vms")
        assert "/mnt/nvme/vms" in desc
        assert "pool=" not in desc

    def test_create_command_description_uses_pool_without_storage_path(self, provider):
        vm = VMConfig(name="vm", os="win10", vcpus=2, ram_gb=4, disk_gb=40, os_media="win10.iso")
        desc = provider.create_command_description(vm)
        assert "pool=default" in desc
