import json
import re
import subprocess
from support_paths import FORMAL


MODULE = FORMAL / "schedule-exports.js"
VENDOR = FORMAL / "vendor" / "xlsx.full.min.js"


def run_node(script):
    result = subprocess.run(
        ["node", "-e", script, str(MODULE)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_export_module_builds_class_teacher_and_upload_rows():
    output = run_node(r"""
const exp=require(process.argv[1]);
const data={
  classes:[{g:1,i:1,code:'1甲'}],
  subjects:{'國語文':{},'本土語文':{}},
  nativeLockEnabled:true,
  nativeBands:[{g:1,d:'二',p:1}],
  nativeGroups:[{g:1,grp:'一年級客語組',lang:'客語',sources:['1甲'],t:'客語教師',assistant:'協同教師'}]
};
const entries=exp.buildEntries(data,[
  {code:'1甲',d:'一',p:1,s:'國語文',t:'導師'},
  {code:'1甲',d:'二',p:1,s:'本土語文',t:''}
],[]);
const ids={'導師':'A123456789','客語教師':'B123456789'};
const upload=exp.uploadRows(data,entries,ids);
const classSheet=exp.classSheets(data,entries)[0];
const printable=exp.printDocument([classSheet],'班級課表');
process.stdout.write(JSON.stringify({
  classTitle:classSheet.rows[0][0],
  classSubtitle:classSheet.rows[1][0],
  teachers:exp.teacherSheets(data,entries).map(item=>item.name),
  headers:upload[0],
  nativeRow:upload.find(row=>row[4]==='客語教師'),
  assistantUploaded:upload.some(row=>row[4]==='協同教師'),
  issues:exp.validateUpload(data,entries,ids),
  printable
}));
""")

    assert output["classTitle"] == "一年甲班 班級課表"
    assert output["classSubtitle"] == "導師：未填　｜　班級代碼：1甲"
    assert set(output["teachers"]) == {"導師", "客語教師", "協同教師"}
    assert output["headers"] == [
        "星期幾", "第幾節", "年級", "班級", "教師姓名", "教師身分證號",
        "類別", "領域", "科目", "語言別", "校訂課程名稱", "上課頻率",
    ]
    assert output["nativeRow"][0:6] == ["週二", "第一節", "一年級", "第01班", "客語教師", "B123456789"]
    assert output["nativeRow"][8:10] == ["本土語文", "客語"]
    assert output["assistantUploaded"] is False
    assert output["issues"] == []
    assert "A4 landscape" in output["printable"]
    assert "學校正式課表" in output["printable"]
    assert "閩南語（原班）" in output["printable"]
    assert "客語" in output["printable"]


def test_special_language_group_does_not_replace_original_minnan_teacher():
    output = run_node(r"""
const exp=require(process.argv[1]);
const data={
  classes:[{g:1,i:1,code:'1甲',tutor:'王導師'}],subjects:{'本土語文':{}},
  nativeLockEnabled:true,nativeBands:[{g:1,d:'二',p:1}],
  nativeGroups:[{g:1,grp:'一年級客語組',lang:'客語',sources:['1甲'],t:'客語教師'}]
};
const entries=exp.buildEntries(data,[
  {code:'1甲',d:'二',p:1,s:'本土語文',t:'閩南教師',room:'R00'}
],[]);
process.stdout.write(JSON.stringify(entries));
""")

    by_source = {item["source"]: (item["displaySubject"], item["t"]) for item in output}
    assert by_source == {
        "native-base": ("閩南語（原班）", "閩南教師"),
        "native": ("客語", "客語教師"),
    }


def test_upload_validation_requires_private_teacher_id_mapping():
    output = run_node(r"""
const exp=require(process.argv[1]);
const data={classes:[{g:3,i:2,code:'3乙'}],subjects:{'數學':{}},nativeLockEnabled:false};
const entries=exp.buildEntries(data,[{code:'3乙',d:'三',p:4,s:'數學',t:'王老師'}],[]);
process.stdout.write(JSON.stringify({
  missing:exp.validateUpload(data,entries,{}),
  parsed:exp.parseTeacherIdRows([['教師姓名','教師身分證號'],['王老師','a123456789']])
}));
""")

    assert output["missing"] == ["王老師缺少教師身分證號"]
    assert output["parsed"] == {"王老師": "A123456789"}


def test_combined_resource_group_counts_one_teacher_period_and_lists_both_classes():
    output = run_node(r"""
const exp=require(process.argv[1]);
const data={classes:[{g:1,i:1,code:'1甲'},{g:1,i:2,code:'1乙'}],
  subjects:{'國語文':{}},nativeLockEnabled:false,roster:{'資源教師':'資源班教師'}};
const entries=exp.buildEntries(data,[],[
  {id:'group-a-1',grp:'一年級A組',code:'1甲',subj:'國語文',pullSubj:'綜合活動',t:'資源教師',d:'一',p:1},
  {id:'group-a-1',grp:'一年級A組',code:'1乙',subj:'國語文',pullSubj:'綜合活動',t:'資源教師',d:'一',p:1}
]);
const sheet=exp.teacherSheets(data,entries)[0];
process.stdout.write(JSON.stringify({subtitle:sheet.rows[1][0],cell:sheet.rows[3][1],entries}));
""")

    assert "每週授課：1 節" in output["subtitle"]
    assert "一年甲班" in output["cell"]
    assert "一年乙班" in output["cell"]
    assert len(output["entries"]) == 2


def test_resource_early_study_appears_in_timetables_but_not_upload_rows():
    output = run_node(r"""
const exp=require(process.argv[1]);
const data={classes:[{g:1,i:1,code:'1甲',tutor:'王導師'}],subjects:{'國語文':{}},
  nativeLockEnabled:false,roster:{'資源教師':'資源班教師'}};
const entries=exp.buildEntries(data,[],[
  {id:'group-a-1',grp:'一年級A組',code:'1甲',subj:'國語文',pullSubj:'早自修',t:'資源教師',d:'一',p:0}
]);
process.stdout.write(JSON.stringify({
  entries,
  classRows:exp.classSheets(data,entries)[0].rows,
  teacherRows:exp.teacherSheets(data,entries)[0].rows,
  upload:exp.uploadRows(data,entries,{'資源教師':'A123456789'}),
  issues:exp.validateUpload(data,entries,{'資源教師':'A123456789'})
}));
""")

    assert output["entries"][0]["p"] == 0
    assert output["classRows"][3][0] == "早自修"
    assert "國語文" in output["classRows"][3][1]
    assert output["teacherRows"][3][0] == "早自修"
    assert len(output["upload"]) == 1
    assert output["issues"] == ["尚無可匯出的正式課表資料"]


def test_excel_timetable_styles_are_written_to_cells():
    output = run_node(r"""
const exp=require(process.argv[1]);
const XLSX=require(process.argv[2]);
const rows=exp.classSheets({
  _school:'新竹市內湖國小',
  classes:[{g:1,i:1,code:'1甲',tutor:'江老師'}]
},[{code:'1甲',d:'一',p:1,s:'數學',displaySubject:'數學',t:'江老師'}])[0].rows;
const ws=exp.makeWorksheet(XLSX,rows,'timetable');
process.stdout.write(JSON.stringify({
  title:ws.A1.v,
  titleFill:ws.A1.s.fill.fgColor.rgb,
  mathFill:ws.B4.s.fill.fgColor.rgb,
  merges:ws['!merges'].length,
  orientation:ws['!pageSetup'].orientation
}));
""".replace("process.argv[2]", repr(str(VENDOR))))

    assert output == {
        "title": "新竹市內湖國小　一年甲班 班級課表",
        "titleFill": "294D45",
        "mathFill": "FFF3D7",
        "merges": 2,
        "orientation": "landscape",
    }


def test_frontend_wires_four_exports_and_keeps_ids_out_of_case_data():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")

    assert re.search(r'<script src="setup-builder\.js\?v=\d{8}-\d+"></script>', html)
    assert '<script src="schedule-exports.js?v=20260717-1"></script>' in html
    assert '<button data-v="export"><span class="ic">⇩</span>課表匯出</button>' in html
    assert '<section class="view" id="v-export">' in html
    assert html.index('data-v="tt"') < html.index('data-v="export"')
    assert "班級課表 PDF" in html
    assert "教師課表 PDF" in html
    assert "班級課表 Excel" in html
    assert "教師課表 Excel" in html
    assert "人力資源網" in html
    assert "校務系統" in html
    assert "不會寫入案件、雲端暫存或工作進度檔" in html
    assert "let EXPORT_TEACHER_IDS={}" in html
    assert "teacherIds:" not in html
    assert "ScheduleExports.makeWorksheet" in html
    assert "printTimetables(kind)" in html
    assert (FORMAL / "vendor" / "xlsx-js-style.LICENSE").is_file()


def test_export_javascript_has_valid_syntax():
    subprocess.run(
        ["node", "--check", str(MODULE)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
