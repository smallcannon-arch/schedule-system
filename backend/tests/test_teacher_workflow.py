import json
import subprocess
from support_paths import ONLINE


MODULE = ONLINE / "teacher-workflow.js"


def run_node(script):
    result = subprocess.run(
        ["node", "-e", script, str(MODULE)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_resource_subjects_are_engine_owned_but_only_overlay_slots_are_locked():
    output = run_node(r"""
const workflow=require(process.argv[1]);
const data={
  classes:[{code:'3甲',res:true}],
  subjects:{'國語文':{},'數學':{},'綜合活動':{}},
  resGroups:[{sources:['3甲'],subj:'國語文',pullSubjects:['國語文','綜合活動']}]
};
const schedule={
  '3甲|一|1':{s:'國語文'},
  '3甲|一|2':{s:'綜合活動'},
  '3甲|一|3':{s:'數學'}
};
const overlay=[{code:'3甲',d:'一',p:2,subj:'綜合活動'}];
process.stdout.write(JSON.stringify({
  language:workflow.isResourceBound(data,'3甲','國語文'),
  math:workflow.isResourceBound(data,'3甲','數學'),
  group:workflow.isResourceBound(data,'3甲','綜合活動'),
  lock1:workflow.isResourceLockedSlot(data,schedule,overlay,'3甲','一',1),
  lock2:workflow.isResourceLockedSlot(data,schedule,overlay,'3甲','一',2),
  free:workflow.isResourceLockedSlot(data,schedule,overlay,'3甲','一',4)
}));
""")

    assert output == {
        "language": True,
        "math": False,
        "group": True,
        "lock1": False,
        "lock2": True,
        "free": False,
    }


def test_teacher_package_signature_changes_when_fixed_schedule_changes():
    output = run_node(r"""
const workflow=require(process.argv[1]);
const data={classes:[{code:'3甲',g:3,tutor:'王老師',res:false}],subjects:{'國語文':{}},
  resGroups:[],locks:[],limits:[],gslot:{3:[[1]]}};
const a={'3甲|一|1':{s:'國語文',t:'王老師',room:'R00'}};
const b={'3甲|一|2':{s:'國語文',t:'王老師',room:'R00'}};
const one=workflow.fixedSignature(data,a,[],'3甲',['二|3']);
const stable=workflow.fixedSignature(data,a,[],'3甲',['二|3']);
const changed=workflow.fixedSignature(data,b,[],'3甲',['二|3']);
process.stdout.write(JSON.stringify({stable:one===stable,changed:one!==changed}));
""")

    assert output == {"stable": True, "changed": True}


def test_frontend_loads_teacher_workflow_before_main_logic():
    html = (ONLINE / "index.html").read_text(encoding="utf-8")

    assert '<script src="teacher-workflow.js?v=20260717-1"></script>' in html
    assert html.index('src="teacher-workflow.js?') < html.index("const DAYS=")
    assert "if(isResourceBound(code,s))" in html
    assert "currentTeacherSignature(code)!==issued.baseSignature" in html
    assert "ts.add(o.t+'（資源班）')" not in html
    assert "val.endsWith('（資源班）')" not in html


def test_teacher_package_encryption_round_trip_and_wrong_code_rejection():
    output = run_node(r"""
const workflow=require(process.argv[1]);
(async()=>{
  const payload={schema:'schedule-teacher-package-v1',class_code:'3甲',placements:{'一|1':'國語文'}};
  const envelope=await workflow.encryptPackage(payload,'Class-9A-safe');
  const restored=await workflow.decryptPackage(envelope,'Class-9A-safe');
  let rejected=false;
  try{await workflow.decryptPackage(envelope,'wrong-code')}catch(error){rejected=true}
  process.stdout.write(JSON.stringify({
    encrypted:envelope.schema==='schedule-teacher-encrypted-v1'&&!JSON.stringify(envelope).includes('3甲'),
    restored:restored.class_code,
    rejected
  }));
})().catch(error=>{console.error(error);process.exit(1)});
""")

    assert output == {"encrypted": True, "restored": "3甲", "rejected": True}
