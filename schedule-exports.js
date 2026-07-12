(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ScheduleExports = api;
}(typeof globalThis !== "undefined" ? globalThis : window, function () {
  "use strict";

  const DAYS = ["一", "二", "三", "四", "五"];
  const PERIODS = [1, 2, 3, 4, 5, 6, 7];
  const NUMBER_TEXT = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"];
  const UPLOAD_HEADERS = [
    "星期幾", "第幾節", "年級", "班級", "教師姓名", "教師身分證號",
    "類別", "領域", "科目", "語言別", "校訂課程名稱", "上課頻率",
  ];

  function text(value) {
    return String(value == null ? "" : value).trim();
  }

  function listValues(value) {
    const source = Array.isArray(value) ? value : text(value).split(/[、,，;；\s]+/);
    return [...new Set(source.map(text).filter(Boolean))];
  }

  function defaultMapping(name) {
    const value = text(name);
    const result = {category: "領域學習", domain: value, subject: value, language: "", schoolName: "", frequency: "每週上課"};
    if (/國語/.test(value)) Object.assign(result, {domain: "語文", subject: "國語文"});
    else if (/英語/.test(value)) Object.assign(result, {domain: "語文", subject: "英語文"});
    else if (/本土|閩南|臺灣台語|客語|原住民/.test(value)) Object.assign(result, {domain: "語文", subject: "本土語文"});
    else if (/數學/.test(value)) Object.assign(result, {domain: "數學", subject: "數學"});
    else if (/生活課程/.test(value)) Object.assign(result, {domain: "生活課程", subject: "生活課程"});
    else if (/自然/.test(value)) Object.assign(result, {domain: "自然科學", subject: "自然科學"});
    else if (/社會/.test(value)) Object.assign(result, {domain: "社會", subject: "社會"});
    else if (/音樂|視覺藝術|表演藝術|藝術/.test(value)) Object.assign(result, {domain: "藝術", subject: value});
    else if (/健康|體育/.test(value)) Object.assign(result, {domain: "健康與體育", subject: value});
    else if (/綜合/.test(value)) Object.assign(result, {domain: "綜合活動", subject: "綜合活動"});
    else if (/科技|資訊/.test(value)) Object.assign(result, {domain: "科技", subject: value});
    if (/校訂|彈性/.test(value)) Object.assign(result, {category: "彈性學習", domain: "彈性課程", subject: value, schoolName: value});
    return result;
  }

  function ensureMappings(data) {
    data.exportMappings = data.exportMappings && typeof data.exportMappings === "object" ? data.exportMappings : {};
    for (const name of Object.keys(data.subjects || {})) {
      data.exportMappings[name] = Object.assign(defaultMapping(name), data.exportMappings[name] || {});
    }
    return data.exportMappings;
  }

  function nativeLanguage(value, fallback) {
    let language = text(value).replace(/[（(]\s*直播(?:共學)?\s*[）)]/g, "").replace(/直播共學/g, "").trim();
    if (!language || language === "本土語文" || language === "本土語") language = text(fallback);
    return language;
  }

  function classMap(data) {
    return new Map((data.classes || []).map((item) => [text(item.code), item]));
  }

  function nativeSlot(data, group) {
    const band = (data.nativeBands || []).find((item) => Number(item.g) === Number(group.g));
    return {d: text((band || group).d), p: Number((band || group).p)};
  }

  function buildEntries(data, schedule, overlays) {
    const output = [];
    const nativeEnabled = data.nativeLockEnabled === true;
    for (const item of schedule || []) {
      if (nativeEnabled && text(item.s) === "本土語文") continue;
      output.push({
        code: text(item.code), d: text(item.d), p: Number(item.p), s: text(item.s),
        displaySubject: text(item.s), t: text(item.t), room: text(item.room), source: text(item.source) || "schedule",
      });
    }
    if (nativeEnabled) {
      for (const group of data.nativeGroups || []) {
        const slot = nativeSlot(data, group);
        const language = nativeLanguage(group.lang, "");
        for (const code of listValues(group.sources)) {
          if (text(group.t)) output.push({
            code, d: slot.d, p: slot.p, s: "本土語文", displaySubject: language || "本土語文",
            language, t: text(group.t), room: text(group.room) || "R00", group: text(group.grp), source: "native",
          });
          if (text(group.assistant)) output.push({
            code, d: slot.d, p: slot.p, s: "本土語文", displaySubject: language || "本土語文",
            language, t: text(group.assistant), room: text(group.room) || "R00", group: text(group.grp),
            source: "native", assistant: true,
          });
        }
      }
    }
    for (const item of overlays || []) output.push({
      code: text(item.code), d: text(item.d), p: Number(item.p), s: text(item.subj || item.s),
      displaySubject: text(item.subj || item.s), t: text(item.t), room: text(item.room) || "R00",
      group: text(item.grp), source: "overlay",
    });
    return output.filter((item) => item.code && DAYS.includes(item.d) && PERIODS.includes(item.p) && item.s)
      .sort((a, b) => DAYS.indexOf(a.d) - DAYS.indexOf(b.d) || a.p - b.p || a.code.localeCompare(b.code, "zh-Hant") || a.t.localeCompare(b.t, "zh-Hant"));
  }

  function classLabel(item) {
    if (!item) return "未知班級";
    const grade = Number(item.g) || "";
    return `${NUMBER_TEXT[grade] || grade}年${text(item.code).replace(/^\d+/, "") || Number(item.i) || ""}班`;
  }

  function timetableRows(title, subtitle, items, cellText) {
    const cells = new Map();
    for (const item of items) {
      const key = `${item.d}|${item.p}`;
      if (!cells.has(key)) cells.set(key, []);
      const value = cellText(item);
      if (value && !cells.get(key).includes(value)) cells.get(key).push(value);
    }
    const rows = [[title], [subtitle], ["節次", ...DAYS.map((day) => `星期${day}`)]];
    for (const period of PERIODS) rows.push([
      `第${NUMBER_TEXT[period]}節`,
      ...DAYS.map((day) => (cells.get(`${day}|${period}`) || []).join("\n")),
    ]);
    return rows;
  }

  function uniqueSheetName(value, used) {
    const base = (text(value).replace(/[\\/?*\[\]:]/g, "_") || "課表").slice(0, 31);
    let result = base;
    let index = 2;
    while (used.has(result)) {
      const suffix = `_${index++}`;
      result = base.slice(0, 31 - suffix.length) + suffix;
    }
    used.add(result);
    return result;
  }

  function classSheets(data, entries) {
    const used = new Set();
    return (data.classes || []).map((item) => {
      const title = [text(data._school), `${classLabel(item)} 班級課表`].filter(Boolean).join("　");
      const subtitle = `導師：${text(item.tutor) || "未填"}　｜　班級代碼：${text(item.code)}`;
      const rows = timetableRows(title, subtitle, entries.filter((entry) => entry.code === text(item.code)), (entry) => {
        const role = entry.assistant ? "（協同）" : "";
        const group = entry.group ? `｜${entry.group}` : "";
        return `${entry.displaySubject || entry.s}${group}\n${entry.t}${role}`.trim();
      });
      return {name: uniqueSheetName(text(item.code), used), rows};
    });
  }

  function teacherSheets(data, entries) {
    const classes = classMap(data);
    const used = new Set();
    const teachers = [...new Set(entries.map((item) => item.t).filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-Hant"));
    return teachers.map((teacher) => {
      const teacherEntries = entries.filter((entry) => entry.t === teacher);
      const title = [text(data._school), `${teacher} 教師課表`].filter(Boolean).join("　");
      const subtitle = `職別：${text((data.roster || {})[teacher]) || "教師"}　｜　每週授課：${teacherEntries.length} 節`;
      const rows = timetableRows(title, subtitle, teacherEntries, (entry) => {
        const group = entry.group ? `｜${entry.group}` : "";
        const role = entry.assistant ? "（協同）" : "";
        return `${entry.displaySubject || entry.s}${group}${role}\n${classLabel(classes.get(entry.code))}`;
      });
      return {name: uniqueSheetName(teacher, used), rows};
    });
  }

  function gradeText(grade) {
    return `${NUMBER_TEXT[Number(grade)] || grade}年級`;
  }

  function periodText(period) {
    return `第${NUMBER_TEXT[Number(period)] || period}節`;
  }

  function classNumber(item) {
    return `第${String(Number(item && item.i) || 0).padStart(2, "0")}班`;
  }

  function uploadDataRows(data, entries, teacherIds) {
    const mappings = ensureMappings(data);
    const classes = classMap(data);
    return entries.filter((item) => item.t && !item.assistant).map((item) => {
      const classroom = classes.get(item.code);
      const mapping = Object.assign(defaultMapping(item.s), mappings[item.s] || {});
      return [
        `週${item.d}`, periodText(item.p), gradeText(classroom && classroom.g), classNumber(classroom),
        item.t, text((teacherIds || {})[item.t]), mapping.category, mapping.domain, mapping.subject,
        item.source === "native" ? nativeLanguage(item.language, mapping.language) : mapping.language,
        mapping.schoolName, mapping.frequency || "每週上課",
      ];
    }).sort((a, b) => DAYS.indexOf(a[0].replace("週", "")) - DAYS.indexOf(b[0].replace("週", ""))
      || NUMBER_TEXT.indexOf(a[1].replace(/[第節]/g, "")) - NUMBER_TEXT.indexOf(b[1].replace(/[第節]/g, ""))
      || a[2].localeCompare(b[2], "zh-Hant") || a[3].localeCompare(b[3], "zh-Hant") || a[4].localeCompare(b[4], "zh-Hant"));
  }

  function uploadRows(data, entries, teacherIds) {
    return [UPLOAD_HEADERS.slice(), ...uploadDataRows(data, entries, teacherIds)];
  }

  function validateUpload(data, entries, teacherIds) {
    const issues = [];
    const mappings = ensureMappings(data);
    const classes = classMap(data);
    const uploadEntries = entries.filter((item) => item.t && !item.assistant);
    if (!uploadEntries.length) issues.push("尚無可匯出的正式課表資料");
    for (const item of uploadEntries) {
      const classroom = classes.get(item.code);
      const mapping = mappings[item.s] || defaultMapping(item.s);
      if (!classroom || !Number(classroom.g) || !Number(classroom.i)) issues.push(`${item.code}缺少年級或班序`);
      if (!text((teacherIds || {})[item.t])) issues.push(`${item.t}缺少教師身分證號`);
      if (!text(mapping.category)) issues.push(`${item.s}缺少類別對應`);
      if (!text(mapping.domain)) issues.push(`${item.s}缺少領域對應`);
      if (!text(mapping.subject)) issues.push(`${item.s}缺少科目對應`);
      if (item.source === "native" && !nativeLanguage(item.language, mapping.language)) issues.push(`${item.group || item.s}缺少語言別`);
      if (mapping.category === "彈性學習" && !text(mapping.schoolName)) issues.push(`${item.s}缺少校訂課程名稱`);
    }
    return [...new Set(issues)];
  }

  function parseTeacherIdRows(rows) {
    const source = (rows || []).filter((row) => Array.isArray(row) && row.some((value) => text(value)));
    if (!source.length) return {};
    const normalize = (value) => text(value).replace(/[\s　()（）]/g, "");
    const headers = source[0].map(normalize);
    let nameIndex = headers.findIndex((value) => ["姓名", "教師姓名", "老師姓名"].includes(value));
    let idIndex = headers.findIndex((value) => ["身分證", "身分證字號", "教師身分證號", "統一證號"].includes(value));
    let start = 1;
    if (nameIndex < 0 || idIndex < 0) {
      nameIndex = 0;
      idIndex = 1;
      start = 0;
    }
    const result = {};
    for (const row of source.slice(start)) {
      const name = text(row[nameIndex]);
      const id = text(row[idIndex]).toUpperCase();
      if (name && id) result[name] = id;
    }
    return result;
  }

  function html(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function subjectClass(value) {
    const name = text(value).split("\n")[0];
    if (/國語|英語|本土|閩南|客語|原住民|閱讀/.test(name)) return "language";
    if (/數學/.test(name)) return "math";
    if (/自然|生活課程|科技|資訊/.test(name)) return "science";
    if (/社會|綜合/.test(name)) return "social";
    if (/音樂|藝術|表演|視覺/.test(name)) return "arts";
    if (/健康|體育/.test(name)) return "health";
    return "general";
  }

  function subjectFill(value) {
    return ({
      language: "EDF4FB", math: "FFF3D7", science: "EAF5E9", social: "F3EDF8",
      arts: "FBECEF", health: "E7F4F2", general: "FAFAF8",
    })[subjectClass(value)];
  }

  function thinBorder(color) {
    const line = {style: "thin", color: {rgb: color || "C8D3CF"}};
    return {top: line, bottom: line, left: line, right: line};
  }

  function styleTimetableWorksheet(xlsx, worksheet, rows) {
    worksheet["!merges"] = [{s: {r: 0, c: 0}, e: {r: 0, c: 5}}, {s: {r: 1, c: 0}, e: {r: 1, c: 5}}];
    worksheet["!cols"] = [{wch: 12}, ...DAYS.map(() => ({wch: 23}))];
    worksheet["!rows"] = [{hpt: 34}, {hpt: 22}, {hpt: 25}, ...PERIODS.map(() => ({hpt: 50}))];
    const border = thinBorder();
    const range = xlsx.utils.decode_range(worksheet["!ref"]);
    for (let row = range.s.r; row <= range.e.r; row += 1) {
      for (let column = range.s.c; column <= range.e.c; column += 1) {
        const address = xlsx.utils.encode_cell({r: row, c: column});
        const cell = worksheet[address] || (worksheet[address] = {t: "s", v: ""});
        if (row === 0) cell.s = {
          font: {name: "Microsoft JhengHei", sz: 18, bold: true, color: {rgb: "FFFFFF"}},
          fill: {patternType: "solid", fgColor: {rgb: "294D45"}},
          alignment: {horizontal: "center", vertical: "center"},
        };
        else if (row === 1) cell.s = {
          font: {name: "Microsoft JhengHei", sz: 10, color: {rgb: "53635F"}},
          fill: {patternType: "solid", fgColor: {rgb: "EDF2F0"}},
          alignment: {horizontal: "right", vertical: "center"},
          border: {bottom: {style: "medium", color: {rgb: "2F7765"}}},
        };
        else if (row === 2) cell.s = {
          font: {name: "Microsoft JhengHei", sz: 11, bold: true, color: {rgb: "FFFFFF"}},
          fill: {patternType: "solid", fgColor: {rgb: "3D665C"}},
          alignment: {horizontal: "center", vertical: "center"}, border,
        };
        else if (column === 0) cell.s = {
          font: {name: "Microsoft JhengHei", sz: 10, bold: true, color: {rgb: "35564E"}},
          fill: {patternType: "solid", fgColor: {rgb: "EDF2F0"}},
          alignment: {horizontal: "center", vertical: "center", wrapText: true}, border,
        };
        else cell.s = {
          font: {name: "Microsoft JhengHei", sz: 11, color: {rgb: "24332F"}},
          fill: {patternType: "solid", fgColor: {rgb: subjectFill(cell.v)}},
          alignment: {horizontal: "center", vertical: "center", wrapText: true}, border,
        };
        if (row === 7 && cell.s && cell.s.border) {
          cell.s.border.top = {style: "medium", color: {rgb: "7D948D"}};
        }
      }
    }
    worksheet["!margins"] = {left: .3, right: .3, top: .35, bottom: .35, header: .15, footer: .15};
    worksheet["!pageSetup"] = {
      orientation: "landscape", paperSize: 9, fitToWidth: 1, fitToHeight: 1,
      horizontalCentered: true, verticalCentered: false,
    };
    worksheet["!sheetPr"] = {pageSetUpPr: {fitToPage: true}};
    worksheet["!printArea"] = `A1:F${rows.length}`;
  }

  function styleUploadWorksheet(xlsx, worksheet, rows) {
    worksheet["!cols"] = UPLOAD_HEADERS.map((header, index) =>
      ({wch: index === 5 ? 16 : Math.max(12, header.length * 2 + 2)}));
    worksheet["!autofilter"] = {ref: `A1:L${Math.max(1, rows.length)}`};
    for (let column = 0; column < UPLOAD_HEADERS.length; column += 1) {
      const cell = worksheet[xlsx.utils.encode_cell({r: 0, c: column})];
      if (!cell) continue;
      cell.s = {
        font: {name: "Microsoft JhengHei", sz: 10, bold: true, color: {rgb: "FFFFFF"}},
        fill: {patternType: "solid", fgColor: {rgb: "3D665C"}},
        alignment: {horizontal: "center", vertical: "center", wrapText: true},
        border: thinBorder("AEBDB8"),
      };
    }
    worksheet["!rows"] = [{hpt: 28}];
  }

  function makeWorksheet(xlsx, rows, kind) {
    const worksheet = xlsx.utils.aoa_to_sheet(rows);
    if (kind === "timetable") styleTimetableWorksheet(xlsx, worksheet, rows);
    else styleUploadWorksheet(xlsx, worksheet, rows);
    return worksheet;
  }

  function printCell(value) {
    const lines = String(value == null ? "" : value).split("\n").filter(Boolean);
    if (!lines.length) return "";
    return `<strong>${html(lines[0])}</strong>${lines.slice(1).map((line) => `<span>${html(line)}</span>`).join("")}`;
  }

  function printDocument(sheets, documentTitle) {
    const pages = (sheets || []).map((sheet, index) => {
      const rows = sheet.rows || [];
      const headers = rows[2] || [];
      const body = rows.slice(3).map((row, rowIndex) =>
        `<tr class="${rowIndex === 4 ? "afternoon" : ""}"><th>${html(row[0])}</th>${DAYS.map((_, column) => {
          const value = row[column + 1] || "";
          return `<td class="${subjectClass(value)}">${printCell(value)}</td>`;
        }).join("")}</tr>`).join("");
      return `<section class="page">
        <header><p>學校正式課表</p><h1>${html((rows[0] || [sheet.name])[0])}</h1><div>${html((rows[1] || [""])[0])}</div></header>
        <table><thead><tr>${headers.map((value) => `<th>${html(value)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>
        <footer><span>智慧排課系統</span><span>${index + 1} / ${sheets.length}</span></footer>
      </section>`;
    }).join("");
    return `<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><title>${html(documentTitle || "正式課表")}</title><style>
      @page{size:A4 landscape;margin:9mm}*{box-sizing:border-box}html,body{margin:0;background:#eef1ef;color:#24332f;font-family:"Microsoft JhengHei","Noto Sans TC",sans-serif}
      .page{width:279mm;min-height:192mm;margin:8mm auto;padding:8mm 9mm 6mm;background:#fff;display:flex;flex-direction:column;break-after:page;page-break-after:always;box-shadow:0 2mm 7mm rgba(24,48,41,.12)}
      .page:last-child{break-after:auto;page-break-after:auto}header{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:8mm;padding:0 0 4mm;border-bottom:1.2mm solid #2f7765}header p{grid-column:1;grid-row:1;margin:0 0 1mm;color:#2f7765;font-size:9pt;font-weight:700}
      h1{grid-column:1;grid-row:2;margin:0;font-size:20pt;line-height:1.25;letter-spacing:0}header div{grid-column:2;grid-row:1/3;align-self:end;max-width:95mm;color:#5d6b67;font-size:10pt;text-align:right}
      table{width:100%;height:140mm;margin-top:5mm;border-collapse:separate;border-spacing:0;table-layout:fixed;border:0.35mm solid #aebdb8}
      th,td{border-right:0.25mm solid #c8d3cf;border-bottom:0.25mm solid #c8d3cf;text-align:center;vertical-align:middle;padding:2mm 1.5mm;overflow-wrap:anywhere}
      tr>*:last-child{border-right:0}tbody tr:last-child>*{border-bottom:0}thead th{height:10mm;background:#294d45;color:#fff;font-size:11pt;font-weight:700}
      thead th:first-child,tbody th{width:19mm}tbody th{background:#edf2f0;color:#35564e;font-size:10pt}tbody td{font-size:10.5pt;line-height:1.35}
      tbody td strong{display:block;font-size:11.5pt}tbody td span{display:block;margin-top:.6mm;color:#53635f;font-size:8.5pt}
      tr.afternoon>*{border-top:0.65mm solid #7d948d}.language{background:#edf4fb}.math{background:#fff3d7}.science{background:#eaf5e9}.social{background:#f3edf8}.arts{background:#fbecef}.health{background:#e7f4f2}.general{background:#fafaf8}
      footer{display:flex;justify-content:space-between;margin-top:auto;padding-top:3mm;color:#77837f;font-size:8pt}
      @media print{html,body{background:#fff}.page{width:auto;min-height:0;height:190mm;margin:0;padding:0;box-shadow:none}header{padding-top:0}}
    </style></head><body>${pages}</body></html>`;
  }

  return {
    DAYS, PERIODS, UPLOAD_HEADERS,
    defaultMapping, ensureMappings, buildEntries, classSheets, teacherSheets,
    uploadRows, validateUpload, parseTeacherIdRows, classLabel, printDocument, makeWorksheet,
  };
}));
