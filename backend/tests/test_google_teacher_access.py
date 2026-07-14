from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

import app
import auth_service
import schedule_store
from schedule_store import (
    FirestoreScheduleStore,
    FirestoreTenantDirectory,
    MemoryScheduleStore,
    MemoryTenantDirectory,
)
import teacher_portal


CLIENT = TestClient(app.app)


@pytest.fixture(autouse=True)
def tenant_directory(monkeypatch):
    directory = MemoryTenantDirectory("default-school", app.STORE)
    directory.upsert_school({
        "school_id": "default-school", "name": "測試學校",
        "domains": ["school.test"], "admin_emails": ["admin@school.test"],
        "active": True,
    })
    monkeypatch.setattr(app, "DEFAULT_SCHOOL_ID", "default-school")
    monkeypatch.setattr(app, "TENANT_DIRECTORY", directory)
    monkeypatch.setattr(app, "ADMIN_EMAILS", ())
    monkeypatch.setattr(app, "SUPER_ADMIN_EMAILS", ())
    return directory


def sample_snapshot(resource_class=False):
    subjects = {
        "國語文": {"hours": [0, 0, 1, 0, 0, 0], "room": "R00", "banned": [], "self": True},
        "英語文": {"hours": [0, 0, 1, 0, 0, 0], "room": "R00", "banned": [], "self": False},
    }
    return {
        "data": {
            "classes": [
                {"g": 3, "code": "3甲", "tutor": "王導師", "res": resource_class},
                {"g": 3, "code": "3乙", "tutor": "李導師", "res": False},
            ],
            "subjects": subjects,
            "assign": {
                "3甲": {"國語文": "王導師", "英語文": "陳科任"},
                "3乙": {"國語文": "李導師", "英語文": "陳科任"},
            },
            "override": {}, "locks": [], "limits": [], "rules": [], "blocked": [],
            "gslot": {"3": [[1] * 7 for _ in range(5)]}, "rooms": {"R00": 99},
            "roster": {"王導師": "導師", "李導師": "導師", "陳科任": "科任", "資源教師": "科任"},
            "resGroups": [], "tcap": {},
        },
        "schedule": {
            "3甲|二|2": {"s": "英語文", "t": "陳科任", "room": "R00"},
            "3乙|三|3": {"s": "英語文", "t": "陳科任", "room": "R00"},
        },
        "tutor_placements": {"3甲": {"一|1": "國語文"}},
        "overlay": [{"grp": "資源A", "code": "3甲", "subj": "國語文", "t": "資源教師", "d": "一", "p": 1}],
        "limits": [], "rules": [], "label": "測試正式課表",
    }


def principal(name, role, classes=()):
    return auth_service.Principal("sub-1", "teacher@school.test", name, role, tuple(classes))


def state(resource_class=False):
    return {"revision": "rev-1", "published_at": "2026-07-10T00:00:00+00:00",
            "snapshot": sample_snapshot(resource_class)}


def test_subject_teacher_sees_only_personal_timetable_and_cannot_edit():
    workspace = teacher_portal.build_teacher_workspace(
        state(), principal("陳科任", "subject_teacher"))

    assert {(row["code"], row["subject"]) for row in workspace["personal_schedule"]} == {
        ("3甲", "英語文"), ("3乙", "英語文")}
    assert workspace["editable_classes"] == []


def test_resource_teacher_personal_timetable_includes_overlay():
    workspace = teacher_portal.build_teacher_workspace(
        state(), principal("資源教師", "resource_teacher"))

    assert len(workspace["personal_schedule"]) == 1
    assert workspace["personal_schedule"][0]["source"] == "overlay"
    assert workspace["editable_classes"] == []


def test_native_language_staff_see_hard_locked_session_in_personal_timetable():
    native_state = state()
    native_state["snapshot"]["data"]["nativeBands"] = [{"g": 3, "d": "二", "p": 4}]
    native_state["snapshot"]["data"]["nativeGroups"] = [{
        "g": 3, "d": "二", "p": 4, "lang": "原民語(直播)",
        "grp": "三年級原民語直播組", "sources": ["3甲"],
        "t": "直播教師", "room": "電腦教室", "assistant": "協同教師",
    }]

    teacher_workspace = teacher_portal.build_teacher_workspace(
        native_state, principal("直播教師", "subject_teacher"))
    assistant_workspace = teacher_portal.build_teacher_workspace(
        native_state, principal("協同教師", "subject_teacher"))

    assert teacher_workspace["personal_schedule"] == [{
        "code": "3年級", "day": "二", "period": 4, "subject": "原民語(直播)",
        "teacher": "直播教師", "room": "電腦教室", "source": "native",
        "group": "三年級原民語直播組", "class_label": "3年級",
    }]
    assert assistant_workspace["personal_schedule"][0]["group"] == "三年級原民語直播組・直播協同"
    assert assistant_workspace["editable_classes"] == []


def test_homeroom_pool_never_exposes_native_language_for_manual_move():
    snapshot = sample_snapshot()
    snapshot["data"]["subjects"]["本土語文"] = {
        "hours": [0, 0, 1, 0, 0, 0], "room": "R00", "banned": [], "self": True,
    }
    snapshot["data"]["nativeLockEnabled"] = True
    classroom = snapshot["data"]["classes"][0]

    assert "本土語文" not in teacher_portal._allowed_pool(snapshot["data"], classroom)


def test_homeroom_pool_includes_native_language_when_optional_lock_is_off():
    snapshot = sample_snapshot()
    snapshot["data"]["subjects"]["本土語文"] = {
        "hours": [0, 0, 1, 0, 0, 0], "room": "R00", "banned": [], "self": True,
    }
    snapshot["data"]["nativeLockEnabled"] = False
    classroom = snapshot["data"]["classes"][0]

    assert teacher_portal._allowed_pool(snapshot["data"], classroom)["本土語文"] == 1


def test_class_subject_mode_overrides_schoolwide_tutor_default():
    snapshot = sample_snapshot()
    classroom = snapshot["data"]["classes"][0]
    snapshot["data"]["assignmentModes"] = {"3甲": {"國語文": "engine"}}

    assert "國語文" not in teacher_portal._allowed_pool(snapshot["data"], classroom)

    snapshot["data"]["assignmentModes"]["3甲"]["國語文"] = "tutor"
    assert teacher_portal._allowed_pool(snapshot["data"], classroom)["國語文"] == 1


def test_released_subject_is_never_editable_by_homeroom_teacher():
    snapshot = sample_snapshot()
    classroom = snapshot["data"]["classes"][0]
    snapshot["data"]["assign"]["3甲"]["國語文"] = "李導師"
    snapshot["data"]["assignmentModes"] = {"3甲": {"國語文": "tutor"}}

    assert "國語文" not in teacher_portal._allowed_pool(snapshot["data"], classroom)


def test_homeroom_cross_class_teaching_appears_in_personal_schedule():
    cross_state = state()
    cross_state["snapshot"]["schedule"]["3乙|三|4"] = {
        "s": "自然科學", "t": "王導師", "room": "R00",
    }

    workspace = teacher_portal.build_teacher_workspace(
        cross_state, principal("王導師", "homeroom_teacher", ("3甲",)))

    assert any(row["code"] == "3乙" and row["subject"] == "自然科學"
               for row in workspace["personal_schedule"])
    assert [item["class_code"] for item in workspace["editable_classes"]] == ["3甲"]


def test_homeroom_teacher_gets_own_editable_class_and_personal_timetable():
    workspace = teacher_portal.build_teacher_workspace(
        state(), principal("王導師", "homeroom_teacher", ("3甲",)))

    assert [item["class_code"] for item in workspace["editable_classes"]] == ["3甲"]
    assert workspace["personal_schedule"][0]["source"] == "tutor"


def test_homeroom_teacher_cannot_change_another_class():
    with pytest.raises(teacher_portal.TeacherChangeError, match="其他班級"):
        teacher_portal.validate_teacher_placements(
            state(), principal("王導師", "homeroom_teacher", ("3甲",)),
            "3乙", {"一|1": "國語文"})


def test_resource_bound_subject_is_rejected_server_side():
    resource_state = state(resource_class=True)
    resource_state["snapshot"]["tutor_placements"]["3甲"] = {}

    with pytest.raises(teacher_portal.TeacherChangeError, match="資源班綁課"):
        teacher_portal.validate_teacher_placements(
            resource_state, principal("王導師", "homeroom_teacher", ("3甲",)),
            "3甲", {"一|1": "國語文"})


def test_google_account_is_bound_on_first_authorized_login(monkeypatch):
    store = MemoryScheduleStore()
    store.import_teachers([{
        "email": "subject@school.test", "name": "陳科任", "role": "subject_teacher",
        "class_codes": [], "active": True,
    }])
    monkeypatch.setattr(app, "STORE", store)
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app, "GOOGLE_WORKSPACE_DOMAIN", "school.test")
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "google-subject-123", "subject@school.test", "Google Name", "school.test"))

    response = CLIENT.get("/auth/me", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json()["role"] == "subject_teacher"
    assert store.get_teacher("subject@school.test")["google_sub"] == "google-subject-123"


def test_school_admin_is_bound_to_google_subject(monkeypatch, tenant_directory):
    identity = {"subject": "admin-subject-1"}
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        identity["subject"], "admin@school.test", "學校承辦人", "school.test"))

    first = CLIENT.get("/auth/me", headers={"Authorization": "Bearer token"})
    identity["subject"] = "replacement-subject"
    replaced = CLIENT.get("/auth/me", headers={"Authorization": "Bearer token"})

    assert first.status_code == 200
    assert tenant_directory.get_school("default-school")["admin_subjects"] == {
        "admin@school.test": "admin-subject-1"}
    assert replaced.status_code == 403
    assert "綁定其他 Google 身分" in replaced.json()["detail"]


def test_teacher_record_cannot_grant_hidden_admin_role():
    store = MemoryScheduleStore()
    store.import_teachers([{
        "email": "hidden@school.test", "name": "隱藏管理員", "role": "admin",
        "class_codes": [], "active": True,
    }])
    identity = auth_service.GoogleIdentity(
        "hidden-subject", "hidden@school.test", "隱藏管理員", "school.test")

    with pytest.raises(auth_service.AuthorizationError, match="管理員權限必須"):
        auth_service.authorize_identity(
            identity, store, (), {"school_id": "default-school", "name": "測試學校"})


def test_teacher_csv_rejects_admin_role():
    with pytest.raises(ValueError, match="角色"):
        app._normalize_teacher_rows([{
            "教師姓名": "隱藏管理員", "學校Google帳號": "hidden@school.test",
            "角色": "admin", "負責班級": "",
        }])


def test_legacy_environment_admin_is_not_merged_after_school_setup(monkeypatch):
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app, "ADMIN_EMAILS", ("legacy@school.test",))
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "legacy-subject", "legacy@school.test", "舊管理員", "school.test"))

    response = CLIENT.get("/auth/me", headers={"Authorization": "Bearer token"})

    assert response.status_code == 403
    assert "教師名單" in response.json()["detail"]


def test_unlisted_google_account_is_denied(monkeypatch):
    monkeypatch.setattr(app, "STORE", MemoryScheduleStore())
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "unknown-subject", "unknown@school.test", "Unknown", "school.test"))

    response = CLIENT.get("/auth/me", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 403
    assert "教師名單" in response.json()["detail"]


def test_formal_solver_accepts_admin_google_login_and_rejects_anonymous(monkeypatch):
    monkeypatch.setattr(app, "API_KEY", "")
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app, "ADMIN_EMAILS", ("admin@school.test",))
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "admin-sub", "admin@school.test", "排課管理員", "school.test"))

    denied = CLIENT.post(
        "/solve", files={"file": ("bad.xlsx", b"not-excel", app.XLSX_MIME)})
    accepted = CLIENT.post(
        "/solve", headers={"Authorization": "Bearer admin-token"},
        files={"file": ("bad.xlsx", b"not-excel", app.XLSX_MIME)})

    assert denied.status_code == 401
    assert accepted.status_code == 422


def test_teacher_workspace_endpoint_filters_subject_teacher_data(monkeypatch):
    store = MemoryScheduleStore()
    store.import_teachers([{
        "email": "subject@school.test", "name": "陳科任", "role": "subject_teacher",
        "class_codes": [], "active": True,
    }])
    store.publish_snapshot(deepcopy(sample_snapshot()), "admin@school.test")
    monkeypatch.setattr(app, "STORE", store)
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "subject-sub", "subject@school.test", "陳科任", "school.test"))

    response = CLIENT.get("/teacher/workspace", headers={"Authorization": "Bearer token"})

    assert response.status_code == 200
    assert len(response.json()["personal_schedule"]) == 2
    assert response.json()["editable_classes"] == []


def test_admin_can_import_information_office_csv(monkeypatch):
    store = MemoryScheduleStore()
    monkeypatch.setattr(app, "STORE", store)
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app, "ADMIN_EMAILS", ("admin@school.test",))
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "admin-sub", "admin@school.test", "排課管理員", "school.test"))
    csv_data = (
        "教師姓名,學校Google帳號,角色,負責班級\n"
        "王導師,homeroom@school.test,導師,3甲\n"
        "陳科任,subject@school.test,科任,\n"
    ).encode("utf-8-sig")

    response = CLIENT.post(
        "/admin/teachers/import-csv",
        headers={"Authorization": "Bearer admin-token"},
        files={"file": ("teachers.csv", csv_data, "text/csv")},
        data={"replace": "true"},
    )

    assert response.status_code == 200
    assert response.json()["imported"] == 2
    assert store.get_teacher("homeroom@school.test")["class_codes"] == ["3甲"]


def test_homeroom_teacher_submission_waits_for_admin_approval(monkeypatch):
    store = MemoryScheduleStore()
    store.import_teachers([{
        "email": "homeroom@school.test", "name": "王導師", "role": "homeroom_teacher",
        "class_codes": ["3甲"], "active": True,
    }])
    source = deepcopy(sample_snapshot())
    source["tutor_placements"] = {}
    published = store.publish_snapshot(source, "admin@school.test")
    monkeypatch.setattr(app, "STORE", store)
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "homeroom-sub", "homeroom@school.test", "王導師", "school.test"))

    response = CLIENT.put(
        "/teacher/classes/3甲/placements",
        headers={"Authorization": "Bearer teacher-token"},
        json={"revision": published["revision"], "placements": {"一|1": "國語文"}},
    )

    assert response.status_code == 200
    assert response.json()["pending_review"] is True
    assert store.get_active_state()["snapshot"].get("tutor_placements", {}) == {}
    assert store.get_active_state()["pending_teacher_updates"]["3甲"]["placements"] == {
        "一|1": "國語文"}
    assert response.json()["update_sequence"] == 1

    workspace = CLIENT.get(
        "/teacher/workspace", headers={"Authorization": "Bearer teacher-token"})
    assert workspace.status_code == 200
    assert workspace.json()["editable_classes"][0]["pending_review"] is True
    assert workspace.json()["editable_classes"][0]["placements"] == {"一|1": "國語文"}

    monkeypatch.setattr(app, "ADMIN_EMAILS", ("admin@school.test",))
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "admin-sub", "admin@school.test", "排課管理員", "school.test"))
    updates = CLIENT.get(
        f"/admin/teacher-updates?revision={published['revision']}&after=0",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert updates.status_code == 200
    assert updates.json()["placements"] == {"3甲": {"一|1": "國語文"}}
    assert updates.json()["updates"]["3甲"]["submitted_by"] == "homeroom@school.test"

    approved = CLIENT.post(
        "/admin/teacher-updates/approve",
        headers={"Authorization": "Bearer admin-token"},
        json={"revision": published["revision"], "updates": {"3甲": 1}},
    )

    assert approved.status_code == 200
    assert approved.json()["approved_codes"] == ["3甲"]
    state = store.get_active_state()
    assert state["snapshot"]["tutor_placements"]["3甲"] == {"一|1": "國語文"}
    assert state["pending_teacher_updates"] == {}
    assert state["snapshot"]["teacher_updates"]["3甲"]["approved_by"] == "admin@school.test"


def test_published_versions_can_be_listed_and_restored():
    store = MemoryScheduleStore()
    first_snapshot = deepcopy(sample_snapshot())
    first_snapshot["label"] = "第一版"
    first = store.publish_snapshot(first_snapshot, "admin@school.test")
    second_snapshot = deepcopy(sample_snapshot())
    second_snapshot["label"] = "第二版"
    second = store.publish_snapshot(second_snapshot, "admin@school.test")

    versions = store.list_published_versions()
    restored = store.restore_published_version(first["revision"], "admin2@school.test")

    assert [item["revision"] for item in versions[:2]] == [second["revision"], first["revision"]]
    assert restored["revision"] not in {first["revision"], second["revision"]}
    assert restored["restored_from"] == first["revision"]
    assert store.get_active_state()["snapshot"]["label"] == "第一版"


def test_admin_can_list_and_restore_published_version_api(monkeypatch):
    store = MemoryScheduleStore()
    first_snapshot = deepcopy(sample_snapshot())
    first_snapshot["label"] = "第一版"
    first = store.publish_snapshot(first_snapshot, "admin@school.test")
    second_snapshot = deepcopy(sample_snapshot())
    second_snapshot["label"] = "第二版"
    second = store.publish_snapshot(second_snapshot, "admin@school.test")
    monkeypatch.setattr(app, "STORE", store)
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "admin-sub", "admin@school.test", "排課管理員", "school.test"))

    versions = CLIENT.get(
        "/admin/published-versions", headers={"Authorization": "Bearer admin-token"})
    restored = CLIENT.post(
        f"/admin/published-versions/{first['revision']}/restore",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert versions.status_code == 200
    assert versions.json()["active_revision"] == second["revision"]
    assert len(versions.json()["versions"]) == 2
    assert restored.status_code == 200
    assert restored.json()["restored_from"] == first["revision"]
    assert restored.json()["snapshot"]["label"] == "第一版"


def test_cloud_drafts_are_shared_by_school_coordinators():
    store = MemoryScheduleStore()
    snapshot = sample_snapshot()

    saved = store.save_draft(snapshot, "admin1@school.test", "revision-1")

    assert saved["active_revision"] == "revision-1"
    assert store.get_draft("admin1@school.test")["snapshot"]["label"] == "測試正式課表"
    assert store.get_draft("admin2@school.test")["snapshot"]["label"] == "測試正式課表"
    assert store.get_draft("admin2@school.test")["saved_by"] == "admin1@school.test"


def test_shared_draft_rejects_stale_coordinator_version():
    store = MemoryScheduleStore()
    snapshot = sample_snapshot()

    first = store.save_draft(snapshot, "admin1@school.test")
    second = store.save_draft(
        snapshot, "admin2@school.test", expected_draft_revision=first["draft_revision"])

    with pytest.raises(schedule_store.StoreConflictError, match="較新的案件"):
        store.save_draft(
            snapshot, "admin1@school.test", expected_draft_revision=first["draft_revision"])

    assert store.get_draft("admin1@school.test")["draft_revision"] == second["draft_revision"]


def test_shared_draft_rejects_empty_revision_after_first_save():
    store = MemoryScheduleStore()
    snapshot = sample_snapshot()

    store.save_draft(snapshot, "admin1@school.test", expected_draft_revision="")

    with pytest.raises(schedule_store.StoreConflictError, match="較新的案件"):
        store.save_draft(snapshot, "admin2@school.test", expected_draft_revision="")


def test_shared_draft_delete_removes_shared_and_legacy_copies():
    store = MemoryScheduleStore()
    saved = store.save_draft(sample_snapshot(), "admin1@school.test")
    store._drafts["legacy@school.test"] = {
        "saved_at": "2026-07-01T00:00:00+00:00", "saved_by": "legacy@school.test",
        "active_revision": "", "snapshot": sample_snapshot(),
    }

    deleted = store.delete_draft(saved["draft_revision"])

    assert deleted is True
    assert store.get_draft("admin2@school.test") is None
    assert store._drafts == {}


def test_shared_draft_delete_rejects_stale_revision():
    store = MemoryScheduleStore()
    first = store.save_draft(sample_snapshot(), "admin1@school.test")
    newer = store.save_draft(
        sample_snapshot(), "admin2@school.test",
        expected_draft_revision=first["draft_revision"],
    )

    with pytest.raises(schedule_store.StoreConflictError, match="較新的案件"):
        store.delete_draft(first["draft_revision"])

    assert store.get_draft("admin1@school.test")["draft_revision"] == newer["draft_revision"]


def test_memory_store_migrates_latest_legacy_draft_to_shared_copy():
    store = MemoryScheduleStore()
    older = {"saved_at": "2026-07-01T00:00:00+00:00", "saved_by": "old@school.test",
             "active_revision": "", "snapshot": {**sample_snapshot(), "label": "舊案件"}}
    latest = {"saved_at": "2026-07-02T00:00:00+00:00", "saved_by": "admin1@school.test",
              "active_revision": "rev-2", "snapshot": {**sample_snapshot(), "label": "最新案件"}}
    store._drafts["old@school.test"] = older
    store._drafts["admin1@school.test"] = latest

    restored = store.get_draft("admin2@school.test")

    assert restored["snapshot"]["label"] == "最新案件"
    assert restored["draft_revision"]
    assert store._drafts["shared"]["saved_by"] == "admin1@school.test"
    assert store._drafts["admin1@school.test"] == latest


def test_first_save_cannot_bypass_an_unmigrated_legacy_draft():
    store = MemoryScheduleStore()
    store._drafts["admin1@school.test"] = {
        "saved_at": "2026-07-02T00:00:00+00:00", "saved_by": "admin1@school.test",
        "active_revision": "", "snapshot": sample_snapshot(),
    }

    with pytest.raises(schedule_store.StoreConflictError, match="較新的案件"):
        store.save_draft(
            sample_snapshot(), "admin2@school.test", expected_draft_revision="")

    assert store._drafts["shared"]["saved_by"] == "admin1@school.test"


def test_firestore_draft_serializes_nested_timetable_arrays():
    class FakeSnapshot:
        exists = True

        def __init__(self, value):
            self.value = value

        def to_dict(self):
            return deepcopy(self.value)

    class FakeDocument:
        def __init__(self):
            self.value = None

        def set(self, value):
            self.value = deepcopy(value)

        def get(self):
            return FakeSnapshot(self.value)

    class FakeCollection:
        def __init__(self):
            self.documents = {}

        def document(self, key):
            return self.documents.setdefault(key, FakeDocument())

    store = object.__new__(FirestoreScheduleStore)
    store._drafts = FakeCollection()
    snapshot = sample_snapshot()
    snapshot["data"]["slot_matrix"] = [[1, 1, 0], [0, 1, 1]]

    store.save_draft(snapshot, "admin@school.test", "revision-1")
    persisted = store._drafts.document("shared").value
    restored = store.get_draft("admin@school.test")

    assert "snapshot" not in persisted
    assert isinstance(persisted["snapshot_json"], str)
    assert restored["snapshot"] == snapshot
    assert restored["active_revision"] == "revision-1"


def test_firestore_store_migrates_latest_legacy_draft_without_deleting_originals():
    class FakeSnapshot:
        def __init__(self, key, value):
            self.id = key
            self.value = deepcopy(value)
            self.exists = value is not None

        def to_dict(self):
            return deepcopy(self.value)

    class FakeDocument:
        def __init__(self, collection, key):
            self.collection = collection
            self.key = key

        def get(self, transaction=None):
            return FakeSnapshot(self.key, self.collection.values.get(self.key))

        def set(self, value):
            self.collection.values[self.key] = deepcopy(value)

    class FakeCollection:
        def __init__(self, values):
            self.values = deepcopy(values)

        def document(self, key):
            return FakeDocument(self, key)

        def stream(self):
            return [FakeSnapshot(key, value) for key, value in self.values.items()]

    class FakeTransaction:
        def set(self, ref, value):
            ref.set(value)

    class FakeClient:
        def transaction(self):
            return FakeTransaction()

    class FakeFirestore:
        @staticmethod
        def transactional(function):
            return function

    older = schedule_store._encode_snapshot_document({
        "saved_at": "2026-07-01T00:00:00+00:00", "saved_by": "old@school.test",
        "active_revision": "", "snapshot": {**sample_snapshot(), "label": "舊案件"},
    })
    latest = schedule_store._encode_snapshot_document({
        "saved_at": "2026-07-02T00:00:00+00:00", "saved_by": "admin1@school.test",
        "active_revision": "rev-2", "snapshot": {**sample_snapshot(), "label": "最新案件"},
    })
    store = object.__new__(FirestoreScheduleStore)
    store._drafts = FakeCollection({"old@school.test": older, "admin1@school.test": latest})
    store._client = FakeClient()
    store._firestore = FakeFirestore()

    restored = store.get_draft("admin2@school.test")

    assert restored["snapshot"]["label"] == "最新案件"
    assert restored["draft_revision"]
    assert "shared" in store._drafts.values
    assert "admin1@school.test" in store._drafts.values


def test_firestore_snapshot_decoder_supports_legacy_documents():
    class LegacySnapshot:
        exists = True

        def to_dict(self):
            return {"revision": "legacy", "snapshot": sample_snapshot()}

    class LegacyDocument:
        def get(self):
            return LegacySnapshot()

    store = object.__new__(FirestoreScheduleStore)
    store._state = LegacyDocument()

    restored = store.get_active_state()

    assert restored["revision"] == "legacy"
    assert restored["snapshot"]["label"] == "測試正式課表"


def test_admin_can_save_and_restore_cloud_draft(monkeypatch):
    store = MemoryScheduleStore()
    monkeypatch.setattr(app, "STORE", store)
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app, "ADMIN_EMAILS", ("admin@school.test",))
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "admin-sub", "admin@school.test", "排課管理員", "school.test"))
    source = sample_snapshot()
    payload = {
        "data": source["data"], "sol": None, "tp": {}, "ovl": [],
        "limits": [], "rules": [], "label": "尚未求解的排課草稿",
        "active_revision": "revision-1",
    }

    saved = CLIENT.put(
        "/admin/draft", headers={"Authorization": "Bearer admin-token"}, json=payload)
    restored = CLIENT.get(
        "/admin/draft", headers={"Authorization": "Bearer admin-token"})

    assert saved.status_code == 200
    assert saved.json()["draft_revision"]
    assert restored.status_code == 200
    assert restored.json()["active_revision"] == "revision-1"
    assert restored.json()["snapshot"]["schedule"] == {}
    assert restored.json()["snapshot"]["schedule_ready"] is False
    assert restored.json()["snapshot"]["label"] == "尚未求解的排課草稿"


def test_admin_draft_preserves_first_stage_schedule_readiness(monkeypatch):
    store = MemoryScheduleStore()
    monkeypatch.setattr(app, "STORE", store)
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app, "ADMIN_EMAILS", ("admin@school.test",))
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "admin-sub", "admin@school.test", "排課管理員", "school.test"))
    source = sample_snapshot()
    response = CLIENT.put("/admin/draft", headers={"Authorization": "Bearer admin-token"}, json={
        "data": source["data"], "sol": {}, "tp": {}, "ovl": [],
        "scheduleReady": True, "label": "第一階段已完成",
    })

    restored = CLIENT.get("/admin/draft", headers={"Authorization": "Bearer admin-token"})

    assert response.status_code == 200
    assert restored.json()["snapshot"]["schedule_ready"] is True


def test_admin_draft_api_rejects_stale_shared_version(monkeypatch):
    store = MemoryScheduleStore()
    monkeypatch.setattr(app, "STORE", store)
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app, "ADMIN_EMAILS", ("admin@school.test",))
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "admin-sub", "admin@school.test", "排課管理員", "school.test"))
    source = sample_snapshot()
    payload = {"data": source["data"], "sol": {}, "tp": {}, "ovl": [], "label": "案件"}

    first = CLIENT.put("/admin/draft", headers={"Authorization": "Bearer token"}, json=payload)
    stale_revision = first.json()["draft_revision"]
    newer = CLIENT.put("/admin/draft", headers={"Authorization": "Bearer token"},
                       json={**payload, "expected_draft_revision": stale_revision})
    conflict = CLIENT.put("/admin/draft", headers={"Authorization": "Bearer token"},
                          json={**payload, "expected_draft_revision": stale_revision})

    assert newer.status_code == 200
    assert conflict.status_code == 409
    assert "先載入雲端暫存" in conflict.json()["detail"]


def test_admin_can_delete_cloud_draft_without_deleting_published_schedule(monkeypatch):
    store = MemoryScheduleStore()
    monkeypatch.setattr(app, "STORE", store)
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app, "ADMIN_EMAILS", ("admin@school.test",))
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "admin-sub", "admin@school.test", "排課管理員", "school.test"))
    source = sample_snapshot()
    published = store.publish_snapshot(source, "admin@school.test")
    payload = {"data": source["data"], "sol": {}, "tp": {}, "ovl": [], "label": "案件"}
    saved = CLIENT.put(
        "/admin/draft", headers={"Authorization": "Bearer token"}, json=payload)

    deleted = CLIENT.delete(
        "/admin/draft",
        headers={"Authorization": "Bearer token"},
        params={"expected_draft_revision": saved.json()["draft_revision"]},
    )
    restored = CLIENT.get("/admin/draft", headers={"Authorization": "Bearer token"})

    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "published_schedule_preserved": True}
    assert restored.status_code == 404
    assert store.get_active_state()["revision"] == published["revision"]


def test_unknown_workspace_domain_is_denied_before_teacher_lookup(monkeypatch):
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "outsider-sub", "teacher@unknown.test", "外校教師", "unknown.test"))

    response = CLIENT.get("/auth/me", headers={"Authorization": "Bearer token"})

    assert response.status_code == 403
    assert "尚未加入系統" in response.json()["detail"]


def test_workspace_domain_routes_each_school_to_its_own_store(monkeypatch, tenant_directory):
    school_a = MemoryScheduleStore()
    school_a.import_teachers([{
        "email": "teacher@school.test", "name": "甲校教師", "role": "subject_teacher",
        "class_codes": [], "active": True,
    }])
    snapshot_a = sample_snapshot()
    snapshot_a["label"] = "甲校課表"
    school_a.publish_snapshot(snapshot_a, "admin@school.test")
    monkeypatch.setattr(app, "STORE", school_a)

    tenant_directory.upsert_school({
        "school_id": "school-b", "name": "乙校", "domains": ["school-b.test"],
        "admin_emails": ["admin@school-b.test"], "active": True,
    })
    school_b = tenant_directory.get_store("school-b")
    school_b.import_teachers([{
        "email": "teacher@school-b.test", "name": "乙校教師", "role": "subject_teacher",
        "class_codes": [], "active": True,
    }])
    snapshot_b = sample_snapshot()
    snapshot_b["label"] = "乙校課表"
    school_b.publish_snapshot(snapshot_b, "admin@school-b.test")
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "teacher-b-sub", "teacher@school-b.test", "乙校教師", "school-b.test"))

    response = CLIENT.get("/teacher/workspace", headers={"Authorization": "Bearer token"})

    assert response.status_code == 200
    assert response.json()["label"] == "乙校課表"
    assert school_a.get_teacher("teacher@school-b.test") is None


def test_shared_workspace_domain_routes_by_school_membership(monkeypatch, tenant_directory):
    tenant_directory.upsert_school({
        "school_id": "school-b", "name": "乙校", "domains": ["school.test"],
        "admin_emails": ["admin-b@school.test"], "active": True,
    })
    school_b = tenant_directory.get_store("school-b")
    school_b.import_teachers([{
        "email": "teacher-b@school.test", "name": "乙校教師", "role": "subject_teacher",
        "class_codes": [], "active": True,
    }])
    snapshot_b = deepcopy(sample_snapshot())
    snapshot_b["label"] = "乙校正式課表"
    snapshot_b["schedule"]["3甲|二|2"]["t"] = "乙校教師"
    school_b.publish_snapshot(snapshot_b, "admin-b@school.test")
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "teacher-b-sub", "teacher-b@school.test", "乙校教師", "school.test"))

    response = CLIENT.get(
        "/teacher/workspace", headers={"Authorization": "Bearer teacher-b-token"})

    assert response.status_code == 200
    assert response.json()["profile"]["school_id"] == "school-b"
    assert response.json()["label"] == "乙校正式課表"
    assert len(tenant_directory.get_schools_by_domain("school.test")) == 2


def test_only_super_admin_can_create_school(monkeypatch, tenant_directory):
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app, "SUPER_ADMIN_EMAILS", ("owner@school.test",))
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "owner-sub", "owner@school.test", "平台管理員", "school.test"))
    payload = {
        "moe_code": "123456", "name": "乙校", "domains": ["school-b.test"],
        "admin_emails": ["admin@school-b.test"], "active": True,
    }

    created = CLIENT.put(
        "/platform/schools/school-b", headers={"Authorization": "Bearer owner-token"}, json=payload)
    duplicate = CLIENT.put(
        "/platform/schools/school-c", headers={"Authorization": "Bearer owner-token"},
        json={**payload, "name": "丙校", "admin_emails": ["admin2@school-b.test"]})

    assert created.status_code == 200
    assert created.json()["school"]["school_id"] == "school-b"
    assert created.json()["school"]["moe_code"] == "123456"
    assert duplicate.status_code == 409
    assert tenant_directory.get_school_by_domain("school-b.test")["name"] == "乙校"


def test_moe_school_code_uses_six_digits_and_can_be_the_tenant_id():
    record = schedule_store.normalize_school_record({
        "school_id": "183622", "name": "內湖國小",
        "domains": ["nhps.hc.edu.tw"], "admin_emails": ["admin@nhps.hc.edu.tw"],
    })

    assert record["school_id"] == "183622"
    assert record["moe_code"] == "183622"
    with pytest.raises(ValueError, match="6 位數字"):
        schedule_store.normalize_school_record({
            "school_id": "legacy-school", "moe_code": "18362", "name": "測試學校",
            "domains": ["school.test"], "admin_emails": ["admin@school.test"],
        })


def test_school_admin_cannot_manage_tenant_directory(monkeypatch):
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "admin-sub", "admin@school.test", "學校承辦人", "school.test"))

    response = CLIENT.put(
        "/platform/schools/school-b",
        headers={"Authorization": "Bearer admin-token"},
        json={"name": "乙校", "domains": ["school-b.test"],
              "admin_emails": ["admin@school-b.test"], "active": True},
    )

    assert response.status_code == 403


def test_personal_google_super_admin_gets_platform_only_access(monkeypatch):
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app, "SUPER_ADMIN_EMAILS", ("chihhung1988@gmail.com",))
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "owner-sub", "chihhung1988@gmail.com", "平台管理員", ""))

    profile = CLIENT.get("/auth/me", headers={"Authorization": "Bearer owner-token"})
    schools = CLIENT.get("/platform/schools", headers={"Authorization": "Bearer owner-token"})
    school_draft = CLIENT.get("/admin/draft", headers={"Authorization": "Bearer owner-token"})

    assert profile.status_code == 200
    assert profile.json()["role"] == "platform_admin"
    assert profile.json()["school_id"] == ""
    assert profile.json()["is_super_admin"] is True
    assert schools.status_code == 200
    assert school_draft.status_code == 403


def test_firestore_directory_does_not_query_an_empty_hosted_domain():
    class ExplodingCollection:
        def document(self, _):
            raise AssertionError("empty hosted domain must not reach Firestore")

    directory = object.__new__(FirestoreTenantDirectory)
    directory._domains = ExplodingCollection()

    assert directory.get_school_by_domain("") is None


def test_school_admin_cannot_import_another_domains_teacher(monkeypatch):
    store = MemoryScheduleStore()
    monkeypatch.setattr(app, "STORE", store)
    monkeypatch.setattr(app, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(app.auth_service, "verify_google_token", lambda *args: auth_service.GoogleIdentity(
        "admin-sub", "admin@school.test", "學校承辦人", "school.test"))
    csv_data = (
        "教師姓名,學校Google帳號,角色,負責班級\n"
        "外校教師,teacher@other.test,科任,\n"
    ).encode("utf-8-sig")

    response = CLIENT.post(
        "/admin/teachers/import-csv",
        headers={"Authorization": "Bearer admin-token"},
        files={"file": ("teachers.csv", csv_data, "text/csv")},
        data={"replace": "true"},
    )

    assert response.status_code == 422
    assert "不屬於本校" in response.json()["detail"]
    assert store.get_teacher("teacher@other.test") is None


def test_cors_preflight_allows_formal_put_requests():
    response = CLIENT.options(
        "/admin/draft",
        headers={
            "Origin": "https://smallcannon-arch.github.io",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]
    assert "DELETE" in response.headers["access-control-allow-methods"]
    assert response.headers["access-control-allow-origin"] == "https://smallcannon-arch.github.io"
