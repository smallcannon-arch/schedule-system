# -*- coding: utf-8 -*-
"""Persistence adapters for teacher access and the published timetable."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import os
import re
import threading
import uuid

from auth_service import normalize_email


LOGGER = logging.getLogger(__name__)


class StoreConflictError(RuntimeError):
    pass


SCHOOL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,49}$")
MOE_SCHOOL_CODE_PATTERN = re.compile(r"^\d{6}$")
SHARED_DRAFT_ID = "shared"
LEGACY_DRAFT_SCAN_LIMIT = 20


def normalize_domain(value):
    return str(value or "").strip().lower().lstrip("@")


def normalize_school_id(value):
    school_id = str(value or "").strip().lower()
    if not SCHOOL_ID_PATTERN.fullmatch(school_id):
        raise ValueError("學校代碼須為 3 至 50 個小寫英文字母、數字或連字號")
    return school_id


def normalize_moe_school_code(value, school_id="", existing=None):
    code = str(value or "").strip()
    if not code:
        code = str((existing or {}).get("moe_code") or "").strip()
    if not code and MOE_SCHOOL_CODE_PATTERN.fullmatch(str(school_id or "")):
        code = str(school_id)
    if code and not MOE_SCHOOL_CODE_PATTERN.fullmatch(code):
        raise ValueError("教育部學校代碼須為 6 位數字")
    return code


def normalize_school_record(record, existing=None):
    school_id = normalize_school_id(record.get("school_id"))
    moe_code = normalize_moe_school_code(
        record.get("moe_code"), school_id=school_id, existing=existing)
    name = str(record.get("name") or "").strip()
    domains = sorted({normalize_domain(item) for item in record.get("domains") or [] if normalize_domain(item)})
    admin_emails = sorted({normalize_email(item) for item in record.get("admin_emails") or [] if normalize_email(item)})
    if not name:
        raise ValueError("請輸入學校名稱")
    if not domains:
        raise ValueError("每間學校至少需要一個 Google Workspace 網域")
    if not admin_emails:
        raise ValueError("每間學校至少需要一位排課承辦人")
    if len(domains) > 10:
        raise ValueError("單一學校最多設定 10 個 Workspace 網域")
    if len(admin_emails) > 20:
        raise ValueError("單一學校最多設定 20 位排課承辦人")
    if any("." not in domain or "/" in domain for domain in domains):
        raise ValueError("Google Workspace 網域格式不正確")
    if any(email.rsplit("@", 1)[-1] not in domains for email in admin_emails):
        raise ValueError("承辦人帳號必須屬於該校 Workspace 網域")
    existing_subjects = (existing or {}).get("admin_subjects") or {}
    admin_subjects = {
        email: str(existing_subjects.get(email) or "").strip()
        for email in admin_emails if str(existing_subjects.get(email) or "").strip()
    }
    now = utc_now()
    return {
        "school_id": school_id,
        "moe_code": moe_code,
        "name": name[:120],
        "domains": domains,
        "admin_emails": admin_emails,
        "admin_subjects": admin_subjects,
        "active": bool(record.get("active", True)),
        "created_at": (existing or {}).get("created_at") or now,
        "updated_at": now,
    }


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _encode_snapshot(snapshot):
    """Store complex timetable arrays without relying on Firestore nested entities."""
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))


def _decode_snapshot(document):
    value = deepcopy(document or {})
    encoded = value.pop("snapshot_json", None)
    if encoded is not None:
        value["snapshot"] = json.loads(encoded)
    return value


def _extract_aggregation_count(results):
    """Read Firestore count results without hiding malformed SDK responses."""
    if not results:
        return 0
    result = results[0]
    if isinstance(result, (list, tuple)):
        if not result:
            raise TypeError("Firestore count aggregation returned an empty result row")
        result = result[0]
    value = getattr(result, "value", None)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Firestore count aggregation result has no integer value")
    return value


def _encode_snapshot_document(document):
    value = deepcopy(document)
    value["snapshot_json"] = _encode_snapshot(value.pop("snapshot"))
    return value


def _snapshot_summary(snapshot):
    value = snapshot or {}
    data = value.get("data") or {}
    schedule = value.get("schedule") or {}
    overlays = value.get("overlay") or []
    return {
        "label": str(value.get("label") or "排課案件")[:120],
        "classes": len(data.get("classes") or []),
        "teachers": len(data.get("roster") or {}),
        "subjects": len(data.get("subjects") or {}),
        "scheduled_entries": len(schedule) + len(overlays),
        "schedule_ready": bool(value.get("schedule_ready")),
    }


def _case_overview_summary(snapshot):
    summary = _snapshot_summary(snapshot)
    summary.pop("label", None)
    return summary


def _backup_metadata(backup):
    return {key: deepcopy(backup.get(key)) for key in (
        "backup_id", "created_at", "created_by", "active_revision",
        "source_draft_revision", "summary")}


class MemoryScheduleStore:
    def __init__(self):
        self._teachers = {}
        self._state = None
        self._drafts = {}
        self._history = {}
        self._backups = {}
        self._lock = threading.RLock()

    def get_teacher(self, email):
        with self._lock:
            value = self._teachers.get(normalize_email(email))
            return deepcopy(value) if value else None

    def bind_google_subject(self, email, subject):
        with self._lock:
            key = normalize_email(email)
            if key not in self._teachers:
                raise StoreConflictError("教師名單已更新，請重新登入")
            current = str(self._teachers[key].get("google_sub") or "")
            if current and current != subject:
                raise StoreConflictError("教師帳號已綁定其他 Google 身分")
            self._teachers[key]["google_sub"] = subject

    def import_teachers(self, records, replace=True):
        with self._lock:
            previous = self._teachers
            imported = {} if replace else deepcopy(previous)
            for record in records:
                key = normalize_email(record["email"])
                value = deepcopy(record)
                value["email"] = key
                if key in previous and previous[key].get("google_sub"):
                    value["google_sub"] = previous[key]["google_sub"]
                imported[key] = value
            self._teachers = imported
            return len(records)

    def publish_snapshot(self, snapshot, published_by, restored_from=""):
        published_at = utc_now()
        state = {
            "revision": str(uuid.uuid4()),
            "published_at": published_at,
            "updated_at": published_at,
            "update_sequence": 0,
            "published_by": published_by,
            "restored_from": str(restored_from or ""),
            "pending_teacher_updates": {},
            "snapshot": deepcopy(snapshot),
        }
        with self._lock:
            self._state = state
            self._history[state["revision"]] = deepcopy(state)
        return deepcopy(state)

    def get_active_state(self):
        with self._lock:
            return deepcopy(self._state)

    def submit_teacher_placements(self, class_code, placements, expected_revision, updated_by):
        with self._lock:
            if not self._state:
                raise StoreConflictError("目前沒有已發布的正式課表")
            if self._state["revision"] != expected_revision:
                raise StoreConflictError("正式課表已更新，請重新載入後再調整")
            self._state["update_sequence"] = int(self._state.get("update_sequence") or 0) + 1
            self._state["updated_at"] = utc_now()
            self._state.setdefault("pending_teacher_updates", {})[class_code] = {
                "placements": deepcopy(placements),
                "submitted_at": self._state["updated_at"], "submitted_by": updated_by,
                "sequence": self._state["update_sequence"],
            }
            return deepcopy(self._state)

    def update_teacher_placements(self, class_code, placements, expected_revision, updated_by):
        return self.submit_teacher_placements(
            class_code, placements, expected_revision, updated_by)

    def approve_teacher_updates(self, expected_revision, expected_updates, approved_by):
        with self._lock:
            if not self._state or self._state.get("revision") != expected_revision:
                raise StoreConflictError("正式課表已更新，請重新載入後再確認")
            pending = self._state.setdefault("pending_teacher_updates", {})
            selected = {}
            for class_code, sequence in (expected_updates or {}).items():
                item = pending.get(str(class_code))
                if not item or int(item.get("sequence") or 0) != int(sequence or 0):
                    raise StoreConflictError("導師存檔已有更新，請重新讀取後再確認")
                selected[str(class_code)] = deepcopy(item)
            if not selected:
                raise StoreConflictError("目前沒有可確認的導師存檔")
            approved_at = utc_now()
            snapshot = self._state["snapshot"]
            approved = snapshot.setdefault("teacher_updates", {})
            for class_code, item in selected.items():
                snapshot.setdefault("tutor_placements", {})[class_code] = deepcopy(item["placements"])
                approved[class_code] = {
                    "submitted_at": item.get("submitted_at"),
                    "submitted_by": item.get("submitted_by"),
                    "approved_at": approved_at,
                    "approved_by": approved_by,
                    "sequence": int(item.get("sequence") or 0),
                }
                pending.pop(class_code, None)
            self._state["updated_at"] = approved_at
            self._history[self._state["revision"]] = deepcopy(self._state)
            return deepcopy(self._state)

    def list_published_versions(self, limit=20):
        with self._lock:
            states = sorted(
                self._history.values(),
                key=lambda item: str(item.get("published_at") or ""), reverse=True)
            return [self._version_metadata(item) for item in states[:max(1, int(limit))]]

    @staticmethod
    def _version_metadata(state):
        return {key: deepcopy(state.get(key)) for key in (
            "revision", "published_at", "updated_at", "published_by", "restored_from")}

    def restore_published_version(self, revision, restored_by):
        with self._lock:
            historical = self._history.get(str(revision or ""))
            if not historical:
                raise StoreConflictError("找不到指定的正式課表版本")
            snapshot = deepcopy(historical["snapshot"])
        return self.publish_snapshot(snapshot, restored_by, restored_from=revision)

    def save_draft(self, snapshot, saved_by, active_revision="", expected_draft_revision=""):
        with self._lock:
            if SHARED_DRAFT_ID not in self._drafts:
                self.get_draft(saved_by)
            current = self._drafts.get(SHARED_DRAFT_ID)
            current_revision = str((current or {}).get("draft_revision") or "")
            if expected_draft_revision != current_revision:
                raise StoreConflictError("另一位管理員已儲存較新的案件，請先載入雲端暫存")
            draft = {
                "draft_revision": str(uuid.uuid4()),
                "saved_at": utc_now(), "saved_by": saved_by,
                "active_revision": active_revision, "snapshot": deepcopy(snapshot),
            }
            self._drafts[SHARED_DRAFT_ID] = draft
        return deepcopy(draft)

    def get_draft(self, saved_by):
        with self._lock:
            value = self._drafts.get(SHARED_DRAFT_ID)
            if not value:
                legacy = [(key, item) for key, item in self._drafts.items()
                          if key != SHARED_DRAFT_ID and item]
                if legacy:
                    key, value = max(
                        legacy, key=lambda row: str(row[1].get("saved_at") or ""))
                    value = deepcopy(value)
                    value["draft_revision"] = str(value.get("draft_revision") or uuid.uuid4())
                    value["saved_at"] = value.get("saved_at") or utc_now()
                    value["saved_by"] = value.get("saved_by") or key
                    value["active_revision"] = str(value.get("active_revision") or "")
                    self._drafts[SHARED_DRAFT_ID] = deepcopy(value)
            return deepcopy(value) if value else None

    def delete_draft(self, expected_draft_revision=""):
        with self._lock:
            if SHARED_DRAFT_ID not in self._drafts:
                self.get_draft("")
            current = self._drafts.get(SHARED_DRAFT_ID)
            if not current:
                return False
            current_revision = str(current.get("draft_revision") or "")
            if str(expected_draft_revision or "") != current_revision:
                raise StoreConflictError("另一位管理員已儲存較新的案件，請先重新載入後再刪除")
            self._drafts.clear()
            return True

    def create_backup(self, snapshot, created_by, active_revision="",
                      source_draft_revision=""):
        backup = {
            "backup_id": str(uuid.uuid4()),
            "created_at": utc_now(),
            "created_by": created_by,
            "active_revision": str(active_revision or ""),
            "source_draft_revision": str(source_draft_revision or ""),
            "summary": _snapshot_summary(snapshot),
            "snapshot": deepcopy(snapshot),
        }
        with self._lock:
            self._backups[backup["backup_id"]] = backup
            ordered = sorted(
                self._backups.values(),
                key=lambda item: str(item.get("created_at") or ""), reverse=True)
            for item in ordered[10:]:
                self._backups.pop(item["backup_id"], None)
        return deepcopy(backup)

    def list_backups(self, limit=10):
        with self._lock:
            ordered = sorted(
                self._backups.values(),
                key=lambda item: str(item.get("created_at") or ""), reverse=True)
            return [_backup_metadata(item) for item in ordered[:max(1, min(int(limit), 10))]]

    def get_backup(self, backup_id):
        with self._lock:
            value = self._backups.get(str(backup_id or ""))
            return deepcopy(value) if value else None

    def get_case_overview(self):
        with self._lock:
            draft = self._drafts.get(SHARED_DRAFT_ID)
            if not draft:
                legacy = [item for key, item in self._drafts.items()
                          if key != SHARED_DRAFT_ID and item]
                draft = max(legacy, key=lambda item: str(item.get("saved_at") or "")) if legacy else None
            active = self._state
            snapshot = (draft or active or {}).get("snapshot") or {}
            return {
                "has_draft": bool(draft),
                "draft_saved_at": str((draft or {}).get("saved_at") or ""),
                "has_published": bool(active),
                "published_at": str((active or {}).get("published_at") or ""),
                "backup_count": len(self._backups),
                **_case_overview_summary(snapshot),
            }


class FirestoreScheduleStore:
    def __init__(self, project_id, school_id, client=None):
        from google.cloud import firestore

        self._firestore = firestore
        self._client = client or firestore.Client(project=project_id or None)
        self._school = self._client.collection("schedule_schools").document(school_id)
        self._teachers = self._school.collection("teachers")
        self._state = self._school.collection("state").document("active")
        self._drafts = self._school.collection("drafts")
        self._history = self._school.collection("published_versions")
        self._backups = self._school.collection("backups")

    def _teacher_ref(self, email):
        return self._teachers.document(normalize_email(email))

    def get_teacher(self, email):
        snapshot = self._teacher_ref(email).get()
        return snapshot.to_dict() if snapshot.exists else None

    def bind_google_subject(self, email, subject):
        transaction = self._client.transaction()
        ref = self._teacher_ref(email)

        @self._firestore.transactional
        def bind(tx):
            snapshot = ref.get(transaction=tx)
            if not snapshot.exists:
                raise StoreConflictError("教師名單已更新，請重新登入")
            current = str((snapshot.to_dict() or {}).get("google_sub") or "")
            if current and current != subject:
                raise StoreConflictError("教師帳號已綁定其他 Google 身分")
            tx.update(ref, {"google_sub": subject})

        bind(transaction)

    def import_teachers(self, records, replace=True):
        if replace:
            existing = list(self._teachers.stream())
            for start in range(0, len(existing), 450):
                batch = self._client.batch()
                for snapshot in existing[start:start + 450]:
                    batch.update(snapshot.reference, {"active": False})
                batch.commit()

        for start in range(0, len(records), 450):
            batch = self._client.batch()
            for record in records[start:start + 450]:
                ref = self._teacher_ref(record["email"])
                previous = ref.get()
                value = deepcopy(record)
                value["email"] = normalize_email(record["email"])
                if previous.exists and (previous.to_dict() or {}).get("google_sub"):
                    value["google_sub"] = previous.to_dict()["google_sub"]
                batch.set(ref, value, merge=True)
            batch.commit()
        return len(records)

    def publish_snapshot(self, snapshot, published_by, restored_from=""):
        published_at = utc_now()
        state = {
            "revision": str(uuid.uuid4()),
            "published_at": published_at,
            "updated_at": published_at,
            "update_sequence": 0,
            "published_by": published_by,
            "restored_from": str(restored_from or ""),
            "pending_teacher_updates": {},
            "snapshot": deepcopy(snapshot),
        }
        encoded = _encode_snapshot_document(state)
        batch = self._client.batch()
        batch.set(self._state, encoded)
        batch.set(self._history.document(state["revision"]), encoded)
        batch.commit()
        return state

    def get_active_state(self):
        snapshot = self._state.get()
        return _decode_snapshot(snapshot.to_dict()) if snapshot.exists else None

    def submit_teacher_placements(self, class_code, placements, expected_revision, updated_by):
        transaction = self._client.transaction()
        ref = self._state

        @self._firestore.transactional
        def update(tx):
            document = ref.get(transaction=tx)
            if not document.exists:
                raise StoreConflictError("目前沒有已發布的正式課表")
            state = _decode_snapshot(document.to_dict())
            if state.get("revision") != expected_revision:
                raise StoreConflictError("正式課表已更新，請重新載入後再調整")
            state["update_sequence"] = int(state.get("update_sequence") or 0) + 1
            state["updated_at"] = utc_now()
            state.setdefault("pending_teacher_updates", {})[class_code] = {
                "placements": deepcopy(placements),
                "submitted_at": state["updated_at"], "submitted_by": updated_by,
                "sequence": state["update_sequence"],
            }
            tx.set(ref, _encode_snapshot_document(state))
            return state

        return update(transaction)

    def update_teacher_placements(self, class_code, placements, expected_revision, updated_by):
        return self.submit_teacher_placements(
            class_code, placements, expected_revision, updated_by)

    def approve_teacher_updates(self, expected_revision, expected_updates, approved_by):
        transaction = self._client.transaction()
        ref = self._state

        @self._firestore.transactional
        def approve(tx):
            document = ref.get(transaction=tx)
            if not document.exists:
                raise StoreConflictError("目前沒有已發布的正式課表")
            state = _decode_snapshot(document.to_dict())
            if state.get("revision") != expected_revision:
                raise StoreConflictError("正式課表已更新，請重新載入後再確認")
            pending = state.setdefault("pending_teacher_updates", {})
            selected = {}
            for class_code, sequence in (expected_updates or {}).items():
                item = pending.get(str(class_code))
                if not item or int(item.get("sequence") or 0) != int(sequence or 0):
                    raise StoreConflictError("導師存檔已有更新，請重新讀取後再確認")
                selected[str(class_code)] = deepcopy(item)
            if not selected:
                raise StoreConflictError("目前沒有可確認的導師存檔")
            approved_at = utc_now()
            snapshot = state["snapshot"]
            approved_updates = snapshot.setdefault("teacher_updates", {})
            for class_code, item in selected.items():
                snapshot.setdefault("tutor_placements", {})[class_code] = deepcopy(item["placements"])
                approved_updates[class_code] = {
                    "submitted_at": item.get("submitted_at"),
                    "submitted_by": item.get("submitted_by"),
                    "approved_at": approved_at,
                    "approved_by": approved_by,
                    "sequence": int(item.get("sequence") or 0),
                }
                pending.pop(class_code, None)
            state["updated_at"] = approved_at
            encoded = _encode_snapshot_document(state)
            tx.set(ref, encoded)
            tx.set(self._history.document(state["revision"]), encoded)
            return state

        return approve(transaction)

    @staticmethod
    def _version_metadata(state):
        return {key: deepcopy(state.get(key)) for key in (
            "revision", "published_at", "updated_at", "published_by", "restored_from")}

    def list_published_versions(self, limit=20):
        states = []
        for document in self._history.stream():
            value = _decode_snapshot(document.to_dict())
            if value:
                states.append(value)
        if not states:
            active = self.get_active_state()
            if active and active.get("revision"):
                self._history.document(active["revision"]).set(_encode_snapshot_document(active))
                states.append(active)
        states.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
        return [self._version_metadata(item) for item in states[:max(1, int(limit))]]

    def restore_published_version(self, revision, restored_by):
        document = self._history.document(str(revision or "")).get()
        if not document.exists:
            raise StoreConflictError("找不到指定的正式課表版本")
        historical = _decode_snapshot(document.to_dict())
        return self.publish_snapshot(
            historical["snapshot"], restored_by, restored_from=revision)

    def save_draft(self, snapshot, saved_by, active_revision="", expected_draft_revision=""):
        ref = self._drafts.document(SHARED_DRAFT_ID)

        def make_draft(current):
            current_revision = str((current or {}).get("draft_revision") or "")
            if expected_draft_revision != current_revision:
                raise StoreConflictError("另一位管理員已儲存較新的案件，請先載入雲端暫存")
            return {
                "draft_revision": str(uuid.uuid4()),
                "saved_at": utc_now(), "saved_by": saved_by,
                "active_revision": active_revision, "snapshot": deepcopy(snapshot),
            }

        if hasattr(self, "_client") and hasattr(self, "_firestore"):
            if not ref.get().exists:
                self.get_draft(saved_by)
            transaction = self._client.transaction()

            @self._firestore.transactional
            def save(tx):
                current_snapshot = ref.get(transaction=tx)
                draft = make_draft(current_snapshot.to_dict() if current_snapshot.exists else None)
                tx.set(ref, _encode_snapshot_document(draft))
                return draft

            return save(transaction)

        current_snapshot = ref.get()
        draft = make_draft(current_snapshot.to_dict() if current_snapshot.exists else None)
        ref.set(_encode_snapshot_document(draft))
        return draft

    def get_draft(self, saved_by):
        ref = self._drafts.document(SHARED_DRAFT_ID)
        snapshot = ref.get()
        if snapshot.exists:
            return _decode_snapshot(snapshot.to_dict())

        legacy = []
        for document in self._drafts.stream():
            document_id = str(getattr(document, "id", "") or "")
            if document_id == SHARED_DRAFT_ID:
                continue
            value = _decode_snapshot(document.to_dict())
            if value and value.get("snapshot"):
                legacy.append((document_id, value))
        if not legacy:
            return None

        document_id, migrated = max(
            legacy, key=lambda row: str(row[1].get("saved_at") or ""))
        migrated = deepcopy(migrated)
        migrated["draft_revision"] = str(
            migrated.get("draft_revision") or uuid.uuid4())
        migrated["saved_at"] = migrated.get("saved_at") or utc_now()
        migrated["saved_by"] = migrated.get("saved_by") or document_id or normalize_email(saved_by)
        migrated["active_revision"] = str(migrated.get("active_revision") or "")

        transaction = self._client.transaction()

        @self._firestore.transactional
        def migrate(tx):
            current = ref.get(transaction=tx)
            if current.exists:
                return _decode_snapshot(current.to_dict())
            tx.set(ref, _encode_snapshot_document(migrated))
            return migrated

        return migrate(transaction)

    def delete_draft(self, expected_draft_revision=""):
        ref = self._drafts.document(SHARED_DRAFT_ID)
        if not ref.get().exists:
            self.get_draft("")
        document_ids = {
            str(getattr(document, "id", "") or "")
            for document in self._drafts.stream()
        }
        document_ids.discard("")
        document_ids.add(SHARED_DRAFT_ID)
        transaction = self._client.transaction()

        @self._firestore.transactional
        def remove(tx):
            current = ref.get(transaction=tx)
            if not current.exists:
                return False
            current_revision = str((current.to_dict() or {}).get("draft_revision") or "")
            if str(expected_draft_revision or "") != current_revision:
                raise StoreConflictError("另一位管理員已儲存較新的案件，請先重新載入後再刪除")
            for document_id in document_ids:
                tx.delete(self._drafts.document(document_id))
            return True

        return remove(transaction)

    def create_backup(self, snapshot, created_by, active_revision="",
                      source_draft_revision=""):
        backup = {
            "backup_id": str(uuid.uuid4()),
            "created_at": utc_now(),
            "created_by": created_by,
            "active_revision": str(active_revision or ""),
            "source_draft_revision": str(source_draft_revision or ""),
            "summary": _snapshot_summary(snapshot),
            "snapshot": deepcopy(snapshot),
        }
        self._backups.document(backup["backup_id"]).set(
            _encode_snapshot_document(backup))
        ordered = sorted(
            (document for document in self._backups.stream()),
            key=lambda document: str((_decode_snapshot(document.to_dict()) or {}).get("created_at") or ""),
            reverse=True)
        for document in ordered[10:]:
            document.reference.delete()
        return backup

    def list_backups(self, limit=10):
        values = [_decode_snapshot(document.to_dict()) for document in self._backups.stream()]
        values = [value for value in values if value]
        values.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return [_backup_metadata(item) for item in values[:max(1, min(int(limit), 10))]]

    def get_backup(self, backup_id):
        document = self._backups.document(str(backup_id or "")).get()
        return _decode_snapshot(document.to_dict()) if document.exists else None

    def get_case_overview(self):
        draft_document = self._drafts.document(SHARED_DRAFT_ID).get()
        draft = _decode_snapshot(draft_document.to_dict()) if draft_document.exists else None
        if not draft:
            query = self._drafts.order_by(
                "saved_at", direction=self._firestore.Query.DESCENDING).limit(
                    LEGACY_DRAFT_SCAN_LIMIT)
            for document in query.stream():
                if str(getattr(document, "id", "") or "") == SHARED_DRAFT_ID:
                    continue
                value = _decode_snapshot(document.to_dict())
                if value and value.get("snapshot"):
                    draft = value
                    break
        if not draft:
            compatibility_query = self._drafts.limit(LEGACY_DRAFT_SCAN_LIMIT)
            for document in compatibility_query.stream():
                if str(getattr(document, "id", "") or "") == SHARED_DRAFT_ID:
                    continue
                value = _decode_snapshot(document.to_dict())
                if value and value.get("snapshot") and not value.get("saved_at"):
                    LOGGER.warning(
                        "Using bounded legacy draft fallback without saved_at for school %s",
                        str(getattr(getattr(self, "_school", None), "id", "") or "unknown"))
                    draft = value
                    break
        active_document = self._state.get()
        active = _decode_snapshot(active_document.to_dict()) if active_document.exists else None
        snapshot = (draft or active or {}).get("snapshot") or {}
        backup_results = self._backups.count(alias="backup_count").get()
        backup_count = _extract_aggregation_count(backup_results)
        return {
            "has_draft": bool(draft),
            "draft_saved_at": str((draft or {}).get("saved_at") or ""),
            "has_published": bool(active),
            "published_at": str((active or {}).get("published_at") or ""),
            "backup_count": backup_count,
            **_case_overview_summary(snapshot),
        }


class MemoryTenantDirectory:
    def __init__(self, default_school_id="", default_store=None):
        self._schools = {}
        self._domains = {}
        self._stores = {}
        self._lock = threading.RLock()
        if default_school_id and default_store:
            self._stores[normalize_school_id(default_school_id)] = default_store

    def upsert_school(self, record):
        with self._lock:
            school_id = normalize_school_id(record.get("school_id"))
            existing = self._schools.get(school_id)
            value = normalize_school_record(record, existing)
            for domain in (existing or {}).get("domains", []):
                if domain not in value["domains"]:
                    school_ids = set(self._domains.get(domain) or ())
                    school_ids.discard(school_id)
                    if school_ids:
                        self._domains[domain] = school_ids
                    else:
                        self._domains.pop(domain, None)
            for domain in value["domains"]:
                self._domains.setdefault(domain, set()).add(school_id)
            self._schools[school_id] = value
            self._stores.setdefault(school_id, MemoryScheduleStore())
            return deepcopy(value)

    def ensure_school(self, record):
        school_id = normalize_school_id(record.get("school_id"))
        return self.get_school(school_id) or self.upsert_school(record)

    def get_school(self, school_id):
        with self._lock:
            value = self._schools.get(str(school_id or "").strip().lower())
            return deepcopy(value) if value else None

    def get_school_by_domain(self, domain):
        schools = self.get_schools_by_domain(domain)
        return schools[0] if len(schools) == 1 else None

    def get_schools_by_domain(self, domain):
        with self._lock:
            school_ids = sorted(self._domains.get(normalize_domain(domain)) or ())
            return [deepcopy(self._schools[school_id]) for school_id in school_ids
                    if school_id in self._schools]

    def list_schools(self):
        with self._lock:
            return [deepcopy(self._schools[key]) for key in sorted(self._schools)]

    def bind_admin_subject(self, school_id, email, subject):
        with self._lock:
            key = normalize_school_id(school_id)
            normalized_email = normalize_email(email)
            value = self._schools.get(key)
            if not value or normalized_email not in value.get("admin_emails", []):
                raise StoreConflictError("此帳號已不在學校管理員名單中")
            subjects = value.setdefault("admin_subjects", {})
            current = str(subjects.get(normalized_email) or "")
            if current and current != subject:
                raise StoreConflictError("此管理員帳號已綁定其他 Google 身分")
            if not current:
                subjects[normalized_email] = str(subject)
                value["updated_at"] = utc_now()

    def get_store(self, school_id):
        with self._lock:
            key = normalize_school_id(school_id)
            if key not in self._schools:
                raise StoreConflictError("找不到學校租戶")
            return self._stores.setdefault(key, MemoryScheduleStore())


class FirestoreTenantDirectory:
    def __init__(self, project_id):
        from google.cloud import firestore

        self._firestore = firestore
        self._project_id = project_id
        self._client = firestore.Client(project=project_id or None)
        self._schools = self._client.collection("schedule_schools")
        self._domains = self._client.collection("schedule_school_domains")
        self._stores = {}
        self._lock = threading.RLock()

    def upsert_school(self, record):
        school_id = normalize_school_id(record.get("school_id"))
        school_ref = self._schools.document(school_id)
        transaction = self._client.transaction()

        @self._firestore.transactional
        def save(tx):
            current = school_ref.get(transaction=tx)
            existing = current.to_dict() if current.exists else None
            value = normalize_school_record(record, existing)
            previous_domains = set((existing or {}).get("domains") or ())
            current_domains = set(value["domains"])
            domain_mappings = {}

            # Firestore transactions require every read to happen before the first write.
            for domain in sorted(previous_domains | current_domains):
                mapping_ref = self._domains.document(domain)
                mapping = mapping_ref.get(transaction=tx)
                mapping_value = mapping.to_dict() or {} if mapping.exists else {}
                school_ids = set(mapping_value.get("school_ids") or ())
                legacy_owner = str(mapping_value.get("school_id") or "")
                if legacy_owner:
                    school_ids.add(legacy_owner)
                domain_mappings[domain] = (mapping_ref, school_ids)

            for domain in sorted(previous_domains - current_domains):
                mapping_ref, school_ids = domain_mappings[domain]
                school_ids.discard(school_id)
                if school_ids:
                    tx.set(mapping_ref, {
                        "school_ids": sorted(school_ids), "updated_at": value["updated_at"]})
                else:
                    tx.delete(mapping_ref)
            tx.set(school_ref, value, merge=True)
            for domain in sorted(current_domains):
                mapping_ref, school_ids = domain_mappings[domain]
                school_ids.add(school_id)
                tx.set(mapping_ref, {
                    "school_ids": sorted(school_ids), "updated_at": value["updated_at"],
                })
            return value

        return save(transaction)

    def ensure_school(self, record):
        school_id = normalize_school_id(record.get("school_id"))
        return self.get_school(school_id) or self.upsert_school(record)

    def get_school(self, school_id):
        snapshot = self._schools.document(str(school_id or "").strip().lower()).get()
        return snapshot.to_dict() if snapshot.exists else None

    def get_school_by_domain(self, domain):
        schools = self.get_schools_by_domain(domain)
        return schools[0] if len(schools) == 1 else None

    def get_schools_by_domain(self, domain):
        normalized = normalize_domain(domain)
        if not normalized:
            return []
        mapping = self._domains.document(normalized).get()
        if not mapping.exists:
            return []
        value = mapping.to_dict() or {}
        school_ids = set(value.get("school_ids") or ())
        legacy_owner = str(value.get("school_id") or "")
        if legacy_owner:
            school_ids.add(legacy_owner)
        schools = [self.get_school(school_id) for school_id in sorted(school_ids)]
        return [school for school in schools if school]

    def list_schools(self):
        return sorted((snapshot.to_dict() for snapshot in self._schools.stream()),
                      key=lambda item: str(item.get("school_id") or ""))

    def bind_admin_subject(self, school_id, email, subject):
        key = normalize_school_id(school_id)
        normalized_email = normalize_email(email)
        school_ref = self._schools.document(key)
        transaction = self._client.transaction()

        @self._firestore.transactional
        def bind(tx):
            snapshot = school_ref.get(transaction=tx)
            if not snapshot.exists:
                raise StoreConflictError("找不到學校租戶")
            value = snapshot.to_dict() or {}
            if normalized_email not in value.get("admin_emails", []):
                raise StoreConflictError("此帳號已不在學校管理員名單中")
            subjects = dict(value.get("admin_subjects") or {})
            current = str(subjects.get(normalized_email) or "")
            if current and current != subject:
                raise StoreConflictError("此管理員帳號已綁定其他 Google 身分")
            if not current:
                subjects[normalized_email] = str(subject)
                tx.set(school_ref, {"admin_subjects": subjects, "updated_at": utc_now()}, merge=True)

        bind(transaction)

    def get_store(self, school_id):
        key = normalize_school_id(school_id)
        if not self.get_school(key):
            raise StoreConflictError("找不到學校租戶")
        with self._lock:
            if key not in self._stores:
                self._stores[key] = FirestoreScheduleStore(
                    self._project_id, key, client=self._client)
            return self._stores[key]


def create_store():
    backend = os.getenv("SCHEDULE_STORE", "memory").strip().lower()
    if backend == "firestore":
        return FirestoreScheduleStore(
            os.getenv("FIRESTORE_PROJECT_ID", "").strip(),
            os.getenv("SCHEDULE_SCHOOL_ID", "default-school").strip(),
        )
    return MemoryScheduleStore()


def create_tenant_directory(default_school_id, default_store):
    backend = os.getenv("SCHEDULE_STORE", "memory").strip().lower()
    if backend == "firestore":
        return FirestoreTenantDirectory(os.getenv("FIRESTORE_PROJECT_ID", "").strip())
    return MemoryTenantDirectory(default_school_id, default_store)
