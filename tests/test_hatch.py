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
