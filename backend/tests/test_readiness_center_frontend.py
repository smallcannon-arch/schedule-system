import json
import subprocess

from support_paths import FORMAL


MODULE = FORMAL / "readiness-center.js"


def run_node(script):
    result = subprocess.run(
        ["node", "-e", script, str(MODULE)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_readiness_center_classifies_blockers_and_builds_automatic_checklist():
    output = run_node(r"""
global.document={getElementById:()=>null,querySelectorAll:()=>[]};
require(process.argv[1]);
ScheduleReadiness.initialize({
  mode:'formal',
  getData:()=>({classes:[{code:'1甲'}]}),
  getSetupValidation:()=>({
    hard:['1甲 國語文尚未配課','3年級本土語共同時段不正確'],
    warnings:['王老師尚未填 Google 帳號'],
    counts:{classes:1,teachers:1,subjects:1,assignments:0,assignmentTotal:1,assignmentMissing:1}
  }),
  isScheduleReady:()=>false,
  getScheduleValidation:()=>({hard:[],pending:[]}),
  getExportIssues:()=>[],
  getCloudState:()=>({isAdmin:true,hasCloudDraft:false,draftConflict:false,activeRevision:''}),
  navigate:()=>{}
});
const report=ScheduleReadiness.collect();
process.stdout.write(JSON.stringify({
  blockers:report.counts.blocker,
  foundation:report.groups.find(x=>x.id==='foundation').items.map(x=>x.view),
  conditions:report.groups.find(x=>x.id==='conditions').items.map(x=>x.view),
  checklist:report.checklist.map(x=>[x.label,x.done])
}));
""")

    assert output["blockers"] == 3
    assert "build" in output["foundation"]
    assert "native" in output["conditions"]
    assert output["checklist"][0] == ["建立或載入案件", True]
    assert output["checklist"][3] == ["完成配課", False]
    assert output["checklist"][6] == ["儲存學校雲端", False]


def test_readiness_center_uses_validator_source_instead_of_message_guessing():
    output = run_node(r"""
global.document={getElementById:()=>null,querySelectorAll:()=>[]};
require(process.argv[1]);
const hardItems=[
  {text:'1甲 數學固定在週三第4節，但該年級此時段不上課',
   group:'conditions',view:'fixed',label:'檢查固定課程'},
  {text:'一年級A組固定時段週三第4節不在來源年級可排時段',
   group:'conditions',view:'res',label:'檢查資源班'},
  {text:'1甲在週三第4節的語言抽離群組沒有共同可抽離科目',
   group:'conditions',view:'native',label:'檢查語言分組'}
];
ScheduleReadiness.initialize({
  mode:'formal',getData:()=>({classes:[{code:'1甲'}]}),
  getSetupValidation:()=>({
    hard:hardItems.map((item)=>item.text),hardItems,warnings:[],
    counts:{classes:1,teachers:1,subjects:1,assignmentTotal:1,assignmentMissing:0}
  }),
  isScheduleReady:()=>false,getScheduleValidation:()=>({hard:[],pending:[]}),
  getExportIssues:()=>[],getCloudState:()=>({isAdmin:false}),navigate:()=>{}
});
const report=ScheduleReadiness.collect();
process.stdout.write(JSON.stringify(
  report.groups.find((group)=>group.id==='conditions').items
    .filter((item)=>item.level==='blocker')
    .map((item)=>({text:item.text,view:item.view,label:item.label}))
));
""")

    assert [item["view"] for item in output] == ["fixed", "res", "native"]
    assert [item["label"] for item in output] == [
        "檢查固定課程", "檢查資源班", "檢查語言分組"]


def test_readiness_center_never_marks_diagnostic_draft_as_formally_complete():
    output = run_node(r"""
global.document={getElementById:()=>null,querySelectorAll:()=>[]};
require(process.argv[1]);
ScheduleReadiness.initialize({
  mode:'formal',
  getData:()=>({classes:[{code:'1甲'}]}),
  getSetupValidation:()=>({
    hard:[],warnings:[],counts:{classes:1,teachers:1,subjects:1,
      assignmentTotal:1,assignmentMissing:0}
  }),
  isScheduleReady:()=>true,
  isDiagnosticDraft:()=>true,
  getScheduleValidation:()=>({hard:[],pending:[]}),
  getExportIssues:()=>[],
  getCloudState:()=>({isAdmin:false,hasCloudDraft:true,draftConflict:false,activeRevision:''}),
  navigate:()=>{}
});
const report=ScheduleReadiness.collect();
process.stdout.write(JSON.stringify({
  schedule:report.groups.find(x=>x.id==='schedule').items,
  completed:report.checklist.find(x=>x.label==='完成正式排課').done
}));
""")

    assert output["completed"] is False
    assert any(item["level"] == "blocker" and "診斷草案" in item["text"]
               for item in output["schedule"])


def test_readiness_center_frontend_controls_and_backup_actions_are_wired():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    auth = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert 'data-v="readiness"' in html
    assert 'id="onboardingChecklist"' in html
    assert 'id="readinessSummary"' in html
    assert 'id="readinessGroups"' in html
    assert 'id="backupHistoryDialog"' in html
    assert 'id="createBackupButton"' in html
    assert "resourceItems=resourceIssues.map" in html
    assert "hardItems:[...(result.hardItems||result.hard||[]),...resourceItems]" in html
    assert 'request("/admin/backups", {method: "POST"})' in auth
    assert '/admin/backups/${encodeURIComponent(backupId)}/restore' in auth
    assert "已發布的正式教師課表不會改動" in auth


def test_readiness_center_javascript_has_valid_syntax():
    subprocess.run(
        ["node", "--check", str(MODULE)], check=True, capture_output=True,
        text=True, encoding="utf-8")
