from copy import deepcopy

import engine
import pytest
from openpyxl import load_workbook
from support_paths import FIXTURES


V5_TEMPLATE = FIXTURES / "排課母版_v5.xlsx"
V6_TEMPLATE = FIXTURES / "排課母版_v6.xlsx"
V4_TEMPLATE = FIXTURES / "排課系統_通用母版_v4.xlsx"


def test_loads_v5_schema_and_expands_teacher_centered_assignments():
    data = engine.load_data(V5_TEMPLATE)

    assert data["schema_version"] == 5
    assert len(data["classes"]) == 3
    assert data["assign"][("1甲", "國語文")] == "王導師"
    assert data["assign"][("1甲", "音樂")] == "張科任"
    assert ("英語教室", "二", 1) in data["room_blocked"]
    assert ("閩語教支", "二", 1) in data["teacher_limit"]


def test_loads_v6_merged_teacher_and_assignment_sheet():
    data = engine.load_data(V6_TEMPLATE)

    assert data["schema_version"] == 6
    assert "張科任" in data["roster"]
    assert data["assign"][("1甲", "音樂")] == "張科任"
    assert data["assign"][("1甲", "國語文")] == "王導師"


def test_v6_direct_parser_reads_alias_limits_and_resource_overlay(tmp_path):
    workbook = load_workbook(V6_TEMPLATE)
    teacher_sheet = workbook["教師與配課"]
    teacher = teacher_sheet["A3"].value
    code = workbook["班級"]["A2"].value
    row = teacher_sheet.max_row + 1
    teacher_sheet.cell(row, 9, teacher)
    teacher_sheet.cell(row, 10, "閩南語")
    teacher_sheet.cell(row, 11, code)

    limit_sheet = (workbook["不排課時間"] if "不排課時間" in workbook.sheetnames
                   else workbook.create_sheet("不排課時間"))
    if limit_sheet.max_row == 1 and limit_sheet["A1"].value is None:
        limit_sheet.append(["對象", "星期", "節次", "類型", "備註"])
    limit_sheet.append([teacher, "五", 7, "不可排", "測試限制"])
    overlay_sheet = (workbook["資源班overlay"] if "資源班overlay" in workbook.sheetnames
                     else workbook.create_sheet("資源班overlay"))
    if overlay_sheet.max_row == 1 and overlay_sheet["A1"].value is None:
        overlay_sheet.append(["組別", "原班", "科目", "資源班教師", "星期", "節次"])
    overlay_sheet.append(["測試資源組", code, "國語文", teacher, "一", 1])
    target = tmp_path / "v6-options.xlsx"
    workbook.save(target)

    data = engine.load_data(target)

    assert data["assign"][(code, "本土語文")] == teacher
    assert (teacher, "五", 7) in data["teacher_limit"]
    assert data["overlay"] == [{
        "grp": "測試資源組", "class": code, "subj": "國語文", "t": teacher,
        "day": "一", "p": 1,
    }]


def test_v6_template_uses_consistent_fonts_and_bounded_notes():
    workbook = load_workbook(V6_TEMPLATE, data_only=False)

    assert "教師與配課" in workbook.sheetnames
    assert "教師" not in workbook.sheetnames
    assert "配課" not in workbook.sheetnames
    assert workbook["教師與配課"]["A2"].value == "姓名"
    assert workbook["教師與配課"]["E2"].value == "學校 Google 帳號\n(教支人員可選填)"
    assert workbook["教師與配課"]["F2"].value == "可授本土語別\n(可複選)"
    assert workbook["教師與配課"]["B7"].value == "教支人員"
    assert workbook["教師與配課"]["I2"].value == "教師姓名"
    assert workbook["本土語分組"]["E1"].value == "分組名稱"
    assert workbook["本土語分組"]["H1"].value == "授課教師"
    assert workbook["說明"].max_column == 8
    assert any("只填帳號，不需提供密碼" in str(cell.value or "")
               for row in workbook["說明"].iter_rows() for cell in row)
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value not in (None, ""):
                    assert cell.font.name == "Microsoft JhengHei"


def test_loads_frontend_cloud_draft_schema_without_excel():
    slots = [[1, 1, 1, 1, 0, 0, 0] for _ in range(5)]
    payload = {
        "classes": [{"g": 1, "i": 1, "code": "1甲", "tutor": "王老師"}],
        "roster": {"王老師": "導師"},
        "tcap": {"王老師": {"cap": 16, "minus": 0}},
        "rooms": {"R00": 99},
        "subjects": {"國語文": {
            "hours": [1, 0, 0, 0, 0, 0], "room": "R00", "banned": [],
            "block": "", "self": True, "pairMode": "",
        }},
        "gslot": {str(grade): slots for grade in range(1, 7)},
        "assign": {"1甲": {"國語文": "王老師"}},
        "override": {}, "locks": [], "blocked": [], "resGroups": [],
    }

    data = engine.load_frontend_data(
        payload,
        limits=[["王老師", "一", "1", "不可排", "會議"]],
        rules=[["S01", "軟", "偏好", "國語優先上午", "penalty=4", "是"]],
    )
    schedule, _, _, meta, _ = engine.solve(data, time_limit=5, auto_schedule_tutor=True)

    assert data["assign"][("1甲", "國語文")] == "王老師"
    assert ("王老師", "一", 1) in data["teacher_limit"]
    assert data["rules"]["S01"] == {"on": True, "w": 4}
    assert len(schedule) == 1
    assert meta["completion"] == "complete"


def test_per_class_arrangement_mode_controls_cp_sat_ownership():
    slots = [[1, 1, 1, 1, 0, 0, 0] for _ in range(5)]
    payload = {
        "classes": [{"g": 1, "i": 1, "code": "1甲", "tutor": "王老師"}],
        "roster": {"王老師": "導師"}, "rooms": {"R00": 99},
        "subjects": {"國語文": {"hours": [1, 0, 0, 0, 0, 0], "room": "R00",
                                   "banned": [], "block": "", "self": True, "pairMode": ""}},
        "gslot": {str(grade): slots for grade in range(1, 7)},
        "assign": {"1甲": {"國語文": "王老師"}},
        "override": {}, "locks": [], "blocked": [], "resGroups": [],
    }

    engine_payload = deepcopy(payload)
    engine_payload["assignmentModes"] = {"1甲": {"國語文": "engine"}}
    engine_data = engine.load_frontend_data(engine_payload)
    engine_schedule, *_ = engine.solve(engine_data, time_limit=5, auto_schedule_tutor=False)
    assert engine_data["assignment_modes"][("1甲", "國語文")] == "engine"
    assert len(engine_schedule) == 1

    tutor_payload = deepcopy(payload)
    tutor_payload["assignmentModes"] = {"1甲": {"國語文": "tutor"}}
    tutor_data = engine.load_frontend_data(tutor_payload)
    tutor_schedule, *_ = engine.solve(tutor_data, time_limit=5, auto_schedule_tutor=False)
    assert tutor_schedule == {}
    assert tutor_data["pool"]["1甲"] == [("國語文", 1, "王老師")]


def _native_frontend_payload():
    slots = [[1, 1, 1, 1, 0, 0, 0] for _ in range(5)]
    return {
        "classes": [
            {"g": 1, "i": 1, "code": "1甲", "tutor": "王導師"},
            {"g": 1, "i": 2, "code": "1乙", "tutor": "李導師"},
        ],
        "roster": {"王導師": "導師", "李導師": "導師", "直播教師": "科任",
                   "協同教師": "科任", "客語教師": "科任"},
        "rooms": {"R00": 99, "電腦教室": 1},
        "subjects": {"本土語文": {
            "hours": [1, 0, 0, 0, 0, 0], "room": "R00", "banned": [],
            "block": "", "self": False, "pairMode": "",
        }},
        "gslot": {str(grade): slots for grade in range(1, 7)},
        "assign": {"1甲": {"本土語文": "舊配課教師"}},
        "override": {}, "locks": [], "blocked": [], "resGroups": [],
        "nativeLockEnabled": True,
        "nativeBands": [{"g": 1, "d": "二", "p": 1}],
        "nativeGroups": [{
            "g": 1, "d": "二", "p": 1, "lang": "原民語(直播)",
            "grp": "一年級原民語組", "sources": ["1甲", "1乙"], "students": 5,
            "mode": "直播共學", "t": "直播教師", "room": "電腦教室",
            "assistant": "協同教師",
        }],
    }


def test_frontend_native_language_locks_classes_staff_and_room():
    data = engine.load_frontend_data(_native_frontend_payload())
    schedule, tasks, _, meta, overlay = engine.solve(data, time_limit=5)

    native_locks = [lock for lock in data["locks"] if lock["subj"] == "本土語文"]
    assert {(lock["class"], lock["day"], lock["p"]) for lock in native_locks} == {
        ("1甲", "二", 1), ("1乙", "二", 1)}
    assert ("直播教師", "二", 1) in data["teacher_limit"]
    assert ("協同教師", "二", 1) in data["teacher_limit"]
    assert ("電腦教室", "二", 1) in data["room_blocked"]
    assert data["native_groups"][0]["lang"] == "原民語(直播)"
    assert data["native_groups"][0]["sources"] == ["1甲", "1乙"]
    assert data["native_groups"][0]["students"] == 5
    assert data["teacher_weekly_load"]["直播教師"] == 1
    assert data["teacher_weekly_load"]["協同教師"] == 1
    assert data["teacher_weekly_load"]["舊配課教師"] == 1
    assert tasks[("1甲", "本土語文")]["t"] == "舊配課教師"
    assert schedule[("1甲", "二", 1)][1] == "舊配課教師"
    assert {(code, day, period) for code, day, period in schedule} == {
        ("1甲", "二", 1), ("1乙", "二", 1)}
    assert meta["completion"] == "complete"
    assert engine.validate(data, schedule, tasks, overlay) == []


def test_frontend_native_language_allows_band_without_extraction_group():
    payload = _native_frontend_payload()
    payload["nativeGroups"] = []

    data = engine.load_frontend_data(payload)

    assert data["native_groups"] == []
    assert data["teacher_weekly_load"]["舊配課教師"] == 1
    assert {(lock["class"], lock["day"], lock["p"]) for lock in data["locks"]} == {
        ("1甲", "二", 1), ("1乙", "二", 1)}


def test_legacy_minnan_group_keeps_group_teacher_and_suppresses_base_assignment():
    payload = _native_frontend_payload()
    payload["nativeGroups"][0]["lang"] = "閩南語"

    data = engine.load_frontend_data(payload)
    schedule, tasks, *_ = engine.solve(data, time_limit=5)

    assert "舊配課教師" not in data["teacher_weekly_load"]
    assert tasks[("1甲", "本土語文")]["t"] == ""
    assert schedule[("1甲", "二", 1)][1] == ""


def test_frontend_native_language_rejects_duplicate_staff_assignment():
    payload = _native_frontend_payload()
    payload["nativeGroups"].append({
        "g": 1, "d": "二", "p": 1, "lang": "客語", "grp": "一年級客語組",
        "sources": ["1甲"], "t": "直播教師", "room": "R00",
    })

    with pytest.raises(ValueError, match="重複指派本土語分組"):
        engine.load_frontend_data(payload)


def test_frontend_native_language_enforces_room_capacity():
    payload = _native_frontend_payload()
    payload["nativeGroups"].append({
        "g": 1, "d": "二", "p": 1, "lang": "客語", "grp": "一年級客語組",
        "sources": ["1甲"], "t": "客語教師", "room": "電腦教室",
    })

    with pytest.raises(ValueError, match="超過本土語分組可用容量"):
        engine.load_frontend_data(payload)


def test_frontend_native_language_rejects_unknown_source_class():
    payload = _native_frontend_payload()
    payload["nativeGroups"][0]["sources"] = ["1甲", "2甲"]

    with pytest.raises(ValueError, match="引用不存在的來源班級：2甲"):
        engine.load_frontend_data(payload)


def test_frontend_native_language_teacher_must_come_from_roster():
    payload = _native_frontend_payload()
    payload["nativeGroups"][0]["t"] = "名冊外教師"

    with pytest.raises(ValueError, match="授課教師不在教師名冊"):
        engine.load_frontend_data(payload)


def test_frontend_native_language_migrates_legacy_group_fields():
    payload = _native_frontend_payload()
    payload.pop("nativeBands")
    for key in ("grp", "sources", "students", "mode"):
        payload["nativeGroups"][0].pop(key)

    data = engine.load_frontend_data(payload)

    assert data["native_bands"] == [{"g": 1, "d": "二", "p": 1}]
    assert data["native_groups"][0]["sources"] == ["1甲", "1乙"]
    assert data["native_groups"][0]["grp"].startswith("1年級原民語")


def test_frontend_native_language_lock_is_optional():
    payload = _native_frontend_payload()
    payload["nativeLockEnabled"] = False

    data = engine.load_frontend_data(payload)

    assert data["native_lock_enabled"] is False
    assert data["native_groups"] == []
    assert not any(lock["subj"] == "本土語文" for lock in data["locks"])


def test_v5_solves_and_passes_independent_validation():
    data = engine.load_data(V5_TEMPLATE)
    sched, tasks, warn, meta, overlay = engine.solve(data, time_limit=5)

    assert meta["status"] in {"OPTIMAL", "FEASIBLE"}
    assert sched
    assert data["pool"]
    assert engine.validate(data, sched, tasks, overlay) == []


def test_v5_formal_mode_auto_schedules_tutor_pool_and_reports_completeness():
    data = engine.load_data(V5_TEMPLATE)
    sched, tasks, warn, meta, overlay = engine.solve(
        data, time_limit=5, auto_schedule_tutor=True)

    assert meta["status"] in {"OPTIMAL", "FEASIBLE"}
    assert meta["pool_total"] == 0
    assert meta["scheduled_total"] == len(sched)
    assert meta["required_total"] >= meta["scheduled_total"]
    assert meta["completion"] == "partial"
    assert meta["missing_total"] > 0
    assert meta["weekly_cap_violations"] == []
    assert any("尚未填寫教師每週基準節數" in item for item in meta["compliance_warnings"])
    assert engine.validate(data, sched, tasks, overlay) == []


def test_v4_parser_is_preserved():
    data = engine.load_data(V4_TEMPLATE)

    assert data.get("schema_version", 4) == 4
    assert data["classes"]
    assert data["subjects"]


def _validation_fixture(classes, subject_info):
    return {
        "classes": classes,
        "grade_slot": {(1, day, period): True for day in engine.DAYS for period in engine.PERIODS},
        "teacher_limit": set(),
        "grade_limit": set(),
        "class_limit": set(),
        "room_blocked": set(),
        "rooms": {"R00": 999},
        "locks": [],
        "roster": {},
    }, subject_info


def test_validator_detects_nonconsecutive_two_period_block():
    data, info = _validation_fixture(
        [{"code": "1甲", "grade": 1}],
        {"block": "2連堂", "banned": set()},
    )
    tasks = {("1甲", "視覺藝術"): {"h": 2, "info": info}}
    sched = {
        ("1甲", "一", 1): ("視覺藝術", "張老師", "R00"),
        ("1甲", "一", 3): ("視覺藝術", "張老師", "R00"),
    }

    assert any("H09違反" in error for error in engine.validate(data, sched, tasks))


def test_validator_detects_tutor_daily_hard_cap():
    classes = [{"code": f"1班{i}", "grade": 1} for i in range(1, 8)]
    data, info = _validation_fixture(classes, {"block": "", "banned": set()})
    data["roster"] = {"王導師": "導師"}
    tasks = {(c["code"], "課程"): {"h": 1, "info": info} for c in classes}
    sched = {(c["code"], "一", i): ("課程", "王導師", "R00")
             for i, c in enumerate(classes, 1)}

    assert any("每日上限違反" in error for error in engine.validate(data, sched, tasks))


def test_excel_safe_neutralizes_formula_prefixes():
    for value in ("=1+1", "+SUM(A1:A2)", "-2+3", "@SUM(A1:A2)", "  =CMD()"):
        protected = engine.excel_safe(value)
        assert protected.startswith("'")
        assert protected[1:] == value

    assert engine.excel_safe("一般文字") == "一般文字"
    assert engine.excel_safe(12) == 12


def test_infeasibility_diagnosis_finds_class_and_teacher_capacity():
    task = {"h": 3, "t": "王老師", "room": "R00",
            "info": {"block": "", "banned": set()}}
    data = {
        "locks": [], "rooms": {"R00": 999}, "room_names": {},
        "room_blocked": set(), "native_groups": [], "roster": {"王老師": "科任"},
    }
    tasks = {("1甲", "數學"): task}
    candidates = {
        ("1甲", "數學", "一", 1): object(),
        ("1甲", "數學", "二", 1): object(),
    }

    diagnostics = engine.diagnose_infeasibility(data, tasks, candidates)

    assert any(item["title"] == "1甲 可排節次不足" for item in diagnostics)
    assert any(item["title"] == "王老師的授課容量不足" for item in diagnostics)
    assert all(item["confirmed"] is True for item in diagnostics)
