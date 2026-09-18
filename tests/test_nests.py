"""Nest connection registry (#207)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import lib.config as config
import lib.db as db_module
import lib.nests as nests_lib


@pytest.fixture(autouse=True)
def isolate_db(tmp_path, monkeypatch):
    db_module.init_db(tmp_path / "hatchery.db")
    monkeypatch.setattr(config, "nest_ssh_identities", lambda: [])
    monkeypatch.setattr(
        config, "get", lambda: {"nest_ssh_identities": [], "data_dir": str(tmp_path)}
    )
    monkeypatch.setattr(config, "save", lambda _c: None)
    yield
    db_module._db_path = None


class TestSeedAndList:
    def test_seeds_local_nest(self):
        nests = nests_lib.list_nests()
        assert len(nests) == 1
        assert nests[0]["id"] == "local"
        assert nests[0]["location"] == "local"
        assert nests[0]["provider_type"] == "libvirt"
        assert nests[0]["name"] == "Local"

    def test_ensure_local_idempotent(self):
        nests_lib.ensure_local_nest()
        nests_lib.ensure_local_nest()
        assert len(nests_lib.list_nests()) == 1


class TestReplaceNests:
    def test_add_remote_ssh_nest(self):
        local = nests_lib.get_nest("local")
        nests_lib.replace_nests(
            [
                local,
                {
                    "id": "lab1",
                    "name": "Lab Hyper-V",
                    "provider_type": "hyperv",
                    "location": "remote",
                    "transport": "ssh",
                    "host": "nest.example",
                    "port": 22,
                    "ssh_user": "ops",
                    "identity_file": "~/.ssh/nest",
                    "identity_expires_at": "2026-12-01",
                    "known_hosts": "accept-new",
                },
            ]
        )
        nests = nests_lib.list_nests()
        assert [n["id"] for n in nests] == ["local", "lab1"]
        remote = nests_lib.get_nest("lab1")
        assert remote["host"] == "nest.example"
        assert remote["transport"] == "ssh"
        assert remote["identity_file"] == "~/.ssh/nest"
        assert remote["identity_expires_at"].startswith("2026-12-01")

    def test_cannot_remove_local(self):
        with pytest.raises(ValueError, match="cannot be removed"):
            nests_lib.replace_nests(
                [
                    {
                        "id": "only-remote",
                        "name": "Remote",
                        "provider_type": "libvirt",
                        "location": "remote",
                        "host": "x.example",
                    }
                ]
            )

    def test_local_must_stay_local(self):
        with pytest.raises(ValueError, match="must have location 'local'"):
            nests_lib.replace_nests(
                [
                    {
                        "id": "local",
                        "name": "Local",
                        "provider_type": "libvirt",
                        "location": "remote",
                        "host": "x.example",
                    }
                ]
            )


class TestConnectionConfig:
    def test_local_has_no_transport(self):
        cfg = nests_lib.to_connection_config(nests_lib.get_nest("local"))
        assert cfg.location == "local"
        with patch(
            "lib.requirements.check_nest",
            return_value=[],
        ):
            result = nests_lib.test_connection(nests_lib.get_nest("local"))
        assert result["ok"] is True
        assert "capability" in result["message"].lower()

    def test_resolve_identity_file(self):
        nest = {
            "id": "r1",
            "name": "R",
            "provider_type": "libvirt",
            "location": "remote",
            "transport": "ssh",
            "host": "h",
            "identity_file": "~/.ssh/id_ed25519",
        }
        assert nests_lib.resolve_identity_file(nest) == "~/.ssh/id_ed25519"

    def test_winrm_test_requires_password(self):
        nest = {
            "id": "w1",
            "name": "Win",
            "provider_type": "hyperv",
            "location": "remote",
            "transport": "winrm",
            "host": "win.example",
            "winrm_user": "Administrator",
        }
        result = nests_lib.test_connection(nest)
        assert result["ok"] is False
        assert "password" in result["message"].lower()

    def test_to_connection_config_ssh_and_winrm(self):
        ssh = nests_lib.normalize_nest(
            {
                "id": "s1",
                "name": "SSH",
                "provider_type": "libvirt",
                "location": "remote",
                "transport": "ssh",
                "host": "ssh.example",
                "port": 2222,
                "ssh_user": "nest",
                "identity_file": "/tmp/key",
            }
        )
        cfg = nests_lib.to_connection_config(ssh)
        assert cfg.transport == "ssh"
        assert cfg.ssh is not None
        assert cfg.ssh.port == 2222
        assert cfg.ssh.identity_file == "/tmp/key"

        win = nests_lib.normalize_nest(
            {
                "id": "w1",
                "name": "Win",
                "provider_type": "hyperv",
                "location": "remote",
                "transport": "winrm",
                "host": "win.example",
                "winrm_user": "Administrator",
                "port": 5986,
            }
        )
        wcfg = nests_lib.to_connection_config(win, winrm_password="secret")
        assert wcfg.transport == "winrm"
        assert wcfg.winrm is not None
        assert wcfg.winrm.password == "secret"
        assert wcfg.winrm.port == 5986

    def test_parse_rejects_bad_provider_and_duplicate(self):
        with pytest.raises(ValueError, match="unsupported provider_type"):
            nests_lib.normalize_nest(
                {
                    "id": "x",
                    "name": "X",
                    "provider_type": "vmware",
                    "location": "local",
                }
            )
        with pytest.raises(ValueError, match="duplicate"):
            nests_lib.parse_nests(
                [
                    {
                        "id": "local",
                        "name": "Local",
                        "provider_type": "libvirt",
                        "location": "local",
                    },
                    {
                        "id": "local",
                        "name": "Dup",
                        "provider_type": "libvirt",
                        "location": "local",
                    },
                ]
            )

    def test_remote_requires_host(self):
        with pytest.raises(ValueError, match="requires a host"):
            nests_lib.normalize_nest(
                {
                    "id": "r",
                    "name": "R",
                    "provider_type": "libvirt",
                    "location": "remote",
                }
            )

    def test_identities_for_expiry_from_nest_rows(self):
        local = nests_lib.get_nest("local")
        nests_lib.replace_nests(
            [
                local,
                {
                    "id": "lab1",
                    "name": "Lab",
                    "provider_type": "libvirt",
                    "location": "remote",
                    "host": "n.example",
                    "identity_file": "~/.ssh/nest",
                    "identity_expires_at": "2026-09-20",
                },
            ]
        )
        ids = nests_lib.identities_for_expiry()
        assert len(ids) == 1
        assert ids[0].id == "lab1"
        assert ids[0].identity_file == "~/.ssh/nest"
        assert ids[0].expires_at is not None

    def test_rejects_second_local_and_duplicate_name_or_endpoint(self):
        local = nests_lib.get_nest("local")
        # Non-builtin rows cannot stay local — coerced to remote, which needs a host.
        with pytest.raises(ValueError, match="requires a host"):
            nests_lib.replace_nests(
                [
                    local,
                    {
                        "id": "other",
                        "name": "Other local",
                        "provider_type": "libvirt",
                        "location": "local",
                    },
                ]
            )
        with pytest.raises(ValueError, match="duplicate Nest name"):
            nests_lib.replace_nests(
                [
                    local,
                    {
                        "id": "a1",
                        "name": "Lab",
                        "provider_type": "libvirt",
                        "location": "remote",
                        "host": "a.example",
                    },
                    {
                        "id": "a2",
                        "name": "lab",
                        "provider_type": "libvirt",
                        "location": "remote",
                        "host": "b.example",
                    },
                ]
            )
        with pytest.raises(ValueError, match="duplicate remote Nest endpoint"):
            nests_lib.replace_nests(
                [
                    local,
                    {
                        "id": "a1",
                        "name": "A",
                        "provider_type": "libvirt",
                        "location": "remote",
                        "host": "same.example",
                        "port": 22,
                        "transport": "ssh",
                    },
                    {
                        "id": "a2",
                        "name": "B",
                        "provider_type": "libvirt",
                        "location": "remote",
                        "host": "SAME.example",
                        "port": 22,
                        "transport": "ssh",
                    },
                ]
            )

    def test_allows_same_host_different_transport(self):
        local = nests_lib.get_nest("local")
        nests_lib.replace_nests(
            [
                local,
                {
                    "id": "ssh1",
                    "name": "Via SSH",
                    "provider_type": "hyperv",
                    "location": "remote",
                    "host": "win.example",
                    "transport": "ssh",
                    "port": 22,
                },
                {
                    "id": "wr1",
                    "name": "Via WinRM",
                    "provider_type": "hyperv",
                    "location": "remote",
                    "host": "win.example",
                    "transport": "winrm",
                    "port": 5985,
                    "winrm_user": "Administrator",
                },
            ]
        )
        assert len(nests_lib.list_nests()) == 3

    def test_non_local_id_forced_remote(self):
        nest = nests_lib.normalize_nest(
            {
                "id": "forced",
                "name": "Forced",
                "provider_type": "libvirt",
                "location": "local",
                "host": "ignored.example",
            }
        )
        assert nest["location"] == "remote"
        assert nest["host"] == "ignored.example"
