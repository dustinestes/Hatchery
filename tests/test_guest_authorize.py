"""Guest SSH authorize: Clutch remoting.ssh.authorize (#524). Mocked; no live guest."""

from __future__ import annotations

import shutil
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from lib import config as cfg
from lib import db as db_module
from lib import guest_authorize as ga
from lib import remoting_identities as ri
from lib.clutch import RemotingSshConfig, VMConfig

pytestmark = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen required")


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


def _vm(**kwargs):
    base = dict(
        name="vm1",
        os="windows",
        vcpus=2,
        ram_gb=4,
        disk_gb=40,
        os_media="win.iso",
    )
    base.update(kwargs)
    return VMConfig(**base)


class TestClutchRemotingSchema:
    def test_default_authorize_hatchery(self):
        vm = _vm()
        assert vm.remoting.ssh.authorize == ["hatchery"]
        assert vm.remoting.ssh.port == 22

    def test_empty_authorize_rejected(self):
        with pytest.raises(ValidationError, match="authorize"):
            RemotingSshConfig(authorize=[])

    def test_authorize_dedupes(self):
        cfg_ssh = RemotingSshConfig(authorize=["hatchery", "hatchery", "lab"])
        assert cfg_ssh.authorize == ["hatchery", "lab"]


class TestVmHelpers:
    def test_authorize_ids_and_port_from_vm(self):
        vm = _vm(remoting={"ssh": {"port": 2222, "authorize": ["hatchery", "lab"]}})
        assert ga.authorize_ids_for_vm(vm) == ["hatchery", "lab"]
        assert ga.ssh_port_for_vm(vm) == 2222

    def test_authorize_ids_default_when_remoting_missing(self):
        class Bare:
            pass

        bare = Bare()
        assert ga.authorize_ids_for_vm(bare) == ["hatchery"]
        assert ga.ssh_port_for_vm(bare) == 22


class TestResolveAuthorizePubkeys:
    def test_empty_raises(self):
        with pytest.raises(ga.GuestAuthorizeError, match="empty"):
            ga.resolve_authorize_pubkeys([])

    def test_resolves_pubkey(self, isolated_config):
        ri.ensure_hatchery_identity()
        pairs = ga.resolve_authorize_pubkeys(["hatchery"])
        assert pairs[0][0] == "hatchery"
        assert pairs[0][1].startswith("ssh-")

    def test_unknown_identity_raises(self, isolated_config):
        with pytest.raises(ga.GuestAuthorizeError, match="unknown"):
            ga.resolve_authorize_pubkeys(["missing-id"])


class TestInjectAndDisable:
    def test_inject_rejects_empty_pubkeys(self):
        with pytest.raises(ga.GuestAuthorizeError, match="no public keys"):
            ga.inject_authorized_keys(MagicMock(), [])

    def test_inject_raises_on_remote_failure(self):
        transport = MagicMock()
        transport.run_ps.return_value = (1, "boom")
        with pytest.raises(ga.GuestAuthorizeError, match="failed to inject"):
            ga.inject_authorized_keys(transport, ["ssh-ed25519 AAAA comment"])

    def test_disable_raises_on_remote_failure(self):
        transport = MagicMock()
        transport.run_ps.return_value = (1, "nope")
        with pytest.raises(ga.GuestAuthorizeError, match="PasswordAuthentication"):
            ga.disable_password_authentication(transport)

    def test_ps_helpers_emit_markers(self):
        inject = ga._inject_authorized_keys_ps(["ssh-ed25519 AAAA x"])
        assert "hatchery-authorize-ok" in inject
        assert "ssh-ed25519 AAAA x" in inject
        assert "''" in ga._ps_quote("O'Brien")
        disable = ga._disable_password_auth_ps()
        assert "PasswordAuthentication no" in disable
        assert "hatchery-password-auth-disabled" in disable


class TestVerifyKeySsh:
    def test_verify_ok(self):
        ssh = MagicMock(spec=ga.SshGuestTransport)
        ssh.run_ps.return_value = (0, "hatchery-guest-ok")
        with (
            patch("lib.guest_authorize.get_guest_transport", return_value=ssh),
            patch("lib.guest_authorize.isinstance", return_value=True),
        ):
            ga.verify_key_ssh("10.0.0.1", "admin", "/tmp/key")
        ssh.run_ps.assert_called_once()

    def test_verify_transport_error(self):
        with patch(
            "lib.guest_authorize.get_guest_transport",
            side_effect=ga.GuestTransportError("down"),
        ):
            with pytest.raises(ga.GuestAuthorizeError, match="key SSH transport"):
                ga.verify_key_ssh("10.0.0.1", "admin", "/tmp/key")

    def test_verify_wrong_kind(self):
        winrm = MagicMock()
        with patch("lib.guest_authorize.get_guest_transport", return_value=winrm):
            with pytest.raises(ga.GuestAuthorizeError, match="expected SSH"):
                ga.verify_key_ssh("10.0.0.1", "admin", "/tmp/key")

    def test_verify_probe_fails(self):
        ssh = MagicMock(spec=ga.SshGuestTransport)
        ssh.run_ps.return_value = (255, "Permission denied (publickey)")
        with (
            patch("lib.guest_authorize.get_guest_transport", return_value=ssh),
            patch("lib.guest_authorize.isinstance", return_value=True),
        ):
            with pytest.raises(ga.GuestAuthorizeError, match="Permission denied"):
                ga.verify_key_ssh("10.0.0.1", "admin", "/tmp/key", ssh_port=2222)


class TestApplyGuestSshAuthorize:
    def test_skips_when_ssh_closed(self, isolated_config):
        ri.ensure_hatchery_identity()
        with patch("lib.guest_authorize.check_ssh", return_value=False):
            result = ga.apply_guest_ssh_authorize(
                "10.0.0.1",
                "admin",
                "pw",
                authorize_ids=["hatchery"],
            )
        assert result.skipped
        assert result.identity_file
        assert not result.password_auth_disabled

    def test_inject_verify_disable_order(self, isolated_config):
        ri.ensure_hatchery_identity()
        calls: list[str] = []

        transport = MagicMock()
        transport.kind = "ssh"

        def run_ps(code, *, timeout=300):
            if "hatchery-authorize-ok" in code or "authorized_keys" in code:
                calls.append("inject")
                return 0, "hatchery-authorize-ok"
            if "PasswordAuthentication" in code:
                calls.append("disable")
                return 0, "hatchery-password-auth-disabled"
            return 0, "ok"

        transport.run_ps.side_effect = run_ps

        key_transport = MagicMock()
        key_transport.kind = "ssh"
        key_transport.test_connection.return_value = True
        key_transport.run_ps.side_effect = run_ps

        with (
            patch("lib.guest_authorize.check_ssh", return_value=True),
            patch(
                "lib.guest_authorize.verify_key_ssh",
                side_effect=lambda *a, **k: calls.append("verify"),
            ),
            patch(
                "lib.guest_authorize.get_guest_transport",
                return_value=key_transport,
            ),
        ):
            result = ga.apply_guest_ssh_authorize(
                "10.0.0.1",
                "admin",
                "pw",
                authorize_ids=["hatchery"],
                password_transport=transport,
            )
        assert calls == ["inject", "verify", "disable"]
        assert result.password_auth_disabled
        assert result.client_identity_id == "hatchery"

    def test_resolves_password_transport_when_omitted(self, isolated_config):
        ri.ensure_hatchery_identity()
        password_t = MagicMock()
        password_t.run_ps.return_value = (0, "hatchery-authorize-ok")
        key_t = MagicMock()
        key_t.run_ps.return_value = (0, "hatchery-password-auth-disabled")

        with (
            patch("lib.guest_authorize.check_ssh", return_value=True),
            patch("lib.guest_authorize.verify_key_ssh"),
            patch(
                "lib.guest_authorize.get_guest_transport",
                side_effect=[password_t, key_t],
            ),
        ):
            result = ga.apply_guest_ssh_authorize(
                "10.0.0.1",
                "admin",
                "pw",
                authorize_ids=["hatchery"],
            )
        assert result.password_auth_disabled

    def test_disable_falls_back_when_key_transport_unavailable(self, isolated_config):
        ri.ensure_hatchery_identity()
        password_t = MagicMock()
        password_t.run_ps.side_effect = [
            (0, "hatchery-authorize-ok"),
            (0, "hatchery-password-auth-disabled"),
        ]
        with (
            patch("lib.guest_authorize.check_ssh", return_value=True),
            patch("lib.guest_authorize.verify_key_ssh"),
            patch(
                "lib.guest_authorize.get_guest_transport",
                side_effect=ga.GuestTransportError("no key ssh"),
            ),
        ):
            result = ga.apply_guest_ssh_authorize(
                "10.0.0.1",
                "admin",
                "pw",
                authorize_ids=["hatchery"],
                password_transport=password_t,
            )
        assert result.password_auth_disabled
        assert password_t.run_ps.call_count == 2


class TestHatchLifecycleAuthorize:
    def test_client_defaults_none_vm(self):
        from lib import hatch_lifecycle as hl

        path, port = hl._guest_ssh_client_defaults(None)
        assert path is None
        assert port == 22

    def test_client_defaults_resolves_path(self, isolated_config):
        from lib import hatch_lifecycle as hl

        ri.ensure_hatchery_identity()
        vm = _vm()
        path, port = hl._guest_ssh_client_defaults(vm)
        assert path
        assert path.endswith("hatchery_ed25519")
        assert port == 22

    def test_client_defaults_unknown_identity(self, isolated_config):
        from lib import hatch_lifecycle as hl
        from lib.clutch import RemotingConfig, RemotingSshConfig

        vm = _vm(remoting=RemotingConfig(ssh=RemotingSshConfig(authorize=["nope"])))
        path, port = hl._guest_ssh_client_defaults(vm)
        assert path is None
        assert port == 22

    def test_client_defaults_empty_authorize_list(self):
        from lib import hatch_lifecycle as hl

        class FakeVm:
            remoting = type("R", (), {"ssh": type("S", (), {"authorize": [], "port": 2222})()})()

        path, port = hl._guest_ssh_client_defaults(FakeVm())
        assert path is None
        assert port == 2222

    def test_provision_guest_transport_defaults_scope(self):
        from lib import provision as provision_lib

        with patch("lib.guest_transport.resolve_guest_transport") as resolve:
            resolve.return_value = MagicMock()
            with provision_lib.guest_transport_defaults(
                identity_file="/tmp/id",
                ssh_port=2222,
                winrm_port=5986,
            ):
                provision_lib._guest_transport("10.0.0.1", "admin", "pw")
            kwargs = resolve.call_args.kwargs
            assert kwargs["identity_file"] == "/tmp/id"
            assert kwargs["ssh_port"] == 2222
            assert kwargs["winrm_port"] == 5986
            # Outside the scope, defaults reset.
            provision_lib._guest_transport("10.0.0.1", "admin", "pw")
            kwargs2 = resolve.call_args.kwargs
            assert kwargs2["identity_file"] is None
            assert kwargs2["ssh_port"] == 22

    def test_apply_success_and_skip_and_fail(self, isolated_config):
        from lib import hatch as hatch_lib
        from lib import hatch_lifecycle as hl

        ri.ensure_hatchery_identity()
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "vm1", admin_username="admin", admin_password="pw")

        ok = ga.GuestAuthorizeResult(
            authorize_ids=["hatchery"],
            client_identity_id="hatchery",
            identity_file="/tmp/key",
            ssh_port=22,
            password_auth_disabled=True,
        )
        with (
            patch.object(hl, "_clutch_vm_for_session", return_value=_vm()),
            patch("lib.guest_authorize.apply_guest_ssh_authorize", return_value=ok),
        ):
            path, port = hl._apply_guest_ssh_authorize(
                sid, "vm1", "10.0.0.1", "admin", "pw", password_transport=None
            )
        assert path == "/tmp/key"
        assert port == 22

        skipped = ga.GuestAuthorizeResult(
            authorize_ids=["hatchery"],
            client_identity_id="hatchery",
            identity_file="/tmp/key",
            ssh_port=22,
            skipped=True,
            skip_reason="SSH closed",
        )
        with (
            patch.object(hl, "_clutch_vm_for_session", return_value=None),
            patch("lib.guest_authorize.apply_guest_ssh_authorize", return_value=skipped),
        ):
            path, port = hl._apply_guest_ssh_authorize(
                sid, "vm1", "10.0.0.1", "admin", "pw", password_transport=None
            )
        assert path == "/tmp/key"

        with (
            patch.object(hl, "_clutch_vm_for_session", return_value=_vm()),
            patch(
                "lib.guest_authorize.apply_guest_ssh_authorize",
                side_effect=ga.GuestAuthorizeError("boom"),
            ),
        ):
            path, port = hl._apply_guest_ssh_authorize(
                sid, "vm1", "10.0.0.1", "admin", "pw", password_transport=None
            )
        assert path is None
        row = hatch_lib.get_vm_record(sid, "vm1")
        assert row["status"] == "failed"
