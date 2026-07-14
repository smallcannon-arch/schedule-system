# -*- coding: utf-8 -*-
"""Build least-privilege teacher views and validate homeroom changes."""
from collections import Counter
from copy import deepcopy
import re
import schedule_policy


DAYS = ("一", "二", "三", "四", "五")
class TeacherChangeError(RuntimeError):
    pass


def _classes(data):
    return {str(item.get("code")): item for item in data.get("classes") or []}


def _native_lock_enabled(data):
    flag = data.get("nativeLockEnabled")
    if isinstance(flag, bool):
        return flag
    return bool(data.get("nativeBands") or data.get("nativeGroups") or any(
        item.get("s") == "本土語文" for item in data.get("locks") or []))


def _schedule_entries(snapshot, include_overlay=True):
    data = snapshot.get("data") or {}
    classrooms = _classes(data)
    entries = []
    for key, value in (snapshot.get("schedule") or {}).items():
        parts = str(key).split("|")
        if len(parts) != 3:
            continue
        code, day, period = parts
        entries.append({
            "code": code, "day": day, "period": int(period),
            "subject": value.get("s") or value.get("subject") or "",
            "teacher": value.get("t") or value.get("teacher") or "",
            "room": value.get("room") or "R00", "source": "engine",
        })
    for code, placements in (snapshot.get("tutor_placements") or {}).items():
        classroom = classrooms.get(str(code)) or {}
        for slot, subject in (placements or {}).items():
            day, period = str(slot).split("|", 1)
            entries.append({
                "code": str(code), "day": day, "period": int(period),
                "subject": subject, "teacher": classroom.get("tutor") or "",
                "room": _room_of(data, str(code), subject), "source": "tutor",
            })
    if include_overlay:
        for item in snapshot.get("overlay") or []:
            entries.append({
                "code": str(item.get("code") or ""),
                "day": item.get("d") or item.get("day") or "",
                "period": int(item.get("p") or item.get("period") or 0),
                "subject": item.get("subj") or item.get("subject") or "",
                "teacher": item.get("t") or item.get("teacher") or "",
                "room": "R00", "source": "overlay", "group": item.get("grp") or item.get("group") or "",
            })
    for item in (data.get("nativeGroups") or []) if _native_lock_enabled(data) else []:
        grade = int(item.get("g") or item.get("grade") or 0)
        band = next((row for row in data.get("nativeBands") or []
                     if int(row.get("g") or row.get("grade") or 0) == grade), {})
        day = band.get("d") or band.get("day") or item.get("d") or item.get("day") or ""
        period = int(band.get("p") or band.get("period") or item.get("p") or item.get("period") or 0)
        subject = item.get("lang") or item.get("language") or "本土語文"
        room = item.get("room") or "R00"
        group_name = item.get("grp") or item.get("group") or f"{grade}年級本土語組"
        for teacher, group in ((item.get("t") or item.get("teacher"), group_name),
                               (item.get("assistant"), f"{group_name}・直播協同")):
            if teacher:
                entries.append({
                    "code": f"{grade}年級", "day": day, "period": period,
                    "subject": subject, "teacher": teacher, "room": room,
                    "source": "native", "group": group,
                })
    return entries


def _room_of(data, code, subject):
    override = (data.get("override") or {}).get(code) or {}
    return override.get(subject) or ((data.get("subjects") or {}).get(subject) or {}).get("room") or "R00"


def _is_resource_bound(data, code, subject):
    classroom = _classes(data).get(code) or {}
    if classroom.get("res") and subject in {"國語文", "數學"}:
        return True
    return any(str(group.get("code")) == code and group.get("subj") == subject
               for group in data.get("resGroups") or [])


def _hours(subject, grade):
    values = subject.get("hours") or []
    index = int(grade) - 1
    return int(values[index] or 0) if 0 <= index < len(values) else 0


def _allowed_pool(data, classroom):
    code = str(classroom.get("code"))
    tutor = str(classroom.get("tutor") or "")
    assigned = (data.get("assign") or {}).get(code) or {}
    result = {}
    for name, subject in (data.get("subjects") or {}).items():
        if name == "本土語文" and _native_lock_enabled(data):
            continue
        hours = _hours(subject, classroom.get("g") or 0)
        teacher = assigned.get(name) or ""
        mode = ((data.get("assignmentModes") or {}).get(code) or {}).get(name)
        tutor_arrangeable = mode == "tutor" if mode in {"tutor", "engine"} else bool(subject.get("self"))
        engine_owned = (not tutor_arrangeable or _is_resource_bound(data, code, name)
                        or (teacher and teacher != tutor))
        if hours > 0 and tutor_arrangeable and not engine_owned:
            result[name] = hours
    return result


def _class_package(snapshot, class_code, teacher_name, revision, pending=None):
    data = snapshot.get("data") or {}
    classroom = _classes(data)[class_code]
    fixed = {key: deepcopy(value) for key, value in (snapshot.get("schedule") or {}).items()
             if str(key).split("|", 1)[0] == class_code}
    overlay = [deepcopy(item) for item in snapshot.get("overlay") or []
               if str(item.get("code")) == class_code]
    relevant_names = {teacher_name}
    relevant_names.update(str(value.get("t") or value.get("teacher") or "") for value in fixed.values())
    relevant_names.update(str(item.get("t") or item.get("teacher") or "") for item in overlay)
    limits = [deepcopy(row) for row in snapshot.get("limits") or data.get("limits") or []
              if row and row[0] in {teacher_name, class_code, f"{classroom.get('g')}年級"}]
    class_data = {
        "classes": [deepcopy(classroom)],
        "subjects": deepcopy(data.get("subjects") or {}),
        "assign": {class_code: deepcopy((data.get("assign") or {}).get(class_code) or {})},
        "assignmentModes": {class_code: deepcopy(
            (data.get("assignmentModes") or {}).get(class_code) or {})},
        "override": {class_code: deepcopy((data.get("override") or {}).get(class_code) or {})},
        "locks": [deepcopy(item) for item in data.get("locks") or [] if str(item.get("c")) == class_code],
        "limits": limits,
        "derived": [], "rules": deepcopy(snapshot.get("rules") or data.get("rules") or []),
        "blocked": deepcopy(data.get("blocked") or []), "gslot": deepcopy(data.get("gslot") or {}),
        "rooms": deepcopy(data.get("rooms") or {}),
        "roster": {name: (data.get("roster") or {}).get(name, "") for name in relevant_names if name},
        "resGroups": [deepcopy(item) for item in data.get("resGroups") or []
                      if str(item.get("code")) == class_code],
        "nativeGroups": [deepcopy(item) for item in data.get("nativeGroups") or []
                         if int(item.get("g") or 0) == int(classroom.get("g") or 0)],
        "nativeBands": [deepcopy(item) for item in data.get("nativeBands") or []
                        if int(item.get("g") or 0) == int(classroom.get("g") or 0)],
        "nativeLockEnabled": _native_lock_enabled(data),
        "teacherNativeLangs": deepcopy(data.get("teacherNativeLangs") or {}),
        "teacherSubjects": deepcopy(data.get("teacherSubjects") or {}),
        "policy": deepcopy(data.get("policy") or {}),
        "tcap": {name: deepcopy(value) for name, value in (data.get("tcap") or {}).items()
                 if name in relevant_names},
    }
    pending = pending or {}
    return {
        "schema": "schedule-server-teacher-v1", "class_code": class_code,
        "teacher": teacher_name, "revision": revision, "data": class_data,
        "fixed": fixed, "overlay": overlay,
        "placements": deepcopy(
            pending.get("placements")
            if pending else (snapshot.get("tutor_placements") or {}).get(class_code) or {}),
        "pending_review": bool(pending),
        "pending_submitted_at": str(pending.get("submitted_at") or ""),
    }


def build_teacher_workspace(state, principal):
    if not state or not state.get("snapshot"):
        raise TeacherChangeError("目前尚未發布正式課表")
    snapshot = state["snapshot"]
    classrooms = _classes(snapshot.get("data") or {})
    personal = []
    for entry in _schedule_entries(snapshot):
        if entry["teacher"] != principal.name:
            continue
        row = deepcopy(entry)
        row["class_label"] = str((classrooms.get(entry["code"]) or {}).get("code") or entry["code"])
        personal.append(row)
    personal.sort(key=lambda row: (DAYS.index(row["day"]) if row["day"] in DAYS else 99,
                                   row["period"], row["class_label"], row["subject"]))

    editable = []
    pending_updates = state.get("pending_teacher_updates") or {}
    if principal.can_edit_classes:
        codes = classrooms.keys() if principal.is_admin else principal.class_codes
        for code in codes:
            classroom = classrooms.get(str(code))
            if not classroom:
                continue
            if not principal.is_admin and classroom.get("tutor") != principal.name:
                continue
            pending = pending_updates.get(str(code)) or {}
            if pending and pending.get("submitted_by") != principal.email and not principal.is_admin:
                pending = {}
            editable.append(_class_package(
                snapshot, str(code), classroom.get("tutor") or principal.name,
                state["revision"], pending=pending))
    return {
        "profile": {"email": principal.email, "name": principal.name, "role": principal.role,
                    "school_id": principal.school_id, "school_name": principal.school_name},
        "revision": state["revision"], "published_at": state.get("published_at"),
        "label": snapshot.get("label") or "正式課表", "personal_schedule": personal,
        "editable_classes": editable,
    }


def validate_teacher_placements(state, principal, class_code, placements):
    if not state or not state.get("snapshot"):
        raise TeacherChangeError("目前尚未發布正式課表")
    if not principal.can_edit_classes:
        raise TeacherChangeError("此帳號只有個人課表檢視權限")
    if not principal.is_admin and class_code not in principal.class_codes:
        raise TeacherChangeError("不可修改其他班級的課表")

    snapshot = state["snapshot"]
    data = snapshot.get("data") or {}
    classroom = _classes(data).get(class_code)
    if not classroom:
        raise TeacherChangeError("班級不存在或已停止開放調整")
    if not principal.is_admin and classroom.get("tutor") != principal.name:
        raise TeacherChangeError("教師姓名與該班導師設定不符")
    if not isinstance(placements, dict) or len(placements) > 35:
        raise TeacherChangeError("課程調整資料格式不正確")

    pool = _allowed_pool(data, classroom)
    counts = Counter()
    normalized = {}
    fixed = snapshot.get("schedule") or {}
    teacher_name = str(classroom.get("tutor") or "")
    limits = snapshot.get("limits") or data.get("limits") or []
    other_entries = [entry for entry in _schedule_entries(snapshot)
                     if not (entry["source"] == "tutor" and entry["code"] == class_code)]
    daily_counts = Counter((entry["teacher"], entry["day"]) for entry in other_entries if entry["teacher"])
    daily_cap = schedule_policy.daily_hard_cap(data)

    for slot, subject in placements.items():
        match = re.fullmatch(r"([一二三四五])\|([1-7])", str(slot))
        if not match or not isinstance(subject, str):
            raise TeacherChangeError(f"不允許的課程或時段：{slot}")
        day, period = match.group(1), int(match.group(2))
        if _is_resource_bound(data, class_code, subject):
            raise TeacherChangeError(f"{subject} 為資源班綁課，不可由導師調整")
        if subject not in pool:
            raise TeacherChangeError(f"不允許的課程或時段：{slot}")
        if f"{class_code}|{day}|{period}" in fixed:
            raise TeacherChangeError(f"週{day}第{period}節已有固定課程")
        grade_slots = (data.get("gslot") or {}).get(str(classroom.get("g"))) or []
        day_index = DAYS.index(day)
        if day_index >= len(grade_slots) or period > len(grade_slots[day_index]) or not grade_slots[day_index][period - 1]:
            raise TeacherChangeError(f"週{day}第{period}節不是該年級可上課時段")
        info = (data.get("subjects") or {}).get(subject) or {}
        if period in (info.get("banned") or []):
            raise TeacherChangeError(f"{subject} 不可排第 {period} 節")
        if any(len(row) >= 3 and row[0] in {teacher_name, class_code, f"{classroom.get('g')}年級"}
               and row[1] == day and int(row[2]) == period for row in limits if str(row[2]).isdigit()):
            raise TeacherChangeError(f"週{day}第{period}節已設定為不可排")
        if any(entry["teacher"] == teacher_name and entry["day"] == day and entry["period"] == period
               for entry in other_entries):
            raise TeacherChangeError(f"{teacher_name} 週{day}第{period}節已有其他課程")
        if daily_counts[(teacher_name, day)] + sum(1 for key in normalized if key.startswith(f"{day}|")) >= daily_cap:
            raise TeacherChangeError(f"{teacher_name} 週{day}已達每日 {daily_cap} 節上限")
        normalized[f"{day}|{period}"] = subject
        counts[subject] += 1

    if counts != Counter(pool):
        missing = [f"{name} {hours - counts[name]}節" for name, hours in pool.items() if counts[name] != hours]
        raise TeacherChangeError("回傳結果的科目節數不完整：" + "、".join(missing))
    return normalized
