import pytest

import lib.db as db_module
import lib.hatch as hatch_lib


@pytest.fixture(autouse=True)
def isolate_db(tmp_path):
    db_module.init_db(tmp_path / "hatchery.db")
    yield
    db_module._db_path = None


# ── create_session ────────────────────────────────────────────────────────────


class TestCreateSession:
    def test_returns_string_uuid(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        assert isinstance(sid, str)
        assert len(sid) == 36  # uuid4

    def test_session_persists_in_db(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        sessions = hatch_lib.list_sessions()
        assert any(s["id"] == sid for s in sessions)

    def test_stores_clutch_file_and_name(self):
        sid = hatch_lib.create_session("my-lab.yaml", "My Lab")
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert s["clutch_file"] == "my-lab.yaml"
        assert s["clutch_name"] == "My Lab"

    def test_defaults_nest_to_local(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert s["nest"] == "local"

    def test_custom_nest(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab", nest="remote-host")
        # list_sessions defaults to "local" so it won't appear there
        sessions = hatch_lib.list_sessions("remote-host")
        assert any(s["id"] == sid for s in sessions)

    def test_hatched_at_is_set(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert s["hatched_at"]

    def test_completed_at_is_null_initially(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert s["completed_at"] is None

    def test_each_call_returns_unique_id(self):
        sid1 = hatch_lib.create_session("lab.yaml", "Lab")
        sid2 = hatch_lib.create_session("lab.yaml", "Lab")
        assert sid1 != sid2


# ── add_vm ────────────────────────────────────────────────────────────────────


class TestAddVm:
    def test_vm_appears_in_session(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert any(v["vm_name"] == "dc01" for v in s["vms"])

    def test_vm_starts_as_pending(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        vm = next(v for v in s["vms"] if v["vm_name"] == "dc01")
        assert vm["status"] == "pending"

    def test_multiple_vms_in_order(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm(sid, "ws01")
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        names = [v["vm_name"] for v in s["vms"]]
        assert names == ["dc01", "ws01"]


# ── set_vm_status ─────────────────────────────────────────────────────────────


class TestSetVmStatus:
    def _setup(self, vm_name="dc01"):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, vm_name)
        return sid

    def _get_vm(self, sid, vm_name="dc01"):
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        return next(v for v in s["vms"] if v["vm_name"] == vm_name)

    def test_pending_to_hatching_sets_started_at(self):
        sid = self._setup()
        hatch_lib.set_vm_status(sid, "dc01", "hatching")
        vm = self._get_vm(sid)
        assert vm["status"] == "hatching"
        assert vm["started_at"] is not None

    def test_hatching_to_fledged_sets_fledged_at(self):
        sid = self._setup()
        hatch_lib.set_vm_status(sid, "dc01", "hatching")
        hatch_lib.set_vm_status(sid, "dc01", "fledged")
        vm = self._get_vm(sid)
        assert vm["status"] == "fledged"
        assert vm["fledged_at"] is not None

    def test_failed_stores_error(self):
        sid = self._setup()
        hatch_lib.set_vm_status(sid, "dc01", "failed", error="disk not found")
        vm = self._get_vm(sid)
        assert vm["status"] == "failed"
        assert vm["error"] == "disk not found"

    def test_non_hatching_non_fledged_no_timestamps(self):
        sid = self._setup()
        hatch_lib.set_vm_status(sid, "dc01", "blocked")
        vm = self._get_vm(sid)
        assert vm["status"] == "blocked"
        assert vm["started_at"] is None
        assert vm["fledged_at"] is None

    def test_all_fledged_sets_session_completed_at(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm(sid, "ws01")
        hatch_lib.set_vm_status(sid, "dc01", "fledged")
        # Not all fledged yet — completed_at should still be null
        s = next(s for s in hatch_lib.list_sessions() if s["id"] == sid)
        assert s["completed_at"] is None
        hatch_lib.set_vm_status(sid, "ws01", "fledged")
        # Now all fledged — completed_at should be set
        s = next(s for s in hatch_lib.list_sessions() if s["id"] == sid)
        assert s["completed_at"] is not None

    def test_partial_fledged_does_not_set_completed_at(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm(sid, "ws01")
        hatch_lib.set_vm_status(sid, "dc01", "fledged")
        s = next(s for s in hatch_lib.list_sessions() if s["id"] == sid)
        assert s["completed_at"] is None


# ── set_vm_uuid ───────────────────────────────────────────────────────────────


class TestSetVmUuid:
    def _setup(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        return sid

    def _get_vm(self, sid):
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        return next(v for v in s["vms"] if v["vm_name"] == "dc01")

    def test_stores_uuid(self):
        sid = self._setup()
        hatch_lib.set_vm_uuid(sid, "dc01", "aabbccdd-1234-5678-abcd-000000000001")
        vm = self._get_vm(sid)
        assert vm["libvirt_uuid"] == "aabbccdd-1234-5678-abcd-000000000001"

    def test_uuid_is_none_before_set(self):
        sid = self._setup()
        vm = self._get_vm(sid)
        assert vm["libvirt_uuid"] is None

    def test_overwrites_existing_uuid(self):
        sid = self._setup()
        hatch_lib.set_vm_uuid(sid, "dc01", "aaaa-old")
        hatch_lib.set_vm_uuid(sid, "dc01", "bbbb-new")
        vm = self._get_vm(sid)
        assert vm["libvirt_uuid"] == "bbbb-new"

    def test_noop_when_vm_not_found(self):
        sid = self._setup()
        hatch_lib.set_vm_uuid(sid, "ghost", "some-uuid")
        vm = self._get_vm(sid)
        assert vm["libvirt_uuid"] is None


# ── update_vm_name ────────────────────────────────────────────────────────────


class TestUpdateVmName:
    def _setup(self, name="dc01"):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, name)
        return sid

    def test_updates_name(self):
        sid = self._setup("dc01")
        hatch_lib.update_vm_name(sid, "dc01", "dc01-renamed")
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        names = [v["vm_name"] for v in s["vms"]]
        assert "dc01-renamed" in names
        assert "dc01" not in names

    def test_noop_when_old_name_not_found(self):
        sid = self._setup("dc01")
        hatch_lib.update_vm_name(sid, "ghost", "newname")
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert s["vms"][0]["vm_name"] == "dc01"

    def test_preserves_status_after_rename(self):
        sid = self._setup("dc01")
        hatch_lib.set_vm_status(sid, "dc01", "hatching")
        hatch_lib.update_vm_name(sid, "dc01", "dc01-renamed")
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        vm = next(v for v in s["vms"] if v["vm_name"] == "dc01-renamed")
        assert vm["status"] == "hatching"


# ── _compute_session_status ───────────────────────────────────────────────────


class TestComputeSessionStatus:
    def _status(self, *statuses):
        vms = [{"status": s} for s in statuses]
        return hatch_lib._compute_session_status(vms)

    def test_empty_vms_returns_unknown(self):
        assert hatch_lib._compute_session_status([]) == "unknown"

    def test_all_pending_is_in_progress(self):
        assert self._status("pending") == "in_progress"

    def test_any_hatching_is_in_progress(self):
        assert self._status("fledged", "hatching") == "in_progress"

    def test_any_pending_is_in_progress(self):
        assert self._status("fledged", "pending") == "in_progress"

    def test_all_fledged_is_completed(self):
        assert self._status("fledged", "fledged") == "completed"

    def test_failed_with_no_active_is_failed(self):
        assert self._status("fledged", "failed") == "failed"

    def test_blocked_with_no_active_is_failed(self):
        assert self._status("blocked") == "failed"

    def test_culled_only_is_degraded(self):
        assert self._status("culled") == "degraded"

    def test_fledged_and_culled_is_degraded(self):
        assert self._status("fledged", "culled") == "degraded"

    def test_failed_takes_priority_over_culled(self):
        assert self._status("failed", "culled") == "failed"


# ── list_sessions ─────────────────────────────────────────────────────────────


class TestListSessions:
    def test_empty_when_no_sessions(self):
        assert hatch_lib.list_sessions() == []

    def test_returns_sessions_newest_first(self):
        hatch_lib.create_session("a.yaml", "A")
        hatch_lib.create_session("b.yaml", "B")
        sessions = hatch_lib.list_sessions()
        assert sessions[0]["clutch_file"] == "b.yaml"
        assert sessions[1]["clutch_file"] == "a.yaml"

    def test_filters_by_nest(self):
        hatch_lib.create_session("a.yaml", "A", nest="local")
        hatch_lib.create_session("b.yaml", "B", nest="remote")
        local = hatch_lib.list_sessions("local")
        remote = hatch_lib.list_sessions("remote")
        assert len(local) == 1 and local[0]["clutch_file"] == "a.yaml"
        assert len(remote) == 1 and remote[0]["clutch_file"] == "b.yaml"

    def test_session_includes_vms(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        sessions = hatch_lib.list_sessions()
        assert len(sessions[0]["vms"]) == 1

    def test_session_includes_computed_status(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        sessions = hatch_lib.list_sessions()
        assert sessions[0]["status"] == "in_progress"

    def test_session_status_completed_when_all_fledged(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.set_vm_status(sid, "dc01", "fledged")
        sessions = hatch_lib.list_sessions()
        assert sessions[0]["status"] == "completed"

    def test_excludes_archived_sessions(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.archive_session(sid)
        assert hatch_lib.list_sessions() == []

    def test_non_archived_sessions_still_appear(self):
        sid1 = hatch_lib.create_session("a.yaml", "A")
        sid2 = hatch_lib.create_session("b.yaml", "B")
        hatch_lib.archive_session(sid1)
        sessions = hatch_lib.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == sid2


# ── archive_session ───────────────────────────────────────────────────────────


class TestArchiveSession:
    def test_removes_session_from_list(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.archive_session(sid)
        assert all(s["id"] != sid for s in hatch_lib.list_sessions())

    def test_idempotent(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.archive_session(sid)
        hatch_lib.archive_session(sid)  # should not raise
        assert hatch_lib.list_sessions() == []

    def test_only_archives_target_session(self):
        sid1 = hatch_lib.create_session("a.yaml", "A")
        sid2 = hatch_lib.create_session("b.yaml", "B")
        hatch_lib.archive_session(sid1)
        sessions = hatch_lib.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == sid2

    def test_purges_session_children(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm_scripts(sid, "dc01", [_Script("a.ps1")])
        hatch_lib.add_event(sid, "dc01", "hatchery", "INFO", "Hatching")
        hatch_lib.archive_session(sid)
        assert hatch_lib.get_events(sid, "dc01") == []
        assert hatch_lib.get_vm_scripts(sid, "dc01") == []
        assert hatch_lib.get_vm_record(sid, "dc01") is None

    def test_purge_leaves_sibling_session_children(self):
        sid1 = hatch_lib.create_session("a.yaml", "A")
        sid2 = hatch_lib.create_session("b.yaml", "B")
        hatch_lib.add_vm(sid1, "dc01")
        hatch_lib.add_vm(sid2, "ws01")
        hatch_lib.add_event(sid1, "dc01", "hatchery", "INFO", "from A")
        hatch_lib.add_event(sid2, "ws01", "hatchery", "INFO", "from B")
        hatch_lib.archive_session(sid1)
        assert hatch_lib.get_events(sid1, "dc01") == []
        assert hatch_lib.get_vm_record(sid1, "dc01") is None
        events = hatch_lib.get_events(sid2, "ws01")
        assert len(events) == 1
        assert events[0]["message"] == "from B"
        assert hatch_lib.get_vm_record(sid2, "ws01") is not None


# ── archive_if_terminal ───────────────────────────────────────────────────────


class TestArchiveIfTerminal:
    def _degraded_session(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.set_vm_status(sid, "dc01", "culled")
        return sid

    def _failed_session(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.set_vm_status(sid, "dc01", "failed")
        return sid

    def _completed_session(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.set_vm_status(sid, "dc01", "fledged")
        return sid

    def test_archives_degraded_session(self):
        sid = self._degraded_session()
        result = hatch_lib.archive_if_terminal(sid)
        assert result is not None
        assert hatch_lib.list_sessions() == []

    def test_archives_failed_session(self):
        sid = self._failed_session()
        result = hatch_lib.archive_if_terminal(sid)
        assert result is not None
        assert hatch_lib.list_sessions() == []

    def test_purges_children_when_archiving(self):
        sid = self._failed_session()
        hatch_lib.add_vm_scripts(sid, "dc01", [_Script("a.ps1")])
        hatch_lib.add_event(sid, "dc01", "hatchery", "ERROR", "boom")
        result = hatch_lib.archive_if_terminal(sid)
        assert result is not None
        assert any(v["vm_name"] == "dc01" for v in result["vms"])
        assert hatch_lib.get_events(sid, "dc01") == []
        assert hatch_lib.get_vm_scripts(sid, "dc01") == []
        assert hatch_lib.get_vm_record(sid, "dc01") is None

    def test_does_not_archive_completed_session(self):
        sid = self._completed_session()
        result = hatch_lib.archive_if_terminal(sid)
        assert result is None
        assert len(hatch_lib.list_sessions()) == 1

    def test_does_not_archive_in_progress_session(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.set_vm_status(sid, "dc01", "hatching")
        result = hatch_lib.archive_if_terminal(sid)
        assert result is None
        assert len(hatch_lib.list_sessions()) == 1

    def test_returns_clutch_name_and_vms(self):
        sid = self._degraded_session()
        result = hatch_lib.archive_if_terminal(sid)
        assert result["clutch_name"] == "Lab"
        assert any(v["vm_name"] == "dc01" for v in result["vms"])

    def test_returns_none_if_already_archived(self):
        sid = self._degraded_session()
        hatch_lib.archive_session(sid)
        result = hatch_lib.archive_if_terminal(sid)
        assert result is None

    def test_returns_none_for_unknown_session(self):
        result = hatch_lib.archive_if_terminal("nonexistent-id")
        assert result is None

    def test_mixed_fledged_culled_is_archived(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm(sid, "ws01")
        hatch_lib.set_vm_status(sid, "dc01", "fledged")
        hatch_lib.set_vm_status(sid, "ws01", "culled")
        result = hatch_lib.archive_if_terminal(sid)
        assert result is not None


# ── add_vm credentials ────────────────────────────────────────────────────────


class TestAddVmCredentials:
    def test_stores_admin_username(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01", admin_username="alice")
        rec = hatch_lib.get_vm_record(sid, "dc01")
        assert rec is not None
        assert rec["admin_username"] == "alice"

    def test_stores_admin_password(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01", admin_password="s3cr3t")
        rec = hatch_lib.get_vm_record(sid, "dc01")
        assert rec is not None
        assert rec["admin_password"] == "s3cr3t"

    def test_credentials_default_to_none(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        rec = hatch_lib.get_vm_record(sid, "dc01")
        assert rec is not None
        assert rec["admin_username"] is None
        assert rec["admin_password"] is None


# ── get_vm_record ─────────────────────────────────────────────────────────────


class TestGetVmRecord:
    def test_returns_none_for_unknown_vm(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        assert hatch_lib.get_vm_record(sid, "missing") is None

    def test_returns_none_for_unknown_session(self):
        assert hatch_lib.get_vm_record("no-such-session", "dc01") is None

    def test_returns_record_with_expected_fields(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01", admin_username="admin", admin_password="pass")
        rec = hatch_lib.get_vm_record(sid, "dc01")
        assert rec is not None
        assert rec["vm_name"] == "dc01"
        assert rec["status"] == "pending"
        assert rec["admin_username"] == "admin"
        assert rec["admin_password"] == "pass"
        assert "started_at" in rec
        assert "fledged_at" in rec

    def test_returns_dict_not_row(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        rec = hatch_lib.get_vm_record(sid, "dc01")
        assert isinstance(rec, dict)


# ── add_vm_scripts ────────────────────────────────────────────────────────────


class _Script:
    """Minimal stand-in for AutomationScript in tests."""

    def __init__(self, name, reboot_after=False):
        self.name = name
        self.reboot_after = reboot_after


class TestAddVmScripts:
    def test_inserts_pending_rows(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm_scripts(sid, "dc01", [_Script("a.ps1"), _Script("b.ps1")])
        rows = hatch_lib.get_vm_scripts(sid, "dc01")
        assert len(rows) == 2
        assert all(r["status"] == "pending" for r in rows)

    def test_run_order_matches_list_position(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm_scripts(sid, "dc01", [_Script("a.ps1"), _Script("b.ps1")])
        rows = hatch_lib.get_vm_scripts(sid, "dc01")
        assert rows[0]["run_order"] == 0
        assert rows[1]["run_order"] == 1

    def test_stores_reboot_after(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm_scripts(sid, "dc01", [_Script("a.ps1", reboot_after=True)])
        rows = hatch_lib.get_vm_scripts(sid, "dc01")
        assert rows[0]["reboot_after"] == 1

    def test_noop_for_empty_list(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm_scripts(sid, "dc01", [])
        assert hatch_lib.get_vm_scripts(sid, "dc01") == []

    def test_stores_script_name(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm_scripts(sid, "dc01", [_Script("setup.ps1")])
        rows = hatch_lib.get_vm_scripts(sid, "dc01")
        assert rows[0]["script_name"] == "setup.ps1"


# ── get_vm_scripts ────────────────────────────────────────────────────────────


class TestGetVmScripts:
    def test_returns_empty_for_unknown_vm(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        assert hatch_lib.get_vm_scripts(sid, "missing") == []

    def test_ordered_by_run_order(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm_scripts(sid, "dc01", [_Script("z.ps1"), _Script("a.ps1")])
        rows = hatch_lib.get_vm_scripts(sid, "dc01")
        assert rows[0]["script_name"] == "z.ps1"
        assert rows[1]["script_name"] == "a.ps1"

    def test_returns_dicts(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm_scripts(sid, "dc01", [_Script("a.ps1")])
        rows = hatch_lib.get_vm_scripts(sid, "dc01")
        assert isinstance(rows[0], dict)

    def test_expected_fields_present(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm_scripts(sid, "dc01", [_Script("a.ps1")])
        row = hatch_lib.get_vm_scripts(sid, "dc01")[0]
        for field in (
            "script_name",
            "run_order",
            "reboot_after",
            "status",
            "exit_code",
            "output",
            "started_at",
            "completed_at",
        ):
            assert field in row


# ── set_script_status ─────────────────────────────────────────────────────────


class TestSetScriptStatus:
    def _setup(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm_scripts(sid, "dc01", [_Script("a.ps1"), _Script("b.ps1")])
        return sid

    def test_running_sets_started_at(self):
        sid = self._setup()
        hatch_lib.set_script_status(sid, "dc01", 0, "running")
        row = hatch_lib.get_vm_scripts(sid, "dc01")[0]
        assert row["status"] == "running"
        assert row["started_at"] is not None

    def test_succeeded_sets_completed_at_and_exit_code(self):
        sid = self._setup()
        hatch_lib.set_script_status(sid, "dc01", 0, "succeeded", exit_code=0, output="ok")
        row = hatch_lib.get_vm_scripts(sid, "dc01")[0]
        assert row["status"] == "succeeded"
        assert row["exit_code"] == 0
        assert row["output"] == "ok"
        assert row["completed_at"] is not None

    def test_failed_stores_exit_code_and_output(self):
        sid = self._setup()
        hatch_lib.set_script_status(sid, "dc01", 0, "failed", exit_code=1, output="error")
        row = hatch_lib.get_vm_scripts(sid, "dc01")[0]
        assert row["status"] == "failed"
        assert row["exit_code"] == 1
        assert row["output"] == "error"

    def test_skipped_sets_completed_at(self):
        sid = self._setup()
        hatch_lib.set_script_status(sid, "dc01", 1, "skipped")
        row = hatch_lib.get_vm_scripts(sid, "dc01")[1]
        assert row["status"] == "skipped"
        assert row["completed_at"] is not None

    def test_only_updates_target_run_order(self):
        sid = self._setup()
        hatch_lib.set_script_status(sid, "dc01", 0, "succeeded", exit_code=0)
        rows = hatch_lib.get_vm_scripts(sid, "dc01")
        assert rows[1]["status"] == "pending"


# ── reset_scripts_for_retry ───────────────────────────────────────────────────


class TestResetScriptsForRetry:
    def test_resets_failed_to_pending(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm_scripts(sid, "dc01", [_Script("a.ps1")])
        hatch_lib.set_script_status(sid, "dc01", 0, "failed", exit_code=1, output="err")
        hatch_lib.reset_scripts_for_retry(sid, "dc01")
        row = hatch_lib.get_vm_scripts(sid, "dc01")[0]
        assert row["status"] == "pending"
        assert row["exit_code"] is None
        assert row["output"] is None

    def test_resets_skipped_to_pending(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm_scripts(sid, "dc01", [_Script("a.ps1"), _Script("b.ps1")])
        hatch_lib.set_script_status(sid, "dc01", 0, "failed", exit_code=1)
        hatch_lib.set_script_status(sid, "dc01", 1, "skipped")
        hatch_lib.reset_scripts_for_retry(sid, "dc01")
        rows = hatch_lib.get_vm_scripts(sid, "dc01")
        assert all(r["status"] == "pending" for r in rows)

    def test_preserves_succeeded_scripts(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm_scripts(sid, "dc01", [_Script("a.ps1"), _Script("b.ps1")])
        hatch_lib.set_script_status(sid, "dc01", 0, "succeeded", exit_code=0)
        hatch_lib.set_script_status(sid, "dc01", 1, "failed", exit_code=1)
        hatch_lib.reset_scripts_for_retry(sid, "dc01")
        rows = hatch_lib.get_vm_scripts(sid, "dc01")
        assert rows[0]["status"] == "succeeded"
        assert rows[1]["status"] == "pending"


# ── update_vm_name syncs scripts ──────────────────────────────────────────────


class TestUpdateVmNameSyncsScripts:
    def test_scripts_follow_renamed_vm(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm_scripts(sid, "dc01", [_Script("setup.ps1")])
        hatch_lib.update_vm_name(sid, "dc01", "dc01-renamed")
        assert hatch_lib.get_vm_scripts(sid, "dc01") == []
        assert len(hatch_lib.get_vm_scripts(sid, "dc01-renamed")) == 1


# ── provisioning status in session compute ────────────────────────────────────


class TestComputeSessionStatusProvisioning:
    def test_provisioning_vm_means_in_progress(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.set_vm_status(sid, "dc01", "provisioning")
        sessions = hatch_lib.list_sessions()
        s = next(s for s in sessions if s["id"] == sid)
        assert s["status"] == "in_progress"


# ── parse_hatch_event_lines ───────────────────────────────────────────────────


class TestParseHatchEventLines:
    def test_info_line_parsed(self):
        events = hatch_lib.parse_hatch_event_lines("[HATCH:INFO] Script started")
        assert events == [
            {"level": "INFO", "component": None, "received_at": None, "message": "Script started"}
        ]

    def test_warn_line_parsed(self):
        events = hatch_lib.parse_hatch_event_lines("[HATCH:WARN] Key not found")
        assert events[0]["level"] == "WARN"

    def test_error_line_parsed(self):
        events = hatch_lib.parse_hatch_event_lines("[HATCH:ERROR] Install failed")
        assert events[0]["level"] == "ERROR"

    def test_component_label_parsed(self):
        events = hatch_lib.parse_hatch_event_lines("[HATCH:INFO][Chocolatey] Installing git")
        assert events[0]["component"] == "Chocolatey"
        assert events[0]["message"] == "Installing git"

    def test_no_component_is_none(self):
        events = hatch_lib.parse_hatch_event_lines("[HATCH:INFO] Done")
        assert events[0]["component"] is None

    def test_non_matching_lines_ignored(self):
        output = "[Hatchery] endpoint : http://...\n[HATCH:INFO] real line"
        events = hatch_lib.parse_hatch_event_lines(output)
        assert len(events) == 1
        assert events[0]["message"] == "real line"

    def test_empty_string_returns_empty_list(self):
        assert hatch_lib.parse_hatch_event_lines("") == []

    def test_multiple_events_in_order(self):
        output = "[HATCH:INFO] first\n[HATCH:WARN] second\n[HATCH:ERROR] third"
        events = hatch_lib.parse_hatch_event_lines(output)
        assert [e["level"] for e in events] == ["INFO", "WARN", "ERROR"]
        assert [e["message"] for e in events] == ["first", "second", "third"]

    def test_strips_whitespace_from_lines(self):
        events = hatch_lib.parse_hatch_event_lines("  [HATCH:INFO] padded  ")
        assert events[0]["message"] == "padded"

    def test_no_timestamp_returns_none(self):
        events = hatch_lib.parse_hatch_event_lines("[HATCH:INFO][step-1] Step 1 started: do thing")
        assert events[0]["received_at"] is None

    def test_timestamp_extracted(self):
        line = "[HATCH:INFO][step-1][2026-07-20T12:34:56+00:00] Step 1 succeeded: do thing"
        events = hatch_lib.parse_hatch_event_lines(line)
        assert events[0]["received_at"] == "2026-07-20T12:34:56+00:00"
        assert events[0]["component"] == "step-1"
        assert events[0]["message"] == "Step 1 succeeded: do thing"

    def test_timestamp_without_component(self):
        line = "[HATCH:INFO][2026-07-20T12:34:56+00:00] setup started"
        events = hatch_lib.parse_hatch_event_lines(line)
        assert events[0]["received_at"] == "2026-07-20T12:34:56+00:00"
        assert events[0]["component"] is None


# ── add_event / get_events ───────────────────────────────────────────────────


class TestAddEvent:
    def test_event_stored_and_retrievable(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_event(sid, "dc01", "hatchery", "INFO", "Starting provisioning")
        events = hatch_lib.get_events(sid, "dc01")
        assert len(events) == 1
        assert events[0]["message"] == "Starting provisioning"
        assert events[0]["level"] == "INFO"
        assert events[0]["context"] == "hatchery"

    def test_script_name_stored(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_event(sid, "dc01", "hatchery", "INFO", "msg", script_name="setup.ps1")
        events = hatch_lib.get_events(sid, "dc01")
        assert events[0]["script_name"] == "setup.ps1"

    def test_component_stored(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_event(sid, "dc01", "script", "INFO", "msg", component="Chocolatey")
        events = hatch_lib.get_events(sid, "dc01")
        assert events[0]["component"] == "Chocolatey"

    def test_guest_timestamp_stored_as_received_at(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_event(
            sid, "dc01", "script", "INFO", "msg", received_at="2026-07-20T12:34:56+00:00"
        )
        events = hatch_lib.get_events(sid, "dc01")
        assert events[0]["received_at"] == "2026-07-20T12:34:56+00:00"

    def test_received_at_defaults_to_host_time_when_none(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_event(sid, "dc01", "hatchery", "INFO", "msg")
        events = hatch_lib.get_events(sid, "dc01")
        assert events[0]["received_at"] is not None
        assert events[0]["received_at"] != "2026-07-20T12:34:56+00:00"

    def test_session_level_event_has_null_script_name(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_event(sid, "dc01", "hatchery", "INFO", "msg")
        events = hatch_lib.get_events(sid, "dc01")
        assert events[0]["script_name"] is None

    def test_received_at_is_set(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_event(sid, "dc01", "hatchery", "INFO", "msg")
        events = hatch_lib.get_events(sid, "dc01")
        assert events[0]["received_at"] is not None

    def test_multiple_events_in_insertion_order(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_event(sid, "dc01", "hatchery", "INFO", "first")
        hatch_lib.add_event(sid, "dc01", "script", "WARN", "second")
        hatch_lib.add_event(sid, "dc01", "hatchery", "INFO", "third")
        events = hatch_lib.get_events(sid, "dc01")
        assert [e["message"] for e in events] == ["first", "second", "third"]

    def test_events_isolated_by_vm(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_vm(sid, "ws01")
        hatch_lib.add_event(sid, "dc01", "hatchery", "INFO", "dc01 event")
        hatch_lib.add_event(sid, "ws01", "hatchery", "INFO", "ws01 event")
        dc_events = hatch_lib.get_events(sid, "dc01")
        ws_events = hatch_lib.get_events(sid, "ws01")
        assert len(dc_events) == 1 and dc_events[0]["message"] == "dc01 event"
        assert len(ws_events) == 1 and ws_events[0]["message"] == "ws01 event"


class TestGetEvents:
    def test_returns_empty_list_when_no_events(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        assert hatch_lib.get_events(sid, "dc01") == []

    def test_returns_dicts(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_event(sid, "dc01", "hatchery", "INFO", "msg")
        events = hatch_lib.get_events(sid, "dc01")
        assert isinstance(events[0], dict)

    def test_expected_fields_present(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_event(sid, "dc01", "hatchery", "INFO", "msg", script_name="a.ps1")
        event = hatch_lib.get_events(sid, "dc01")[0]
        for field in (
            "id",
            "context",
            "level",
            "script_name",
            "component",
            "message",
            "received_at",
        ):
            assert field in event


# ── get_last_script_event_messages ───────────────────────────────────────────


class TestGetLastScriptEventMessages:
    def test_returns_empty_when_no_events(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        assert hatch_lib.get_last_script_event_messages(sid, "dc01") == {}

    def test_returns_latest_message_per_script(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_event(sid, "dc01", "script", "INFO", "first", script_name="setup.ps1")
        hatch_lib.add_event(sid, "dc01", "script", "INFO", "second", script_name="setup.ps1")
        hatch_lib.add_event(sid, "dc01", "script", "WARN", "other", script_name="other.ps1")
        result = hatch_lib.get_last_script_event_messages(sid, "dc01")
        assert result == {"setup.ps1": "second", "other.ps1": "other"}

    def test_ignores_hatchery_context_and_null_script_name(self):
        sid = hatch_lib.create_session("lab.yaml", "Lab")
        hatch_lib.add_vm(sid, "dc01")
        hatch_lib.add_event(sid, "dc01", "hatchery", "INFO", "lifecycle")
        hatch_lib.add_event(
            sid, "dc01", "hatchery", "INFO", "script start", script_name="setup.ps1"
        )
        hatch_lib.add_event(sid, "dc01", "script", "INFO", "from script", script_name="setup.ps1")
        result = hatch_lib.get_last_script_event_messages(sid, "dc01")
        assert result == {"setup.ps1": "from script"}
