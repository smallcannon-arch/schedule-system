# -*- coding: utf-8 -*-
"""School-configurable scheduling policy rules for Taiwan elementary schools."""

PROFILE_ID = "tw-elementary-custom-v1"
LEGACY_PROFILE_ID = "hsinchu-elementary-115"
PROFILE_LABEL = "國民小學自訂規則"
DAILY_HARD_CAP = 6
GRADE_TOTALS = {
    1: (22, 24), 2: (22, 24), 3: (28, 31),
    4: (28, 31), 5: (30, 33), 6: (30, 33),
}
FIXED_WEEKLY_TARGETS = {
    "專任輔導教師": 0, "教支人員": 0, "鐘點教師": 0, "其他": 0, "": 0,
}
LEGACY_DIRECTOR_TARGETS = ((12, 4), (24, 3), (30, 3), (36, 2), (48, 1), (60, 1), (10**9, 0))
LEGACY_CHIEF_TARGETS = ((12, 10), (24, 9), (30, 8), (36, 8), (48, 7), (60, 7), (10**9, 6))


def _tier_value(rows, count):
    return next((value for maximum, value in rows if count <= maximum), 0)


def _number_or_none(value, fallback=None):
    if value in (None, ""):
        return fallback
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return fallback


def _bounded_int(value, fallback, minimum, maximum):
    parsed = _number_or_none(value, fallback)
    return min(maximum, max(minimum, parsed))


def normalize(data):
    source = data.get("policy") if isinstance(data.get("policy"), dict) else {}
    targets = source.get("weeklyTargets") if isinstance(source.get("weeklyTargets"), dict) else {}
    legacy = source.get("profileId") == LEGACY_PROFILE_ID
    official_count = _number_or_none(source.get("officialClassCount"), 0)
    class_count = official_count or len(data.get("classes") or [])
    data["policy"] = {
        "profileId": PROFILE_ID,
        "region": str(source.get("region") or ("新竹市" if legacy else "")).strip()[:30],
        "academicYear": _bounded_int(source.get("academicYear"), 115 if legacy else 0, 0, 999),
        "periodMinutes": _bounded_int(source.get("periodMinutes"), 40, 1, 120),
        "dailyHardCap": _bounded_int(source.get("dailyHardCap"), DAILY_HARD_CAP, 1, DAILY_HARD_CAP),
        "officialClassCount": official_count,
        "weeklyTargets": {
            "導師": _number_or_none(targets.get("導師"), 16 if legacy else 0),
            "科任": _number_or_none(targets.get("科任"), 20 if legacy else 0),
            "組長": _number_or_none(
                targets.get("組長"), _tier_value(LEGACY_CHIEF_TARGETS, class_count) if legacy else 0),
            "主任": _number_or_none(
                targets.get("主任"), _tier_value(LEGACY_DIRECTOR_TARGETS, class_count) if legacy else 0),
        },
        "staffingPrinciplesApproved": source.get("staffingPrinciplesApproved") is True,
        "staffingMeetingDate": str(source.get("staffingMeetingDate") or "")[:10],
        "schedulePlanApproved": source.get("schedulePlanApproved") is True,
        "schedulePlanMeetingDate": str(source.get("schedulePlanMeetingDate") or "")[:10],
    }
    _migrate_teacher_adjustments(data)
    return data["policy"]


def official_class_count(data):
    config = data.get("policy") if isinstance(data.get("policy"), dict) else {}
    configured = _number_or_none(config.get("officialClassCount"), 0)
    return configured or len(data.get("classes") or [])


def weekly_target(data, role):
    config = normalize(data)
    shared_role = {
        "資源班教師": "科任", "資源班導師": "導師",
        "導師兼主任": "導師", "導師兼組長": "導師",
    }.get(role)
    if shared_role:
        return weekly_target(data, shared_role)
    configured = config["weeklyTargets"].get(role)
    if role in {"導師", "科任", "組長", "主任"} and configured is not None:
        return configured
    return FIXED_WEEKLY_TARGETS.get(role, 0)


def teacher_target(data, teacher):
    normalize(data)
    custom = (data.get("tcap") or {}).get(teacher) or {}
    role = (data.get("roster") or {}).get(teacher, "")
    base = weekly_target(data, role)
    return max(0, base + _number_or_none(custom.get("extra"), 0)
               - _number_or_none(custom.get("minus"), 0))


def has_weekly_target(role):
    return role in {
        "導師", "科任", "組長", "主任", "導師兼組長", "導師兼主任",
        "資源班教師", "資源班導師", "專任輔導教師",
    }


def daily_hard_cap(data=None):
    if not isinstance(data, dict):
        return DAILY_HARD_CAP
    return normalize(data)["dailyHardCap"]


def _migrate_teacher_adjustments(data):
    tcap = data.setdefault("tcap", {})
    for teacher, custom in tcap.items():
        if not isinstance(custom, dict) or "extra" in custom:
            continue
        role = (data.get("roster") or {}).get(teacher, "")
        role = {
            "資源班教師": "科任", "資源班導師": "導師",
            "導師兼主任": "導師", "導師兼組長": "導師",
        }.get(role, role)
        if role in {"導師", "科任", "組長", "主任"}:
            base = _number_or_none(data["policy"]["weeklyTargets"].get(role), 0)
        else:
            base = FIXED_WEEKLY_TARGETS.get(role, 0)
        old_target = _number_or_none(custom.get("cap"), base)
        old_minus = _number_or_none(custom.get("minus"), 0)
        custom["extra"] = max(0, old_target - base)
        custom["minus"] = old_minus + max(0, base - old_target)
        custom.pop("cap", None)


def validate_case(data, require_approval=False):
    config = normalize(data)
    blocking, warnings = [], []
    actual_classes = len(data.get("classes") or [])
    if config["officialClassCount"] and config["officialClassCount"] < actual_classes:
        blocking.append(
            f"校務核定班級數 {config['officialClassCount']} 不可少於已建立班級 {actual_classes} 班")

    grade_key = "g" if any("g" in item for item in data.get("classes") or []) else "grade"
    grades = {int(item.get(grade_key) or 0) for item in data.get("classes") or []}
    for grade in sorted(grades & set(GRADE_TOTALS)):
        total = 0
        for subject in (data.get("subjects") or {}).values():
            hours = subject.get("hours") or []
            if isinstance(hours, dict):
                total += max(0, int(hours.get(grade, 0) or 0))
            elif grade <= len(hours):
                total += max(0, int(hours[grade - 1] or 0))
        minimum, maximum = GRADE_TOTALS[grade]
        if not minimum <= total <= maximum:
            blocking.append(
                f"{grade}年級每週學習總節數 {total} 節，應介於 {minimum} 至 {maximum} 節")

    for teacher, value in (data.get("tcap") or {}).items():
        minus = _number_or_none(value.get("minus"), 0)
        reason = str(value.get("reason") or "")
        if not minus:
            continue
        if not reason:
            warnings.append(f"{teacher}已設定減課 {minus} 節，但尚未填寫減課原因")

    if not config["region"]:
        warnings.append("尚未填寫縣市或適用規則名稱")
    if not config["academicYear"]:
        warnings.append("尚未填寫適用學年度")
    if not any(config["weeklyTargets"].values()):
        warnings.append("尚未填寫教師每週基準節數；填 0 的職務將不檢核應授節數")

    if require_approval:
        if not config["region"] or not config["academicYear"]:
            blocking.append("正式發布前須填寫縣市或適用規則名稱及學年度")
    return {"blocking": list(dict.fromkeys(blocking)), "warnings": list(dict.fromkeys(warnings))}


def metadata(data):
    config = normalize(data)
    scope = config["region"] or "學校自訂"
    label = f"{scope}國民小學"
    if config["academicYear"]:
        label += f" {config['academicYear']} 學年度"
    return {
        "id": PROFILE_ID,
        "label": label,
        "region": config["region"],
        "academic_year": config["academicYear"],
        "period_minutes": config["periodMinutes"],
        "official_class_count": official_class_count(data),
        "weekly_targets": {
            role: weekly_target(data, role) for role in ("導師", "科任", "組長", "主任")
        },
        "daily_hard_cap": daily_hard_cap(data),
        "approvals": {
            "staffing": config["staffingPrinciplesApproved"],
            "schedule_plan": config["schedulePlanApproved"],
        },
    }
