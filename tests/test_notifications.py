import pytest

import lib.db as db_module
import lib.notifications as notif


@pytest.fixture(autouse=True)
def isolate_db(tmp_path):
    db_module.init_db(tmp_path / "hatchery.db")
    yield
    db_module._db_path = None


class TestRecord:
    def test_returns_int_id(self):
        nid = notif.record("activity", "test")
        assert isinstance(nid, int) and nid > 0

    def test_stored_in_db(self):
        notif.record("activity", "hello")
        rows = notif.list_recent()
        assert any(r["message"] == "hello" for r in rows)

    def test_invalid_tier_raises(self):
        with pytest.raises(ValueError, match="tier"):
            notif.record("bogus", "msg")

    def test_defaults_resolved_zero(self):
        notif.record("warning", "test")
        assert notif.list_recent()[0]["resolved"] == 0

    def test_defaults_dismissed_zero(self):
        notif.record("activity", "test")
        assert notif.list_recent()[0]["dismissed"] == 0

    def test_tier_stored_correctly(self):
        notif.record("warning", "a warning")
        assert notif.list_recent()[0]["tier"] == "warning"

    def test_created_at_is_set(self):
        notif.record("activity", "ts test")
        row = notif.list_recent()[0]
        assert row["created_at"] != "" and row["created_at"] is not None

    def test_trims_on_insert(self, monkeypatch):
        monkeypatch.setattr(db_module, "_MAX_NOTIFICATIONS", 3)
        for i in range(5):
            notif.record("activity", f"msg {i}")
        assert len(notif.list_recent(100)) == 3


class TestListRecent:
    def test_returns_list(self):
        assert isinstance(notif.list_recent(), list)

    def test_empty_when_no_notifications(self):
        assert notif.list_recent() == []

    def test_newest_first(self):
        notif.record("activity", "first")
        notif.record("activity", "second")
        rows = notif.list_recent()
        assert rows[0]["message"] == "second"
        assert rows[1]["message"] == "first"

    def test_respects_limit(self):
        for i in range(10):
            notif.record("activity", f"msg {i}")
        assert len(notif.list_recent(3)) == 3

    def test_returns_dicts(self):
        notif.record("activity", "test")
        assert isinstance(notif.list_recent()[0], dict)


class TestResolve:
    def test_marks_resolved(self):
        nid = notif.record("warning", "something broke")
        notif.resolve(nid)
        row = next(r for r in notif.list_recent() if r["id"] == nid)
        assert row["resolved"] == 1

    def test_does_not_affect_other_rows(self):
        nid1 = notif.record("warning", "one")
        nid2 = notif.record("warning", "two")
        notif.resolve(nid1)
        rows = {r["id"]: r for r in notif.list_recent()}
        assert rows[nid2]["resolved"] == 0


class TestDismiss:
    def test_marks_dismissed(self):
        nid = notif.record("activity", "done")
        notif.dismiss(nid)
        row = next(r for r in notif.list_recent() if r["id"] == nid)
        assert row["dismissed"] == 1

    def test_does_not_affect_other_rows(self):
        nid1 = notif.record("activity", "one")
        nid2 = notif.record("activity", "two")
        notif.dismiss(nid1)
        rows = {r["id"]: r for r in notif.list_recent()}
        assert rows[nid2]["dismissed"] == 0


class TestResolveByMessagePrefix:
    def test_resolves_matching_warnings(self):
        nid = notif.record("warning", "Missing requirement: virsh not found")
        notif.resolve_by_message_prefix("Missing requirement:")
        row = next(r for r in notif.list_recent() if r["id"] == nid)
        assert row["resolved"] == 1

    def test_only_resolves_matching_prefix(self):
        nid_match = notif.record("warning", "Missing requirement: foo")
        nid_other = notif.record("warning", "Different warning message")
        notif.resolve_by_message_prefix("Missing requirement:")
        rows = {r["id"]: r for r in notif.list_recent()}
        assert rows[nid_match]["resolved"] == 1
        assert rows[nid_other]["resolved"] == 0

    def test_does_not_resolve_activity_tier(self):
        nid = notif.record("activity", "Missing requirement: mentioned in activity")
        notif.resolve_by_message_prefix("Missing requirement:")
        row = next(r for r in notif.list_recent() if r["id"] == nid)
        assert row["resolved"] == 0

    def test_noop_when_no_matches(self):
        notif.record("warning", "Some other warning")
        notif.resolve_by_message_prefix("Nonexistent prefix:")
        assert notif.count_unresolved_warnings() == 1

    def test_idempotent_on_already_resolved(self):
        nid = notif.record("warning", "Missing requirement: already resolved")
        notif.resolve(nid)
        notif.resolve_by_message_prefix("Missing requirement:")
        row = next(r for r in notif.list_recent() if r["id"] == nid)
        assert row["resolved"] == 1


class TestCountUnresolvedWarnings:
    def test_zero_when_empty(self):
        assert notif.count_unresolved_warnings() == 0

    def test_counts_unresolved_warnings(self):
        notif.record("warning", "first warning")
        notif.record("warning", "second warning")
        assert notif.count_unresolved_warnings() == 2

    def test_excludes_resolved_warnings(self):
        nid = notif.record("warning", "resolved warning")
        notif.resolve(nid)
        notif.record("warning", "active warning")
        assert notif.count_unresolved_warnings() == 1

    def test_excludes_activity_tier(self):
        notif.record("activity", "not a warning")
        assert notif.count_unresolved_warnings() == 0

    def test_dismissed_warning_still_counts_as_unresolved(self):
        nid = notif.record("warning", "dismissed but not resolved")
        notif.dismiss(nid)
        assert notif.count_unresolved_warnings() == 1
