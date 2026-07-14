# -*- coding: utf-8 -*-
"""Privacy-preserving aggregate usage tracking for the scheduling platform."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
import threading


ALLOWED_EVENTS = {
    "login", "draft_save", "draft_delete", "publish", "solve_success", "solve_failed",
    "teacher_open", "teacher_save", "teacher_import", "backup_create", "backup_restore",
}
ALLOWED_ROLES = {
    "admin", "homeroom_teacher", "subject_teacher", "resource_teacher",
}


def normalize_school_id(value):
    return str(value or "").strip().lower()


def _utc_now():
    return datetime.now(timezone.utc)


def _as_datetime(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _iso(value):
    parsed = _as_datetime(value)
    return parsed.astimezone(timezone.utc).isoformat() if parsed else ""


def _safe_counter(value):
    if not isinstance(value, dict):
        return {}
    return {str(key): max(0, int(count or 0)) for key, count in value.items()}


def _overview(schools, daily_rows, summary_rows, days, now):
    now = _as_datetime(now) or _utc_now()
    period_days = min(max(int(days or 30), 1), 90)
    cutoff = now.date() - timedelta(days=period_days - 1)
    seven_day_cutoff = now.date() - timedelta(days=6)
    school_events = {}
    school_roles = {}
    school_last_events = {}
    active_7d = set()
    active_period = set()

    for raw in daily_rows:
        row = raw or {}
        school_id = normalize_school_id(row.get("school_id"))
        try:
            activity_date = datetime.strptime(str(row.get("date") or ""), "%Y-%m-%d").date()
        except ValueError:
            continue
        if not school_id or activity_date < cutoff or activity_date > now.date():
            continue
        active_period.add(school_id)
        if activity_date >= seven_day_cutoff:
            active_7d.add(school_id)
        event_target = school_events.setdefault(school_id, {})
        for event, count in _safe_counter(row.get("events")).items():
            if event in ALLOWED_EVENTS:
                event_target[event] = event_target.get(event, 0) + count
                event_at = _as_datetime(row.get(f"last_{event}_at"))
                if not event_at:
                    event_at = _as_datetime(f"{activity_date.isoformat()}T00:00:00+00:00")
                current = _as_datetime(
                    school_last_events.setdefault(school_id, {}).get(event))
                if event_at and (not current or event_at > current):
                    school_last_events[school_id][event] = _iso(event_at)
        role_target = school_roles.setdefault(school_id, {})
        for role, count in _safe_counter(row.get("roles")).items():
            if role in ALLOWED_ROLES:
                role_target[role] = role_target.get(role, 0) + count

    last_active = {}
    for row in summary_rows:
        if not row or not row.get("school_id"):
            continue
        school_id = normalize_school_id(row.get("school_id"))
        last_active[school_id] = _iso(row.get("last_active_at"))
        target = school_last_events.setdefault(school_id, {})
        for event in ALLOWED_EVENTS:
            event_at = _as_datetime(row.get(f"last_{event}_at"))
            current = _as_datetime(target.get(event))
            if event_at and (not current or event_at > current):
                target[event] = _iso(event_at)
    event_totals = {event: 0 for event in sorted(ALLOWED_EVENTS)}
    for events in school_events.values():
        for event, count in events.items():
            event_totals[event] += count

    school_items = []
    for school in schools:
        school_id = normalize_school_id(school.get("school_id"))
        school_items.append({
            "school_id": school_id,
            "moe_code": str(school.get("moe_code") or ""),
            "name": str(school.get("name") or school_id),
            "active": bool(school.get("active", True)),
            "created_at": _iso(school.get("created_at")),
            "last_active_at": last_active.get(school_id, ""),
            "last_events": school_last_events.get(school_id, {}),
            "events": school_events.get(school_id, {}),
            "roles": school_roles.get(school_id, {}),
        })
    school_items.sort(key=lambda item: (not bool(item["last_active_at"]),
                                        item["last_active_at"]), reverse=False)
    school_items.sort(key=lambda item: item["last_active_at"], reverse=True)

    return {
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "days": period_days,
        "privacy": "aggregate_only",
        "totals": {
            "configured_schools": len(school_items),
            "enabled_schools": sum(1 for item in school_items if item["active"]),
            "active_7d": len(active_7d),
            "active_period": len(active_period),
            **event_totals,
        },
        "schools": school_items,
    }


def enrich_overview(overview, case_overviews, now=None):
    """Add operational progress without exposing timetable or personal data."""
    result = deepcopy(overview or {})
    schools = result.setdefault("schools", [])
    case_lookup = {}
    for raw_school_id, case in ((case_overviews or {}).items()
                                if isinstance(case_overviews, dict) else []):
        school_id = normalize_school_id(raw_school_id)
        if school_id:
            case_lookup[school_id] = case
    current = _as_datetime(now) or _as_datetime(result.get("generated_at")) or _utc_now()
    stage_totals = {
        "not_started": 0, "building": 0, "scheduled": 0,
        "published": 0, "needs_attention": 0,
    }
    for school in schools:
        school_id = normalize_school_id(school.get("school_id"))
        case = deepcopy(case_lookup.get(school_id) or {})
        attention = []
        metadata_unavailable = bool(case.get("metadata_unavailable"))
        if metadata_unavailable:
            progress = "unknown"
            attention.append("案件狀態暫時無法取得")
        elif not school.get("active", True):
            progress = "disabled"
        elif case.get("has_published"):
            progress = "published"
        elif case.get("schedule_ready"):
            progress = "scheduled"
        elif case.get("has_draft"):
            progress = "building"
        elif int((school.get("events") or {}).get("login") or 0) > 0:
            progress = "signed_in"
        else:
            progress = "not_started"

        if not metadata_unavailable:
            draft_saved_at = _as_datetime(case.get("draft_saved_at"))
            published_at = _as_datetime(case.get("published_at"))
            case["has_unpublished_changes"] = bool(
                draft_saved_at and published_at and draft_saved_at > published_at)
            if case["has_unpublished_changes"]:
                attention.append("有未發布草稿變更")

        if school.get("active", True):
            last_active_at = _as_datetime(school.get("last_active_at"))
            created_at = _as_datetime(school.get("created_at"))
            if last_active_at and current - last_active_at >= timedelta(days=7):
                attention.append("超過 7 日未操作")
            elif not last_active_at and created_at and current - created_at >= timedelta(days=7):
                attention.append("開通超過 7 日尚未使用")
            if not metadata_unavailable:
                if progress == "signed_in":
                    attention.append("已登入但尚未建立雲端案件")
                events = school.get("events") or {}
                if int(events.get("solve_failed") or 0) >= 3 and int(events.get("solve_failed") or 0) > int(events.get("solve_success") or 0):
                    attention.append("近 30 日多次排課失敗")
                if case.get("has_draft") and int(case.get("backup_count") or 0) == 0:
                    attention.append("尚未建立案件還原點")
                if progress == "scheduled":
                    attention.append("已完成排課但尚未發布")

        school["case"] = case
        school["progress"] = progress
        school["attention"] = attention[:4]
        if progress in {"not_started", "signed_in"}:
            stage_totals["not_started"] += 1
        elif progress == "building":
            stage_totals["building"] += 1
        elif progress == "scheduled":
            stage_totals["scheduled"] += 1
        elif progress == "published":
            stage_totals["published"] += 1
        if attention:
            stage_totals["needs_attention"] += 1

    schools.sort(
        key=lambda item: (
            bool(item.get("attention")),
            _as_datetime(item.get("last_active_at")) or datetime.min.replace(
                tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    result.setdefault("totals", {}).update(stage_totals)
    return result


class MemoryUsageTracker:
    def __init__(self):
        self._daily = {}
        self._summary = {}
        self._lock = threading.RLock()

    def record(self, school_id, event, role="", at=None):
        school_id = normalize_school_id(school_id)
        event = str(event or "").strip().lower()
        role = str(role or "").strip().lower()
        if not school_id or event not in ALLOWED_EVENTS:
            return False
        timestamp = _as_datetime(at) or _utc_now()
        day = timestamp.date().isoformat()
        with self._lock:
            row = self._daily.setdefault((day, school_id), {
                "date": day, "school_id": school_id, "events": {}, "roles": {},
            })
            row["events"][event] = row["events"].get(event, 0) + 1
            if role in ALLOWED_ROLES:
                row["roles"][role] = row["roles"].get(role, 0) + 1
            row["last_active_at"] = timestamp
            row[f"last_{event}_at"] = timestamp
            self._summary[school_id] = {
                **self._summary.get(school_id, {}),
                "school_id": school_id, "last_active_at": timestamp,
                f"last_{event}_at": timestamp,
            }
        return True

    def get_overview(self, schools, days=30, now=None):
        with self._lock:
            return _overview(
                deepcopy(list(schools)), deepcopy(list(self._daily.values())),
                deepcopy(list(self._summary.values())), days, now or _utc_now())


class FirestoreUsageTracker:
    def __init__(self, project_id):
        from google.cloud import firestore

        self._firestore = firestore
        self._client = firestore.Client(project=project_id or None)
        self._daily = self._client.collection("schedule_usage_daily")
        self._summary = self._client.collection("schedule_usage")

    def record(self, school_id, event, role="", at=None):
        school_id = normalize_school_id(school_id)
        event = str(event or "").strip().lower()
        role = str(role or "").strip().lower()
        if not school_id or event not in ALLOWED_EVENTS:
            return False
        timestamp = _as_datetime(at) or _utc_now()
        day = timestamp.date().isoformat()
        payload = {
            "school_id": school_id,
            "last_active_at": timestamp,
            f"last_{event}_at": timestamp,
            "events": {event: self._firestore.Increment(1)},
        }
        if role in ALLOWED_ROLES:
            payload["roles"] = {role: self._firestore.Increment(1)}
        self._summary.document(school_id).set(payload, merge=True)
        self._daily.document(f"{day}__{school_id}").set(
            {**payload, "date": day}, merge=True)
        return True

    def get_overview(self, schools, days=30, now=None):
        now = _as_datetime(now) or _utc_now()
        period_days = min(max(int(days or 30), 1), 90)
        cutoff = (now.date() - timedelta(days=period_days - 1)).isoformat()
        query = self._daily.where("date", ">=", cutoff)
        daily_rows = [snapshot.to_dict() for snapshot in query.stream()]
        summary_rows = [snapshot.to_dict() for snapshot in self._summary.stream()]
        return _overview(list(schools), daily_rows, summary_rows, period_days, now)


def create_usage_tracker():
    backend = os.getenv("SCHEDULE_STORE", "memory").strip().lower()
    if backend == "firestore":
        return FirestoreUsageTracker(os.getenv("FIRESTORE_PROJECT_ID", "").strip())
    return MemoryUsageTracker()
