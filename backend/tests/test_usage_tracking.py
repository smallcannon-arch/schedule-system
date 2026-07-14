from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

import app
import auth_service
from schedule_store import MemoryScheduleStore, MemoryTenantDirectory
from usage_tracker import MemoryUsageTracker, enrich_overview


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
    assert "email" not in str(result).lower()


def test_backup_events_are_recorded_with_last_event_time():
    tracker = MemoryUsageTracker()
    now = datetime(2026, 7, 14, 8, tzinfo=timezone.utc)

    assert tracker.record("183622", "backup_create", "admin", at=now) is True
    result = tracker.get_overview([{
        "school_id": "183622", "name": "內湖國小", "active": True,
    }], now=now)

    assert result["totals"]["backup_create"] == 1
    assert result["schools"][0]["last_events"]["backup_create"] == now.isoformat()


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
    assert "label" not in school["case"]


def test_school_admin_cannot_read_platform_usage(monkeypatch, school_directory):
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args:
                        auth_service.GoogleIdentity(
                            "admin-sub", "admin@school.test", "排課管理員", "school.test"))

    response = CLIENT.get("/platform/usage",
                          headers={"Authorization": "Bearer admin-token"})

    assert response.status_code == 403
