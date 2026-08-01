import pytest

import lib.alerts as alerts
import lib.db as db_module


@pytest.fixture(autouse=True)
def isolate_db(tmp_path):
    db_module.init_db(tmp_path / "hatchery.db")
    yield
    db_module._db_path = None


class TestRecordAlert:
    def test_returns_int_id(self):
        nid = alerts.record_alert("disk full")
        assert isinstance(nid, int) and nid > 0

    def test_stored_in_db(self):
        alerts.record_alert("disk full")
        rows = alerts.list_recent()
        assert any(r["message"] == "disk full" for r in rows)

    def test_tier_is_alert(self):
        alerts.record_alert("disk full")
        row = alerts.list_recent()[0]
        assert row["tier"] == "alert"

    def test_defaults_resolved_zero(self):
        alerts.record_alert("disk full")
        assert alerts.list_recent()[0]["resolved"] == 0

    def test_resolved_at_null_on_creation(self):
        alerts.record_alert("disk full")
        assert alerts.list_recent()[0]["resolved_at"] is None

    def test_created_at_is_set(self):
        alerts.record_alert("disk full")
        row = alerts.list_recent()[0]
        assert row["created_at"] not in ("", None)

    def test_keeps_all_rows_on_insert(self):
        for i in range(5):
            alerts.record_alert(f"alert {i}")
        assert len(alerts.list_recent(100)) == 5


class TestListRecent:
    def test_returns_list(self):
        assert isinstance(alerts.list_recent(), list)

    def test_empty_when_no_alerts(self):
        assert alerts.list_recent() == []

    def test_newest_first(self):
        alerts.record_alert("first")
        alerts.record_alert("second")
        rows = alerts.list_recent()
        assert rows[0]["message"] == "second"
        assert rows[1]["message"] == "first"

    def test_respects_limit(self):
        for i in range(10):
            alerts.record_alert(f"msg {i}")
        assert len(alerts.list_recent(3)) == 3

    def test_returns_dicts(self):
        alerts.record_alert("test")
        assert isinstance(alerts.list_recent()[0], dict)

    def test_alert_rows_include_resolved_field(self):
        alerts.record_alert("alert msg")
        row = alerts.list_recent()[0]
        assert "resolved" in row


class TestResolve:
    def test_marks_resolved(self):
        nid = alerts.record_alert("something broke")
        alerts.resolve(nid)
        row = next(r for r in alerts.list_recent() if r["id"] == nid)
        assert row["resolved"] == 1

    def test_sets_resolved_at(self):
        nid = alerts.record_alert("something broke")
        alerts.resolve(nid)
        row = next(r for r in alerts.list_recent() if r["id"] == nid)
        assert row["resolved_at"] is not None

    def test_resolved_at_is_none_before_resolution(self):
        nid = alerts.record_alert("something broke")
        row = next(r for r in alerts.list_recent() if r["id"] == nid)
        assert row["resolved_at"] is None

    def test_does_not_affect_other_alerts(self):
        nid1 = alerts.record_alert("one")
        nid2 = alerts.record_alert("two")
        alerts.resolve(nid1)
        rows = {r["id"]: r for r in alerts.list_recent()}
        assert rows[nid2]["resolved"] == 0


class TestResolveAlertsByPrefix:
    def test_resolves_matching_alerts(self):
        nid = alerts.record_alert("Missing requirement: virsh not found")
        alerts.resolve_alerts_by_prefix("Missing requirement:")
        row = next(r for r in alerts.list_recent() if r["id"] == nid)
        assert row["resolved"] == 1

    def test_only_resolves_matching_prefix(self):
        nid_match = alerts.record_alert("Missing requirement: foo")
        nid_other = alerts.record_alert("Different alert message")
        alerts.resolve_alerts_by_prefix("Missing requirement:")
        rows = {r["id"]: r for r in alerts.list_recent()}
        assert rows[nid_match]["resolved"] == 1
        assert rows[nid_other]["resolved"] == 0

    def test_sets_resolved_at_on_matching_alerts(self):
        nid = alerts.record_alert("Missing requirement: virsh not found")
        alerts.resolve_alerts_by_prefix("Missing requirement:")
        row = next(r for r in alerts.list_recent() if r["id"] == nid)
        assert row["resolved_at"] is not None

    def test_resolved_at_null_on_unresolved(self):
        nid = alerts.record_alert("Missing requirement: virsh not found")
        row = next(r for r in alerts.list_recent() if r["id"] == nid)
        assert row["resolved_at"] is None

    def test_noop_when_no_matches(self):
        alerts.record_alert("Some other alert")
        alerts.resolve_alerts_by_prefix("Nonexistent prefix:")
        assert alerts.count_active_alerts() == 1

    def test_idempotent_on_already_resolved(self):
        nid = alerts.record_alert("Missing requirement: already resolved")
        alerts.resolve(nid)
        alerts.resolve_alerts_by_prefix("Missing requirement:")
        row = next(r for r in alerts.list_recent() if r["id"] == nid)
        assert row["resolved"] == 1


class TestHasActiveAlert:
    def test_returns_false_when_no_alerts(self):
        assert alerts.has_active_alert("some alert") is False

    def test_returns_true_for_active_alert(self):
        alerts.record_alert("virsh missing")
        assert alerts.has_active_alert("virsh missing") is True

    def test_returns_false_after_alert_resolved(self):
        nid = alerts.record_alert("virsh missing")
        alerts.resolve(nid)
        assert alerts.has_active_alert("virsh missing") is False

    def test_exact_match_only(self):
        alerts.record_alert("virsh missing — details")
        assert alerts.has_active_alert("virsh missing") is False


class TestCountActiveAlerts:
    def test_zero_when_empty(self):
        assert alerts.count_active_alerts() == 0

    def test_counts_active_alerts(self):
        alerts.record_alert("first alert")
        alerts.record_alert("second alert")
        assert alerts.count_active_alerts() == 2

    def test_excludes_resolved_alerts(self):
        nid = alerts.record_alert("resolved alert")
        alerts.resolve(nid)
        alerts.record_alert("active alert")
        assert alerts.count_active_alerts() == 1
