(function (root) {
  "use strict";

  let adapter = null;
  let activeFilter = "all";
  const expandedGroups = new Set();

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function issueTarget(text) {
    const value = String(text || "");
    if (/本土語|語言分組|共同時段/.test(value)) return {group: "conditions", view: "native", label: "檢查語言分組"};
    if (/資源班|抽離組/.test(value)) return {group: "conditions", view: "res", label: "檢查資源班"};
    if (/不排|禁排|可排時段|週.+第.+節/.test(value)) return {group: "conditions", view: "lim", label: "檢查時段"};
    if (/縣市|學年度|基準節數|每日硬上限|核定班級/.test(value)) return {group: "conditions", view: "build", label: "檢查學校規則"};
    if (/Google 帳號|教師名冊|可授|授課教師/.test(value)) return {group: "foundation", view: "build", tab: "teachers", label: "檢查教師"};
    if (/尚未配課|配課|的教師不在名冊/.test(value)) return {group: "foundation", view: "build", tab: "assign", label: "檢查配課"};
    if (/科目|節數全部/.test(value)) return {group: "foundation", view: "build", tab: "subjects", label: "檢查科目"};
    if (/班級|導師/.test(value)) return {group: "foundation", view: "build", tab: "classes", label: "檢查班級"};
    return {group: "foundation", view: "build", label: "回到資料建置"};
  }

  function makeItem(level, text, target) {
    return {level, text: String(text || ""), ...(target || {})};
  }

  function collect() {
    if (!adapter) return {groups: [], checklist: [], counts: {blocker: 0, warning: 0, pass: 0}};
    const data = adapter.getData();
    const setup = adapter.getSetupValidation();
    const cloud = adapter.getCloudState();
    const scheduleReady = adapter.isScheduleReady();
    const schedule = scheduleReady ? adapter.getScheduleValidation() : {hard: [], pending: []};
    const groups = [
      {id: "foundation", title: "基礎資料", description: "班級、教師、科目與配課", items: []},
      {id: "conditions", title: "排課條件", description: "學校規則、時段、語言與資源班", items: []},
      {id: "schedule", title: "課表完整度", description: "硬規則、缺課與正式完成狀態", items: []},
      {id: "collaboration", title: "雲端與教師協作", description: "共用暫存、發布版本與帳號", items: []},
      {id: "exports", title: "匯出準備", description: "課表與系統上傳欄位", items: []},
    ];
    const groupMap = Object.fromEntries(groups.map((group) => [group.id, group]));

    for (const text of setup.hard || []) {
      const target = issueTarget(text);
      groupMap[target.group].items.push(makeItem("blocker", text, target));
    }
    const setupWarnings = setup.warnings || [];
    const missingGoogleAccounts = setupWarnings.filter((text) => /尚未填 Google 帳號/.test(text));
    const missingLanguageCounts = setupWarnings.filter((text) => /語.+尚未填寫學生人數/.test(text));
    const summarizedWarnings = setupWarnings.filter((text) => !missingGoogleAccounts.includes(text) && !missingLanguageCounts.includes(text));
    if (missingGoogleAccounts.length) {
      groupMap.foundation.items.push(makeItem(
        "warning",
        `${missingGoogleAccounts.length} 位教師尚未填 Google 帳號；不影響排課，但會影響教師登入與課表瀏覽。`,
        {view: "build", tab: "teachers", label: "補齊教師帳號"},
      ));
    }
    if (missingLanguageCounts.length) {
      groupMap.conditions.items.push(makeItem(
        "warning",
        `${missingLanguageCounts.length} 個語言分組尚未填寫學生人數；請確認分組名單後補齊。`,
        {view: "native", label: "檢查語言分組"},
      ));
    }
    for (const text of summarizedWarnings) {
      const target = issueTarget(text);
      groupMap[target.group].items.push(makeItem("warning", text, target));
    }

    if (!scheduleReady) {
      groupMap.schedule.items.push(makeItem("blocker", "尚未執行正式排課", {view: "run", label: "前往執行排課"}));
    } else {
      for (const item of schedule.hard || []) {
        groupMap.schedule.items.push(makeItem("blocker", item.text || item, {view: "edit", label: "開啟課表編修"}));
      }
      for (const text of schedule.pending || []) {
        groupMap.schedule.items.push(makeItem("blocker", text, {view: "tutor", label: "處理待排課程"}));
      }
    }

    if (adapter.mode === "formal" && cloud.isAdmin) {
      groupMap.collaboration.items.push(cloud.hasCloudDraft
        ? makeItem("pass", "目前案件已建立學校共用雲端暫存")
        : makeItem("warning", "目前案件尚未建立雲端暫存", {view: "build", label: "回到資料建置"}));
      groupMap.collaboration.items.push(cloud.activeRevision
        ? makeItem("pass", "已建立正式發布版本，教師可依權限查看")
        : makeItem("warning", "尚未發布正式教師課表", {view: "tutor", label: "檢查導師協作"}));
      if (cloud.draftConflict) {
        groupMap.collaboration.items.push(makeItem("blocker", "雲端已有較新案件，請先重新載入再編修", {view: "build", label: "處理雲端衝突"}));
      }
    }

    if (!scheduleReady) {
      groupMap.exports.items.push(makeItem("warning", "完成正式課表後才可檢查匯出資料", {view: "run", label: "先執行排課"}));
    } else {
      const exportIssues = adapter.getExportIssues();
      for (const text of exportIssues) {
        groupMap.exports.items.push(makeItem("warning", text, {view: "export", label: "檢查匯出設定"}));
      }
    }

    for (const group of groups) {
      if (!group.items.length) group.items.push(makeItem("pass", `${group.title}目前沒有發現問題`));
    }

    const foundationalHard = (setup.hard || []).filter((text) => issueTarget(text).group === "foundation");
    const conditionHard = (setup.hard || []).filter((text) => issueTarget(text).group === "conditions");
    const counts = setup.counts || {};
    const projectStarted = Number(counts.classes || 0) > 0 || Number(counts.teachers || 0) > 0 || Number(counts.subjects || 0) > 0;
    const checklist = [
      {label: "建立或載入案件", done: projectStarted, view: "build"},
      {label: "完成班級與教師", done: Number(counts.classes || 0) > 0 && Number(counts.teachers || 0) > 0 && !foundationalHard.some((text) => /班級|導師|教師名冊/.test(text)), view: "build", tab: "classes"},
      {label: "完成科目節數", done: Number(counts.subjects || 0) > 0 && !foundationalHard.some((text) => /科目|節數/.test(text)), view: "build", tab: "subjects"},
      {label: "完成配課", done: Number(counts.assignmentTotal || 0) > 0 && Number(counts.assignmentMissing || 0) === 0, view: "build", tab: "assign"},
      {label: "確認排課條件", done: projectStarted && conditionHard.length === 0, view: "readiness"},
      {label: "完成正式排課", done: scheduleReady && !(schedule.hard || []).length && !(schedule.pending || []).length, view: "run"},
      {label: "儲存學校雲端", done: adapter.mode !== "formal" || !cloud.isAdmin || cloud.hasCloudDraft, view: "build"},
      {label: "發布教師課表", done: adapter.mode !== "formal" || !cloud.isAdmin || !!cloud.activeRevision, view: "tutor"},
    ];
    const resultCounts = {blocker: 0, warning: 0, pass: 0};
    groups.forEach((group) => group.items.forEach((item) => { resultCounts[item.level] += 1; }));
    return {groups, checklist, counts: resultCounts, data};
  }

  function actionButton(item) {
    if (!item.view) return "";
    const tab = item.tab ? `'${esc(item.tab)}'` : "null";
    return `<button class="btn soft sm" type="button" onclick="ScheduleReadiness.navigate('${esc(item.view)}',${tab})">${esc(item.label || "前往處理")}</button>`;
  }

  function renderChecklist(report) {
    const target = document.getElementById("onboardingChecklistBody");
    const progress = document.getElementById("onboardingChecklistProgress");
    const details = document.getElementById("onboardingChecklist");
    if (!target || !progress || !details) return;
    const done = report.checklist.filter((item) => item.done).length;
    progress.textContent = `${done}/${report.checklist.length}`;
    progress.className = `chip ${done === report.checklist.length ? "ok" : "warn"}`;
    details.classList.toggle("complete", done === report.checklist.length);
    if (done === report.checklist.length) details.open = false;
    target.innerHTML = report.checklist.map((item, index) => `<button type="button" class="onboarding-step ${item.done ? "done" : ""}" onclick="ScheduleReadiness.navigate('${esc(item.view)}',${item.tab ? `'${esc(item.tab)}'` : "null"})"><span>${item.done ? "完成" : index + 1}</span><b>${esc(item.label)}</b></button>`).join("");
  }

  function renderCenter(report) {
    const summary = document.getElementById("readinessSummary");
    const groups = document.getElementById("readinessGroups");
    if (!summary || !groups) return;
    const healthy = report.counts.blocker === 0;
    summary.innerHTML = `<div><span>阻擋問題</span><b>${report.counts.blocker}</b></div><div><span>建議確認</span><b>${report.counts.warning}</b></div><div><span>通過項目</span><b>${report.counts.pass}</b></div><div class="readiness-overall ${healthy ? "ok" : "bad"}"><span>目前狀態</span><b>${healthy ? "可進入下一階段" : "請先修正阻擋問題"}</b></div>`;
    groups.innerHTML = report.groups.map((group) => {
      const visible = group.items.filter((item) => activeFilter === "all" || item.level === activeFilter);
      if (!visible.length) return "";
      const expanded = expandedGroups.has(group.id);
      const shown = expanded ? visible : visible.slice(0, 6);
      const more = visible.length - shown.length;
      const toggle = visible.length > 6
        ? `<button class="readiness-more" type="button" onclick="ScheduleReadiness.toggleGroup('${esc(group.id)}')">${expanded ? "收合項目" : `展開其餘 ${more} 項`}</button>`
        : "";
      return `<section class="readiness-group"><header><div><h2>${esc(group.title)}</h2><p>${esc(group.description)}</p></div><span>${visible.length} 項</span></header><div class="readiness-list">${shown.map((item) => `<div class="readiness-item ${item.level}"><span class="readiness-state">${item.level === "blocker" ? "需修正" : item.level === "warning" ? "待確認" : "已通過"}</span><p>${esc(item.text)}</p>${actionButton(item)}</div>`).join("")}</div>${toggle}</section>`;
    }).join("") || '<div class="readiness-empty">目前篩選條件沒有項目。</div>';
    document.querySelectorAll("[data-readiness-filter]").forEach((button) => {
      button.classList.toggle("on", button.dataset.readinessFilter === activeFilter);
    });
  }

  function render() {
    const report = collect();
    renderChecklist(report);
    renderCenter(report);
    return report;
  }

  function setFilter(filter) {
    activeFilter = ["all", "blocker", "warning", "pass"].includes(filter) ? filter : "all";
    expandedGroups.clear();
    render();
  }

  function toggleGroup(groupId) {
    if (expandedGroups.has(groupId)) expandedGroups.delete(groupId);
    else expandedGroups.add(groupId);
    render();
  }

  function navigate(view, tab) {
    if (!adapter) return;
    adapter.navigate(view, tab || "");
  }

  function initialize(value) {
    adapter = value;
    render();
  }

  root.ScheduleReadiness = {initialize, collect, render, setFilter, toggleGroup, navigate};
}(typeof globalThis !== "undefined" ? globalThis : window));
