"""Install media cleanup (#144 / ADR-0035) and nest_storage VM dirs (#587)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import lib.config as cfg
import lib.db as db_module
from lib.providers.base import (
    MediaCleanupStep,
    answer_media_path,
    resolve_nest_storage_root,
    vm_nest_dir,
)
from lib.providers.hyperv import HyperVProvider, _JSON_MARKER
from lib.providers.libvirt import LibvirtProvider


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(cfg, "DEFAULT_DATA_DIR", data)
    monkeypatch.setattr(
        cfg,
        "_DEFAULTS",
        {
            "data_dir": str(data),
            "bg_interval": 60,
            "validators": {},
            "validators_run_retention": 50,
            "nest_reachability_status": {},
            "nest_health_status": {},
            "show_passwords": False,
            "display_timezone": "UTC",
            "vms_show_external": False,
            "library_enabled": False,
            "library_connections": [],
            "library_script_bindings": [],
            "library_clutch_bindings": [],
            "library_media_bindings": [],
            "nest_key_alert_tiers": [],
            "nest_ssh_identities": [],
        },
    )
    monkeypatch.setattr(cfg, "_config", {"data_dir": str(data)})
    monkeypatch.setattr(cfg, "_pending_yaml_settings", {})
    monkeypatch.setattr(cfg, "_db_bound", False)
    monkeypatch.setattr(cfg, "_runtime_data_dir", None)
    monkeypatch.setattr(cfg, "_runtime_nest_local", False)
    monkeypatch.setattr(cfg, "_bootstrap_data_dir", None)
    db_module.init_db(data / "hatchery.db")
    cfg.bind_db()
    yield data
    db_module._db_path = None
    cfg.set_runtime_data_dir(None)
    cfg.set_runtime_nest_local(False)


@pytest.fixture
def nest_root(tmp_path):
    iso = tmp_path / "media" / "iso"
    virtio = tmp_path / "media" / "virtio"
    automation = tmp_path / "automation" / "answerfiles"
    storage = tmp_path / "nest_storage"
    iso.mkdir(parents=True)
    virtio.mkdir(parents=True)
    automation.mkdir(parents=True)
    storage.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def libvirt(nest_root):
    return LibvirtProvider(
        iso_dir=nest_root / "media" / "iso",
        virtio_dir=nest_root / "media" / "virtio",
        automation_dir=nest_root / "automation" / "answerfiles",
        nest_cache=nest_root,
        nest_storage=nest_root / "nest_storage",
    )


class TestNestStoragePaths:
    def test_resolve_priority(self, tmp_path):
        nest = tmp_path / "nest"
        clutch = tmp_path / "clutch"
        default = tmp_path / "default"
        nest.mkdir()
        clutch.mkdir()
        default.mkdir()
        assert (
            resolve_nest_storage_root(
                nest_storage=nest, clutch_storage_path=clutch, provider_default=default
            )
            == nest
        )
        assert (
            resolve_nest_storage_root(
                nest_storage=None, clutch_storage_path=clutch, provider_default=default
            )
            == clutch
        )
        assert (
            resolve_nest_storage_root(
                nest_storage=None, clutch_storage_path=None, provider_default=default
            )
            == default
        )
        assert (
            resolve_nest_storage_root(
                nest_storage=None, clutch_storage_path=None, provider_default=None
            )
            is None
        )

    def test_answer_under_vm_dir_not_nest_cache(self, nest_root, libvirt, monkeypatch):
        import tempfile

        monkeypatch.setattr(tempfile, "gettempdir", lambda: "/should-not-use")
        vm_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        path = libvirt._floppy_path(libvirt._vm_dir_for(vm_id))
        assert path == nest_root / "nest_storage" / vm_id / "autounattend.img"
        assert path.parent.is_dir()
        assert "nest-work" not in str(path)
        assert "tmp" not in str(path).lower() or "nest_storage" in str(path)

    def test_helper_matches_layout(self, nest_root):
        vm_dir = vm_nest_dir(nest_root / "nest_storage", "vm-id")
        assert answer_media_path(vm_dir, ".iso").name == "autounattend.iso"


class TestLibvirtCleanup:
    def test_ejects_and_deletes_answer(self, nest_root, libvirt):
        vm_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        answer = nest_root / "nest_storage" / vm_id / "autounattend.img"
        answer.parent.mkdir(parents=True)
        answer.write_bytes(b"x")
        iso = nest_root / "media" / "iso" / "win.iso"
        iso.parent.mkdir(parents=True, exist_ok=True)
        iso.touch()
        virtio = nest_root / "media" / "virtio" / "virtio-win.iso"
        virtio.touch()
        xml = f"""
        <domain>
          <devices>
            <disk type='file' device='cdrom'>
              <source file='{iso}'/>
              <target dev='sda' bus='sata'/>
            </disk>
            <disk type='file' device='cdrom'>
              <source file='{virtio}'/>
              <target dev='sdb' bus='sata'/>
            </disk>
            <disk type='file' device='floppy'>
              <source file='{answer}'/>
              <target dev='fda' bus='fdc'/>
            </disk>
          </devices>
        </domain>
        """
        ejects: list[str] = []

        def fake_run_cmd(cmd, **_kwargs):
            if cmd[:2] == ["virsh", "dumpxml"]:
                return MagicMock(stdout=xml, returncode=0)
            if cmd[:2] == ["virsh", "change-media"]:
                ejects.append(cmd[3])
                return MagicMock(stdout="", returncode=0)
            raise AssertionError(cmd)

        with patch("lib.providers.libvirt.run_cmd", side_effect=fake_run_cmd):
            steps = libvirt.cleanup_install_media("lab")

        assert ejects == ["sda", "sdb", "fda"]
        assert not answer.exists()
        assert not answer.parent.exists()
        kinds = [(s.kind, s.action, s.ok) for s in steps]
        assert ("installation", "detach", True) in kinds
        assert ("drivers", "detach", True) in kinds
        assert ("answer", "detach", True) in kinds
        assert ("answer", "delete", True) in kinds

    def test_skips_delete_when_answer_detach_fails(self, nest_root, libvirt):
        vm_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        answer = nest_root / "nest_storage" / vm_id / "autounattend.img"
        answer.parent.mkdir(parents=True)
        answer.write_bytes(b"x")
        xml = f"""
        <domain>
          <devices>
            <disk type='file' device='floppy'>
              <source file='{answer}'/>
              <target dev='fda' bus='fdc'/>
            </disk>
          </devices>
        </domain>
        """

        def fake_run_cmd(cmd, **_kwargs):
            if cmd[:2] == ["virsh", "dumpxml"]:
                return MagicMock(stdout=xml, returncode=0)
            if cmd[:2] == ["virsh", "change-media"]:
                raise RuntimeError("eject failed")
            raise AssertionError(cmd)

        with patch("lib.providers.libvirt.run_cmd", side_effect=fake_run_cmd):
            steps = libvirt.cleanup_install_media("lab")

        assert answer.exists()
        assert any(s.kind == "answer" and s.action == "detach" and not s.ok for s in steps)
        assert not any(s.action == "delete" for s in steps)


class TestHyperVCleanup:
    def test_ejects_dvds_and_deletes_answer(self, nest_root):
        vm_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        answer = nest_root / "nest_storage" / vm_id / "autounattend.iso"
        answer.parent.mkdir(parents=True)
        answer.write_bytes(b"iso")
        os_iso = nest_root / "media" / "iso" / "server.iso"
        os_iso.parent.mkdir(parents=True, exist_ok=True)
        os_iso.touch()
        scripts: list[str] = []

        def runner(script: str) -> str:
            scripts.append(script)
            if "Get-VMDvdDrive" in script:
                payload = [
                    {
                        "Path": str(os_iso),
                        "ControllerNumber": 1,
                        "ControllerLocation": 0,
                    },
                    {
                        "Path": str(answer),
                        "ControllerNumber": 1,
                        "ControllerLocation": 1,
                    },
                ]
                return f"{_JSON_MARKER}{json.dumps(payload)}"
            if "Set-VMDvdDrive" in script or '"ok":true' in script or '{"ok":true}' in script:
                return f'{_JSON_MARKER}{{"ok":true}}'
            raise AssertionError(script)

        p = HyperVProvider(
            "hv1",
            runner=runner,
            iso_dir=nest_root / "media" / "iso",
            virtio_dir=nest_root / "media" / "virtio",
            nest_cache=nest_root,
            nest_storage=nest_root / "nest_storage",
        )
        steps = p.cleanup_install_media("hv")
        assert not answer.exists()
        assert not answer.parent.exists()
        assert any(s.kind == "installation" and s.ok for s in steps)
        assert any(s.kind == "answer" and s.action == "delete" and s.ok for s in steps)


class TestLifecycleEvents:
    def test_warn_continues_and_emits_bookends(self, isolated_config):
        from lib import hatch as hatch_lib
        from lib import hatch_lifecycle as hl

        session_id = hatch_lib.create_session("demo.yaml", "Demo")
        hatch_lib.add_vm(session_id, "vm1", guest_os="windows")

        class BoomProvider:
            def cleanup_install_media(self, name: str) -> list[MediaCleanupStep]:
                return [
                    MediaCleanupStep(
                        kind="installation",
                        action="detach",
                        basename="win.iso",
                        target="sda",
                        ok=False,
                        error="device busy",
                    )
                ]

        hl._run_install_media_cleanup(session_id, "vm1", BoomProvider())  # type: ignore[arg-type]
        messages = [e["message"] for e in hatch_lib.get_events(session_id, "vm1")]
        assert messages[0] == "Starting install media cleanup"
        assert "Detaching installation media: win.iso on sda" in messages
        assert any(m.startswith("Failed to detach installation media:") for m in messages)
        assert messages[-1] == "Ending install media cleanup (with warnings)"
        # Hygiene only - status untouched
        assert (hatch_lib.get_vm_record(session_id, "vm1") or {}).get("status") != "failed"

    def test_success_bookends(self, isolated_config):
        from lib import hatch as hatch_lib
        from lib import hatch_lifecycle as hl

        session_id = hatch_lib.create_session("demo.yaml", "Demo")
        hatch_lib.add_vm(session_id, "vm1", guest_os="windows")

        class OkProvider:
            def cleanup_install_media(self, name: str) -> list[MediaCleanupStep]:
                return [
                    MediaCleanupStep(
                        kind="answer",
                        action="detach",
                        basename="autounattend.img",
                        target="fda",
                        path="/nest_storage/vm-id/autounattend.img",
                        ok=True,
                    ),
                    MediaCleanupStep(
                        kind="answer",
                        action="delete",
                        basename="autounattend.img",
                        target="nest_storage",
                        path="/nest_storage/vm-id/autounattend.img",
                        ok=True,
                    ),
                ]

        hl._run_install_media_cleanup(session_id, "vm1", OkProvider())  # type: ignore[arg-type]
        messages = [e["message"] for e in hatch_lib.get_events(session_id, "vm1")]
        assert "Starting install media cleanup" in messages
        assert "Successfully deleted silent answer media" in messages
        assert messages[-1] == "Ending install media cleanup"
