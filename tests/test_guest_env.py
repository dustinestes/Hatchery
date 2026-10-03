"""Tests for guest/Clutch environment helpers (#501 / ADR-0026)."""

from __future__ import annotations

import pytest

from lib import guest_env
from lib.clutch import GuestOS


class TestValidateUserEnvironment:
    def test_empty(self):
        assert guest_env.validate_user_environment(None) == {}
        assert guest_env.validate_user_environment({}) == {}

    def test_normalizes_values(self):
        assert guest_env.validate_user_environment({"FOO": 1}) == {"FOO": "1"}

    def test_rejects_reserved(self):
        with pytest.raises(ValueError, match="reserved"):
            guest_env.validate_user_environment({"hatchery_logs": "x"})

    def test_rejects_bad_identifier(self):
        with pytest.raises(ValueError, match="portable identifier"):
            guest_env.validate_user_environment({"1BAD": "x"})


class TestReservedAndMerge:
    def test_base_reserved_windows(self):
        env = guest_env.reserved_environment(GuestOS.WINDOWS)
        assert env["HATCHERY_ROOT"] == r"C:\Program Files\Hatchery"
        assert env["HATCHERY_LOGS"].endswith(r"\logs")
        assert "HATCHERY_SOFTWARE_PACKAGE" not in env
        assert "HATCHERY_SOFTWARE_LOG" not in env

    def test_software_scoped(self):
        env = guest_env.reserved_environment("win11", package_id="Hatchery.SoftwareExample.1.0.0")
        assert env["HATCHERY_SOFTWARE_PACKAGE"].endswith(
            r"\software\Hatchery.SoftwareExample.1.0.0"
        )
        assert env["HATCHERY_SOFTWARE_LOG"].endswith(
            r"\logs\software\Hatchery.SoftwareExample.1.0.0.log"
        )

    def test_merge_reserved_wins(self):
        reserved = guest_env.reserved_environment(GuestOS.WINDOWS)
        # validate rejects reserved user keys; merge still puts reserved last
        merged = guest_env.merge_guest_environment(reserved, {"MY_FLAG": "1"})
        assert merged["MY_FLAG"] == "1"
        assert merged["HATCHERY_ROOT"] == reserved["HATCHERY_ROOT"]


class TestShellAssignments:
    def test_powershell_escapes_quotes(self):
        text = guest_env.powershell_env_assignments({"FOO": "a'b"})
        assert text == "$env:FOO = 'a''b'\n"

    def test_posix_export(self):
        text = guest_env.posix_export_assignments({"FOO": "a'b"})
        assert "export FOO=" in text
        assert "a'\"'\"'b" in text

    def test_catalog_includes_software_scope(self):
        rows = guest_env.reserved_env_catalog(GuestOS.WINDOWS)
        scopes = {r["name"]: r["scope"] for r in rows}
        assert scopes["HATCHERY_ROOT"] == "always"
        assert scopes["HATCHERY_SOFTWARE_LOG"] == "software"
        persist = {r["name"]: r["persist"] for r in rows}
        assert persist["HATCHERY_ROOT"] == "machine"
        assert persist["HATCHERY_SOFTWARE_PACKAGE"] == "job"


class TestPersistPlanSummary:
    def test_lists_reserved_and_persist_entries(self):
        from lib.clutch import EnvironmentEntry, EnvMode, EnvScope

        lines = guest_env.persist_plan_summary(
            GuestOS.WINDOWS,
            [
                EnvironmentEntry(name="KEEP", value="1"),
                EnvironmentEntry(name="SKIP", value="1", persist=False),
                EnvironmentEntry(
                    name="PATH_EXTRA",
                    value=r"C:\Tools",
                    scope=EnvScope.USER,
                    mode=EnvMode.APPEND,
                ),
            ],
        )
        assert any(line.startswith("HATCHERY_ROOT") for line in lines)
        assert any("KEEP → Machine" in line for line in lines)
        assert any("PATH_EXTRA → User (append)" in line for line in lines)
        assert not any("SKIP" in line for line in lines)


class TestPersistScript:
    def test_replace_and_append(self):
        from lib.clutch import EnvironmentEntry, EnvMode, EnvScope

        body = guest_env.powershell_persist_script(
            reserved={"HATCHERY_ROOT": r"C:\Program Files\Hatchery"},
            entries=[
                EnvironmentEntry(name="MY_ROLE", value="dc"),
                EnvironmentEntry(
                    name="PATH",
                    value=r"C:\Tools",
                    scope=EnvScope.MACHINE,
                    mode=EnvMode.APPEND,
                ),
                EnvironmentEntry(name="SKIP", value="1", persist=False),
            ],
        )
        assert "HATCHERY_ROOT" in body
        assert "MY_ROLE" in body
        assert "PATH" in body
        assert "append" in body
        assert "SKIP" not in body
        assert "WM_SETTINGCHANGE" in body or "SendMessageTimeout" in body

    def test_persist_guest_environment_calls_winrm(self, monkeypatch):
        from lib.clutch import EnvironmentEntry

        class _Result:
            status_code = 0
            std_out = b"ok"
            std_err = b""

        class _Session:
            def run_ps(self, body):
                self.body = body
                return _Result()

        sess = _Session()
        monkeypatch.setattr("lib.provision._make_session", lambda *a, **k: sess)
        code, out = guest_env.persist_guest_environment(
            "10.0.0.1",
            "admin",
            "secret",
            guest_os=GuestOS.WINDOWS,
            entries=[EnvironmentEntry(name="MY_ROLE", value="dc")],
        )
        assert code == 0
        assert "MY_ROLE" in sess.body
        assert "HATCHERY_ROOT" in sess.body
