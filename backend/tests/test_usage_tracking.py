from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

import app
import auth_service
from schedule_store import MemoryScheduleStore, MemoryTenantDirectory
from usage_tracker import MemoryUsageTracker


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
    assert set(result["schools"][0]) == {
        "school_id", "moe_code", "name", "active", "last_active_at", "events", "roles",
    }


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


def test_school_admin_cannot_read_platform_usage(monkeypatch, school_directory):
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args:
                        auth_service.GoogleIdentity(
                            "admin-sub", "admin@school.test", "排課管理員", "school.test"))

    response = CLIENT.get("/platform/usage",
                          headers={"Authorization": "Bearer admin-token"})

    assert response.status_code == 403
