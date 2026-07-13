(function (root) {
  "use strict";

  const state = {credential: "", profile: null, workspace: null, apiBaseUrl: "",
    activeRevision: "", updateSequence: 0, draftRevision: "", draftConflict: false,
    draftReady: false, hasLocalBackup: false, lastDraftHash: "", automationStarted: false,
    autoSaveTimer: null, saveInFlight: null, savePending: false, pendingManual: false,
    autoSaveInterval: null, sessionExpired: false, schools: [], usage: null};

  function apiBaseUrl() {
    const configured = String((root.SCHEDULE_AUTH_CONFIG || {}).apiBaseUrl || "").trim();
    if (configured) return configured.replace(/\/$/, "");
    if (["127.0.0.1", "localhost"].includes(location.hostname)) return "http://127.0.0.1:8766";
    return "";
  }

  function status(message, kind) {
    ["googleAuthStatus", "formalAuthStatus", "platformFooterStatus"].forEach((id) => {
      const element = document.getElementById(id);
      if (!element) return;
      element.textContent = message;
      element.dataset.kind = kind || "";
    });
  }

  function userStorageKey(name) {
    const school = (state.profile && state.profile.school_id) || "platform";
    return `${name}:${school}:${(state.profile && state.profile.email) || "anonymous"}`;
  }

  function authorizationHeaders() {
    return state.credential ? {Authorization: `Bearer ${state.credential}`} : {};
  }

  async function request(path, options) {
    if (!state.apiBaseUrl) throw new Error("正式教師入口尚未設定 API 網址");
    const headers = new Headers((options && options.headers) || {});
    if (state.credential) headers.set("Authorization", `Bearer ${state.credential}`);
    const response = await fetch(`${state.apiBaseUrl}${path}`, {...(options || {}), headers});
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : null;
    if (!response.ok) {
      const error = new Error((payload && (payload.detail || payload.error)) || `伺服器回應 ${response.status}`);
      error.status = response.status;
      if (response.status === 401 && state.profile) handleSessionExpired();
      throw error;
    }
    return payload;
  }

  function roleLabel(role) {
    return ({admin: "學校系統管理員", homeroom_teacher: "導師", subject_teacher: "科任教師",
      resource_teacher: "資源班教師", platform_admin: "平台總管理員"})[role] || "教師";
  }

  function schoolLabel(profile) {
    return profile && profile.school_name ? `${profile.school_name}｜` : "";
  }

  function renderPersonalSchedule(workspace) {
    const rows = workspace.personal_schedule || [];
    const bySlot = new Map();
    rows.forEach((row) => {
      const key = `${row.day}|${row.period}`;
      const items = bySlot.get(key) || [];
      items.push(row);
      bySlot.set(key, items);
    });
    const days = ["一", "二", "三", "四", "五"];
    let html = `<tr><th class="pd">節次</th>${days.map((day) => `<th>星期${day}</th>`).join("")}</tr>`;
    for (let period = 1; period <= 7; period += 1) {
      if (period === 5) html += '<tr class="lunch"><td></td><td colspan="5">午　休</td></tr>';
      html += `<tr><th class="pd">${period}</th>`;
      days.forEach((day) => {
        const items = bySlot.get(`${day}|${period}`) || [];
        if (!items.length) html += "<td></td>";
        else if (items.length === 1) {
          const item = items[0];
          const suffix = item.source === "overlay" ? "・資源班" :
            item.source === "native" ? `・${item.group || "本土語"}` : "";
          html += `<td><div class="les ${root.cat ? root.cat(item.subject) : ""}"><b>${root.esc(item.subject)}</b><small>${root.esc(item.class_label + suffix)}</small></div></td>`;
        } else {
          html += `<td><div class="les conflict"><b>衝堂 ${items.length} 筆</b>${items.map((item) => `<small>${root.esc(item.subject)}｜${root.esc(item.class_label)}</small>`).join("")}</div></td>`;
        }
      });
      html += "</tr>";
    }
    document.getElementById("myScheduleTable").innerHTML = html;
    document.getElementById("myScheduleTitle").textContent = `${workspace.profile.name}的課表`;
    document.getElementById("myScheduleMeta").textContent = `${roleLabel(workspace.profile.role)}｜${workspace.label}｜${rows.length} 節`;
  }

  async function loadWorkspace() {
    const workspace = await request("/teacher/workspace");
    state.workspace = workspace;
    renderPersonalSchedule(workspace);
    document.body.classList.add("signed-teacher");
    document.getElementById("teacherProfile").textContent = `${schoolLabel(state.profile)}${workspace.profile.name}｜${roleLabel(workspace.profile.role)}`;
    if (workspace.editable_classes && workspace.editable_classes.length) {
      root.openServerTeacherPackage(workspace.editable_classes[0]);
    }
    if (root.enterFormalTeacherMode) root.enterFormalTeacherMode();
    root.go("my");
  }

  async function handleCredential(response) {
    try {
      status("正在確認學校帳號…", "working");
      state.sessionExpired = false;
      state.credential = response.credential || "";
      state.profile = await request("/auth/me");
      document.getElementById("googleAdminActions").hidden = !state.profile.is_admin;
      document.getElementById("platformSchoolActions").hidden = !state.profile.is_super_admin;
      if (state.profile.is_super_admin) await Promise.all([loadSchools(), loadUsage()]);
      if (state.profile.is_admin) {
        setDraftEditingLocked(true);
        if (root.setFormalStorageIdentity) {
          state.hasLocalBackup = !!root.setFormalStorageIdentity(state.profile);
        }
        if (root.enterFormalAdminMode) root.enterFormalAdminMode();
        document.getElementById("teacherProfile").textContent = `${schoolLabel(state.profile)}${state.profile.name}｜學校系統管理員`;
        state.activeRevision = localStorage.getItem(userStorageKey("schedule_active_revision")) || "";
        state.updateSequence = Number(localStorage.getItem(userStorageKey("schedule_teacher_update_sequence")) || 0);
        status("服務正常｜雲端暫存已啟用｜導師存檔：手動讀取", "ok");
        await refreshDraftStatus();
        startAdminAutomation();
      } else if (state.profile.school_id) {
        await loadWorkspace();
        status("已載入您的正式課表。", "ok");
      } else if (state.profile.is_super_admin) {
        if (root.enterPlatformAdminMode) root.enterPlatformAdminMode();
        else if (root.enterFormalAdminMode) root.enterFormalAdminMode();
        const profileLabel = `${state.profile.name}｜平台總管理員`;
        document.getElementById("teacherProfile").textContent = profileLabel;
        document.getElementById("platformFooterProfile").textContent = profileLabel;
        document.getElementById("platformFooterSession").hidden = false;
        status("平台總管理員已登入。", "ok");
      }
      document.getElementById("googleLogoutButton").hidden = false;
      document.getElementById("googleLogoutButton").textContent = "登出";
    } catch (error) {
      state.credential = "";
      status(error.message, "error");
    }
  }

  async function initialize() {
    if ((root.SCHEDULE_APP_CONFIG || {}).mode !== "formal") return;
    state.apiBaseUrl = apiBaseUrl();
    const apiInput = document.getElementById("formalApiUrl");
    if (apiInput && state.apiBaseUrl) apiInput.value = state.apiBaseUrl;
    if (!state.apiBaseUrl) {
      status("正式教師入口尚未啟用；公開 DEMO 仍可正常試用。", "disabled");
      return;
    }
    try {
      const config = await request("/auth/config");
      if (!config.enabled || !config.client_id) {
        status("後端尚未設定 Google OAuth Client ID。", "disabled");
        return;
      }
      if (!root.google && !document.querySelector('script[data-google-identity]')) {
        const script = document.createElement("script");
        script.src = "https://accounts.google.com/gsi/client";
        script.async = true; script.defer = true; script.dataset.googleIdentity = "true";
        document.head.appendChild(script);
      }
      const waitForGoogle = () => new Promise((resolve, reject) => {
        let count = 0;
        const timer = setInterval(() => {
          if (root.google && root.google.accounts && root.google.accounts.id) {
            clearInterval(timer); resolve();
          } else if ((count += 1) > 80) {
            clearInterval(timer); reject(new Error("Google 登入元件載入失敗"));
          }
        }, 100);
      });
      await waitForGoogle();
      root.google.accounts.id.initialize({client_id: config.client_id, callback: handleCredential,
        hd: config.workspace_domain || undefined});
      const gateTarget = document.getElementById("formalGoogleSignInButton") || document.getElementById("googleSignInButton");
      const availableWidth = Math.floor(gateTarget.getBoundingClientRect().width || 360);
      const buttonWidth = Math.max(200, Math.min(360, availableWidth));
      root.google.accounts.id.renderButton(gateTarget, {
        type: "standard", theme: "outline", size: "medium", text: "signin_with", shape: "pill",
        logo_alignment: "left", width: String(buttonWidth), locale: "zh_TW",
      });
      status(config.multi_tenant ? "請使用已核准的學校或平台管理員 Google 帳號登入。" :
        (config.workspace_domain ? `請使用 @${config.workspace_domain} 學校帳號登入。` : "請使用學校 Google 帳號登入。"), "ready");
    } catch (error) {
      status(error.message, "error");
    }
  }

  async function importTeacherCsv(input) {
    const file = input.files && input.files[0];
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    body.append("replace", "true");
    try {
      status("正在匯入教師帳號表…", "working");
      const result = await request("/admin/teachers/import-csv", {method: "POST", body});
      status(`已匯入 ${result.imported} 位教師帳號。`, "ok");
    } catch (error) {
      status(error.message, "error");
    } finally {
      input.value = "";
    }
  }

  function csvCell(value) {
    const text = String(value == null ? "" : value);
    return `"${text.replace(/"/g, '""')}"`;
  }

  async function importTeacherRecords(records) {
    if (!state.profile || !state.profile.is_admin) throw new Error("只有學校系統管理員可以同步教師名冊");
    if (!Array.isArray(records) || !records.length) throw new Error("尚未建立可同步的教師資料");
    const rows = [["教師姓名", "學校Google帳號", "角色", "負責班級"],
      ...records.map((record) => [record.name, record.email, record.role,
        (record.class_codes || []).join("、")])];
    const csv = "\ufeff" + rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
    const body = new FormData();
    body.append("file", new Blob([csv], {type: "text/csv;charset=utf-8"}), "teachers.csv");
    body.append("replace", "true");
    status("正在同步教師登入名冊…", "working");
    const result = await request("/admin/teachers/import-csv", {method: "POST", body});
    status(`已同步 ${result.imported} 位教師登入帳號。`, "ok");
    return result;
  }

  function splitValues(value) {
    return String(value || "").split(/[\s,，;；]+/).map((item) => item.trim()).filter(Boolean);
  }

  function renderSchools() {
    const target = document.getElementById("platformSchoolList");
    if (!target) return;
    target.innerHTML = state.schools.map((school) => `<tr>
      <td><b>${root.esc(school.name)}</b><small>教育部代碼 ${root.esc(school.moe_code || "尚未設定")}</small></td>
      <td>${(school.domains || []).map(root.esc).join("<br>")}</td>
      <td>${(school.admin_emails || []).map(root.esc).join("<br>") || "尚未指定"}</td>
      <td><span class="chip ${school.active ? "ok" : "bad"}">${school.active ? "啟用" : "停用"}</span>
        <button class="btn soft sm" type="button" onclick="ScheduleAuth.editSchool('${school.school_id}')">編輯</button></td>
    </tr>`).join("") || '<tr><td colspan="4">尚未建立學校</td></tr>';
  }

  async function loadSchools() {
    const element = document.getElementById("platformSchoolStatus");
    try {
      const result = await request("/platform/schools");
      state.schools = result.schools || [];
      renderSchools();
      if (element) element.textContent = `共 ${state.schools.length} 間學校。`;
    } catch (error) {
      if (element) element.textContent = error.message;
    }
  }

  function editSchool(schoolId) {
    const school = state.schools.find((item) => item.school_id === schoolId);
    if (!school) return;
    document.getElementById("platformSchoolRecordId").value = school.school_id;
    document.getElementById("platformSchoolId").value = school.moe_code || (/^\d{6}$/.test(school.school_id) ? school.school_id : "");
    document.getElementById("platformSchoolName").value = school.name;
    document.getElementById("platformSchoolDomains").value = (school.domains || []).join(", ");
    document.getElementById("platformSchoolAdmins").value = (school.admin_emails || []).join(", ");
    document.getElementById("platformSchoolActive").checked = school.active !== false;
    document.getElementById("platformSchoolId").focus();
  }

  function newSchool() {
    document.getElementById("platformSchoolRecordId").value = "";
    document.getElementById("platformSchoolId").value = "";
    document.getElementById("platformSchoolName").value = "";
    document.getElementById("platformSchoolDomains").value = "";
    document.getElementById("platformSchoolAdmins").value = "";
    document.getElementById("platformSchoolActive").checked = true;
    document.getElementById("platformSchoolStatus").textContent = "請輸入教育部六碼學校代碼。";
    document.getElementById("platformSchoolId").focus();
  }

  async function saveSchool() {
    const schoolCode = document.getElementById("platformSchoolId").value.trim();
    const schoolId = document.getElementById("platformSchoolRecordId").value.trim().toLowerCase() || schoolCode;
    const payload = {
      moe_code: schoolCode,
      name: document.getElementById("platformSchoolName").value.trim(),
      domains: splitValues(document.getElementById("platformSchoolDomains").value),
      admin_emails: splitValues(document.getElementById("platformSchoolAdmins").value),
      active: document.getElementById("platformSchoolActive").checked,
    };
    const element = document.getElementById("platformSchoolStatus");
    try {
      if (!/^\d{6}$/.test(schoolCode)) throw new Error("教育部學校代碼須為 6 位數字");
      element.textContent = "正在儲存學校…";
      await request(`/platform/schools/${encodeURIComponent(schoolId)}`, {
        method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
      });
      document.getElementById("platformSchoolRecordId").value = schoolId;
      element.textContent = `${payload.name}（${schoolCode}）已儲存。`;
      await loadSchools();
    } catch (error) {
      element.textContent = error.message;
    }
  }

  async function publishCurrent() {
    try {
      const snapshot = root.getScheduleAuthSnapshot();
      if (!snapshot || !snapshot.sol) throw new Error("請先完成排課，再發布正式課表");
      if (root.SchedulePolicy) {
        const compliance = root.SchedulePolicy.validate(snapshot.data, {requireApproval: true});
        if (compliance.blocking.length) throw new Error(compliance.blocking.slice(0, 3).join("；"));
      }
      status("正在發布教師課表…", "working");
      const result = await request("/admin/publish", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(snapshot),
      });
      state.activeRevision = result.revision;
      state.updateSequence = Number(result.update_sequence || 0);
      localStorage.setItem(userStorageKey("schedule_active_revision"), state.activeRevision);
      localStorage.setItem(userStorageKey("schedule_teacher_update_sequence"), String(state.updateSequence));
      document.getElementById("teacherSyncStatus").textContent = "導師儲存後，請按「讀取導師存檔」取得更新。";
      status(`正式課表已發布（${new Date(result.published_at).toLocaleString("zh-TW")}）。`, "ok");
    } catch (error) {
      status(error.message, "error");
    }
  }

  async function refreshDraftStatus() {
    const element = document.getElementById("cloudDraftStatus");
    const continueButton = document.getElementById("cloudContinueButton");
    const localButton = document.getElementById("localBackupButton");
    const adminDock = document.getElementById("adminDock");
    try {
      const draft = await request("/admin/draft");
      state.draftRevision = draft.draft_revision || "";
      state.draftConflict = true;
      setDraftEditingLocked(true);
      if (adminDock) adminDock.open = true;
      if (continueButton) {
        continueButton.hidden = false;
        continueButton.textContent = "繼續上次雲端案件";
      }
      if (localButton) localButton.hidden = !state.hasLocalBackup;
      const saver = draft.saved_by ? `｜儲存者：${draft.saved_by}` : "";
      const localChoice = state.hasLocalBackup ? "，或明確改用這台電腦的備份" : "";
      element.textContent = `找到學校雲端案件：${new Date(draft.saved_at).toLocaleString("zh-TW")}${saver}。請先載入雲端案件${localChoice}，再開始編修。`;
      return draft;
    } catch (error) {
      if (error.status === 404) {
        state.draftRevision = "";
        state.draftConflict = false;
        setDraftEditingLocked(false);
        if (continueButton) continueButton.hidden = true;
        if (localButton) localButton.hidden = true;
        element.textContent = "目前尚無學校雲端案件；開始建置後，停止操作 10 秒會自動存檔。";
      } else {
        state.draftConflict = true;
        setDraftEditingLocked(true);
        if (adminDock) adminDock.open = true;
        if (continueButton) {
          continueButton.hidden = false;
          continueButton.textContent = "重新檢查雲端案件";
        }
        if (localButton) localButton.hidden = true;
        element.textContent = `無法確認雲端案件，編輯已暫停：${error.message}`;
      }
      return null;
    }
  }

  function formatUsageDate(value) {
    if (!value) return "尚無紀錄";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "尚無紀錄" : date.toLocaleString("zh-TW", {
      month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  }

  function renderUsage() {
    const summary = document.getElementById("platformUsageSummary");
    const body = document.getElementById("platformUsageList");
    if (!summary || !body || !state.usage) return;
    const totals = state.usage.totals || {};
    const metrics = [
      ["已開通學校", totals.configured_schools], ["近 7 日活躍", totals.active_7d],
      ["近 30 日活躍", totals.active_period], ["登入", totals.login],
      ["求解完成", totals.solve_success], ["正式發布", totals.publish],
      ["教師送出", totals.teacher_save],
    ];
    summary.innerHTML = metrics.map(([label, value]) =>
      `<div><span>${label}</span><b>${Number(value || 0).toLocaleString("zh-TW")}</b></div>`).join("");
    body.innerHTML = (state.usage.schools || []).map((school) => {
      const events = school.events || {};
      return `<tr><td><b>${root.esc(school.name)}</b><small>${root.esc(school.moe_code || school.school_id)}</small></td>
        <td>${formatUsageDate(school.last_active_at)}</td>
        <td>${Number(events.login || 0)}</td><td>${Number(events.solve_success || 0)}</td>
        <td>${Number(events.publish || 0)}</td><td>${Number(events.teacher_save || 0)}</td></tr>`;
    }).join("") || '<tr><td colspan="6">尚無學校使用紀錄</td></tr>';
  }

  async function loadUsage() {
    const element = document.getElementById("platformUsageStatus");
    try {
      if (element) element.textContent = "正在整理近 30 日使用概況…";
      state.usage = await request("/platform/usage?days=30");
      renderUsage();
      if (element) element.textContent = "本使用概況只彙整學校、日期、角色與操作次數；不保存姓名、Email、IP 或課表內容。";
    } catch (error) {
      if (element) element.textContent = `使用概況載入失敗：${error.message}`;
    }
  }

  function setDraftEditingLocked(locked) {
    state.draftReady = !locked;
    if (root.setFormalEditingLocked) root.setFormalEditingLocked(locked);
    setSaveButtonsBusy(!!state.saveInFlight);
  }

  function setSaveButtonsBusy(busy) {
    document.querySelectorAll("[data-cloud-save]").forEach((button) => {
      button.disabled = busy || !state.draftReady;
      button.textContent = busy ? "正在儲存…" : "儲存至學校雲端";
    });
  }

  function stopSessionTimers() {
    clearTimeout(state.autoSaveTimer);
    state.autoSaveTimer = null;
    if (state.autoSaveInterval) clearInterval(state.autoSaveInterval);
    state.autoSaveInterval = null;
    state.automationStarted = false;
    state.savePending = false;
    state.pendingManual = false;
  }

  function handleSessionExpired() {
    if (state.sessionExpired) return;
    state.sessionExpired = true;
    stopSessionTimers();
    state.credential = "";
    const message = "登入已逾時，請按「重新登入」後繼續；這台電腦的本機備份仍會保留。";
    if (state.profile && state.profile.is_admin) {
      state.draftConflict = true;
      setDraftEditingLocked(true);
      const adminDock = document.getElementById("adminDock");
      if (adminDock) adminDock.open = true;
      const draftStatus = document.getElementById("cloudDraftStatus");
      if (draftStatus) draftStatus.textContent = message;
    }
    const logoutButton = document.getElementById("googleLogoutButton");
    if (logoutButton) logoutButton.textContent = "重新登入";
    status(message, "error");
  }

  async function performDraftSave(manual) {
    const element = document.getElementById("cloudDraftStatus");
    if (!state.draftReady || state.draftConflict) {
      const message = "學校雲端已有案件或較新版本，請先按「繼續上次雲端案件」載入後再編修。";
      element.textContent = message;
      if (manual) alert(message);
      return false;
    }
    try {
      const snapshot = root.getScheduleAuthSnapshot();
      if (!snapshot || !snapshot.data) throw new Error("目前沒有可暫存的排課資料");
      if (!(snapshot.data.classes || []).length || !Object.keys(snapshot.data.subjects || {}).length) {
        if (manual) throw new Error("請先建立空白案件或匯入 Excel，再儲存至學校雲端");
        return;
      }
      if (!manual && String(snapshot.label || "").includes("示範")) {
        element.textContent = "示範資料不會自動存入正式雲端暫存。";
        return;
      }
      const hash = JSON.stringify(snapshot);
      if (hash === state.lastDraftHash) {
        if (manual) element.textContent = "目前內容已儲存至學校雲端，沒有新的變更。";
        return true;
      }
      element.textContent = "正在保存雲端暫存…";
      const result = await request("/admin/draft", {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({...snapshot, active_revision: state.activeRevision,
          expected_draft_revision: state.draftRevision, save_mode: manual ? "manual" : "auto"}),
      });
      state.draftRevision = result.draft_revision || "";
      state.draftConflict = false;
      state.lastDraftHash = hash;
      const continueButton = document.getElementById("cloudContinueButton");
      if (continueButton) {
        continueButton.hidden = false;
        continueButton.textContent = "重新載入雲端案件";
      }
      element.textContent = `${manual ? "已儲存至學校雲端" : "已自動存檔"}：${new Date(result.saved_at).toLocaleString("zh-TW")}｜${result.saved_by || state.profile.email}。`;
      return true;
    } catch (error) {
      if (state.sessionExpired) return false;
      if (error.status === 409) {
        state.draftConflict = true;
        setDraftEditingLocked(true);
        element.textContent = "另一位管理員已儲存較新的版本；為避免覆蓋，請先載入雲端案件。";
      } else element.textContent = `雲端暫存失敗：${error.message}`;
      if (manual) alert(element.textContent);
      return false;
    }
  }

  async function drainDraftSaveQueue(initialManual) {
    let manual = !!initialManual;
    setSaveButtonsBusy(true);
    try {
      while (true) {
        state.savePending = false;
        const requestedManual = manual || state.pendingManual;
        state.pendingManual = false;
        const completed = await performDraftSave(requestedManual);
        manual = false;
        if (!completed || !state.savePending || state.draftConflict) break;
      }
    } finally {
      setSaveButtonsBusy(false);
    }
  }

  function saveDraft(manual) {
    if (!state.profile || !state.profile.is_admin || state.sessionExpired) return Promise.resolve();
    if (manual) {
      clearTimeout(state.autoSaveTimer);
      state.autoSaveTimer = null;
    }
    if (state.saveInFlight) {
      state.savePending = true;
      state.pendingManual = state.pendingManual || !!manual;
      return state.saveInFlight;
    }
    state.saveInFlight = drainDraftSaveQueue(manual).finally(() => {
      state.saveInFlight = null;
      setSaveButtonsBusy(false);
    });
    return state.saveInFlight;
  }

  async function loadDraft() {
    if (!state.profile || !state.profile.is_admin) return;
    try {
      const draft = await request("/admin/draft");
      if (!confirm(`載入 ${new Date(draft.saved_at).toLocaleString("zh-TW")} 的雲端暫存？目前畫面內容會被取代。`)) return;
      root.applyAdminDraft(draft.snapshot);
      state.draftRevision = draft.draft_revision || "";
      state.draftConflict = false;
      state.activeRevision = draft.active_revision || "";
      state.updateSequence = 0;
      if (state.activeRevision) localStorage.setItem(userStorageKey("schedule_active_revision"), state.activeRevision);
      else localStorage.removeItem(userStorageKey("schedule_active_revision"));
      localStorage.setItem(userStorageKey("schedule_teacher_update_sequence"), "0");
      state.lastDraftHash = JSON.stringify(root.getScheduleAuthSnapshot());
      setDraftEditingLocked(false);
      const continueButton = document.getElementById("cloudContinueButton");
      const localButton = document.getElementById("localBackupButton");
      if (continueButton) continueButton.textContent = "重新載入雲端案件";
      if (localButton) localButton.hidden = true;
      document.getElementById("cloudDraftStatus").textContent = `已載入學校雲端案件：${new Date(draft.saved_at).toLocaleString("zh-TW")}｜${draft.saved_by || "管理員"}。`;
    } catch (error) {
      if (error.status === 404) {
        state.draftRevision = "";
        state.draftConflict = false;
        setDraftEditingLocked(false);
        document.getElementById("cloudContinueButton").hidden = true;
        document.getElementById("cloudDraftStatus").textContent = "目前尚無學校雲端案件，可以開始建立新案件。";
      } else alert(`無法載入雲端暫存：${error.message}`);
    }
  }

  function useLocalBackup() {
    if (!state.hasLocalBackup || !state.profile || !state.profile.is_admin) return;
    if (!confirm("確定改用這台電腦的瀏覽器備份？目前雲端案件不會立刻被刪除；下一次儲存時，這份本機內容會成為學校共用的新版本。")) return;
    state.draftConflict = false;
    state.lastDraftHash = "";
    setDraftEditingLocked(false);
    const continueButton = document.getElementById("cloudContinueButton");
    const localButton = document.getElementById("localBackupButton");
    if (continueButton) continueButton.textContent = "載入雲端案件";
    if (localButton) localButton.hidden = true;
    document.getElementById("cloudDraftStatus").textContent = "目前使用這台電腦的備份；確認內容後，請按「儲存至學校雲端」建立新的共用版本。";
  }

  async function syncTeacherUpdates() {
    if (!state.profile || !state.profile.is_admin) return;
    const element = document.getElementById("teacherSyncStatus");
    if (!state.activeRevision) {
      element.textContent = "發布正式課表後，可按「讀取導師存檔」取得更新。";
      return;
    }
    try {
      const query = `?revision=${encodeURIComponent(state.activeRevision)}&after=${state.updateSequence}`;
      const result = await request(`/admin/teacher-updates${query}`);
      const changed = Object.keys(result.placements || {});
      if (changed.length) {
        const applied = root.applyServerTeacherUpdates(result.placements);
        if (!applied.applied) {
          element.textContent = applied.reason || "收到導師更新，但承辦端尚未能套用。";
          return;
        }
        element.textContent = `已讀取並匯入：${applied.codes.join("、")}（${new Date(result.updated_at).toLocaleString("zh-TW")}）。`;
        state.lastDraftHash = "";
      } else {
        element.textContent = "目前沒有新的導師存檔。";
      }
      state.updateSequence = Number(result.update_sequence || state.updateSequence);
      localStorage.setItem(userStorageKey("schedule_teacher_update_sequence"), String(state.updateSequence));
    } catch (error) {
      element.textContent = error.status === 409 ? "正式課表版本已變更，請重新發布或載入對應暫存。" : `導師課表同步失敗：${error.message}`;
    }
  }

  function startAdminAutomation() {
    if (state.automationStarted) return;
    state.automationStarted = true;
    state.autoSaveInterval = setInterval(() => saveDraft(false), 60000);
  }

  function queueDraftSave() {
    if (!state.profile || !state.profile.is_admin || state.sessionExpired || state.draftConflict || !state.draftReady) return;
    if (state.saveInFlight) {
      state.savePending = true;
      return;
    }
    clearTimeout(state.autoSaveTimer);
    const element = document.getElementById("cloudDraftStatus");
    if (element) element.textContent = "尚有未存雲端的變更；停止操作 10 秒後自動存檔。";
    state.autoSaveTimer = setTimeout(() => saveDraft(false), 10000);
  }

  async function savePlacements() {
    const submission = root.getServerTeacherSubmission();
    if (!submission) return;
    const {code, revision, placements, remaining} = submission;
    if (remaining.length) {
      alert(`尚有科目未排完：${remaining.map((item) => `${item[0]} ${item[1]}節`).join("、")}`);
      return;
    }
    try {
      status("正在儲存課表調整…", "working");
      await request(`/teacher/classes/${encodeURIComponent(code)}/placements`, {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({revision, placements}),
      });
      status(`${code} 課表已儲存，承辦人可讀取此存檔。`, "ok");
      alert("課表調整已儲存，承辦人按「讀取導師存檔」即可匯入。");
      await loadWorkspace();
    } catch (error) {
      status(error.message, "error");
      alert(`無法儲存：${error.message}`);
    }
  }

  function logout() {
    stopSessionTimers();
    if (root.clearFormalSessionData) root.clearFormalSessionData();
    state.credential = "";
    state.profile = null;
    state.workspace = null;
    if (root.google && root.google.accounts && root.google.accounts.id) root.google.accounts.id.disableAutoSelect();
    location.reload();
  }

  root.ScheduleAuth = {initialize, authorizationHeaders, importTeacherCsv, importTeacherRecords, publishCurrent, saveDraft, loadDraft, useLocalBackup, queueDraftSave,
    syncTeacherUpdates, savePlacements, loadSchools, loadUsage, saveSchool, editSchool, newSchool, logout};
}(typeof globalThis !== "undefined" ? globalThis : window));
