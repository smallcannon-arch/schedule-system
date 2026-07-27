import pytest

import app
import schedule_policy


def complete_publish_payload():
    days = ("一", "二", "三", "四", "五")
    daily_counts = (5, 5, 5, 4, 4)
    slots = [
        (day, period)
        for day, count in zip(days, daily_counts)
        for period in range(1, count + 1)
    ]
    data = {
        "classes": [{"code": "1甲", "g": 1, "tutor": "王導師"}],
        "subjects": {
            "領域課程": {
                "hours": [23, 0, 0, 0, 0, 0],
                "room": "R00", "banned": [], "block": "", "self": False,
            },
        },
        "roster": {"王導師": "導師"},
        "assign": {"1甲": {"領域課程": "王導師"}},
        "gslot": {"1": [[1] * 7 for _ in days]},
        "rooms": {"R00": 99},
        "override": {}, "locks": [], "blocked": [], "resGroups": [], "tcap": {},
        "policy": {
            "profileId": schedule_policy.PROFILE_ID,
            "region": "新北市", "academicYear": 115,
            "periodMinutes": 40, "dailyHardCap": 6,
            "weeklyTargets": {"導師": 16, "科任": 20, "組長": 9, "主任": 3},
        },
    }
    return {
        "data": data,
        "schedule": {
            f"1甲|{day}|{period}": {
                "s": "領域課程", "t": "王導師", "room": "R00",
            }
            for day, period in slots
        },
        "tutor_placements": {}, "overlay": [], "limits": [], "rules": [],
        "schedule_ready": True,
    }


def case_data(class_count=16):
    subjects = {
        "領域課程": {"hours": [20, 20, 25, 25, 26, 26]},
        "彈性學習": {"hours": [3, 3, 4, 4, 6, 6]},
    }
    return {
        "classes": [{"code": f"1班{i}", "g": 1} for i in range(class_count)],
        "subjects": subjects,
        "roster": {"王導師": "導師", "李組長": "組長", "陳主任": "主任"},
        "tcap": {},
        "policy": {
            "profileId": schedule_policy.PROFILE_ID,
            "region": "新北市", "academicYear": 115,
            "periodMinutes": 45, "dailyHardCap": 5,
            "weeklyTargets": {"導師": 16, "科任": 20, "組長": 9, "主任": 3},
        },
    }


def test_school_role_targets_are_user_configurable():
    data = case_data(16)

    assert schedule_policy.weekly_target(data, "導師") == 16
    assert schedule_policy.weekly_target(data, "科任") == 20
    assert schedule_policy.weekly_target(data, "組長") == 9
    assert schedule_policy.weekly_target(data, "主任") == 3

    data["policy"]["weeklyTargets"]["組長"] = 8
    data["policy"]["weeklyTargets"]["主任"] = 2
    assert schedule_policy.weekly_target(data, "組長") == 8
    assert schedule_policy.weekly_target(data, "主任") == 2


def test_individual_target_uses_overtime_and_reduction():
    data = case_data()
    data["tcap"]["王導師"] = {"extra": 2, "minus": 1, "reason": "其他核定"}

    assert schedule_policy.teacher_target(data, "王導師") == 17


def test_special_roles_share_the_four_common_role_targets():
    data = case_data()
    data["roster"].update({"資源教師": "資源班教師", "行政導師": "導師兼組長"})
    data["tcap"].update({
        "資源教師": {"extra": 0, "minus": 2, "reason": "特教教師節數規定"},
        "行政導師": {"extra": 0, "minus": 4, "reason": "導師兼行政職務"},
    })

    assert schedule_policy.weekly_target(data, "資源班教師") == 20
    assert schedule_policy.teacher_target(data, "資源教師") == 18
    assert schedule_policy.weekly_target(data, "導師兼組長") == 16
    assert schedule_policy.teacher_target(data, "行政導師") == 12


def test_national_grade_total_is_blocking():
    data = case_data()
    data["subjects"]["彈性學習"]["hours"][0] = 1

    result = schedule_policy.validate_case(data)

    assert any("1年級每週學習總節數 21 節" in issue for issue in result["blocking"])


def test_publish_does_not_require_administrative_confirmation_fields():
    data = case_data()

    result = schedule_policy.validate_case(data, require_approval=True)
    assert result["blocking"] == []
    assert not any("校務會議" in issue or "課程計畫" in issue for issue in result["warnings"])


def test_school_can_set_daily_hard_cap_but_never_allow_seven_periods():
    data = case_data()

    assert schedule_policy.daily_hard_cap(data) == 5
    data["policy"]["dailyHardCap"] = 7
    assert schedule_policy.daily_hard_cap(data) == 6


def test_legacy_hsinchu_profile_migrates_without_losing_existing_values():
    data = case_data()
    data["policy"] = {"profileId": schedule_policy.LEGACY_PROFILE_ID}

    config = schedule_policy.normalize(data)

    assert config["profileId"] == schedule_policy.PROFILE_ID
    assert config["region"] == "新竹市"
    assert config["academicYear"] == 115
    assert config["weeklyTargets"] == {"導師": 16, "科任": 20, "組長": 9, "主任": 3}


def test_publish_requires_custom_scope():
    data = case_data()
    data["policy"].update({"region": "", "academicYear": 0})

    result = schedule_policy.validate_case(data, require_approval=True)

    assert result["blocking"] == ["正式發布前須填寫縣市或適用規則名稱及學年度"]


def test_server_publish_normalization_enforces_custom_policy_scope():
    payload = complete_publish_payload()
    data = payload["data"]
    data["policy"].update({"region": "", "academicYear": 0})

    with pytest.raises(ValueError, match="正式發布前的學校自訂規則檢核未通過"):
        app._normalize_schedule_snapshot(payload, require_schedule=True)

    data["policy"].update({"region": "新北市", "academicYear": 115})
    snapshot = app._normalize_schedule_snapshot(payload, require_schedule=True)
    assert snapshot["policy_compliance"]["blocking"] == []


def test_server_publish_rejects_empty_or_incomplete_schedule_even_when_flag_is_true():
    payload = complete_publish_payload()
    payload["schedule"] = {}

    with pytest.raises(ValueError, match="正式課表沒有任何可發布的課程"):
        app._normalize_schedule_snapshot(payload, require_schedule=True)


def test_server_publish_rechecks_fixed_courses():
    payload = complete_publish_payload()
    payload["data"]["locks"] = [{"c": "1甲", "d": "五", "p": 7, "s": "領域課程"}]

    with pytest.raises(ValueError, match="正式課表硬規則檢核未通過.*H10違反"):
        app._normalize_schedule_snapshot(payload, require_schedule=True)


def test_server_publish_accepts_resource_early_study_marker():
    payload = complete_publish_payload()
    payload["data"]["roster"]["資源教師"] = "資源班教師"
    payload["overlay"] = [{
        "group_id": "resource-early",
        "group": "一年級早自修組",
        "code": "1甲",
        "subject": "領域課程",
        "pull_subject": "早自修",
        "teacher": "資源教師",
        "day": "一",
        "period": 0,
    }]

    snapshot = app._normalize_schedule_snapshot(payload, require_schedule=True)

    assert snapshot["overlay"][0]["pull_subject"] == "早自修"


def test_server_publish_allows_first_stage_tutor_pool_but_complete_mode_requires_it():
    payload = complete_publish_payload()
    payload["data"]["subjects"] = {
        "科任課": {
            "hours": [1, 0, 0, 0, 0, 0],
            "room": "R00", "banned": [], "block": "", "self": False,
        },
        "導師課": {
            "hours": [22, 0, 0, 0, 0, 0],
            "room": "R00", "banned": [], "block": "", "self": True,
        },
    }
    payload["data"]["assign"] = {
        "1甲": {"科任課": "王導師", "導師課": "王導師"}}
    payload["schedule"] = {
        "1甲|一|1": {"s": "科任課", "t": "王導師", "room": "R00"}}
    payload["formal_auto_tutor"] = False

    snapshot = app._normalize_schedule_snapshot(payload, require_schedule=True)
    assert snapshot["schedule_ready"] is True

    payload["formal_auto_tutor"] = True
    with pytest.raises(ValueError, match="正式課表硬規則檢核未通過.*導師課.*排0/需22"):
        app._normalize_schedule_snapshot(payload, require_schedule=True)
