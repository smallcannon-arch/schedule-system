import subprocess
import json
import re
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
    assert 'id="platformSchoolFormMode">新增學校' in html
    assert "教育部學校代碼須為 6 位數字" in auth
    assert 'moe_code: schoolCode' in auth
    assert 'school.moe_code || "尚未設定"' in auth
    assert 'document.getElementById("platformSchoolId").readOnly = true' in auth
    assert "既有學校的教育部代碼不可變更" in auth
    assert "表單已清空，可繼續新增下一間學校" in auth


def test_setup_builder_javascript_has_valid_syntax():
    subprocess.run(
        ["node", "--check", str(FORMAL / "setup-builder.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_pages_workflow_copies_every_local_frontend_script():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    workflow = (FORMAL / ".github" / "workflows" / "verify-and-deploy.yml").read_text(
        encoding="utf-8")
    local_scripts = {
        src.split("?", 1)[0]
        for src in re.findall(r'<script\s+src="([^"]+)"', html)
        if not src.startswith(("http://", "https://"))
    }

    for script in local_scripts:
        if script.startswith("vendor/"):
            assert "cp -R vendor _site/vendor" in workflow
        else:
            assert script in workflow, f"GitHub Pages deployment omits {script}"


def test_setup_builder_preserves_combined_resource_references_when_names_change():
    script = r"""
const fs=require('fs'),vm=require('vm');
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const data={classes:[{g:3,i:1,code:'3甲',tutor:'王老師',res:true},{g:3,i:2,code:'3乙',tutor:'李老師',res:true}],
  roster:{'王老師':'導師','李老師':'導師','資源教師':'科任'},teacherAccounts:{},teacherNativeLangs:{},teacherSubjects:{},tcap:{},
  subjects:{'資源課程':{self:false,hours:[0,0,1,0,0,0]},'綜合活動':{self:true,hours:[0,0,1,0,0,0]}},
  assign:{'3甲':{'資源課程':'資源教師','綜合活動':'王老師'},'3乙':{'資源課程':'資源教師','綜合活動':'李老師'}},
  assignmentModes:{},override:{},locks:[],resGroups:[{id:'resource-a',grp:'三年級A組',sources:['3甲','3乙'],
    subj:'資源課程',pullSubjects:['綜合活動'],t:'資源教師',n:1}],nativeBands:[],nativeGroups:[],rooms:{R00:99}};
ScheduleSetup.init({getData:()=>data,getLimits:()=>[],escape:String,commit:()=>{},startBlank:()=>true,syncTeachers:async()=>({})});
ScheduleSetup.renameClass(1,'3丙');
ScheduleSetup.renameSubject(0,'學習策略');
ScheduleSetup.renameSubject(0,'彈性學習');
process.stdout.write(JSON.stringify(data.resGroups[0]));
"""
    result = subprocess.run(
        ["node", "-e", script, str(FORMAL / "setup-builder.js")],
        check=True, capture_output=True, text=True, encoding="utf-8")

    group = json.loads(result.stdout)
    assert group["sources"] == ["3甲", "3丙"]
    assert group["subj"] == "學習策略"
    assert group["pullSubjects"] == ["彈性學習"]


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
    assert "只有實際抽離的節次會鎖定" in html
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


def test_schedule_result_counts_resource_sessions_once_and_zero_target_is_not_overtime():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")

    assert "uniqueResourceSessions(OVL).length" in html
    assert "const hasTarget=SchedulePolicy.hasWeeklyTarget(role)&&quota>0" in html
    assert "可供資源班抽離" in html
    assert "資源班鎖定" not in html


def test_pastel_action_colors_meet_normal_text_contrast_palette():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")

    variables = dict(re.findall(r"--([a-z-]+):(#[0-9a-fA-F]{6})", html))

    def luminance(value):
        channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= 0.03928
                  else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    for name in ("pink", "mint", "lav", "peach", "lemon", "sky"):
        light, dark = luminance(variables[name]), luminance(variables[f"{name}-d"])
        contrast = (max(light, dark) + 0.05) / (min(light, dark) + 0.05)
        assert contrast >= 4.5, f"{name} contrast is only {contrast:.2f}:1"


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
    assert "invalidateSchedule();rebuildLim();renderLim();renderGGrid();renderTeacherLimitGrid();saveLS" in html
    assert "if(!first)return alert('請先在「資料建置」建立班級" in html


def test_teacher_quick_limits_and_combined_resource_groups_are_wired():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")

    assert 'id="teacherLimitGrid"' in html
    assert "function blockAllTeacherSlots()" in html
    assert "function duplicateLimit(index)" in html
    assert "function compactTeacherLimits(teacher,blocked)" in html
    assert "function normalizeResourceGroups()" in html
    assert "function rgToggleSource(index,code,checked)" in html
    assert "function rgTogglePullSubject(index,subject,checked)" in html
    assert "function rgToggleSlot(index,day,period)" in html
    assert 'id="resourceGroupHint"' in html
    assert "pullSubjects" in html
    assert "scheduleMode" in html
    limit_start = html.index('<section class="view" id="v-lim">')
    limit_end = html.index("</section>", limit_start)
    teacher_grid = html.index('id="teacherLimitGrid"')
    assert limit_start < html.index('id="gGrid"') < teacher_grid < html.index('id="limTbl"') < limit_end


def test_v6_browser_import_reports_invalid_rows_and_accepts_valid_fixture():
    script = r"""
const fs=require('fs'),vm=require('vm');
const XLSX=require(process.argv[2]);
const html=fs.readFileSync(process.argv[1],'utf8');
const source=html.slice(html.indexOf('function importRowHasData'),html.indexOf('ScheduleSetup.init'));
const bytes=fs.readFileSync(process.argv[3]);
function parse(workbook){
  const context={DEMO0:{rules:[]},DAYS:['一','二','三','四','五'],
    nativeSourceCodes:value=>String(value||'').split(/[、,，;；\s]+/).filter(Boolean),console};
  context.__wb=workbook;context.__XLSX=XLSX;vm.createContext(context);vm.runInContext(source,context);
  vm.runInContext(`globalThis.__S=n=>__XLSX.utils.sheet_to_json(__wb.Sheets[n],{header:1,defval:null});
    globalThis.__opt=n=>__wb.Sheets[n]?__S(n):[];globalThis.__nd=parseV5(__wb,__S,__opt);`,context);
  return context.__nd;
}
const baseline=parse(XLSX.read(bytes,{type:'buffer'}));
const custom=XLSX.read(bytes,{type:'buffer'});
XLSX.utils.sheet_add_aoa(custom.Sheets['科目節數'],[['閱讀',1,0,0,0,0,0,'原班教室','否','']],{origin:'A20'});
XLSX.utils.sheet_add_aoa(custom.Sheets['教師與配課'],[[custom.Sheets['教師與配課']['A3'].v,'閱讀','1甲']],{origin:'I20'});
const customResult=parse(custom);
const bad=XLSX.read(bytes,{type:'buffer'});
function addRow(name,headers,row,origin){
  if(!bad.Sheets[name]){bad.Sheets[name]=XLSX.utils.aoa_to_sheet([headers]);bad.SheetNames.push(name)}
  XLSX.utils.sheet_add_aoa(bad.Sheets[name],[row],{origin});
}
XLSX.utils.sheet_add_aoa(bad.Sheets['班級'],[['7甲','七年級','王導師']],{origin:'A11'});
XLSX.utils.sheet_add_aoa(bad.Sheets['教師與配課'],[[bad.Sheets['教師與配課']['A3'].v,'組長',20,0]],{origin:'A11'});
XLSX.utils.sheet_add_aoa(bad.Sheets['教師與配課'],[[bad.Sheets['教師與配課']['A3'].v,null,'1甲']],{origin:'I12'});
XLSX.utils.sheet_add_aoa(bad.Sheets['教師與配課'],[[bad.Sheets['教師與配課']['A3'].v,'英語文','1甲']],{origin:'I13'});
XLSX.utils.sheet_add_aoa(bad.Sheets['場地'],[[null,2]],{origin:'A20'});
XLSX.utils.sheet_add_aoa(bad.Sheets['場地'],[['自然教室',2]],{origin:'A21'});
XLSX.utils.sheet_add_aoa(bad.Sheets['場地'],[['創客教室',1.5]],{origin:'A22'});
XLSX.utils.sheet_add_aoa(bad.Sheets['科目節數'],[['閱讀','兩節',0,0,0,0,0,'原班教室','否','']],{origin:'A20'});
XLSX.utils.sheet_add_aoa(bad.Sheets['年段時段'],[['七年級',1,1]],{origin:'A9'});
XLSX.utils.sheet_add_aoa(bad.Sheets['本土語分組'],[[1,'一',1,'客語','名冊外教師','原班教室','','測試組','1甲',1,'實體']],{origin:'A20'});
addRow('不排課時間',['對象','星期','節次','類型','備註'],['王導師','六',1,'不可排',''],'A20');
addRow('資源班overlay',['組別','原班','科目','資源班教師','星期','節次'],['測試組','1甲','國語文','名冊外教師','',''],'A20');
let error='';try{parse(bad)}catch(reason){error=String(reason.message||reason)}
process.stdout.write(JSON.stringify({classes:baseline.classes.length,warnings:baseline._warn,
  customSubject:customResult.subjects['閱讀'],customAssignment:customResult.assign['1甲']['閱讀'],error}));
"""
    result = subprocess.run(
        ["node", "-e", script, str(FORMAL / "index.html"),
         str(FORMAL / "vendor" / "xlsx.full.min.js"),
         str(FORMAL / "backend" / "tests" / "fixtures" / "排課母版_v6.xlsx")],
        check=True, capture_output=True, text=True, encoding="utf-8")
    output = json.loads(result.stdout)

    assert output["classes"] == 3
    assert any("目前沒有符合的任教班級" in warning for warning in output["warnings"])
    assert output["customSubject"]["hours"][0] == 1
    assert output["customAssignment"]
    assert "班級 第 11 列" in output["error"]
    assert "教師與配課 第 11 列" in output["error"]
    assert "教師與配課 第 12 列" in output["error"]
    assert "教師與配課 第 13 列" in output["error"]
    assert "場地 第 20 列" in output["error"]
    assert "場地 第 21 列" in output["error"]
    assert "場地 第 22 列" in output["error"]
    assert "科目節數 第 20 列" in output["error"]
    assert "年段時段 第 9 列" in output["error"]
    assert "本土語分組 第 20 列" in output["error"]
    assert "不排課時間 第 20 列" in output["error"]
    assert "資源班overlay 第 20 列" in output["error"]


def test_teacher_quick_limits_compact_rows_and_preserve_manual_rules():
    script = r"""
const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync(process.argv[1],'utf8');
const start=html.indexOf('function teacherSlotsFromLimits');
const end=html.indexOf('/* 年級快速設定格 */',start);
const context={DAYS:['一','二','三','四','五'],PS:[1,2,3,4,5,6,7],LIMITS:[],saveLimitChange:()=>{}};
vm.createContext(context);vm.runInContext(html.slice(start,end),context);
const blocked=new Set(context.PS.map(p=>`一|${p}`));
context.DAYS.forEach(d=>blocked.add(`${d}|2`));blocked.add('三|3');
const compact=context.compactTeacherLimits('鐘點師',blocked);
context.LIMITS=[['鐘點師','一','1','不可排','行政會議'],
  ['鐘點師','二','1','不可排','教師快速設定']];
context.replaceTeacherBlockedSlots('鐘點師',new Set(['一|1','三|2']),'');
process.stdout.write(JSON.stringify({compact,preserved:context.LIMITS}));
"""
    result = subprocess.run(
        ["node", "-e", script, str(FORMAL / "index.html")],
        check=True, capture_output=True, text=True, encoding="utf-8")
    output = json.loads(result.stdout)

    assert output["compact"] == [
        ["鐘點師", "一", "全部", "不可排", "教師快速設定"],
        ["鐘點師", "每日", "2", "不可排", "教師快速設定"],
        ["鐘點師", "三", "3", "不可排", "教師快速設定"],
    ]
    assert output["preserved"] == [
        ["鐘點師", "一", "1", "不可排", "行政會議"],
        ["鐘點師", "三", "2", "不可排", "教師快速設定"],
    ]


def test_legacy_resource_rows_migrate_without_silent_class_merging():
    script = r"""
const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync(process.argv[1],'utf8');
const start=html.indexOf('function resourceId');
const end=html.indexOf('function resourceSourcePicker',start);
const classes=[{g:1,code:'1甲',res:false},{g:1,code:'1乙',res:false}];
const context={DAYS:['一','二','三','四','五'],PS:[1,2,3,4,5,6,7],
  DATA:{classes,subjects:{'國語文':{}},resGroups:[
    {grp:'A組',code:'1甲',subj:'國語文',t:'資源教師',n:3},
    {grp:'A組',code:'1乙',subj:'國語文',t:'資源教師',n:3}
  ]},CODE2C:{'1甲':classes[0],'1乙':classes[1]}};
vm.createContext(context);vm.runInContext(html.slice(start,end),context);
context.normalizeResourceGroups();
process.stdout.write(JSON.stringify({groups:context.DATA.resGroups.map(g=>g.sources),classes}));
"""
    result = subprocess.run(
        ["node", "-e", script, str(FORMAL / "index.html")],
        check=True, capture_output=True, text=True, encoding="utf-8")
    output = json.loads(result.stdout)

    assert output["groups"] == [["1甲"], ["1乙"]]
    assert [item["res"] for item in output["classes"]] == [True, True]


def test_resource_group_can_switch_grade_and_preserves_class_eligibility():
    script = r"""
const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync(process.argv[1],'utf8');
const start=html.indexOf('function resourceId');
const end=html.indexOf('function hoursOf',start);
const classes=[{g:1,code:'1甲',res:true},{g:2,code:'2甲',res:true},{g:2,code:'2乙',res:false}];
const context={DAYS:['一','二','三','四','五'],PS:[1,2,3,4,5,6,7],RESOURCE_PERIODS:[0,1,2,3,4,5,6,7],
  DATA:{classes,subjects:{'國語文':{}},roster:{'一般教師':'科任','資源教師':'資源班教師'},
    gslot:{2:[[1,1,1,1,0,0,0],[1,1,1,1,1,0,0],[1,1,1,1,0,0,0],[1,1,1,1,0,0,0],[1,1,1,1,0,0,0]]},resGroups:[
    {id:'group-a',grp:'一年級A組',sources:['1甲'],subj:'國語文',pullSubjects:['國語文'],t:'資源教師',n:1}
  ]},CODE2C:{'1甲':classes[0],'2甲':classes[1],'2乙':classes[2]},
  alert:message=>{context.lastAlert=message},invalidateSchedule:()=>{},renderRes:()=>{},fillTutor:()=>{},
  renderTLoad:()=>{},saveLS:()=>{},esc:String,clsName:c=>c.code,jsArg:JSON.stringify,document:{getElementById:()=>({})}};
vm.createContext(context);vm.runInContext(html.slice(start,end),context);
context.renderRes=()=>{};
context.normalizeResourceGroups();
context.rgToggleSource(0,'2甲',true);
context.DATA.resGroups[0].scheduleMode='fixed';
process.stdout.write(JSON.stringify({sources:context.DATA.resGroups[0].sources,groupName:context.DATA.resGroups[0].grp,classes,lastAlert:context.lastAlert||'',
  teacherHtml:context.resourceTeacherSelect(context.DATA.resGroups[0],0),
  pickerHtml:context.resourceSourcePicker(context.DATA.resGroups[0],0),
  slotHtml:context.resourceSlotGrid(context.DATA.resGroups[0],0)}));
"""
    result = subprocess.run(
        ["node", "-e", script, str(FORMAL / "index.html")],
        check=True, capture_output=True, text=True, encoding="utf-8")
    output = json.loads(result.stdout)

    assert output["sources"] == ["2甲"]
    assert output["groupName"] == "2年級A組"
    assert [item["res"] for item in output["classes"]] == [True, True, False]
    assert output["lastAlert"] == ""
    assert output["teacherHtml"].index("資源教師") < output["teacherHtml"].index("一般教師")
    assert "其他兼任教師" in output["teacherHtml"]
    assert "disabled" not in output["pickerHtml"]
    assert "早自修" in output["slotHtml"]
    assert "該年級此節不上課" in output["slotHtml"]


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


def test_resource_pull_subjects_use_a_wrapping_grid():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")

    assert 'class="resource-subject-checks"' in html
    assert ".resource-subject-checks{display:grid" in html
    assert "grid-template-columns:repeat(auto-fit,minmax(150px,1fr))" in html
    assert ".resource-subject-checks span{min-width:0;overflow-wrap:anywhere}" in html
