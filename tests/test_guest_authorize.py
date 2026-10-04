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


class TestResolveAuthorizePubkeys:
    def test_empty_raises(self):
        with pytest.raises(ga.GuestAuthorizeError, match="empty"):
            ga.resolve_authorize_pubkeys([])

    def test_resolves_pubkey(self, isolated_config):
        ri.ensure_hatchery_identity()
        pairs = ga.resolve_authorize_pubkeys(["hatchery"])
        assert pairs[0][0] == "hatchery"
        assert pairs[0][1].startswith("ssh-")


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
