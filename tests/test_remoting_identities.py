"""Tests for Controller remoting identity catalog (#522 / ADR-0030)."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from lib import config as cfg
from lib import db as db_module
from lib import remoting_identities as ri


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


def _make_key(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-f",
            str(path),
            "-N",
            "",
            "-C",
            "test",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return path


class TestHatcheryManaged:
    def test_ensure_generates_and_lists(self, isolated_config):
        ident = ri.ensure_hatchery_identity()
        assert ident.id == "hatchery"
        assert ident.kind == "hatchery"
        assert ident.pubkey
        priv = isolated_config / "remoting" / "hatchery_ed25519"
        assert priv.is_file()
        # Unix mode bits are not meaningful on Windows Controllers.
        if os.name == "posix":
            mode = priv.stat().st_mode
            assert not (mode & (stat.S_IRGRP | stat.S_IROTH))
        listed = ri.list_identities()
        assert any(i.id == "hatchery" for i in listed)
        again = ri.ensure_hatchery_identity()
        assert again.pubkey == ident.pubkey

    def test_rotate_replaces_pubkey(self, isolated_config):
        first = ri.ensure_hatchery_identity()
        second = ri.rotate_hatchery_identity()
        assert second.pubkey
        assert second.pubkey != first.pubkey

    def test_resolve_and_private_path(self, isolated_config):
        ri.ensure_hatchery_identity()
        path = ri.identity_private_path("hatchery")
        assert path.is_file()
        pub = ri.identity_pubkey("hatchery")
        assert pub.startswith("ssh-")
        with pytest.raises(ri.RemotingIdentityError, match="unknown"):
            ri.resolve("missing")

    def test_identity_pubkey_repairs_stale_catalog(self, isolated_config):
        """Inject must use key material that matches the private key (#537)."""
        ident = ri.ensure_hatchery_identity()
        priv = isolated_config / "remoting" / "hatchery_ed25519"
        real_pub = (isolated_config / "remoting" / "hatchery_ed25519.pub").read_text().strip()
        ri._upsert(
            identity_id="hatchery",
            name=ident.name,
            kind="hatchery",
            identity_file=ident.identity_file,
            pubkey=(
                "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA "
                "stale"
            ),
            cert_path=None,
            identity_expires_at=None,
        )
        stale = ri.get_identity("hatchery")
        assert stale is not None
        assert stale.pubkey != real_pub
        check = ri.check_identity(stale)
        assert not check.ok
        assert "does not match" in check.detail
        repaired = ri.identity_pubkey("hatchery")
        assert ri._pubkey_material(repaired) == ri._pubkey_material(real_pub)
        synced = ri.get_identity("hatchery")
        assert synced is not None
        assert ri._pubkey_material(synced.pubkey or "") == ri._pubkey_material(real_pub)
        assert priv.is_file()


class TestPathIdentity:
    def test_add_path_and_check(self, isolated_config, tmp_path):
        key = _make_key(tmp_path / "ops_ed25519")
        ident = ri.add_path_identity(
            identity_id="ops",
            identity_file=str(key),
            name="Ops key",
        )
        assert ident.kind == "path"
        assert ident.pubkey
        check = ri.check_identity(ident)
        assert check.ok

    def test_add_path_rejects_hatchery_id(self, isolated_config, tmp_path):
        key = _make_key(tmp_path / "x")
        with pytest.raises(ri.RemotingIdentityError, match="reserved"):
            ri.add_path_identity(identity_id="hatchery", identity_file=str(key))

    def test_add_path_missing_file(self, isolated_config):
        with pytest.raises(ri.RemotingIdentityError, match="not found"):
            ri.add_path_identity(identity_id="gone", identity_file="/no/such/key")

    def test_check_fails_world_readable(self, isolated_config, tmp_path):
        if os.name != "posix":
            pytest.skip("identity mode check is POSIX-only")
        key = _make_key(tmp_path / "loose")
        os.chmod(key, 0o644)
        ident = ri.add_path_identity(identity_id="loose", identity_file=str(key))
        check = ri.check_identity(ident)
        assert not check.ok
        assert "group/world" in check.detail

    def test_remove_path(self, isolated_config, tmp_path):
        key = _make_key(tmp_path / "rm")
        ri.add_path_identity(identity_id="rm", identity_file=str(key))
        ri.remove_identity("rm")
        assert ri.get_identity("rm") is None

    def test_remove_hatchery_requires_delete_files(self, isolated_config):
        ri.ensure_hatchery_identity()
        with pytest.raises(ri.RemotingIdentityError, match="delete-files"):
            ri.remove_identity("hatchery")
        ri.remove_identity("hatchery", delete_files=True)
        assert ri.get_identity("hatchery") is None
        assert not (isolated_config / "remoting" / "hatchery_ed25519").exists()


class TestExpiryFeed:
    def test_identities_for_expiry(self, isolated_config, tmp_path):
        key = _make_key(tmp_path / "exp")
        ri.add_path_identity(
            identity_id="exp",
            identity_file=str(key),
            identity_expires_at="2030-06-01T00:00:00+00:00",
        )
        feed = ri.identities_for_expiry()
        assert any(i.id == "remoting:exp" and i.expires_at is not None for i in feed)
