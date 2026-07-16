import json
import subprocess
from support_paths import ONLINE


MODULE = ONLINE / "schedule-editor.js"


def run_node(script):
    result = subprocess.run(
        ["node", "-e", script, str(MODULE)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_resource_fixed_and_block_lessons_have_lock_reasons():
    output = run_node(r"""
const editor=require(process.argv[1]);
const data={
  classes:[{code:'3甲',res:true}],
  subjects:{'國語文':{block:''},'自然科學':{block:'2+1'},'社會':{block:''}},
  resGroups:[{sources:['3甲'],subj:'國語文',pullSubjects:['國語文']}],
  locks:[{c:'3甲',d:'二',p:3,s:'社會'}]
};
const schedule={
  '3甲|一|1':{s:'國語文'},
  '3甲|一|2':{s:'自然科學'},
  '3甲|二|3':{s:'社會'}
};
process.stdout.write(JSON.stringify({
  resource:editor.lockedReason(data,schedule,[],'3甲','一',1),
  block:editor.lockedReason(data,schedule,[],'3甲','一',2),
  fixed:editor.lockedReason(data,schedule,[],'3甲','二',3),
  overlay:editor.lockedReason(data,schedule,[{code:'3甲',d:'四',p:4}],'3甲','四',4),
  free:editor.lockedReason(data,schedule,[],'3甲','五',1)
}));
""")

    assert output == {
        "resource": "資源班綁課",
        "block": "2+1 課程需整組調整",
        "fixed": "固定課鎖定",
        "overlay": "資源班抽離綁課",
        "free": "",
    }


def test_snapshot_diff_reports_removed_and_added_slots_for_move():
    output = run_node(r"""
const editor=require(process.argv[1]);
const before={sol:{'3甲|一|1':{s:'社會',t:'王師',room:'R00'}},tp:{}};
const after={sol:{'3甲|二|2':{s:'社會',t:'王師',room:'R00'}},tp:{}};
const changes=editor.diffSnapshots(before,after);
process.stdout.write(JSON.stringify(changes.map(x=>({key:x.key,kind:x.kind}))));
""")

    assert output == [
        {"key": "engine|3甲|一|1", "kind": "removed"},
        {"key": "engine|3甲|二|2", "kind": "added"},
    ]
