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
    return `${Number(item.g) || ""}年${text(item.code).replace(/^\d+/, "") || Number(item.i) || ""}班`;
  }

  function timetableRows(title, items, cellText) {
    const cells = new Map();
    for (const item of items) {
      const key = `${item.d}|${item.p}`;
      if (!cells.has(key)) cells.set(key, []);
      const value = cellText(item);
      if (value && !cells.get(key).includes(value)) cells.get(key).push(value);
    }
    const rows = [[title], ["節次", ...DAYS.map((day) => `星期${day}`)]];
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
      const rows = timetableRows(`${classLabel(item)} 班級課表`, entries.filter((entry) => entry.code === text(item.code)), (entry) => {
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
      const rows = timetableRows(`${teacher} 教師課表`, entries.filter((entry) => entry.t === teacher), (entry) => {
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

  return {
    DAYS, PERIODS, UPLOAD_HEADERS,
    defaultMapping, ensureMappings, buildEntries, classSheets, teacherSheets,
    uploadRows, validateUpload, parseTeacherIdRows, classLabel,
  };
}));
