from datetime import datetime, timedelta, timezone
from copy import deepcopy
from types import SimpleNamespace

from fastapi.testclient import TestClient
from google.api_core.datetime_helpers import DatetimeWithNanoseconds
import pytest

import app
import auth_service
import schedule_store
from schedule_store import FirestoreScheduleStore, MemoryScheduleStore, MemoryTenantDirectory
from usage_tracker import (
    FirestoreUsageTracker, MemoryUsageTracker, _as_datetime, _overview,
    enrich_overview,
)


CLIENT = TestClient(app.app)


@pytest.fixture
def school_directory(monkeypatch):
    store = MemoryScheduleStore()
    directory = MemoryTenantDirectory("default-school", store)
    directory.upsert_school({
        "school_id": "default-school", "moe_code": "123456", "name": "測試國小",
        "domains": ["school.test"], "admin_emails": ["admin@school.test"],
        "active": True,
    })
    tracker = MemoryUsageTracker()
    monkeypatch.setattr(app, "STORE", store)
    monkeypatch.setattr(app, "TENANT_DIRECTORY", directory)
    monkeypatch.setattr(app, "USAGE_TRACKER", tracker)
    monkeypatch.setattr(app, "DEFAULT_SCHOOL_ID", "default-school")
    monkeypatch.setattr(app, "ADMIN_EMAILS", ())
    monkeypatch.setattr(app, "SUPER_ADMIN_EMAILS", ())
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    return directory, tracker


def test_memory_usage_tracker_aggregates_events_without_personal_data():
    tracker = MemoryUsageTracker()
    now = datetime(2026, 7, 13, 8, tzinfo=timezone.utc)
    tracker.record("183622", "login", "admin", at=now)
    tracker.record("183622", "solve_success", "admin", at=now)
    tracker.record("183622", "teacher_save", "homeroom_teacher", at=now - timedelta(days=8))

    result = tracker.get_overview([{
        "school_id": "183622", "moe_code": "183622", "name": "內湖國小", "active": True,
    }], days=30, now=now)

    assert result["privacy"] == "aggregate_only"
    assert result["totals"]["active_7d"] == 1
    assert result["totals"]["login"] == 1
    assert result["totals"]["teacher_save"] == 1
    assert result["schools"][0]["events"]["solve_success"] == 1
    assert result["schools"][0]["last_events"]["login"] == now.isoformat()
    assert set(result["schools"][0]) == {
        "school_id", "moe_code", "name", "active", "created_at", "last_active_at",
        "last_events", "events", "roles",
    }


def test_usage_totals_contract_distinguishes_configured_and_enabled_schools():
    tracker = MemoryUsageTracker()

    result = tracker.get_overview([
        {"school_id": "school-a", "name": "甲校", "active": True},
        {"school_id": "school-b", "name": "乙校", "active": False},
    ])

    assert result["totals"]["configured_schools"] == 2
    assert result["totals"]["enabled_schools"] == 1


def test_usage_overview_derives_progress_and_attention_without_personal_data():
    now = datetime(2026, 7, 14, 8, tzinfo=timezone.utc)
    overview = {
        "generated_at": now.isoformat(),
        "totals": {},
        "schools": [{
            "school_id": "183622", "name": "內湖國小", "active": True,
            "created_at": (now - timedelta(days=20)).isoformat(),
            "last_active_at": (now - timedelta(days=8)).isoformat(),
            "events": {"login": 4, "solve_failed": 3, "solve_success": 1},
            "last_events": {"login": (now - timedelta(days=8)).isoformat()},
            "roles": {"admin": 4},
        }],
    }

    result = enrich_overview(overview, {"183622": {
        "has_draft": True, "schedule_ready": True, "has_published": False,
        "backup_count": 0, "classes": 16, "teachers": 32, "subjects": 12,
    }}, now=now)

    school = result["schools"][0]
    assert school["progress"] == "scheduled"
    assert school["attention"] == [
        "超過 7 日未操作", "近 30 日多次排課失敗",
        "尚未建立案件還原點", "已完成排課但尚未發布",
    ]
    assert result["totals"]["scheduled"] == 1
    assert result["totals"]["needs_attention"] == 1
    assert set(school) == {
        "school_id", "name", "active", "created_at", "last_active_at",
        "events", "last_events", "roles", "case", "progress", "attention",
    }
    assert set(school["case"]) <= {
        "metadata_unavailable", "has_draft", "draft_saved_at", "has_published",
        "published_at", "backup_count", "classes", "teachers", "subjects",
        "scheduled_entries", "schedule_ready", "has_unpublished_changes",
    }
    assert "label" not in school["case"]


def test_enrich_overview_accepts_missing_schools():
    result = enrich_overview({}, {})

    assert result["schools"] == []
    assert result["totals"]["needs_attention"] == 0


def test_case_lookup_uses_normalized_school_ids():
    overview = {"schools": [{
        "school_id": " School-A ", "name": "甲校", "active": True,
        "events": {}, "roles": {}, "last_events": {},
    }]}

    result = enrich_overview(overview, {
        "SCHOOL-A": {"has_draft": True, "schedule_ready": False},
        "   ": {"has_published": True},
    })

    assert result["schools"][0]["progress"] == "building"


def test_metadata_failure_is_unknown_and_attention_has_priority():
    now = datetime(2026, 7, 14, 8, tzinfo=timezone.utc)
    overview = {"generated_at": now.isoformat(), "schools": [{
        "school_id": "school-a", "name": "甲校", "active": True,
        "created_at": (now - timedelta(days=20)).isoformat(),
        "last_active_at": (now - timedelta(days=8)).isoformat(),
        "events": {"login": 5, "solve_failed": 4}, "roles": {}, "last_events": {},
    }]}

    result = enrich_overview(
        overview, {"school-a": {"metadata_unavailable": True}}, now=now)
    school = result["schools"][0]

    assert school["progress"] == "unknown"
    assert school["attention"][0] == "案件狀態暫時無法取得"
    assert school["attention"][:2] == ["案件狀態暫時無法取得", "超過 7 日未操作"]
    assert school["case"] == {"metadata_unavailable": True}
    assert result["totals"]["not_started"] == 0


def test_disabled_school_ignores_unavailable_metadata_and_attention():
    overview = {"schools": [{
        "school_id": "school-a", "name": "停用學校", "active": False,
        "events": {"solve_failed": 5}, "roles": {}, "last_events": {},
    }]}

    result = enrich_overview(overview, {"school-a": {
        "metadata_unavailable": True, "has_draft": True,
        "draft_saved_at": "2026-07-02T00:00:01+00:00",
        "published_at": "2026-07-02T00:00:00+00:00",
    }})
    school = result["schools"][0]

    assert school["progress"] == "disabled"
    assert school["attention"] == []
    assert "has_unpublished_changes" not in school["case"]
    assert result["totals"]["needs_attention"] == 0
    assert result["totals"]["not_started"] == 0


@pytest.mark.parametrize(("draft_saved_at", "published_at", "expected"), [
    ("2026-07-02T00:00:01+00:00", "2026-07-02T00:00:00+00:00", True),
    ("2026-07-01T23:59:59+00:00", "2026-07-02T00:00:00+00:00", False),
    ("2026-07-02T00:00:00+00:00", "2026-07-02T00:00:00+00:00", False),
    ("", "2026-07-02T00:00:00+00:00", False),
])
def test_published_case_reports_only_newer_unpublished_draft(
        draft_saved_at, published_at, expected):
    overview = {"schools": [{
        "school_id": "school-a", "name": "甲校", "active": True,
        "events": {}, "roles": {}, "last_events": {},
    }]}
    case = {
        "has_draft": True, "has_published": True,
        "draft_saved_at": draft_saved_at, "published_at": published_at,
    }

    school = enrich_overview(overview, {"school-a": case})["schools"][0]

    assert school["progress"] == "published"
    assert school["case"]["has_unpublished_changes"] is expected
    assert ("有未發布草稿變更" in school["attention"]) is expected


def test_backup_events_are_recorded_with_last_event_time():
    tracker = MemoryUsageTracker()
    now = datetime(2026, 7, 14, 8, tzinfo=timezone.utc)

    assert tracker.record("183622", "backup_create", "admin", at=now) is True
    result = tracker.get_overview([{
        "school_id": "183622", "name": "內湖國小", "active": True,
    }], now=now)

    assert result["totals"]["backup_create"] == 1
    assert result["schools"][0]["last_events"]["backup_create"] == now.isoformat()


def test_invalid_event_is_rejected_before_dynamic_fields_are_created():
    tracker = MemoryUsageTracker()

    assert tracker.record("school-a", "arbitrary_field", "admin") is False
    assert tracker._daily == {}
    assert tracker._summary == {}


def test_firestore_record_validates_event_and_writes_exact_summary_time():
    class FakeDocument:
        def __init__(self):
            self.writes = []

        def set(self, value, merge=False):
            self.writes.append((deepcopy(value), merge))

    class FakeCollection:
        def __init__(self):
            self.documents = {}

        def document(self, key):
            return self.documents.setdefault(key, FakeDocument())

    tracker = object.__new__(FirestoreUsageTracker)
    tracker._firestore = SimpleNamespace(Increment=lambda value: ("increment", value))
    tracker._summary = FakeCollection()
    tracker._daily = FakeCollection()
    now = datetime(2026, 7, 14, 8, tzinfo=timezone.utc)

    assert tracker.record(" School-A ", "not_allowed", "admin", at=now) is False
    assert tracker._summary.documents == {}
    assert tracker._daily.documents == {}
    assert tracker.record(" School-A ", "login", "admin", at=now) is True

    summary_payload, summary_merge = tracker._summary.documents["school-a"].writes[0]
    daily_payload, daily_merge = tracker._daily.documents[
        "2026-07-14__school-a"].writes[0]
    assert summary_merge is True and daily_merge is True
    assert summary_payload["last_login_at"] == now
    assert daily_payload["last_login_at"] == now
    assert not any(key.startswith("last_not_allowed") for key in summary_payload)


def test_datetime_inputs_and_legacy_fallback_remain_timezone_aware():
    now = datetime(2026, 7, 14, 8, tzinfo=timezone.utc)
    naive = datetime(2026, 7, 10, 12)
    assert _as_datetime(naive).tzinfo == timezone.utc
    firestore_timestamp = DatetimeWithNanoseconds(
        2026, 7, 10, 12, 30, tzinfo=timezone.utc)
    assert _as_datetime(firestore_timestamp) == firestore_timestamp

    fallback = _overview(
        [{"school_id": "school-a", "name": "甲校", "active": True}],
        [{"school_id": "school-a", "date": "2026-07-10", "events": {"login": 1}}],
        [], 30, now)
    assert fallback["schools"][0]["last_events"]["login"] == (
        "2026-07-10T00:00:00+00:00")

    exact = _overview(
        [{"school_id": "school-a", "name": "甲校", "active": True}],
        [{"school_id": "school-a", "date": "2026-07-10", "events": {"login": 1}}],
        [{"school_id": "school-a", "last_active_at": naive,
          "last_login_at": "2026-07-10T12:30:00Z"}], 30, now)
    assert exact["schools"][0]["last_events"]["login"] == (
        "2026-07-10T12:30:00+00:00")


def test_extract_aggregation_count_matches_firestore_2_28_contract():
    # google-cloud-firestore 2.28.0 returns QueryResultsList rows containing
    # AggregationResult objects, represented here by the nested list shape.
    assert schedule_store._extract_aggregation_count(
        [[SimpleNamespace(value=12)]]) == 12
    assert schedule_store._extract_aggregation_count(
        [[SimpleNamespace(value=0)]]) == 0
    assert schedule_store._extract_aggregation_count([]) == 0


@pytest.mark.parametrize("results", [
    [[]],
    [[SimpleNamespace(value=None)]],
    [[SimpleNamespace(value="12")]],
    [SimpleNamespace()],
])
def test_extract_aggregation_count_rejects_malformed_results(results):
    with pytest.raises(TypeError):
        schedule_store._extract_aggregation_count(results)


def test_case_overview_counts_all_backups_without_reading_backup_documents(caplog):
    class FakeSnapshot:
        def __init__(self, key, value):
            self.id = key
            self.value = deepcopy(value)
            self.exists = value is not None

        def to_dict(self):
            return deepcopy(self.value)

    class FakeDocument:
        def __init__(self, key, value=None):
            self.key = key
            self.value = value

        def get(self):
            return FakeSnapshot(self.key, self.value)

    class FakeDraftQuery:
        def __init__(self, values, ordered):
            self.values = values
            self.ordered = ordered
            self.limit_value = None

        def limit(self, value):
            self.limit_value = value
            return self

        def stream(self):
            values = list(self.values.items())
            if self.ordered:
                values = [item for item in values if "saved_at" in item[1]]
                values.sort(key=lambda item: item[1].get("saved_at", ""), reverse=True)
            return [FakeSnapshot(key, value) for key, value in values[:self.limit_value]]

    class FakeDraftCollection:
        def __init__(self, values):
            self.values = values
            self.query = None
            self.compatibility_query = None

        def document(self, key):
            return FakeDocument(key, self.values.get(key))

        def order_by(self, field, direction=None):
            assert field == "saved_at"
            assert direction == "DESCENDING"
            self.query = FakeDraftQuery(self.values, ordered=True)
            return self.query

        def limit(self, value):
            self.compatibility_query = FakeDraftQuery(self.values, ordered=False)
            return self.compatibility_query.limit(value)

    class FakeCountQuery:
        def __init__(self, value):
            self.value = value

        def get(self):
            # Matches google-cloud-firestore 2.28.0 QueryResultsList row shape.
            return [[SimpleNamespace(value=self.value)]]

    class FakeBackupCollection:
        def __init__(self, value):
            self.value = value
            self.alias = None

        def count(self, alias=None):
            self.alias = alias
            return FakeCountQuery(self.value)

        def stream(self):
            raise AssertionError("backup_count must not stream backup snapshots")

    latest = schedule_store._encode_snapshot_document({
        "saved_at": "2026-07-02T00:00:00+00:00", "saved_by": "admin@school.test",
        "snapshot": {"data": {"classes": [{"code": "1甲"}]}, "schedule_ready": False},
    })
    older = schedule_store._encode_snapshot_document({
        "saved_at": "2026-07-01T00:00:00+00:00", "saved_by": "old@school.test",
        "snapshot": {"data": {"classes": []}, "schedule_ready": False},
    })
    store = object.__new__(FirestoreScheduleStore)
    store._drafts = FakeDraftCollection({"old": older, "latest": latest})
    store._state = FakeDocument("active")
    store._backups = FakeBackupCollection(12)
    store._school = SimpleNamespace(id="school-a")
    store._firestore = SimpleNamespace(
        Query=SimpleNamespace(DESCENDING="DESCENDING"))

    result = store.get_case_overview()

    assert result["backup_count"] == 12
    assert result["classes"] == 1
    assert store._backups.alias == "backup_count"
    assert store._drafts.query.limit_value == schedule_store.LEGACY_DRAFT_SCAN_LIMIT
    assert store._drafts.compatibility_query is None

    missing_saved_at = schedule_store._encode_snapshot_document({
        "saved_by": "legacy@school.test",
        "snapshot": {"data": {"classes": [{"code": "1A"}]},
                     "schedule_ready": False},
    })
    legacy_store = object.__new__(FirestoreScheduleStore)
    legacy_store._drafts = FakeDraftCollection({"missing": missing_saved_at})
    legacy_store._state = FakeDocument("active")
    legacy_store._backups = FakeBackupCollection(0)
    legacy_store._school = SimpleNamespace(id="school-a")
    legacy_store._firestore = SimpleNamespace(
        Query=SimpleNamespace(DESCENDING="DESCENDING"))

    with caplog.at_level("WARNING"):
        legacy_result = legacy_store.get_case_overview()

    assert legacy_result["has_draft"] is True
    assert legacy_result["draft_saved_at"] == ""
    assert legacy_result["backup_count"] == 0
    assert legacy_store._drafts.query.limit_value == schedule_store.LEGACY_DRAFT_SCAN_LIMIT
    assert legacy_store._drafts.compatibility_query.limit_value == schedule_store.LEGACY_DRAFT_SCAN_LIMIT
    assert "bounded legacy draft fallback without saved_at" in caplog.text
    assert "legacy@school.test" not in caplog.text

    memory = MemoryScheduleStore()
    memory._backups = {str(index): {} for index in range(12)}
    assert memory.get_case_overview()["backup_count"] == 12


def test_school_login_is_counted_for_platform_overview(monkeypatch, school_directory):
    directory, tracker = school_directory
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args:
                        auth_service.GoogleIdentity(
                            "admin-sub", "admin@school.test", "排課管理員", "school.test"))

    response = CLIENT.get("/auth/me", headers={"Authorization": "Bearer token"})
    overview = tracker.get_overview(directory.list_schools())

    assert response.status_code == 200
    assert overview["totals"]["login"] == 1
    assert overview["schools"][0]["roles"]["admin"] == 1


def test_only_platform_admin_can_read_usage(monkeypatch, school_directory):
    directory, tracker = school_directory
    tracker.record("default-school", "publish", "admin")
    monkeypatch.setattr(app, "SUPER_ADMIN_EMAILS", ("owner@gmail.com",))
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args:
                        auth_service.GoogleIdentity(
                            "owner-sub", "owner@gmail.com", "平台管理員", ""))

    response = CLIENT.get("/platform/usage?days=30",
                          headers={"Authorization": "Bearer owner-token"})

    assert response.status_code == 200
    assert response.json()["totals"]["publish"] == 1
    assert response.json()["totals"]["configured_schools"] == 1
    assert response.json()["totals"]["enabled_schools"] == 1
    assert response.json()["schools"][0]["name"] == "測試國小"


def test_platform_usage_includes_case_progress_and_backup_state(monkeypatch, school_directory):
    directory, tracker = school_directory
    store = directory.get_store("default-school")
    snapshot = {
        "label": "廣測案件", "schedule_ready": True,
        "data": {"classes": [{"code": "1甲"}], "roster": {"T01": {}},
                 "subjects": {"國語文": {}}},
        "schedule": {"1甲|一|1": {"subj": "國語文", "t": "T01"}}, "overlay": [],
    }
    draft = store.save_draft(snapshot, "admin@school.test")
    store.create_backup(snapshot, "admin@school.test",
                        source_draft_revision=draft["draft_revision"])
    tracker.record("default-school", "draft_save", "admin")
    monkeypatch.setattr(app, "SUPER_ADMIN_EMAILS", ("owner@gmail.com",))
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args:
                        auth_service.GoogleIdentity(
                            "owner-sub", "owner@gmail.com", "平台管理員", ""))

    response = CLIENT.get("/platform/usage?days=30",
                          headers={"Authorization": "Bearer owner-token"})

    assert response.status_code == 200
    school = response.json()["schools"][0]
    assert school["progress"] == "scheduled"
    assert school["case"]["backup_count"] == 1
    assert school["case"]["classes"] == 1
    assert school["case"]["teachers"] == 1
    assert set(school["case"]) == {
        "has_draft", "draft_saved_at", "has_published", "published_at",
        "backup_count", "classes", "teachers", "subjects", "scheduled_entries",
        "schedule_ready", "has_unpublished_changes",
    }
    assert "label" not in school["case"]
    assert "snapshot" not in school["case"]


def test_platform_usage_isolates_one_school_metadata_failure(monkeypatch, school_directory):
    directory, tracker = school_directory
    directory.upsert_school({
        "school_id": "broken-school", "moe_code": "654321", "name": "故障測試校",
        "domains": ["broken.test"], "admin_emails": ["admin@broken.test"],
        "active": True,
    })
    original_get_store = directory.get_store

    def get_store(school_id):
        if school_id == "broken-school":
            raise RuntimeError("simulated metadata failure")
        return original_get_store(school_id)

    monkeypatch.setattr(directory, "get_store", get_store)
    monkeypatch.setattr(app, "SUPER_ADMIN_EMAILS", ("owner@gmail.com",))
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args:
                        auth_service.GoogleIdentity(
                            "owner-sub", "owner@gmail.com", "平台管理員", ""))

    response = CLIENT.get("/platform/usage?days=30",
                          headers={"Authorization": "Bearer owner-token"})

    assert response.status_code == 200
    schools = {item["school_id"]: item for item in response.json()["schools"]}
    assert schools["broken-school"]["progress"] == "unknown"
    assert schools["broken-school"]["attention"][0] == "案件狀態暫時無法取得"
    assert schools["broken-school"]["case"] == {"metadata_unavailable": True}
    assert schools["default-school"]["progress"] == "not_started"


def test_platform_usage_skips_case_metadata_for_disabled_school(
        monkeypatch, school_directory):
    directory, _ = school_directory
    directory.upsert_school({
        "school_id": "disabled-school", "moe_code": "654321", "name": "停用學校",
        "domains": ["disabled.test"], "admin_emails": ["admin@disabled.test"],
        "active": False,
    })
    original_get_store = directory.get_store
    calls = []

    def get_store(school_id):
        calls.append(school_id)
        if school_id == "disabled-school":
            raise AssertionError("disabled school metadata must not be queried")
        return original_get_store(school_id)

    monkeypatch.setattr(directory, "get_store", get_store)
    monkeypatch.setattr(app, "SUPER_ADMIN_EMAILS", ("owner@gmail.com",))
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args:
                        auth_service.GoogleIdentity(
                            "owner-sub", "owner@gmail.com", "平台管理員", ""))

    response = CLIENT.get("/platform/usage?days=30",
                          headers={"Authorization": "Bearer owner-token"})

    assert response.status_code == 200
    schools = {item["school_id"]: item for item in response.json()["schools"]}
    assert calls == ["default-school"]
    assert schools["disabled-school"]["progress"] == "disabled"
    assert schools["disabled-school"]["attention"] == []
    assert schools["disabled-school"]["case"] == {}
    assert response.json()["totals"]["configured_schools"] == 2
    assert response.json()["totals"]["enabled_schools"] == 1


def test_school_admin_cannot_read_platform_usage(monkeypatch, school_directory):
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args:
                        auth_service.GoogleIdentity(
                            "admin-sub", "admin@school.test", "排課管理員", "school.test"))

    response = CLIENT.get("/platform/usage",
                          headers={"Authorization": "Bearer admin-token"})

    assert response.status_code == 403
