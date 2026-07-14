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


def test_readiness_center_frontend_controls_and_backup_actions_are_wired():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    auth = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert 'data-v="readiness"' in html
    assert 'id="onboardingChecklist"' in html
    assert 'id="readinessSummary"' in html
    assert 'id="readinessGroups"' in html
    assert 'id="backupHistoryDialog"' in html
    assert 'id="createBackupButton"' in html
    assert 'request("/admin/backups", {method: "POST"})' in auth
    assert '/admin/backups/${encodeURIComponent(backupId)}/restore' in auth
    assert "已發布的正式教師課表不會改動" in auth


def test_readiness_center_javascript_has_valid_syntax():
    subprocess.run(
        ["node", "--check", str(MODULE)], check=True, capture_output=True,
        text=True, encoding="utf-8")
