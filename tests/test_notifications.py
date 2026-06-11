import pytest

import lib.db as db_module
import lib.notifications as notif


@pytest.fixture(autouse=True)
def isolate_db(tmp_path):
    db_module.init_db(tmp_path / "hatchery.db")
    yield
    db_module._db_path = None


class TestRecordAlert:
    def test_returns_int_id(self):
        nid = notif.record_alert("disk full")
        assert isinstance(nid, int) and nid > 0

    def test_stored_in_db(self):
        notif.record_alert("disk full")
        rows = notif.list_recent()
        assert any(r["message"] == "disk full" for r in rows)

    def test_tier_is_alert(self):
        notif.record_alert("disk full")
        row = notif.list_recent()[0]
        assert row["tier"] == "alert"

    def test_defaults_resolved_zero(self):
        notif.record_alert("disk full")
        assert notif.list_recent()[0]["resolved"] == 0

    def test_resolved_at_null_on_creation(self):
        notif.record_alert("disk full")
        assert notif.list_recent()[0]["resolved_at"] is None

    def test_created_at_is_set(self):
        notif.record_alert("disk full")
        row = notif.list_recent()[0]
        assert row["created_at"] not in ("", None)

    def test_trims_on_insert(self, monkeypatch):
        monkeypatch.setattr(db_module, "_MAX_ALERTS", 3)
        for i in range(5):
            notif.record_alert(f"alert {i}")
        alert_rows = [r for r in notif.list_recent(100) if r["tier"] == "alert"]
        assert len(alert_rows) == 3


class TestRecordActivity:
    def test_returns_int_id(self):
        nid = notif.record_activity("VM hatched")
        assert isinstance(nid, int) and nid > 0

    def test_stored_in_db(self):
        notif.record_activity("VM hatched")
        rows = notif.list_recent()
        assert any(r["message"] == "VM hatched" for r in rows)

    def test_tier_is_activity(self):
        notif.record_activity("VM hatched")
        row = notif.list_recent()[0]
        assert row["tier"] == "activity"

    def test_resolved_always_zero(self):
        notif.record_activity("VM hatched")
        assert notif.list_recent()[0]["resolved"] == 0

    def test_resolved_at_always_null(self):
        notif.record_activity("VM hatched")
        assert notif.list_recent()[0]["resolved_at"] is None

    def test_created_at_is_set(self):
        notif.record_activity("VM hatched")
        row = notif.list_recent()[0]
        assert row["created_at"] not in ("", None)

    def test_trims_on_insert(self, monkeypatch):
        monkeypatch.setattr(db_module, "_MAX_ACTIVITY", 3)
        for i in range(5):
            notif.record_activity(f"activity {i}")
        activity_rows = [r for r in notif.list_recent(100) if r["tier"] == "activity"]
        assert len(activity_rows) == 3


class TestListRecent:
    def test_returns_list(self):
        assert isinstance(notif.list_recent(), list)

    def test_empty_when_no_notifications(self):
        assert notif.list_recent() == []

    def test_newest_first(self):
        notif.record_activity("first")
        notif.record_activity("second")
        rows = notif.list_recent()
        assert rows[0]["message"] == "second"
        assert rows[1]["message"] == "first"

    def test_respects_limit(self):
        for i in range(10):
            notif.record_activity(f"msg {i}")
        assert len(notif.list_recent(3)) == 3

    def test_returns_dicts(self):
        notif.record_activity("test")
        assert isinstance(notif.list_recent()[0], dict)

    def test_merges_both_tables(self):
        notif.record_alert("alert msg")
        notif.record_activity("activity msg")
        rows = notif.list_recent()
        tiers = {r["tier"] for r in rows}
        assert tiers == {"alert", "activity"}

    def test_alert_rows_include_resolved_field(self):
        notif.record_alert("alert msg")
        row = next(r for r in notif.list_recent() if r["tier"] == "alert")
        assert "resolved" in row

    def test_activity_rows_have_resolved_zero(self):
        notif.record_activity("activity msg")
        row = next(r for r in notif.list_recent() if r["tier"] == "activity")
        assert row["resolved"] == 0

    def test_activity_rows_have_resolved_at_null(self):
        notif.record_activity("activity msg")
        row = next(r for r in notif.list_recent() if r["tier"] == "activity")
        assert row["resolved_at"] is None


class TestResolve:
    def test_marks_resolved(self):
        nid = notif.record_alert("something broke")
        notif.resolve(nid)
        row = next(r for r in notif.list_recent() if r["id"] == nid and r["tier"] == "alert")
        assert row["resolved"] == 1

    def test_sets_resolved_at(self):
        nid = notif.record_alert("something broke")
        notif.resolve(nid)
        row = next(r for r in notif.list_recent() if r["id"] == nid and r["tier"] == "alert")
        assert row["resolved_at"] is not None

    def test_resolved_at_is_none_before_resolution(self):
        nid = notif.record_alert("something broke")
        row = next(r for r in notif.list_recent() if r["id"] == nid and r["tier"] == "alert")
        assert row["resolved_at"] is None

    def test_does_not_affect_other_alerts(self):
        nid1 = notif.record_alert("one")
        nid2 = notif.record_alert("two")
        notif.resolve(nid1)
        rows = {(r["id"], r["tier"]): r for r in notif.list_recent()}
        assert rows[(nid2, "alert")]["resolved"] == 0


class TestResolveAlertsByPrefix:
    def test_resolves_matching_alerts(self):
        nid = notif.record_alert("Missing requirement: virsh not found")
        notif.resolve_alerts_by_prefix("Missing requirement:")
        row = next(r for r in notif.list_recent() if r["id"] == nid and r["tier"] == "alert")
        assert row["resolved"] == 1

    def test_only_resolves_matching_prefix(self):
        nid_match = notif.record_alert("Missing requirement: foo")
        nid_other = notif.record_alert("Different alert message")
        notif.resolve_alerts_by_prefix("Missing requirement:")
        rows = {(r["id"], r["tier"]): r for r in notif.list_recent()}
        assert rows[(nid_match, "alert")]["resolved"] == 1
        assert rows[(nid_other, "alert")]["resolved"] == 0

    def test_sets_resolved_at_on_matching_alerts(self):
        nid = notif.record_alert("Missing requirement: virsh not found")
        notif.resolve_alerts_by_prefix("Missing requirement:")
        row = next(r for r in notif.list_recent() if r["id"] == nid and r["tier"] == "alert")
        assert row["resolved_at"] is not None

    def test_resolved_at_null_on_unresolved(self):
        nid = notif.record_alert("Missing requirement: virsh not found")
        row = next(r for r in notif.list_recent() if r["id"] == nid and r["tier"] == "alert")
        assert row["resolved_at"] is None

    def test_noop_when_no_matches(self):
        notif.record_alert("Some other alert")
        notif.resolve_alerts_by_prefix("Nonexistent prefix:")
        assert notif.count_active_alerts() == 1

    def test_idempotent_on_already_resolved(self):
        nid = notif.record_alert("Missing requirement: already resolved")
        notif.resolve(nid)
        notif.resolve_alerts_by_prefix("Missing requirement:")
        row = next(r for r in notif.list_recent() if r["id"] == nid and r["tier"] == "alert")
        assert row["resolved"] == 1


class TestHasActiveAlert:
    def test_returns_false_when_no_alerts(self):
        assert notif.has_active_alert("some alert") is False

    def test_returns_true_for_active_alert(self):
        notif.record_alert("virsh missing")
        assert notif.has_active_alert("virsh missing") is True

    def test_returns_false_after_alert_resolved(self):
        nid = notif.record_alert("virsh missing")
        notif.resolve(nid)
        assert notif.has_active_alert("virsh missing") is False

    def test_exact_match_only(self):
        notif.record_alert("virsh missing — details")
        assert notif.has_active_alert("virsh missing") is False


class TestCountActiveAlerts:
    def test_zero_when_empty(self):
        assert notif.count_active_alerts() == 0

    def test_counts_active_alerts(self):
        notif.record_alert("first alert")
        notif.record_alert("second alert")
        assert notif.count_active_alerts() == 2

    def test_excludes_resolved_alerts(self):
        nid = notif.record_alert("resolved alert")
        notif.resolve(nid)
        notif.record_alert("active alert")
        assert notif.count_active_alerts() == 1

    def test_excludes_activity_rows(self):
        notif.record_activity("not an alert")
        assert notif.count_active_alerts() == 0
