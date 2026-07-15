import subprocess
import json
from support_paths import FORMAL


def test_formal_frontend_supports_direct_case_setup_and_solve():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script = (FORMAL / "setup-builder.js").read_text(encoding="utf-8")
    auth = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert 'data-v="build"' in html
    assert "<title>國民小學課務排程輔助系統｜正式版</title>" in html
    assert 'name="application-name" content="國民小學課務排程輔助系統"' in html
    assert "DEMO｜示範資料（已匿名化）" not in html
    assert 'id="setupClassesTable"' in html
    assert 'id="setupTeachersTable"' in html
    assert 'id="setupSubjectsTable"' in html
    assert 'id="setupAssignmentsTable"' in html
    assert 'id="formalFile"' not in html
    assert "ScheduleAuth.solveData(payload)" in html
    assert "ScheduleSetup.validate()" in html
    assert "teacherAccounts" in script
    assert 'role: classCodes.length ? "導師"' in script
    assert "importTeacherRecords" in auth
    assert "下載 Excel 母版填寫後再上傳" in html
    assert "上傳填妥的 Excel" in html
    assert html.index("下載 Excel 母版</a>") < html.index("上傳填妥的 Excel")
    assert "排課母版範本_v6.xlsx" in html
    assert "教師與配課" in html
    assert "正式排課・Google 驗證" not in html
    assert 'id="setupTutorNames"' in html
    assert "導師可調整負責班級" in html
    assert "只填帳號，不需提供密碼" in html
    assert "學校 Google 帳號" in script
    assert "教育部學校代碼（6碼）" in html
    assert 'id="platformSchoolRecordId"' in html
    assert "教育部學校代碼須為 6 位數字" in auth
    assert 'moe_code: schoolCode' in auth
    assert 'school.moe_code || "尚未設定"' in auth


def test_setup_builder_javascript_has_valid_syntax():
    subprocess.run(
        ["node", "--check", str(FORMAL / "setup-builder.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_assignment_table_has_viewport_bottom_horizontal_scroller():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script = (FORMAL / "setup-builder.js").read_text(encoding="utf-8")

    assert 'id="setupAssignmentsScroll"' in html
    assert 'id="setupAssignmentsScrollDock"' in html
    assert 'aria-label="配課表水平捲動"' in html
    assert ".assignment-scroll-dock{position:fixed;bottom:0" in html
    assert "function bindAssignmentScroll()" in script
    assert 'scroller.addEventListener("scroll", fromTable' in script
    assert 'dock.addEventListener("scroll", fromDock' in script
    assert "scroller.scrollWidth > scroller.clientWidth + 1" in script


def test_custom_county_policy_frontend_is_wired_and_valid():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    policy = FORMAL / "schedule-policy.js"
    builder = (FORMAL / "setup-builder.js").read_text(encoding="utf-8")

    subprocess.run(
        ["node", "--check", str(policy)], check=True, capture_output=True,
        text=True, encoding="utf-8")
    assert 'id="setupPolicyPanel"' in html
    assert 'src="schedule-policy.js' in html
    assert html.index('src="schedule-policy.js') < html.index('src="setup-builder.js')
    assert "角色基準＋超鐘點−減課" in html
    assert "每日最多" in policy.read_text(encoding="utf-8") or "dailyHardCap: 6" in policy.read_text(encoding="utf-8")
    assert "縣市／適用單位" in builder
    assert "適用學年度" in builder
    assert "各縣市適用" in builder
    assert "套用新竹市建議值" not in builder
    assert "授課節數編配原則已經校務會議審議通過" not in builder
    assert "學生作息與課表已納入課程計畫" not in builder


def test_custom_policy_calculates_role_individual_and_daily_targets():
    script = r"""
const fs=require('fs'),vm=require('vm');
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const data={classes:Array.from({length:16},(_,i)=>({g:1,code:`1班${i+1}`})),
  subjects:{課程:{hours:[23,0,0,0,0,0]}},roster:{王老師:'導師',李組長:'組長'},
  tcap:{王老師:{extra:2,minus:1,reason:'其他核定'}},policy:{profileId:'tw-elementary-custom-v1',
    region:'臺中市',academicYear:115,periodMinutes:40,dailyHardCap:5,
    weeklyTargets:{導師:16,科任:20,組長:8,主任:2}}};
process.stdout.write(JSON.stringify({homeroom:SchedulePolicy.teacherTarget(data,'王老師'),
  chief:SchedulePolicy.weeklyTarget(data,'組長'),daily:SchedulePolicy.hardDailyCap(data)}));
"""
    result = subprocess.run(
        ["node", "-e", script, str(FORMAL / "schedule-policy.js")],
        check=True, capture_output=True, text=True, encoding="utf-8")

    assert json.loads(result.stdout) == {"homeroom": 17, "chief": 8, "daily": 5}


def test_class_tutor_is_added_to_roster_and_tutor_assignments():
    script = r"""
const fs=require('fs'),vm=require('vm');
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const data={classes:[{g:1,i:1,code:'1甲',tutor:'',res:false}],roster:{},teacherAccounts:{},
  teacherNativeLangs:{},tcap:{},subjects:{'國語文':{self:true,hours:[1,0,0,0,0,0]}},
  assign:{'1甲':{}},override:{},locks:[],resGroups:[],nativeBands:[],nativeGroups:[],rooms:{R00:99}};
ScheduleSetup.init({getData:()=>data,getLimits:()=>[],escape:String,commit:()=>{},startBlank:()=>true,syncTeachers:async()=>({})});
ScheduleSetup.setClass(0,'tutor','王老師');
process.stdout.write(JSON.stringify({tutor:data.classes[0].tutor,role:data.roster['王老師'],assignment:data.assign['1甲']['國語文']}));
"""
    result = subprocess.run(
        ["node", "-e", script, str(FORMAL / "setup-builder.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert json.loads(result.stdout) == {
        "tutor": "王老師", "role": "導師", "assignment": "王老師"}


def test_teacher_subject_skills_and_per_class_arrangement_mode_are_saved():
    script = r"""
const fs=require('fs'),vm=require('vm');
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const data={classes:[{g:3,i:1,code:'3甲',tutor:'王老師',res:false}],
  roster:{'王老師':'導師','李老師':'科任'},teacherAccounts:{},teacherNativeLangs:{},
  teacherSubjects:{},tcap:{},subjects:{'自然科學':{self:false,hours:[0,0,3,0,0,0]}},
  assign:{'3甲':{'自然科學':'王老師'}},assignmentModes:{},override:{},locks:[],
  resGroups:[],nativeBands:[],nativeGroups:[],rooms:{R00:99}};
ScheduleSetup.init({getData:()=>data,getLimits:()=>[],escape:String,commit:()=>{},startBlank:()=>true,syncTeachers:async()=>({})});
ScheduleSetup.setTeacher(0,'subjects','自然科學、音樂');
ScheduleSetup.setAssignmentMode('3甲','自然科學',true);
const tutorMode=data.assignmentModes['3甲']['自然科學'];
ScheduleSetup.setAssignment('3甲','自然科學','李老師');
process.stdout.write(JSON.stringify({subjects:data.teacherSubjects['王老師'],tutorMode,
  releasedMode:data.assignmentModes['3甲']['自然科學']}));
"""
    result = subprocess.run(
        ["node", "-e", script, str(FORMAL / "setup-builder.js")],
        check=True, capture_output=True, text=True, encoding="utf-8")

    assert json.loads(result.stdout) == {
        "subjects": ["自然科學", "音樂"], "tutorMode": "tutor",
        "releasedMode": "engine",
    }


def test_formal_workflow_pages_have_collapsed_help():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")

    assert html.count('class="step-help"') == 11
    assert html.count("<summary>操作說明</summary>") == 11
    assert "導師課預設保留給老師登入後自行安排" in html
    assert "不需要 AI 或模型 API" in html
    assert 'name="formalRunMode" value="tutor" checked' in html
    assert "use_openai:false" in html
    assert 'id="formalUseAI"' not in html
    assert "本次導師課已由 CP-SAT 排完" in html
    assert "資源班綁課屬於鎖定課程" in html
    assert "const limitSheet=opt('不排課時間').length?opt('不排課時間'):opt('教師時段限制')" in html
    assert "for(const r of opt('資源班overlay').slice(1))" in html
    assert "nd.resGroups=Object.entries(rgMap)" in html
    assert ".step-help[open] summary::after" in html
    assert 'id="formalDiagnosis"' in html
    assert "CP-SAT 規則診斷" in html
    assert "renderFormalDiagnosis(data.diagnostics,data.status)" in html
    assert "不使用 AI，也不會呼叫模型 API" in html
    assert "chihhung1988@gmail.com" in html
    assert "教育部六碼學校代碼" in html
    assert "學校 Google Workspace 網域" in html
    assert ">撰寫申請信</a>" in html
    assert "排課管理員 1 Google 帳號（須為同網域）" in html
    assert "排課管理員 2 Google 帳號（選填，須為同網域）" in html
    assert "聯絡電話或 Email" not in html
    assert "排課管理員帳號（可多人）" in html


def test_formal_destructive_buttons_warn_and_invalidate_old_schedule():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")

    assert "匯入 Excel 會取代目前案件" in html
    assert "載入工作進度會取代目前畫面" in html
    assert "function removeLimit(index)" in html
    assert "function removeRule(index)" in html
    assert "function removeResGroup(index)" in html
    assert "確定刪除「${group.grp||group.lang||'此語言分組'}」" in html
    assert "確定清除${classroom?clsName(classroom):code}由導師自行排入" in html
    assert "function saveLimitChange(label)" in html
    assert "function saveRuleChange(label)" in html
    assert "invalidateSchedule();rebuildLim();renderLim();renderGGrid();saveLS" in html
    assert "if(!first)return alert('請先在「資料建置」建立班級" in html


def test_publish_and_export_buttons_require_a_complete_schedule():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    auth = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert html.count("data-schedule-export onclick") == 6
    assert "function schedulePublishability()" in html
    assert "button.disabled=!hasSchedule" in html
    assert "尚有 ${publishability.hard} 項硬規則問題" in html
    assert "root.schedulePublishability" in auth
    assert "課表尚未完成：${result.hard} 項硬規則問題" in auth


def test_native_language_lock_supports_original_class_and_optional_extraction_groups():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script = (FORMAL / "setup-builder.js").read_text(encoding="utf-8")

    assert 'data-v="native"' in html
    assert 'id="nativeTable"' in html
    assert 'id="nativeBandTable"' in html
    assert "班級共同時段" in html
    assert "語言抽離分組" in html
    assert "syncNativeHardLocks" in html
    assert "nativeQualifiedTeachers" in html
    assert "teacherNativeLangs" in script
    assert "來源班級" in html
    assert "語別／組別" in html
    assert "更多設定" in html
    assert "nativeGradeFromSources" in html
    assert "<th>年級</th><th>語別</th><th>分組名稱</th>" not in html
    assert "可授本土語別" in script
    assert "教支人員" in script
    assert "createMinnanGroups" in html
    assert "符合可授語別" in html
    assert "依班級建立閩南語組" not in html
    assert "語言分組鎖定" in html
    assert "閩南語原班教師與班級" in html
    assert 'return subject === "本土語文" ? "閩南語（原班）"' in script
    assert "閩南語|臺語|台語" in html
    assert "group.t === name || group.assistant === name" in script
    assert 'id="nativeLockToggle"' in html
    assert "setNativeLockEnabled" in html
    assert "s==='本土語文'" in html
    assert "本土語文必須設定且只能有一個固定節次" in script
    assert "本土語文每週節數必須為 1" in script
    assert "尚未建立本土語課鎖定分組" not in script
    assert "本土語分組必須使用相同星期與節次" in script


def test_untrusted_excel_files_use_patched_reader_only():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    reader = FORMAL / "vendor" / "xlsx.reader.full.min.js"

    assert reader.is_file()
    assert "script.src='vendor/xlsx.reader.full.min.js?v=0.20.3'" in html
    assert "function loadSafeXlsxReader()" in html
    assert "window.XLSX=writer" in html
    assert "await loadSafeXlsxReader()" in html
    assert "const reader=window.SCHEDULE_XLSX_READER" in html
    assert "XLSX.read(" not in html
    assert b'0.20.3' in reader.read_bytes()


def test_tutor_workflow_is_locked_until_first_stage_is_ready():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    auth = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert 'id="tutorPrerequisite"' in html
    assert "body.tutor-not-ready #tutorWorkPanel" in html
    assert "if(!SCHEDULE_READY)return alert('請先完成第一階段排課。')" in html
    assert "scheduleReady:SCHEDULE_READY" in html
    assert "snapshot.schedule_ready===true" in html
    assert "scheduleReady:SCHEDULE_READY" in html
    assert "!snapshot.scheduleReady" in auth


def test_setup_issues_are_expandable_and_generated_fields_are_named():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script = (FORMAL / "setup-builder.js").read_text(encoding="utf-8")

    assert 'id="setupIssueDetails"' in script
    assert "完整檢核清單" in script
    assert "展開全部 ${policyIssues.length} 項規則檢核" in script
    assert 'aria-label="${esc(name)}學校 Google 帳號"' in script
    assert 'aria-label="${esc(name)} ${gradeIndex + 1} 年級每週節數"' in script
    assert "details.scrollIntoView" in script
    assert "body.platform-admin-mode aside{display:none}" in html
