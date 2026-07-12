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

  function data() {
    const value = adapter.getData();
    value.classes = value.classes || [];
    value.roster = value.roster || {};
    value.teacherAccounts = value.teacherAccounts || {};
    value.teacherNativeLangs = value.teacherNativeLangs || {};
    value.tcap = value.tcap || {};
    value.subjects = value.subjects || {};
    value.assign = value.assign || {};
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

  function teacherOptions(selected, includeBlank) {
    const names = Object.keys(data().roster);
    const blank = includeBlank ? '<option value="">尚未指定</option>' : "";
    return blank + names.map((name) =>
      `<option value="${esc(name)}" ${name === selected ? "selected" : ""}>${esc(name)}</option>`).join("");
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
        if (subject === "本土語文" && nativeLockEnabled) continue;
        const teacher = d.assign[item.code] && d.assign[item.code][subject];
        if (!teacher) {
          assignmentMissing += 1;
          hard.push(`${code} ${subject}尚未配課`);
        } else if (!teacherNames.has(teacher)) {
          hard.push(`${code} ${subject}的教師不在名冊：${teacher}`);
        }
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
        if (!groups.length) hard.push(`${grade}年級尚未建立本土語課鎖定分組`);
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
    target.innerHTML = `<div class="setup-stepbar">${steps.map(([label, value, done]) =>
      `<button type="button" class="setup-step ${done ? "done" : ""}" onclick="ScheduleSetup.show('${label === "班級" ? "classes" : label === "教師" ? "teachers" : label === "科目" ? "subjects" : "assign"}')"><span>${esc(label)}</span><b>${esc(value)}</b></button>`).join("")}</div>
      <div class="setup-health ${result.hard.length ? "bad" : "ok"}">
        <b>${result.hard.length ? `尚有 ${result.hard.length} 項必填資料` : "基礎資料完整，可以執行排課"}</b>
        <span>${result.hard[0] ? esc(result.hard[0]) : (result.warnings[0] ? esc(result.warnings[0]) : esc(lastMessage || "資料變更會自動保存。"))}</span>
        ${result.hard.length ? '<button class="btn soft sm" type="button" onclick="ScheduleSetup.showIssues()">查看問題</button>' : ""}
      </div>`;
  }

  function renderClasses() {
    const d = data();
    const target = document.getElementById("setupClassesTable");
    if (!target) return;
    target.innerHTML = `<thead><tr><th>年級</th><th>班序</th><th>班級代碼</th><th>導師</th><th>資源班學生</th><th></th></tr></thead><tbody>${d.classes.map((item, index) =>
      `<tr>
        <td><select class="edit" onchange="ScheduleSetup.setClass(${index},'g',this.value)">${[1, 2, 3, 4, 5, 6].map((grade) => `<option value="${grade}" ${+item.g === grade ? "selected" : ""}>${grade} 年級</option>`).join("")}</select></td>
        <td><input class="numin" type="number" min="1" max="20" value="${Number(item.i) || 1}" onchange="ScheduleSetup.setClass(${index},'i',this.value)"></td>
        <td><input value="${esc(item.code)}" maxlength="20" onchange="ScheduleSetup.renameClass(${index},this.value)"></td>
        <td><input class="setup-wide-select" list="setupTutorNames" value="${esc(item.tutor)}" placeholder="輸入導師姓名" maxlength="40" onchange="ScheduleSetup.setClass(${index},'tutor',this.value)"></td>
        <td><input type="checkbox" ${item.res ? "checked" : ""} onchange="ScheduleSetup.setClass(${index},'res',this.checked)"></td>
        <td><button class="icon-btn" type="button" title="刪除班級" aria-label="刪除班級" onclick="ScheduleSetup.removeClass(${index})">×</button></td>
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
    const profile = root.SchedulePolicy.profile;
    const config = root.SchedulePolicy.normalize(d);
    const count = root.SchedulePolicy.officialClassCount(d);
    const resolved = Object.fromEntries(["導師", "科任", "組長", "主任"].map((role) =>
      [role, root.SchedulePolicy.weeklyTarget(d, role)]));
    const result = root.SchedulePolicy.validate(d);
    target.innerHTML = `<div class="policy-heading"><div><h2>適用規則</h2><div class="sub">${esc(profile.label)}｜每節 ${profile.periodMinutes} 分鐘｜每日最多 ${profile.dailyHardCap} 節（系統硬規則）</div></div><span class="chip ok">${esc(profile.id)}</span></div>
      <div class="policy-grid">
        <label>校務核定班級數<small>留 0 依目前班級自動計算</small><input type="number" min="0" max="99" value="${Number(config.officialClassCount) || 0}" onchange="ScheduleSetup.setPolicy('officialClassCount',this.value)"></label>
        ${["導師", "科任", "組長", "主任"].map((role) => `<label>${role}每週基準節數<small>${role === "組長" || role === "主任" ? `目前 ${count} 班的建議值` : "新竹市固定基準"}</small><input type="number" min="0" max="30" value="${resolved[role]}" onchange="ScheduleSetup.setWeeklyTarget('${role}',this.value)"></label>`).join("")}
      </div>
      <div class="policy-actions"><button class="btn soft sm" type="button" onclick="ScheduleSetup.applySuggestedPolicy()">套用新竹市建議值</button><span>教師個別差異請在教師頁填寫「超鐘點」或「減課」。</span></div>
      <div class="policy-approvals">
        <label><input type="checkbox" ${config.staffingPrinciplesApproved ? "checked" : ""} onchange="ScheduleSetup.setPolicy('staffingPrinciplesApproved',this.checked)"> 授課節數編配原則已經校務會議審議通過</label>
        <input type="date" value="${esc(config.staffingMeetingDate)}" aria-label="授課節數編配原則會議日期" onchange="ScheduleSetup.setPolicy('staffingMeetingDate',this.value)">
        <label><input type="checkbox" ${config.schedulePlanApproved ? "checked" : ""} onchange="ScheduleSetup.setPolicy('schedulePlanApproved',this.checked)"> 學生作息與課表已納入課程計畫</label>
        <input type="date" value="${esc(config.schedulePlanMeetingDate)}" aria-label="課程計畫通過日期" onchange="ScheduleSetup.setPolicy('schedulePlanMeetingDate',this.value)">
      </div>
      <div class="policy-status ${result.blocking.length ? "bad" : "ok"}"><b>${result.blocking.length ? `${result.blocking.length} 項規則必須修正` : "新竹市節數規則檢核通過"}</b><span>${esc(result.blocking[0] || result.warnings[0] || "發布時會再次由後端驗證。")}</span></div>`;
  }

  function renderTeachers() {
    const d = data();
    const target = document.getElementById("setupTeachersTable");
    if (!target) return;
    const names = Object.keys(d.roster);
    target.innerHTML = `<thead><tr><th>教師姓名</th><th>身分</th><th>學校 Google 帳號<br><small>教支人員可選填</small></th><th>可授本土語別<br><small>可複選</small></th><th>角色基準</th><th>超鐘點</th><th>減課</th><th>減課原因</th><th></th></tr></thead><tbody>${names.map((name, index) => {
      const cap = d.tcap[name] || {extra: 0, minus: 0, reason: ""};
      const base = root.SchedulePolicy ? root.SchedulePolicy.weeklyTarget(d, d.roster[name] || "") : 0;
      return `<tr>
        <td><input value="${esc(name)}" maxlength="40" onchange="ScheduleSetup.renameTeacher(${index},this.value)"></td>
        <td><select class="edit setup-wide-select" onchange="ScheduleSetup.setTeacher(${index},'role',this.value)">${ROLES.map((role) => `<option ${d.roster[name] === role ? "selected" : ""}>${role}</option>`).join("")}</select></td>
        <td><input type="email" value="${esc(d.teacherAccounts[name] || "")}" placeholder="name@school.edu.tw" onchange="ScheduleSetup.setTeacher(${index},'email',this.value)"></td>
        <td><input value="${esc(nativeValues(d.teacherNativeLangs[name]).join("、"))}" placeholder="例：閩南語、客語" onchange="ScheduleSetup.setTeacher(${index},'nativeLangs',this.value)"></td>
        <td><b>${base || "依聘任"}</b></td>
        <td><input class="numin" type="number" min="0" max="20" value="${Number(cap.extra) || 0}" onchange="ScheduleSetup.setTeacher(${index},'extra',this.value)"></td>
        <td><input class="numin" type="number" min="0" max="40" value="${Number(cap.minus) || 0}" onchange="ScheduleSetup.setTeacher(${index},'minus',this.value)"></td>
        <td><select class="edit setup-wide-select" onchange="ScheduleSetup.setTeacher(${index},'reason',this.value)">${REDUCTION_REASONS.map((reason) => `<option value="${esc(reason)}" ${String(cap.reason || "") === reason ? "selected" : ""}>${esc(reason || "未指定")}</option>`).join("")}</select></td>
        <td><button class="icon-btn" type="button" title="刪除教師" aria-label="刪除教師" onclick="ScheduleSetup.removeTeacher(${index})">×</button></td>
      </tr>`;
    }).join("")}</tbody>`;
    const status = document.getElementById("setupTeacherSyncStatus");
    if (status) status.textContent = syncMessage || "學校 Google 帳號填妥後，可一次同步到教師登入名冊；教支人員若不需登入可留空。";
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
        <td><input value="${esc(name)}" maxlength="40" onchange="ScheduleSetup.renameSubject(${index},this.value)"></td>
        ${hours.map((value, gradeIndex) => `<td><input class="numin" type="number" min="0" max="12" value="${Number(value) || 0}" onchange="ScheduleSetup.setSubject(${index},'hours',this.value,${gradeIndex})"></td>`).join("")}
        <td><select class="edit setup-wide-select" onchange="ScheduleSetup.setSubject(${index},'self',this.value)"><option value="false" ${!subject.self ? "selected" : ""}>系統排課</option><option value="true" ${subject.self ? "selected" : ""}>導師可調整</option></select></td>
        <td><select class="edit setup-wide-select" onchange="ScheduleSetup.setSubject(${index},'room',this.value)">${rooms.map((room) => `<option value="${esc(room)}" ${subject.room === room ? "selected" : ""}>${room === "R00" ? "原班教室" : esc(room)}</option>`).join("")}</select></td>
        <td><select class="edit setup-wide-select" onchange="ScheduleSetup.setSubject(${index},'block',this.value)"><option value="" ${!subject.block ? "selected" : ""}>一般</option><option value="2連堂" ${subject.block === "2連堂" ? "selected" : ""}>兩節連堂</option><option value="2+1" ${subject.block === "2+1" ? "selected" : ""}>2+1 分兩天</option></select></td>
        <td><button class="icon-btn" type="button" title="刪除科目" aria-label="刪除科目" onclick="ScheduleSetup.removeSubject(${index})">×</button></td>
      </tr>`;
    }).join("")}</tbody>`;
  }

  function renderAssignments() {
    const d = data();
    const target = document.getElementById("setupAssignmentsTable");
    if (!target) return;
    const subjects = Object.keys(d.subjects).filter((subject) =>
      (d.subjects[subject].hours || []).some((value) => Number(value) > 0));
    target.innerHTML = `<thead><tr><th>班級</th>${subjects.map((subject) => `<th>${esc(subject)}</th>`).join("")}</tr></thead><tbody>${d.classes.map((item) =>
      `<tr><td class="cls">${esc(item.code)}</td>${subjects.map((subject) => {
        const hours = Number((d.subjects[subject].hours || [])[item.g - 1]) || 0;
        if (!hours) return '<td class="na">–</td>';
        if (subject === "本土語文" && d.nativeLockEnabled === true) return '<td class="na">由本土語課鎖定管理</td>';
        const selected = (d.assign[item.code] || {})[subject] || "";
        return `<td><select class="${selected ? "" : "empty"}" data-code="${esc(item.code)}" data-subject="${esc(subject)}" onchange="ScheduleSetup.setAssignment(this.dataset.code,this.dataset.subject,this.value)">${teacherOptions(selected, true)}</select><small class="setup-hours">${hours} 節</small></td>`;
      }).join("")}</tr>`).join("")}</tbody>`;
  }

  function render() {
    if (!adapter || typeof document === "undefined") return;
    renderSummary();
    renderPolicy();
    renderClasses();
    renderTeachers();
    renderSubjects();
    renderAssignments();
    show(activeTab);
  }

  function setPolicy(key, value) {
    const d = data();
    const config = root.SchedulePolicy.normalize(d);
    if (key === "officialClassCount") config[key] = Math.max(0, Number(value) || 0);
    else if (key === "staffingPrinciplesApproved" || key === "schedulePlanApproved") config[key] = !!value;
    else config[key] = String(value || "");
    commit("新竹市案件規則已更新。");
  }

  function setWeeklyTarget(role, value) {
    const d = data();
    const config = root.SchedulePolicy.normalize(d);
    config.weeklyTargets[role] = Math.max(0, Number(value) || 0);
    commit(`${role}每週基準節數已更新。`);
  }

  function applySuggestedPolicy() {
    const d = data();
    root.SchedulePolicy.setSuggestedWeeklyTargets(d);
    commit("已依目前校務核定班級數套用新竹市建議節數。");
  }

  function show(name) {
    activeTab = name;
    document.querySelectorAll("[data-setup-tab]").forEach((button) =>
      button.classList.toggle("on", button.dataset.setupTab === name));
    document.querySelectorAll(".setup-pane").forEach((pane) =>
      pane.classList.toggle("on", pane.id === `setup-${name}`));
  }

  function addClass() {
    const d = data();
    const grade = 1;
    const index = Math.max(0, ...d.classes.filter((item) => +item.g === grade).map((item) => Number(item.i) || 0)) + 1;
    const code = uniqueName(`${grade}${CLASS_SEQUENCE[index - 1] || index}`, d.classes.map((item) => item.code));
    d.classes.push({g: grade, i: index, code, tutor: "", res: false});
    d.assign[code] = {};
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
    d.override[next] = d.override[old] || {};
    delete d.assign[old]; delete d.override[old];
    d.locks.forEach((lock) => { if (lock.c === old) lock.c = next; });
    d.resGroups.forEach((group) => { if (group.code === old) group.code = next; });
    d.nativeGroups.forEach((group) => { group.sources = nativeValues(group.sources).map((code) => code === old ? next : code); });
    adapter.getLimits().forEach((row) => { if (row[0] === old) row[0] = next; });
    commit(`班級 ${old} 已更名為 ${next}。`);
  }

  function removeClass(index) {
    const d = data();
    const item = d.classes[index];
    if (!item || !confirm(`確定刪除班級 ${item.code}？該班配課與資源班設定也會移除。`)) return;
    d.classes.splice(index, 1);
    delete d.assign[item.code]; delete d.override[item.code];
    d.locks = d.locks.filter((lock) => lock.c !== item.code);
    d.resGroups = d.resGroups.filter((group) => group.code !== item.code);
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
    const nextClasses = [];
    const nextAssign = {};
    counts.forEach((count, gradeIndex) => {
      const grade = gradeIndex + 1;
      for (let order = 1; order <= count; order += 1) {
        const code = `${grade}${CLASS_SEQUENCE[order - 1] || order}`;
        nextClasses.push(oldClasses[code] || {g: grade, i: order, code, tutor: "", res: false});
        nextAssign[code] = oldAssign[code] || {};
      }
    });
    const codes = new Set(nextClasses.map((item) => item.code));
    d.classes = nextClasses; d.assign = nextAssign;
    d.override = Object.fromEntries(Object.entries(d.override).filter(([code]) => codes.has(code)));
    d.locks = d.locks.filter((lock) => codes.has(lock.c));
    d.resGroups = d.resGroups.filter((group) => codes.has(group.code));
    d.nativeGroups.forEach((group) => { group.sources = nativeValues(group.sources).filter((code) => codes.has(code)); });
    commit(`已依班級數建立 ${nextClasses.length} 個班級。`);
  }

  function addTeacher() {
    const d = data();
    const name = uniqueName("新教師", Object.keys(d.roster));
    d.roster[name] = "科任";
    d.teacherAccounts[name] = "";
    d.teacherNativeLangs[name] = [];
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
    delete d.roster[name]; delete d.tcap[name]; delete d.teacherAccounts[name]; delete d.teacherNativeLangs[name];
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
    try {
      syncMessage = "正在同步教師登入名冊…"; renderTeachers();
      const result = await adapter.syncTeachers(records);
      syncMessage = `已同步 ${result.imported} 位教師，可使用學校 Google 帳號登入。${skipped ? `另有 ${skipped} 位未填帳號的教支人員未建立登入權限。` : ""}`;
    } catch (error) {
      syncMessage = `同步失敗：${error.message}`;
    }
    renderTeachers();
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
    Object.values(d.override).forEach((row) => { if (Object.prototype.hasOwnProperty.call(row, old)) { row[next] = row[old]; delete row[old]; } });
    d.locks.forEach((lock) => { if (lock.s === old) lock.s = next; });
    d.resGroups.forEach((group) => { if (group.subj === old) group.subj = next; });
    commit(`科目 ${old} 已更名為 ${next}。`);
  }

  function removeSubject(index) {
    const d = data();
    const name = Object.keys(d.subjects)[index];
    if (!name || !confirm(`確定刪除科目 ${name}？相關配課、固定課及資源班設定也會移除。`)) return;
    delete d.subjects[name];
    delete d.exportMappings[name];
    Object.values(d.assign).forEach((row) => delete row[name]);
    Object.values(d.override).forEach((row) => delete row[name]);
    d.locks = d.locks.filter((lock) => lock.s !== name);
    d.resGroups = d.resGroups.filter((group) => group.subj !== name);
    commit(`已刪除科目 ${name}。`);
  }

  function setAssignment(code, subject, teacher) {
    const d = data();
    d.assign[code] = d.assign[code] || {};
    d.assign[code][subject] = teacher;
    commit(`${code} ${subject}已配給${teacher || "未指定教師"}。`);
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
    alert(["必須修正：", ...result.hard.map((item) => `• ${item}`),
      ...(result.warnings.length ? ["", "登入名冊提醒：", ...result.warnings.map((item) => `• ${item}`)] : [])].join("\n"));
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
    setPolicy, setWeeklyTarget, applySuggestedPolicy,
    addClass, setClass, renameClass, removeClass, applyGradeCounts,
    addTeacher, setTeacher, renameTeacher, removeTeacher, syncTeachers,
    addSubject, setSubject, renameSubject, removeSubject,
    setAssignment, autofillTutors,
  };
}(typeof globalThis !== "undefined" ? globalThis : window));
