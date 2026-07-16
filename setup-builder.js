(function (root) {
  "use strict";

  const ROLES = ["導師", "科任", "組長", "主任", "導師兼組長", "導師兼主任",
    "資源班教師", "資源班導師", "專任輔導教師", "教支人員", "鐘點教師", "其他"];
  const REDUCTION_REASONS = ["", "兼任輔導教師", "英語種子教師", "導師兼行政職務",
    "特教教師節數規定", "協助行政工作", "其他核定"];
  const CLASS_SEQUENCE = "甲乙丙丁戊己庚辛壬癸";
  const DAYS = ["一", "二", "三", "四", "五"];
  let adapter = null;
  let activeTab = "classes";
  let lastMessage = "";
  let syncMessage = "";
  let syncingTeachers = false;
  let assignmentScrollCleanup = null;
  let updateAssignmentScrollDock = () => {};

  function data() {
    const value = adapter.getData();
    value.classes = value.classes || [];
    value.roster = value.roster || {};
    value.teacherAccounts = value.teacherAccounts || {};
    value.teacherNativeLangs = value.teacherNativeLangs || {};
    value.teacherSubjects = value.teacherSubjects || {};
    value.tcap = value.tcap || {};
    value.subjects = value.subjects || {};
    value.assign = value.assign || {};
    value.assignmentModes = value.assignmentModes || {};
    value.override = value.override || {};
    value.locks = value.locks || [];
    value.resGroups = value.resGroups || [];
    value.nativeBands = Array.isArray(value.nativeBands) ? value.nativeBands : [];
    value.nativeGroups = Array.isArray(value.nativeGroups) ? value.nativeGroups : [];
    value.exportMappings = value.exportMappings && typeof value.exportMappings === "object" ? value.exportMappings : {};
    value.rooms = value.rooms || {};
    if (!Object.prototype.hasOwnProperty.call(value.rooms, "R00")) value.rooms.R00 = 99;
    if (root.SchedulePolicy) root.SchedulePolicy.normalize(value);
    return value;
  }

  function nativeValues(value) {
    const source = Array.isArray(value) ? value : String(value || "").split(/[、,，;；\s]+/);
    return [...new Set(source.map((item) => String(item || "").trim()).filter(Boolean))];
  }

  function subjectValues(value) {
    const source = Array.isArray(value) ? value : String(value || "").split(/[、,，;；\n]+/);
    return [...new Set(source.map((item) => String(item || "").trim()).filter(Boolean))];
  }

  function resourceSources(group) {
    return nativeValues(Array.isArray(group && group.sources) ? group.sources : [group && group.code]);
  }

  function resourcePullSubjects(group) {
    const values = Array.isArray(group && group.pullSubjects) && group.pullSubjects.length
      ? group.pullSubjects : [group && group.subj];
    return subjectValues(values);
  }

  function isMinnanLanguage(value) {
    const language = String(value || "").replace(/[\s（）()]/g, "");
    return !language || ["本土語", "本土語文", "閩南語", "臺語", "台語", "臺灣台語", "台灣台語", "本土語文閩南語"].includes(language);
  }

  function minnanGroupSources(d) {
    return new Set((d.nativeGroups || []).filter((group) => isMinnanLanguage(group.lang))
      .flatMap((group) => nativeValues(group.sources)));
  }

  function subjectLabel(subject) {
    return subject === "本土語文" ? "閩南語（原班）" : subject;
  }

  function isTutorArrangeable(d, item, subject) {
    const assigned = (d.assign[item.code] || {})[subject] || "";
    if (!item.tutor || assigned !== item.tutor) return false;
    if (subject === "本土語文" && d.nativeLockEnabled === true) return false;
    if ((d.resGroups || []).some((group) =>
      resourceSources(group).includes(item.code) && resourcePullSubjects(group).includes(subject))) return false;
    const configured = (d.assignmentModes[item.code] || {})[subject];
    return configured ? configured === "tutor" : !!(d.subjects[subject] || {}).self;
  }

  function teachingSummary(d, name) {
    const result = {retained: 0, released: 0, cross: 0, total: 0};
    const groupedMinnan = minnanGroupSources(d);
    for (const item of d.classes) {
      for (const [subject, info] of Object.entries(d.subjects)) {
        const hours = Math.max(0, Number((info.hours || [])[item.g - 1]) || 0);
        if (!hours) continue;
        if (subject === "本土語文" && d.nativeLockEnabled === true && groupedMinnan.has(item.code)) continue;
        const assigned = (d.assign[item.code] || {})[subject] || "";
        if (item.tutor === name) {
          if (assigned === name) result.retained += hours;
          else if (assigned) result.released += hours;
        } else if (assigned === name) result.cross += hours;
      }
    }
    for (const group of (d.nativeGroups || [])) {
      if (group.t === name || group.assistant === name) result.cross += 1;
    }
    for (const group of (d.resGroups || [])) {
      if (group.t === name) result.cross += Math.max(0, Number(group.n) || 0);
    }
    result.total = result.retained + result.cross;
    return result;
  }

  function nativeSkillMatches(language, skills) {
    const normalize = (value) => String(value || "").replace(/[\s（）()直播共學語文]/g, "");
    const target = normalize(language);
    return !!target && nativeValues(skills).some((skill) => {
      const value = normalize(skill);
      return value && (target.includes(value) || value.includes(target));
    });
  }

  function esc(value) {
    return adapter.escape(String(value == null ? "" : value));
  }

  function commit(message) {
    lastMessage = message || "資料已更新。";
    adapter.commit(lastMessage);
  }

  function uniqueName(base, values) {
    if (!values.includes(base)) return base;
    let number = 2;
    while (values.includes(`${base}${number}`)) number += 1;
    return `${base}${number}`;
  }

  function teacherOptions(selected, includeBlank, subject) {
    const d = data();
    const names = Object.keys(d.roster);
    const blank = includeBlank ? '<option value="">尚未指定</option>' : "";
    const option = (name) => `<option value="${esc(name)}" ${name === selected ? "selected" : ""}>${esc(name)}</option>`;
    if (!subject) return blank + names.map(option).join("");
    const qualified = names.filter((name) => subjectValues(d.teacherSubjects[name]).includes(subject));
    const other = names.filter((name) => !qualified.includes(name));
    return blank
      + (qualified.length ? `<optgroup label="可授 ${esc(subject)}">${qualified.map(option).join("")}</optgroup>` : "")
      + (other.length ? `<optgroup label="其他教師">${other.map(option).join("")}</optgroup>` : "");
  }

  function validate() {
    const d = data();
    const hard = [];
    const warnings = [];
    const classCodes = new Set();
    const teacherNames = new Set(Object.keys(d.roster));
    const subjectNames = Object.keys(d.subjects);
    const nativeSubject = d.subjects["本土語文"];
    const nativeGroups = Array.isArray(d.nativeGroups) ? d.nativeGroups : [];
    const nativeBands = Array.isArray(d.nativeBands) ? d.nativeBands : [];
    const nativeLockEnabled = d.nativeLockEnabled === true;
    let assignmentTotal = 0;
    let assignmentMissing = 0;

    if (!d.classes.length) hard.push("尚未建立班級");
    if (!teacherNames.size) hard.push("尚未建立教師");
    if (!subjectNames.length) hard.push("尚未建立科目");
    else if (!subjectNames.some((subject) =>
      (d.subjects[subject].hours || []).some((value) => Number(value) > 0))) {
      hard.push("科目節數全部為 0");
    }

    for (const item of d.classes) {
      const code = String(item.code || "").trim();
      if (!code) hard.push("有班級尚未填寫代碼");
      else if (classCodes.has(code)) hard.push(`班級代碼重複：${code}`);
      classCodes.add(code);
      if (!Number.isInteger(+item.g) || +item.g < 1 || +item.g > 6) hard.push(`${code || "未命名班級"}的年級不正確`);
      if (!item.tutor) hard.push(`${code || "未命名班級"}尚未指定導師`);
      else if (!teacherNames.has(item.tutor)) hard.push(`${code}的導師不在教師名冊：${item.tutor}`);

      const slots = ((d.gslot || {})[item.g] || []).flat().filter(Boolean).length;
      const required = subjectNames.reduce((sum, subject) =>
        sum + Math.max(0, Number((d.subjects[subject].hours || [])[item.g - 1]) || 0), 0);
      if (required > slots) hard.push(`${code}需要 ${required} 節，但該年級只有 ${slots} 個可排時段`);

      for (const subject of subjectNames) {
        const hours = Math.max(0, Number((d.subjects[subject].hours || [])[item.g - 1]) || 0);
        if (!hours) continue;
        assignmentTotal += 1;
        const teacher = d.assign[item.code] && d.assign[item.code][subject];
        if (!teacher) {
          assignmentMissing += 1;
          hard.push(`${code} ${subject}尚未配課`);
        } else if (!teacherNames.has(teacher)) {
          hard.push(`${code} ${subject}的教師不在名冊：${teacher}`);
        } else {
          const skills = subjectValues(d.teacherSubjects[teacher]);
          if (skills.length && !skills.includes(subject)) warnings.push(`${teacher}尚未將「${subject}」列入可授科目`);
        }
      }
    }

    for (const group of (d.resGroups || [])) {
      const name = String(group.grp || "資源班抽離組").trim();
      const sources = resourceSources(group);
      const sourceGrades = new Set();
      if (!sources.length) hard.push(`${name}尚未指定來源班級`);
      for (const code of sources) {
        const classroom = d.classes.find((item) => item.code === code);
        if (!classroom) hard.push(`${name}引用不存在的來源班級：${code}`);
        else {
          sourceGrades.add(Number(classroom.g) || 0);
          if (!classroom.res) warnings.push(`${code}已有資源班抽離設定，但班級尚未勾選資源班學生`);
        }
      }
      if (sourceGrades.size > 1) hard.push(`${name}的來源班級必須屬於同一年級`);
      if (!d.subjects[group.subj]) hard.push(`${name}引用不存在的科目：${group.subj || "未填"}`);
      const pullSubjects = resourcePullSubjects(group);
      if (!pullSubjects.length) hard.push(`${name}尚未指定原班可抽離科目`);
      for (const subject of pullSubjects) {
        if (!d.subjects[subject]) hard.push(`${name}引用不存在的原班可抽離科目：${subject}`);
      }
      if (!group.t) hard.push(`${name}尚未指定資源班教師`);
      else if (!teacherNames.has(group.t)) hard.push(`${name}的資源班教師不在名冊：${group.t}`);
      if (!Number.isInteger(+group.n) || +group.n < 1) hard.push(`${name}每週節數必須大於 0`);
    }

    for (const row of (adapter.getLimits() || [])) {
      const target = String(row[0] || "").trim();
      const day = String(row[1] || "").trim();
      const period = String(row[2] || "").trim();
      const knownGrade = /^[1-6]年級$/.test(target);
      if (target && !teacherNames.has(target) && !classCodes.has(target) && !knownGrade) {
        warnings.push(`不排課時間引用不存在的教師、班級或年級：${target}`);
      }
      if (day && ![...DAYS, "每日"].includes(day)) hard.push(`${target || "不排課時間"}的星期設定不正確：${day}`);
      if (period && !["1", "2", "3", "4", "5", "6", "7", "全部"].includes(period)) {
        hard.push(`${target || "不排課時間"}的節次設定不正確：${period}`);
      }
    }

    if (nativeSubject && nativeLockEnabled) {
      const nativeStaffSlots = new Set();
      const nativeRoomLoad = new Map();
      const groupNames = new Set();
      for (let grade = 1; grade <= 6; grade += 1) {
        const hours = Math.max(0, Number((nativeSubject.hours || [])[grade - 1]) || 0);
        const gradeClasses = d.classes.filter((item) => +item.g === grade);
        if (!hours || !gradeClasses.length) continue;
        if (hours !== 1) hard.push(`${grade}年級本土語文每週節數必須為 1`);
        const bands = nativeBands.filter((item) => +item.g === grade);
        if (bands.length !== 1) hard.push(`${grade}年級必須且只能設定一個本土語共同時段`);
        const band = bands[0] || {};
        const day = String(band.d || "");
        const period = Number(band.p);
        if (!DAYS.includes(day) || !Number.isInteger(period) || period < 1 || period > 7) {
          hard.push(`${grade}年級本土語共同時段不正確`);
        } else if (!((d.gslot || {})[grade] || [])[DAYS.indexOf(day)]?.[period - 1]) {
          hard.push(`${grade}年級本土語共同時段不在該年級可排時段內`);
        }
        const groups = nativeGroups.filter((item) => +item.g === grade);
        const groupSlots = new Set();
        for (const group of groups) {
          const groupDay = String(group.d || day);
          const groupPeriod = Number(group.p || period);
          groupSlots.add(`${groupDay}|${groupPeriod}`);
          const groupName = String(group.grp || group.group || "").trim();
          if (!groupName) hard.push(`${grade}年級有本土語分組尚未填寫名稱`);
          else if (groupNames.has(groupName)) hard.push(`本土語分組名稱重複：${groupName}`);
          else groupNames.add(groupName);
          if (!String(group.lang || "").trim()) hard.push(`${grade}年級本土語分組尚未填寫語別`);
          const sourceCodes = nativeValues(group.sources);
          if (!sourceCodes.length) hard.push(`${groupName || `${grade}年級分組`}尚未填寫來源班級`);
          for (const code of sourceCodes) {
            const sourceClass = d.classes.find((item) => item.code === code);
            if (!sourceClass) hard.push(`${groupName || `${grade}年級分組`}引用不存在的來源班級：${code}`);
            else if (+sourceClass.g !== grade) hard.push(`${groupName || `${grade}年級分組`}的來源班級 ${code} 不屬於${grade}年級`);
          }
          if (!(Number(group.students) > 0)) warnings.push(`${groupName || `${grade}年級分組`}尚未填寫學生人數`);
          const mainTeacher = String(group.t || "").trim();
          if (!mainTeacher) hard.push(`${grade}年級本土語分組尚未填寫授課教師`);
          else if (!teacherNames.has(mainTeacher)) hard.push(`${groupName || `${grade}年級分組`}的授課教師不在教師名冊：${mainTeacher}`);
          else if (!nativeSkillMatches(group.lang, d.teacherNativeLangs[mainTeacher])) warnings.push(`${mainTeacher}尚未標示可授「${group.lang}」`);
          const assistant = String(group.assistant || "").trim();
          if (assistant && !teacherNames.has(assistant)) hard.push(`${groupName || `${grade}年級分組`}的協同教師不在教師名冊：${assistant}`);
          for (const teacher of [group.t, group.assistant].map((name) => String(name || "").trim()).filter(Boolean)) {
            const key = `${teacher}|${groupDay}|${groupPeriod}`;
            if (nativeStaffSlots.has(key)) hard.push(`${teacher}在週${groupDay}第${groupPeriod}節被重複指派本土語分組`);
            nativeStaffSlots.add(key);
          }
          if (!Object.prototype.hasOwnProperty.call(d.rooms || {}, group.room || "R00")) {
            hard.push(`${grade}年級本土語分組引用不存在的場地：${group.room}`);
          } else if (group.room && group.room !== "R00") {
            const roomKey = `${group.room}|${groupDay}|${groupPeriod}`;
            const used = (nativeRoomLoad.get(roomKey) || 0) + 1;
            nativeRoomLoad.set(roomKey, used);
            if (used > Number(d.rooms[group.room] || 0)) {
              hard.push(`${group.room}在週${groupDay}第${groupPeriod}節超過本土語分組可用容量`);
            }
          }
          if (!DAYS.includes(groupDay) || !Number.isInteger(groupPeriod) || groupPeriod < 1 || groupPeriod > 7) {
            hard.push(`${grade}年級本土語分組的固定時段不正確`);
          } else if (groupDay !== day || groupPeriod !== period) {
            hard.push(`${groupName || `${grade}年級分組`}未使用年級共同時段`);
          }
        }
        if (groupSlots.size > 1) hard.push(`${grade}年級本土語分組必須使用相同星期與節次`);
        const slots = new Set();
        for (const item of gradeClasses) {
          const locks = (d.locks || []).filter((lock) =>
            lock.c === item.code && lock.s === "本土語文");
          if (locks.length !== 1) {
            hard.push(`${item.code} 本土語文必須設定且只能有一個固定節次`);
            continue;
          }
          const lock = locks[0];
          slots.add(`${lock.d}|${+lock.p}`);
          if (!((d.gslot || {})[grade] || [])[DAYS.indexOf(lock.d)]?.[+lock.p - 1]) {
            hard.push(`${item.code} 本土語固定節次不在該年級可排時段內`);
          }
        }
        if (slots.size > 1) hard.push(`${grade}年級本土語分組必須使用相同星期與節次`);
        if (slots.size === 1 && !slots.has(`${day}|${period}`)) hard.push(`${grade}年級班級鎖課與共同時段不一致`);
      }
    } else if (nativeLockEnabled) {
      hard.push("已設定本土語分組，但科目節數缺少「本土語文」");
    }

    for (const name of teacherNames) {
      const email = String(d.teacherAccounts[name] || "").trim();
      if (!email && d.roster[name] !== "教支人員") warnings.push(`${name}尚未填 Google 帳號`);
      else if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) warnings.push(`${name}的 Google 帳號格式不正確`);
    }

    if (root.SchedulePolicy) {
      const policyResult = root.SchedulePolicy.validate(d);
      hard.push(...policyResult.blocking);
      warnings.push(...policyResult.warnings);
    }

    return {
      hard: [...new Set(hard)], warnings: [...new Set(warnings)],
      counts: {
        classes: d.classes.length,
        teachers: teacherNames.size,
        subjects: subjectNames.length,
        assignments: assignmentTotal - assignmentMissing,
        assignmentTotal,
        assignmentMissing,
      },
    };
  }

  function renderSummary() {
    const target = document.getElementById("setupSummary");
    if (!target) return;
    const result = validate();
    const c = result.counts;
    const steps = [
      ["班級", c.classes, c.classes > 0],
      ["教師", c.teachers, c.teachers > 0],
      ["科目", c.subjects, c.subjects > 0],
      ["配課", `${c.assignments}/${c.assignmentTotal}`, c.assignmentTotal > 0 && !c.assignmentMissing],
    ];
    const issues = [...result.hard.map((text) => ({text, kind: "bad"})),
      ...result.warnings.map((text) => ({text, kind: "warn"}))];
    target.innerHTML = `<div class="setup-stepbar">${steps.map(([label, value, done]) =>
      `<button type="button" class="setup-step ${done ? "done" : ""}" onclick="ScheduleSetup.show('${label === "班級" ? "classes" : label === "教師" ? "teachers" : label === "科目" ? "subjects" : "assign"}')"><span>${esc(label)}</span><b>${esc(value)}</b></button>`).join("")}</div>
      <div class="setup-health ${result.hard.length ? "bad" : "ok"}">
        <b>${result.hard.length ? `尚有 ${result.hard.length} 項必填資料` : "基礎資料完整，可以執行排課"}</b>
        <span>${result.hard[0] ? esc(result.hard[0]) : (result.warnings[0] ? esc(result.warnings[0]) : esc(lastMessage || "資料變更會自動保存。"))}</span>
        ${issues.length ? '<button class="btn soft sm" type="button" onclick="ScheduleSetup.showIssues()">查看全部</button>' : ""}
      </div>
      ${issues.length ? `<details class="setup-issue-details" id="setupIssueDetails"><summary>完整檢核清單（${issues.length} 項）</summary><ul class="setup-issue-list">${issues.map((issue) => `<li class="${issue.kind}">${esc(issue.text)}</li>`).join("")}</ul></details>` : ""}`;
  }

  function renderClasses() {
    const d = data();
    const target = document.getElementById("setupClassesTable");
    if (!target) return;
    target.innerHTML = `<thead><tr><th>年級</th><th>班序</th><th>班級代碼</th><th>導師</th><th>資源班學生</th><th></th></tr></thead><tbody>${d.classes.map((item, index) =>
      `<tr>
        <td><select class="edit" aria-label="${esc(item.code || `第 ${index + 1} 班`)}年級" onchange="ScheduleSetup.setClass(${index},'g',this.value)">${[1, 2, 3, 4, 5, 6].map((grade) => `<option value="${grade}" ${+item.g === grade ? "selected" : ""}>${grade} 年級</option>`).join("")}</select></td>
        <td><input class="numin" type="number" min="1" max="20" aria-label="${esc(item.code || `第 ${index + 1} 班`)}班序" value="${Number(item.i) || 1}" onchange="ScheduleSetup.setClass(${index},'i',this.value)"></td>
        <td><input value="${esc(item.code)}" maxlength="20" aria-label="第 ${index + 1} 筆班級代碼" onchange="ScheduleSetup.renameClass(${index},this.value)"></td>
        <td><input class="setup-wide-select" list="setupTutorNames" value="${esc(item.tutor)}" placeholder="輸入導師姓名" maxlength="40" aria-label="${esc(item.code || `第 ${index + 1} 班`)}導師" onchange="ScheduleSetup.setClass(${index},'tutor',this.value)"></td>
        <td><input type="checkbox" aria-label="${esc(item.code || `第 ${index + 1} 班`)}有資源班學生" ${item.res ? "checked" : ""} onchange="ScheduleSetup.setClass(${index},'res',this.checked)"></td>
        <td><button class="icon-btn" type="button" title="刪除班級" aria-label="刪除 ${esc(item.code || `第 ${index + 1} 班`)}" onclick="ScheduleSetup.removeClass(${index})">×</button></td>
      </tr>`).join("")}</tbody>`;
    const tutorNames = document.getElementById("setupTutorNames");
    if (tutorNames) tutorNames.innerHTML = Object.keys(d.roster).map((name) => `<option value="${esc(name)}"></option>`).join("");

    for (let grade = 1; grade <= 6; grade += 1) {
      const input = document.getElementById(`setupGradeCount${grade}`);
      if (input && document.activeElement !== input) input.value = d.classes.filter((item) => +item.g === grade).length;
    }
  }

  function renderPolicy() {
    const d = data();
    const target = document.getElementById("setupPolicyPanel");
    if (!target || !root.SchedulePolicy) return;
    const config = root.SchedulePolicy.normalize(d);
    const resolved = Object.fromEntries(["導師", "科任", "組長", "主任"].map((role) =>
      [role, root.SchedulePolicy.weeklyTarget(d, role)]));
    const result = root.SchedulePolicy.validate(d);
    const scope = config.region && config.academicYear ? `${config.region}｜${config.academicYear} 學年度` : "請填寫縣市／適用單位與學年度";
    const statusTitle = result.blocking.length ? `${result.blocking.length} 項規則必須修正` :
      (result.warnings.length ? `${result.warnings.length} 項資料待確認` : "學校自訂規則檢核通過");
    const policyIssues = [...result.blocking.map((text) => ({text, kind: "bad"})),
      ...result.warnings.map((text) => ({text, kind: "warn"}))];
    target.innerHTML = `<div class="policy-heading"><div><h2>學校自訂規則</h2><div class="sub">${esc(scope)}｜每節 ${config.periodMinutes} 分鐘｜教師每日最多 ${config.dailyHardCap} 節（系統硬規則）</div></div><span class="chip ok">各縣市適用</span></div>
      <div class="policy-grid policy-context-grid">
        <label>縣市／適用單位<small>自由填寫，例：新竹市、全國</small><input maxlength="30" value="${esc(config.region)}" placeholder="請填寫" onchange="ScheduleSetup.setPolicy('region',this.value)"></label>
        <label>適用學年度<small>請填民國學年度</small><input type="number" min="1" max="999" value="${config.academicYear || ""}" placeholder="例：115" onchange="ScheduleSetup.setPolicy('academicYear',this.value)"></label>
        <label>每節分鐘<small>依學校作息自行填寫</small><input type="number" min="1" max="120" value="${config.periodMinutes}" onchange="ScheduleSetup.setPolicy('periodMinutes',this.value)"></label>
        <label>教師每日硬上限<small>最高 6 節，不允許排滿 7 節</small><input type="number" min="1" max="6" value="${config.dailyHardCap}" onchange="ScheduleSetup.setPolicy('dailyHardCap',this.value)"></label>
      </div>
      <div class="policy-grid">
        <label>校務核定班級數<small>留 0 依目前班級自動計算</small><input type="number" min="0" max="99" value="${Number(config.officialClassCount) || 0}" onchange="ScheduleSetup.setPolicy('officialClassCount',this.value)"></label>
        ${["導師", "科任", "組長", "主任"].map((role) => `<label>${role}每週基準節數<small>依縣市規定或校內核定填寫</small><input type="number" min="0" max="30" value="${resolved[role]}" onchange="ScheduleSetup.setWeeklyTarget('${role}',this.value)"></label>`).join("")}
      </div>
      <div class="policy-actions"><span>以上節數由學校依所在地規定自行填寫；教師個別差異請在教師頁填寫「超鐘點」或「減課」。</span></div>
      <div class="policy-status ${result.blocking.length ? "bad" : "ok"}"><b>${statusTitle}</b><span>${esc(result.blocking[0] || result.warnings[0] || "發布時會再次由後端驗證。")}</span></div>
      ${policyIssues.length ? `<details class="policy-issue-details"><summary>展開全部 ${policyIssues.length} 項規則檢核</summary><ul class="setup-issue-list">${policyIssues.map((issue) => `<li class="${issue.kind}">${esc(issue.text)}</li>`).join("")}</ul></details>` : ""}`;
  }

  function renderTeachers() {
    const d = data();
    const target = document.getElementById("setupTeachersTable");
    if (!target) return;
    const names = Object.keys(d.roster);
    target.innerHTML = `<thead><tr><th>教師姓名</th><th>身分</th><th>學校 Google 帳號<br><small>教支人員可選填</small></th><th>可授一般科目<br><small>以頓號分隔</small></th><th>可授本土語別<br><small>可複選</small></th><th>授課概況<br><small>本班／跨班／釋出</small></th><th>角色基準</th><th>超鐘點</th><th>減課</th><th>減課原因</th><th></th></tr></thead><tbody>${names.map((name, index) => {
      const cap = d.tcap[name] || {extra: 0, minus: 0, reason: ""};
      const base = root.SchedulePolicy ? root.SchedulePolicy.weeklyTarget(d, d.roster[name] || "") : 0;
      const load = teachingSummary(d, name);
      const targetHours = root.SchedulePolicy ? root.SchedulePolicy.teacherTarget(d, name) : 0;
      return `<tr>
        <td><input value="${esc(name)}" maxlength="40" aria-label="第 ${index + 1} 位教師姓名" onchange="ScheduleSetup.renameTeacher(${index},this.value)"></td>
        <td><select class="edit setup-wide-select" aria-label="${esc(name)}身分" onchange="ScheduleSetup.setTeacher(${index},'role',this.value)">${ROLES.map((role) => `<option ${d.roster[name] === role ? "selected" : ""}>${role}</option>`).join("")}</select></td>
        <td><input type="email" value="${esc(d.teacherAccounts[name] || "")}" placeholder="name@school.edu.tw" aria-label="${esc(name)}學校 Google 帳號" onchange="ScheduleSetup.setTeacher(${index},'email',this.value)"></td>
        <td><input class="setup-subject-skills" value="${esc(subjectValues(d.teacherSubjects[name]).join("、"))}" placeholder="例：自然科學、音樂" aria-label="${esc(name)}可授一般科目" onchange="ScheduleSetup.setTeacher(${index},'subjects',this.value)"></td>
        <td><input value="${esc(nativeValues(d.teacherNativeLangs[name]).join("、"))}" placeholder="例：閩南語、客語" aria-label="${esc(name)}可授本土語別" onchange="ScheduleSetup.setTeacher(${index},'nativeLangs',this.value)"></td>
        <td><span class="teaching-load"><b>${load.total}${targetHours ? `／${targetHours}` : ""} 節</b><small>本班 ${load.retained}｜跨班 ${load.cross}｜釋出 ${load.released}</small></span></td>
        <td><b>${base || "依聘任"}</b></td>
        <td><input class="numin" type="number" min="0" max="20" value="${Number(cap.extra) || 0}" aria-label="${esc(name)}超鐘點節數" onchange="ScheduleSetup.setTeacher(${index},'extra',this.value)"></td>
        <td><input class="numin" type="number" min="0" max="40" value="${Number(cap.minus) || 0}" aria-label="${esc(name)}減課節數" onchange="ScheduleSetup.setTeacher(${index},'minus',this.value)"></td>
        <td><select class="edit setup-wide-select" aria-label="${esc(name)}減課原因" onchange="ScheduleSetup.setTeacher(${index},'reason',this.value)">${REDUCTION_REASONS.map((reason) => `<option value="${esc(reason)}" ${String(cap.reason || "") === reason ? "selected" : ""}>${esc(reason || "未指定")}</option>`).join("")}</select></td>
        <td><button class="icon-btn" type="button" title="刪除教師" aria-label="刪除 ${esc(name)}" onclick="ScheduleSetup.removeTeacher(${index})">×</button></td>
      </tr>`;
    }).join("")}</tbody>`;
    const status = document.getElementById("setupTeacherSyncStatus");
    if (status) status.textContent = syncMessage || "學校 Google 帳號填妥後，可一次同步到教師登入名冊；教支人員若不需登入可留空。";
    const syncButton = document.getElementById("setupTeacherSyncButton");
    if (syncButton) {
      syncButton.disabled = syncingTeachers;
      syncButton.textContent = syncingTeachers ? "正在同步…" : "同步教師登入名冊";
    }
  }

  function renderSubjects() {
    const d = data();
    const target = document.getElementById("setupSubjectsTable");
    if (!target) return;
    const names = Object.keys(d.subjects);
    const rooms = Object.keys(d.rooms || {R00: 99});
    target.innerHTML = `<thead><tr><th>科目</th>${[1, 2, 3, 4, 5, 6].map((grade) => `<th>${grade}年</th>`).join("")}<th>排課方式</th><th>場地</th><th>連堂</th><th></th></tr></thead><tbody>${names.map((name, index) => {
      const subject = d.subjects[name];
      const hours = subject.hours || [0, 0, 0, 0, 0, 0];
      return `<tr>
        <td><input value="${esc(name)}" maxlength="40" aria-label="第 ${index + 1} 筆科目名稱" onchange="ScheduleSetup.renameSubject(${index},this.value)"></td>
        ${hours.map((value, gradeIndex) => `<td><input class="numin" type="number" min="0" max="12" value="${Number(value) || 0}" aria-label="${esc(name)} ${gradeIndex + 1} 年級每週節數" onchange="ScheduleSetup.setSubject(${index},'hours',this.value,${gradeIndex})"></td>`).join("")}
        <td><select class="edit setup-wide-select" aria-label="${esc(name)}排課方式" onchange="ScheduleSetup.setSubject(${index},'self',this.value)"><option value="false" ${!subject.self ? "selected" : ""}>系統排課</option><option value="true" ${subject.self ? "selected" : ""}>導師可調整</option></select></td>
        <td><select class="edit setup-wide-select" aria-label="${esc(name)}上課場地" onchange="ScheduleSetup.setSubject(${index},'room',this.value)">${rooms.map((room) => `<option value="${esc(room)}" ${subject.room === room ? "selected" : ""}>${room === "R00" ? "原班教室" : esc(room)}</option>`).join("")}</select></td>
        <td><select class="edit setup-wide-select" aria-label="${esc(name)}連堂設定" onchange="ScheduleSetup.setSubject(${index},'block',this.value)"><option value="" ${!subject.block ? "selected" : ""}>一般</option><option value="2連堂" ${subject.block === "2連堂" ? "selected" : ""}>兩節連堂</option><option value="2+1" ${subject.block === "2+1" ? "selected" : ""}>2+1 分兩天</option></select></td>
        <td><button class="icon-btn" type="button" title="刪除科目" aria-label="刪除 ${esc(name)}" onclick="ScheduleSetup.removeSubject(${index})">×</button></td>
      </tr>`;
    }).join("")}</tbody>`;
  }

  function renderAssignments() {
    const d = data();
    const target = document.getElementById("setupAssignmentsTable");
    if (!target) return;
    const subjects = Object.keys(d.subjects).filter((subject) =>
      (d.subjects[subject].hours || []).some((value) => Number(value) > 0));
    target.innerHTML = `<thead><tr><th>班級</th>${subjects.map((subject) => `<th>${esc(subjectLabel(subject))}</th>`).join("")}</tr></thead><tbody>${d.classes.map((item) =>
      `<tr><td class="cls">${esc(item.code)}</td>${subjects.map((subject) => {
        const hours = Number((d.subjects[subject].hours || [])[item.g - 1]) || 0;
        if (!hours) return '<td class="na">—</td>';
        const selected = (d.assign[item.code] || {})[subject] || "";
        const retained = selected && selected === item.tutor;
        const arrangeable = retained && isTutorArrangeable(d, item, subject);
        const state = !selected ? "待配課" : retained ? "本班保留" : "已釋出";
        return `<td class="assignment-cell"><select class="${selected ? "" : "empty"}" data-code="${esc(item.code)}" data-subject="${esc(subject)}" aria-label="${esc(item.code)} ${esc(subjectLabel(subject))}授課教師" onchange="ScheduleSetup.setAssignment(this.dataset.code,this.dataset.subject,this.value)">${teacherOptions(selected, true, subject)}</select>
          <small class="assignment-state ${!selected ? "missing" : retained ? "retained" : "released"}">${hours} 節｜${state}</small>
          ${retained ? `<label class="assignment-mode"><input type="checkbox" data-code="${esc(item.code)}" data-subject="${esc(subject)}" aria-label="${esc(item.code)} ${esc(subjectLabel(subject))}開放導師自排" ${arrangeable ? "checked" : ""} onchange="ScheduleSetup.setAssignmentMode(this.dataset.code,this.dataset.subject,this.checked)"> 導師自排</label>` : ""}</td>`;
      }).join("")}</tr>`).join("")}</tbody>`;
  }

  function bindAssignmentScroll() {
    if (assignmentScrollCleanup) assignmentScrollCleanup();
    const scroller = document.getElementById("setupAssignmentsScroll");
    const dock = document.getElementById("setupAssignmentsScrollDock");
    const track = document.getElementById("setupAssignmentsScrollTrack");
    if (!scroller || !dock || !track) return;

    let syncing = false;
    const sync = (source, target) => {
      if (syncing || source.scrollLeft === target.scrollLeft) return;
      syncing = true;
      target.scrollLeft = source.scrollLeft;
      syncing = false;
    };
    const fromTable = () => sync(scroller, dock);
    const fromDock = () => sync(dock, scroller);
    const update = () => {
      const rect = scroller.getBoundingClientRect();
      const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
      const viewportHeight = document.documentElement.clientHeight || window.innerHeight;
      const left = Math.max(0, rect.left);
      const right = Math.min(viewportWidth, rect.right);
      const isAssignmentTab = document.getElementById("setup-assign")?.classList.contains("on");
      const isVisible = rect.bottom > 0 && rect.top < viewportHeight;
      const hasOverflow = scroller.scrollWidth > scroller.clientWidth + 1;
      dock.hidden = !(isAssignmentTab && isVisible && hasOverflow && right > left);
      if (dock.hidden) return;
      dock.style.left = `${left}px`;
      dock.style.width = `${right - left}px`;
      track.style.width = `${scroller.scrollWidth}px`;
      dock.scrollLeft = scroller.scrollLeft;
    };

    updateAssignmentScrollDock = update;
    scroller.addEventListener("scroll", fromTable, {passive: true});
    dock.addEventListener("scroll", fromDock, {passive: true});
    window.addEventListener("scroll", update, {passive: true});
    window.addEventListener("resize", update, {passive: true});
    const resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(update) : null;
    resizeObserver?.observe(scroller);
    resizeObserver?.observe(document.getElementById("setupAssignmentsTable"));
    requestAnimationFrame(update);

    assignmentScrollCleanup = () => {
      scroller.removeEventListener("scroll", fromTable);
      dock.removeEventListener("scroll", fromDock);
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
      resizeObserver?.disconnect();
      updateAssignmentScrollDock = () => {};
    };
  }

  function render() {
    if (!adapter || typeof document === "undefined") return;
    renderSummary();
    renderPolicy();
    renderClasses();
    renderTeachers();
    renderSubjects();
    renderAssignments();
    bindAssignmentScroll();
    show(activeTab);
  }

  function setPolicy(key, value) {
    const d = data();
    const config = root.SchedulePolicy.normalize(d);
    if (key === "officialClassCount") config[key] = Math.max(0, Number(value) || 0);
    else if (key === "academicYear") config[key] = Math.min(999, Math.max(0, Math.round(Number(value) || 0)));
    else if (key === "periodMinutes") config[key] = Math.min(120, Math.max(1, Math.round(Number(value) || 40)));
    else if (key === "dailyHardCap") config[key] = Math.min(6, Math.max(1, Math.round(Number(value) || 6)));
    else if (key === "staffingPrinciplesApproved" || key === "schedulePlanApproved") config[key] = !!value;
    else config[key] = String(value || "");
    commit("學校自訂規則已更新。");
  }

  function setWeeklyTarget(role, value) {
    const d = data();
    const config = root.SchedulePolicy.normalize(d);
    config.weeklyTargets[role] = Math.max(0, Number(value) || 0);
    commit(`${role}每週基準節數已更新。`);
  }

  function show(name) {
    activeTab = name;
    document.querySelectorAll("[data-setup-tab]").forEach((button) =>
      button.classList.toggle("on", button.dataset.setupTab === name));
    document.querySelectorAll(".setup-pane").forEach((pane) =>
      pane.classList.toggle("on", pane.id === `setup-${name}`));
    requestAnimationFrame(updateAssignmentScrollDock);
  }

  function addClass() {
    const d = data();
    const grade = 1;
    const index = Math.max(0, ...d.classes.filter((item) => +item.g === grade).map((item) => Number(item.i) || 0)) + 1;
    const code = uniqueName(`${grade}${CLASS_SEQUENCE[index - 1] || index}`, d.classes.map((item) => item.code));
    d.classes.push({g: grade, i: index, code, tutor: "", res: false});
    d.assign[code] = {};
    d.assignmentModes[code] = {};
    commit(`已新增班級 ${code}。`);
  }

  function setClass(index, key, value) {
    const d = data();
    const item = d.classes[index];
    if (!item) return;
    if (key === "g" || key === "i") item[key] = Math.max(1, Number(value) || 1);
    else if (key === "res") item.res = !!value;
    else if (key === "tutor") {
      const previous = item.tutor;
      const tutor = String(value || "").trim();
      item.tutor = tutor;
      if (tutor && !Object.prototype.hasOwnProperty.call(d.roster, tutor)) {
        d.roster[tutor] = "導師";
        d.teacherAccounts[tutor] = "";
        d.teacherNativeLangs[tutor] = [];
        d.teacherSubjects[tutor] = [];
        d.tcap[tutor] = {extra: 0, minus: 0, reason: ""};
      }
      d.assign[item.code] = d.assign[item.code] || {};
      for (const [subject, info] of Object.entries(d.subjects)) {
        const current = d.assign[item.code][subject];
        if (info.self && (!current || current === previous)) d.assign[item.code][subject] = tutor;
      }
    }
    commit(`${item.code || "班級"}已更新。`);
  }

  function renameClass(index, rawValue) {
    const d = data();
    const item = d.classes[index];
    const next = String(rawValue || "").trim();
    if (!item || next === item.code) return;
    if (!next) return alert("班級代碼不可空白。");
    if (d.classes.some((row, rowIndex) => rowIndex !== index && row.code === next)) return alert(`班級代碼「${next}」已存在。`);
    const old = item.code;
    item.code = next;
    d.assign[next] = d.assign[old] || {};
    d.assignmentModes[next] = d.assignmentModes[old] || {};
    d.override[next] = d.override[old] || {};
    delete d.assign[old]; delete d.assignmentModes[old]; delete d.override[old];
    d.locks.forEach((lock) => { if (lock.c === old) lock.c = next; });
    d.resGroups.forEach((group) => {
      if (Array.isArray(group.sources)) group.sources = resourceSources(group).map((code) => code === old ? next : code);
      else if (group.code === old) group.code = next;
    });
    d.nativeGroups.forEach((group) => { group.sources = nativeValues(group.sources).map((code) => code === old ? next : code); });
    adapter.getLimits().forEach((row) => { if (row[0] === old) row[0] = next; });
    commit(`班級 ${old} 已更名為 ${next}。`);
  }

  function removeClass(index) {
    const d = data();
    const item = d.classes[index];
    if (!item || !confirm(`確定刪除班級 ${item.code}？該班配課與資源班設定也會移除。`)) return;
    d.classes.splice(index, 1);
    delete d.assign[item.code]; delete d.assignmentModes[item.code]; delete d.override[item.code];
    d.locks = d.locks.filter((lock) => lock.c !== item.code);
    d.resGroups = d.resGroups.filter((group) => {
      if (!Array.isArray(group.sources)) return group.code !== item.code;
      group.sources = resourceSources(group).filter((code) => code !== item.code);
      return group.sources.length > 0;
    });
    d.nativeGroups.forEach((group) => { group.sources = nativeValues(group.sources).filter((code) => code !== item.code); });
    const limits = adapter.getLimits();
    for (let row = limits.length - 1; row >= 0; row -= 1) if (limits[row][0] === item.code) limits.splice(row, 1);
    commit(`已刪除班級 ${item.code}。`);
  }

  function applyGradeCounts() {
    const d = data();
    const counts = [1, 2, 3, 4, 5, 6].map((grade) =>
      Math.max(0, Math.min(20, Number(document.getElementById(`setupGradeCount${grade}`).value) || 0)));
    if (!counts.some(Boolean)) return alert("請至少建立一個班級。");
    if (d.classes.length && !confirm("套用班級數會重建班級清單；代碼相同的導師與配課會保留。確定繼續？")) return;
    const oldClasses = Object.fromEntries(d.classes.map((item) => [item.code, item]));
    const oldAssign = d.assign;
    const oldModes = d.assignmentModes;
    const nextClasses = [];
    const nextAssign = {};
    const nextModes = {};
    counts.forEach((count, gradeIndex) => {
      const grade = gradeIndex + 1;
      for (let order = 1; order <= count; order += 1) {
        const code = `${grade}${CLASS_SEQUENCE[order - 1] || order}`;
        nextClasses.push(oldClasses[code] || {g: grade, i: order, code, tutor: "", res: false});
        nextAssign[code] = oldAssign[code] || {};
        nextModes[code] = oldModes[code] || {};
      }
    });
    const codes = new Set(nextClasses.map((item) => item.code));
    d.classes = nextClasses; d.assign = nextAssign; d.assignmentModes = nextModes;
    d.override = Object.fromEntries(Object.entries(d.override).filter(([code]) => codes.has(code)));
    d.locks = d.locks.filter((lock) => codes.has(lock.c));
    d.resGroups = d.resGroups.filter((group) => {
      if (!Array.isArray(group.sources)) return codes.has(group.code);
      group.sources = resourceSources(group).filter((code) => codes.has(code));
      return group.sources.length > 0;
    });
    d.nativeGroups.forEach((group) => { group.sources = nativeValues(group.sources).filter((code) => codes.has(code)); });
    commit(`已依班級數建立 ${nextClasses.length} 個班級。`);
  }

  function addTeacher() {
    const d = data();
    const name = uniqueName("新教師", Object.keys(d.roster));
    d.roster[name] = "科任";
    d.teacherAccounts[name] = "";
    d.teacherNativeLangs[name] = [];
    d.teacherSubjects[name] = [];
    d.tcap[name] = {extra: 0, minus: 0, reason: ""};
    commit(`已新增 ${name}。`);
  }

  function setTeacher(index, key, value) {
    const d = data();
    const name = Object.keys(d.roster)[index];
    if (!name) return;
    d.tcap[name] = d.tcap[name] || {extra: 0, minus: 0, reason: ""};
    if (key === "role") d.roster[name] = value;
    else if (key === "email") d.teacherAccounts[name] = String(value || "").trim().toLowerCase();
    else if (key === "subjects") d.teacherSubjects[name] = subjectValues(value);
    else if (key === "nativeLangs") d.teacherNativeLangs[name] = nativeValues(value);
    else if (key === "reason") d.tcap[name].reason = String(value || "");
    else d.tcap[name][key] = Math.max(0, Number(value) || 0);
    commit(`${name}的教師資料已更新。`);
  }

  function renameTeacher(index, rawValue) {
    const d = data();
    const old = Object.keys(d.roster)[index];
    const next = String(rawValue || "").trim();
    if (!old || next === old) return;
    if (!next) return alert("教師姓名不可空白。");
    if (Object.prototype.hasOwnProperty.call(d.roster, next)) return alert(`教師「${next}」已存在。`);
    d.roster[next] = d.roster[old]; delete d.roster[old];
    d.tcap[next] = d.tcap[old] || {extra: 0, minus: 0, reason: ""}; delete d.tcap[old];
    d.teacherAccounts[next] = d.teacherAccounts[old] || ""; delete d.teacherAccounts[old];
    d.teacherNativeLangs[next] = nativeValues(d.teacherNativeLangs[old]); delete d.teacherNativeLangs[old];
    d.teacherSubjects[next] = subjectValues(d.teacherSubjects[old]); delete d.teacherSubjects[old];
    d.classes.forEach((item) => { if (item.tutor === old) item.tutor = next; });
    Object.values(d.assign).forEach((row) => Object.keys(row).forEach((subject) => { if (row[subject] === old) row[subject] = next; }));
    d.resGroups.forEach((group) => { if (group.t === old) group.t = next; });
    d.locks.forEach((lock) => { if (lock.teacher === old) lock.teacher = next; });
    d.nativeGroups.forEach((group) => {
      if (group.t === old) group.t = next;
      if (group.assistant === old) group.assistant = next;
    });
    adapter.getLimits().forEach((row) => { if (row[0] === old) row[0] = next; });
    commit(`教師 ${old} 已更名為 ${next}。`);
  }

  function removeTeacher(index) {
    const d = data();
    const name = Object.keys(d.roster)[index];
    if (!name || !confirm(`確定刪除教師 ${name}？相關導師與配課欄位會改為未指定。`)) return;
    delete d.roster[name]; delete d.tcap[name]; delete d.teacherAccounts[name]; delete d.teacherNativeLangs[name]; delete d.teacherSubjects[name];
    d.classes.forEach((item) => { if (item.tutor === name) item.tutor = ""; });
    Object.values(d.assign).forEach((row) => Object.keys(row).forEach((subject) => { if (row[subject] === name) row[subject] = ""; }));
    d.resGroups.forEach((group) => { if (group.t === name) group.t = ""; });
    d.nativeGroups.forEach((group) => {
      if (group.t === name) group.t = "";
      if (group.assistant === name) group.assistant = "";
    });
    const limits = adapter.getLimits();
    for (let row = limits.length - 1; row >= 0; row -= 1) if (limits[row][0] === name) limits.splice(row, 1);
    commit(`已刪除教師 ${name}。`);
  }

  function portalRole(role) {
    if (role === "導師") return "導師";
    if (role.includes("資源班")) return "資源班教師";
    return "科任";
  }

  async function syncTeachers() {
    if (syncingTeachers) return;
    const d = data();
    const allRecords = Object.keys(d.roster).map((name) => {
      const classCodes = d.classes.filter((item) => item.tutor === name).map((item) => item.code);
      return {
        name,
        email: String(d.teacherAccounts[name] || "").trim().toLowerCase(),
        role: classCodes.length ? "導師" : portalRole(d.roster[name] || ""),
        class_codes: classCodes,
        sourceRole: d.roster[name] || "",
      };
    });
    const records = allRecords.filter((record) => record.email || record.sourceRole !== "教支人員")
      .map(({sourceRole, ...record}) => record);
    const skipped = allRecords.length - records.length;
    const invalid = records.find((record) => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(record.email));
    if (invalid) {
      syncMessage = `${invalid.name}尚未填寫有效的 Google 帳號。`;
      renderTeachers();
      return;
    }
    syncingTeachers = true;
    try {
      syncMessage = "正在同步教師登入名冊…"; renderTeachers();
      const result = await adapter.syncTeachers(records);
      syncMessage = `已同步 ${result.imported} 位教師，可使用學校 Google 帳號登入。${skipped ? `另有 ${skipped} 位未填帳號的教支人員未建立登入權限。` : ""}`;
    } catch (error) {
      syncMessage = `同步失敗：${error.message}`;
    } finally {
      syncingTeachers = false;
      renderTeachers();
    }
  }

  function addSubject() {
    const d = data();
    const name = uniqueName("新科目", Object.keys(d.subjects));
    d.subjects[name] = {hours: [0, 0, 0, 0, 0, 0], room: "R00", banned: [], block: "", self: false, pairMode: ""};
    if (root.ScheduleExports) d.exportMappings[name] = root.ScheduleExports.defaultMapping(name);
    commit(`已新增科目 ${name}。`);
  }

  function setSubject(index, key, value, gradeIndex) {
    const d = data();
    const name = Object.keys(d.subjects)[index];
    const subject = d.subjects[name];
    if (!subject) return;
    if (key === "hours") {
      subject.hours = subject.hours || [0, 0, 0, 0, 0, 0];
      subject.hours[gradeIndex] = Math.max(0, Number(value) || 0);
    } else if (key === "self") {
      subject.self = value === "true";
      if (subject.self) d.classes.forEach((item) => {
        d.assign[item.code] = d.assign[item.code] || {};
        if (!d.assign[item.code][name] && item.tutor) d.assign[item.code][name] = item.tutor;
      });
    } else subject[key] = value;
    commit(`${name}的科目資料已更新。`);
  }

  function renameSubject(index, rawValue) {
    const d = data();
    const old = Object.keys(d.subjects)[index];
    const next = String(rawValue || "").trim();
    if (!old || next === old) return;
    if (!next) return alert("科目名稱不可空白。");
    if (Object.prototype.hasOwnProperty.call(d.subjects, next)) return alert(`科目「${next}」已存在。`);
    d.subjects[next] = d.subjects[old]; delete d.subjects[old];
    if (d.exportMappings[old]) { d.exportMappings[next] = d.exportMappings[old]; delete d.exportMappings[old]; }
    Object.values(d.assign).forEach((row) => { if (Object.prototype.hasOwnProperty.call(row, old)) { row[next] = row[old]; delete row[old]; } });
    Object.values(d.assignmentModes).forEach((row) => { if (Object.prototype.hasOwnProperty.call(row, old)) { row[next] = row[old]; delete row[old]; } });
    Object.keys(d.teacherSubjects).forEach((teacher) => {
      d.teacherSubjects[teacher] = subjectValues(d.teacherSubjects[teacher]).map((subject) => subject === old ? next : subject);
    });
    Object.values(d.override).forEach((row) => { if (Object.prototype.hasOwnProperty.call(row, old)) { row[next] = row[old]; delete row[old]; } });
    d.locks.forEach((lock) => { if (lock.s === old) lock.s = next; });
    d.resGroups.forEach((group) => {
      if (group.subj === old) group.subj = next;
      if (Array.isArray(group.pullSubjects)) {
        group.pullSubjects = resourcePullSubjects(group).map((subject) => subject === old ? next : subject);
      }
    });
    commit(`科目 ${old} 已更名為 ${next}。`);
  }

  function removeSubject(index) {
    const d = data();
    const name = Object.keys(d.subjects)[index];
    if (!name || !confirm(`確定刪除科目 ${name}？相關配課、固定課及資源班設定也會移除。`)) return;
    delete d.subjects[name];
    delete d.exportMappings[name];
    Object.values(d.assign).forEach((row) => delete row[name]);
    Object.values(d.assignmentModes).forEach((row) => delete row[name]);
    Object.keys(d.teacherSubjects).forEach((teacher) => {
      d.teacherSubjects[teacher] = subjectValues(d.teacherSubjects[teacher]).filter((subject) => subject !== name);
    });
    Object.values(d.override).forEach((row) => delete row[name]);
    d.locks = d.locks.filter((lock) => lock.s !== name);
    d.resGroups = d.resGroups.filter((group) => {
      if (group.subj === name) return false;
      if (Array.isArray(group.pullSubjects)) {
        group.pullSubjects = resourcePullSubjects(group).filter((subject) => subject !== name);
        return group.pullSubjects.length > 0;
      }
      return group.subj !== name;
    });
    commit(`已刪除科目 ${name}。`);
  }

  function setAssignment(code, subject, teacher) {
    const d = data();
    d.assign[code] = d.assign[code] || {};
    d.assign[code][subject] = teacher;
    d.assignmentModes[code] = d.assignmentModes[code] || {};
    const classroom = d.classes.find((item) => item.code === code);
    if (!teacher || !classroom || teacher !== classroom.tutor) d.assignmentModes[code][subject] = "engine";
    else delete d.assignmentModes[code][subject];
    commit(`${code} ${subject}已配給${teacher || "未指定教師"}。`);
  }

  function setAssignmentMode(code, subject, tutorArrangeable) {
    const d = data();
    const classroom = d.classes.find((item) => item.code === code);
    const assigned = (d.assign[code] || {})[subject] || "";
    if (!classroom || !classroom.tutor || assigned !== classroom.tutor) {
      return alert("只有由本班導師授課的課程可以交由導師自排。");
    }
    d.assignmentModes[code] = d.assignmentModes[code] || {};
    d.assignmentModes[code][subject] = tutorArrangeable ? "tutor" : "engine";
    commit(`${code} ${subject}已改為${tutorArrangeable ? "導師自排" : "系統排課"}。`);
  }

  function autofillTutors() {
    const d = data();
    let changed = 0;
    for (const item of d.classes) {
      d.assign[item.code] = d.assign[item.code] || {};
      for (const [subject, info] of Object.entries(d.subjects)) {
        if (info.self && item.tutor && !d.assign[item.code][subject]) {
          d.assign[item.code][subject] = item.tutor;
          changed += 1;
        }
      }
    }
    commit(`已自動帶入 ${changed} 筆導師課。`);
  }

  function showIssues() {
    const result = validate();
    const details = document.getElementById("setupIssueDetails");
    if (!details) return alert(result.hard.length || result.warnings.length ? "請重新開啟資料建置頁查看檢核清單。" : "基礎資料檢核已通過。");
    details.open = true;
    details.scrollIntoView({behavior: "smooth", block: "center"});
  }

  function startBlank() {
    if (adapter.startBlank() === false) return;
    activeTab = "classes";
    lastMessage = "已建立空白排課案件。";
    render();
  }

  function init(value) {
    adapter = value;
    render();
  }

  root.ScheduleSetup = {
    init, render, validate, show, showIssues, startBlank,
    setPolicy, setWeeklyTarget,
    addClass, setClass, renameClass, removeClass, applyGradeCounts,
    addTeacher, setTeacher, renameTeacher, removeTeacher, syncTeachers,
    addSubject, setSubject, renameSubject, removeSubject,
    setAssignment, setAssignmentMode, autofillTutors,
  };
}(typeof globalThis !== "undefined" ? globalThis : window));
