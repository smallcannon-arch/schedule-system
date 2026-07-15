(function (root) {
  "use strict";

  const state = {credential: "", profile: null, workspace: null, apiBaseUrl: "",
    activeRevision: "", updateSequence: 0, draftRevision: "", draftConflict: false,
    draftReady: false, hasCloudDraft: false, hasLocalBackup: false, lastDraftHash: "", automationStarted: false,
    autoSaveTimer: null, saveInFlight: null, savePending: false, pendingManual: false,
    autoSaveInterval: null, sessionExpired: false, deletingDraft: false, loadingDraft: false,
    publishing: false, syncingUpdates: false, importingTeacherCsv: false,
    savingSchool: false, loadingUsage: false, savingPlacements: false,
    loadingVersions: false, restoringVersion: false, versions: [],
    loadingBackups: false, creatingBackup: false, restoringBackup: false, backups: [],
    schools: [], usage: null, usageSchoolId: "", usageTrigger: null};

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

  function refreshReadiness() {
    if (root.ScheduleReadiness && root.ScheduleReadiness.render) root.ScheduleReadiness.render();
  }

  function getReadinessState() {
    return {
      isAdmin: !!(state.profile && state.profile.is_admin),
      hasCloudDraft: state.hasCloudDraft,
      draftRevision: state.draftRevision,
      draftConflict: state.draftConflict,
      activeRevision: state.activeRevision,
      backupCount: state.backups.length,
    };
  }

  async function request(path, options) {
    if (!state.apiBaseUrl) throw new Error("正式教師入口尚未設定 API 網址");
    const headers = new Headers((options && options.headers) || {});
    if (state.credential) headers.set("Authorization", `Bearer ${state.credential}`);
    let response;
    try {
      response = await fetch(`${state.apiBaseUrl}${path}`, {...(options || {}), headers});
    } catch (_error) {
      throw new Error("目前無法連線至雲端服務，請確認網路後重新整理再試。");
    }
    const contentType = response.headers.get("content-type") || "";
    let payload = null;
    if (contentType.includes("application/json")) {
      try {
        payload = await response.json();
      } catch (_error) {
        payload = null;
      }
    }
    if (!response.ok) {
      const error = new Error((payload && (payload.detail || payload.error)) || `伺服器回應 ${response.status}`);
      error.status = response.status;
      if (response.status === 401 && state.profile) handleSessionExpired();
      throw error;
    }
    return payload;
  }

  async function solveData(payload) {
    if (!state.apiBaseUrl) throw new Error("正式排課引擎尚未設定");
    if (!state.credential) throw new Error("請先使用學校 Google 帳號登入");
    try {
      return await fetch(`${state.apiBaseUrl}/solve-data`, {
        method: "POST",
        headers: {Authorization: `Bearer ${state.credential}`, "Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
    } catch (_error) {
      throw new Error("目前無法連線至排課引擎，請確認網路後再試。");
    }
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
        state.activeRevision = sessionStorage.getItem(userStorageKey("schedule_active_revision")) || "";
        state.updateSequence = Number(sessionStorage.getItem(userStorageKey("schedule_teacher_update_sequence")) || 0);
        status("服務正常｜雲端暫存已啟用｜導師存檔：手動讀取", "ok");
        await refreshDraftStatus();
        await loadVersions();
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
      updateActionButtons();
    } catch (error) {
      state.credential = "";
      status(error.message, "error");
    }
  }

  async function initialize() {
    if ((root.SCHEDULE_APP_CONFIG || {}).mode !== "formal") return;
    state.apiBaseUrl = apiBaseUrl();
    if (!state.apiBaseUrl) {
      status("正式教師入口尚未啟用；公開 DEMO 仍可正常試用。", "disabled");
      return;
    }
    try {
      const expectedVersion = String((root.SCHEDULE_APP_CONFIG || {}).version || "");
      try {
        const health = await request("/health");
        const notice = document.getElementById("appVersionNotice");
        const message = document.getElementById("appVersionMessage");
        if (notice && message && expectedVersion && health.version !== expectedVersion) {
          message.textContent = `系統已更新（網頁 ${expectedVersion}／服務 ${health.version || "未知"}），請重新載入後再繼續編修。`;
          notice.hidden = false;
        }
      } catch (_) {
        // OAuth 初始化會在下一個請求顯示正式的連線錯誤。
      }
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
    if (teacherCsvImportLocked()) {
      input.value = "";
      alert("案件已開始編輯，無法再批次匯入教師帳號。請到「教師與配課」修改後，按「同步教師登入名冊」。");
      return;
    }
    if (state.importingTeacherCsv) { input.value = ""; return; }
    const body = new FormData();
    body.append("file", file);
    body.append("replace", "true");
    state.importingTeacherCsv = true;
    updateTeacherCsvImportState();
    try {
      status("正在匯入教師帳號表…", "working");
      const result = await request("/admin/teachers/import-csv", {method: "POST", body});
      status(`已匯入 ${result.imported} 位教師帳號。`, "ok");
    } catch (error) {
      status(error.message, "error");
    } finally {
      state.importingTeacherCsv = false;
      updateTeacherCsvImportState();
      input.value = "";
    }
  }

  function csvCell(value) {
    const text = String(value == null ? "" : value);
    return `"${text.replace(/"/g, '""')}"`;
  }

  function csvExportCell(value) {
    const text = String(value == null ? "" : value);
    return csvCell(/^[=+\-@\t\r]/.test(text) ? `'${text}` : text);
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
        <button class="btn soft sm" type="button" onclick="ScheduleAuth.editSchool('${school.school_id}')" ${state.savingSchool ? "disabled" : ""}>編輯</button></td>
    </tr>`).join("") || '<tr><td colspan="4">尚未建立學校</td></tr>';
  }

  async function loadSchools(statusMessage) {
    const element = document.getElementById("platformSchoolStatus");
    try {
      const result = await request("/platform/schools");
      state.schools = result.schools || [];
      renderSchools();
      if (element) element.textContent = statusMessage || `共 ${state.schools.length} 間學校。`;
    } catch (error) {
      if (element) element.textContent = error.message;
    }
  }

  function editSchool(schoolId) {
    if (state.savingSchool) return;
    const school = state.schools.find((item) => item.school_id === schoolId);
    if (!school) return;
    const schoolCode = school.moe_code || (/^\d{6}$/.test(school.school_id) ? school.school_id : "");
    document.getElementById("platformSchoolRecordId").value = school.school_id;
    document.getElementById("platformSchoolId").value = schoolCode;
    document.getElementById("platformSchoolId").readOnly = true;
    document.getElementById("platformSchoolName").value = school.name;
    document.getElementById("platformSchoolDomains").value = (school.domains || []).join(", ");
    document.getElementById("platformSchoolAdmins").value = (school.admin_emails || []).join(", ");
    document.getElementById("platformSchoolActive").checked = school.active !== false;
    document.getElementById("platformSchoolFormMode").textContent = `正在編輯：${school.name}（${schoolCode || school.school_id}）`;
    document.getElementById("platformSchoolStatus").textContent = "教育部代碼是學校識別值，編輯既有學校時不可變更。";
    updateActionButtons();
    document.getElementById("platformSchoolName").focus();
  }

  function resetSchoolForm(statusMessage) {
    document.getElementById("platformSchoolRecordId").value = "";
    document.getElementById("platformSchoolId").value = "";
    document.getElementById("platformSchoolId").readOnly = false;
    document.getElementById("platformSchoolName").value = "";
    document.getElementById("platformSchoolDomains").value = "";
    document.getElementById("platformSchoolAdmins").value = "";
    document.getElementById("platformSchoolActive").checked = true;
    document.getElementById("platformSchoolFormMode").textContent = "新增學校";
    document.getElementById("platformSchoolStatus").textContent = statusMessage || "請輸入教育部六碼學校代碼。";
    updateActionButtons();
    document.getElementById("platformSchoolId").focus();
  }

  function newSchool() {
    if (state.savingSchool) return;
    resetSchoolForm();
  }

  async function saveSchool() {
    if (state.savingSchool) return;
    const schoolCode = document.getElementById("platformSchoolId").value.trim();
    const recordId = document.getElementById("platformSchoolRecordId").value.trim().toLowerCase();
    const schoolId = recordId || schoolCode;
    const editingSchool = recordId ? state.schools.find((item) => item.school_id === recordId) : null;
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
      if (recordId && !editingSchool) throw new Error("找不到正在編輯的學校，請按「新增學校」後重新輸入");
      if (editingSchool && schoolCode !== String(editingSchool.moe_code || "")) {
        throw new Error("既有學校的教育部代碼不可變更；若要建立另一間學校，請先按「新增學校」");
      }
      if (!payload.name) throw new Error("請填寫學校名稱");
      if (!payload.domains.length) throw new Error("請填寫至少一個 Google Workspace 網域");
      if (!payload.admin_emails.length) throw new Error("請填寫至少一位排課管理員帳號");
      const domains = payload.domains.map((domain) => domain.toLowerCase().replace(/^@/, ""));
      const invalidDomain = domains.find((domain) => !/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(domain));
      if (invalidDomain) throw new Error(`Workspace 網域格式不正確：${invalidDomain}`);
      const invalidAdmin = payload.admin_emails.find((email) => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email));
      if (invalidAdmin) throw new Error(`管理員帳號格式不正確：${invalidAdmin}`);
      const outsideDomain = payload.admin_emails.find((email) => !domains.includes(email.toLowerCase().split("@")[1] || ""));
      if (outsideDomain) throw new Error(`管理員帳號必須使用已填寫的 Workspace 網域：${outsideDomain}`);
      if (editingSchool && !confirm(`確定更新「${editingSchool.name}（${schoolCode}）」的學校設定？`)) return;
      state.savingSchool = true;
      updateActionButtons();
      element.textContent = "正在儲存學校…";
      await request(`/platform/schools/${encodeURIComponent(schoolId)}`, {
        method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
      });
      await loadSchools(`${payload.name}（${schoolCode}）已儲存。`);
      if (!recordId) resetSchoolForm(`${payload.name}（${schoolCode}）已建立；表單已清空，可繼續新增下一間學校。`);
    } catch (error) {
      element.textContent = error.message;
    } finally {
      state.savingSchool = false;
      renderSchools();
      updateActionButtons();
    }
  }

  async function publishCurrent() {
    if (state.publishing) return;
    try {
      if (!state.draftReady || state.draftConflict) throw new Error("請先載入學校雲端案件，再發布正式課表");
      const snapshot = root.getScheduleAuthSnapshot();
      if (!snapshot || !snapshot.scheduleReady) throw new Error("請先完成排課，再發布正式課表");
      if (root.schedulePublishability) {
        const result = root.schedulePublishability();
        if (!result.ready) throw new Error(`課表尚未完成：${result.hard} 項硬規則問題、${result.pending} 項待排課程`);
      }
      if (root.SchedulePolicy) {
        const compliance = root.SchedulePolicy.validate(snapshot.data, {requireApproval: true});
        if (compliance.blocking.length) throw new Error(compliance.blocking.slice(0, 3).join("；"));
      }
      if (state.activeRevision && !confirm("重新發布會建立新的正式課表版本；教師目前開啟的舊版本將不能再送出調整。確定發布？")) return;
      state.publishing = true;
      updateActionButtons();
      status("正在發布教師課表…", "working");
      const result = await request("/admin/publish", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(snapshot),
      });
      state.activeRevision = result.revision;
      state.updateSequence = Number(result.update_sequence || 0);
      sessionStorage.setItem(userStorageKey("schedule_active_revision"), state.activeRevision);
      sessionStorage.setItem(userStorageKey("schedule_teacher_update_sequence"), String(state.updateSequence));
      document.getElementById("teacherSyncStatus").textContent = "導師儲存後，請按「讀取導師存檔」取得更新。";
      document.getElementById("versionHistoryStatus").textContent = "已保留本次正式版本，可由「正式版本」查看或還原。";
      status(`正式課表已發布（${new Date(result.published_at).toLocaleString("zh-TW")}）。`, "ok");
      refreshReadiness();
    } catch (error) {
      status(error.message, "error");
    } finally {
      state.publishing = false;
      updateActionButtons();
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
      state.hasCloudDraft = true;
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
        state.hasCloudDraft = false;
        state.draftConflict = false;
        setDraftEditingLocked(false);
        if (continueButton) continueButton.hidden = true;
        if (localButton) localButton.hidden = true;
        element.textContent = "目前尚無學校雲端案件；開始建置後，停止操作 10 秒會自動存檔。";
      } else {
        state.hasCloudDraft = false;
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

  function updateActionButtons() {
    const adminReady = !!(state.profile && state.profile.is_admin) && !state.sessionExpired;
    const publishability = root.schedulePublishability ? root.schedulePublishability() : {ready: true, hard: 0, pending: 0};
    const publish = document.getElementById("publishScheduleButton");
    if (publish) {
      publish.disabled = state.publishing || !!state.saveInFlight || !adminReady || !state.draftReady || !publishability.ready;
      publish.textContent = state.publishing ? "正在發布…" : "發布正式教師課表";
      publish.title = publishability.ready ? "" : (publishability.hard || publishability.pending ?
        `尚有 ${publishability.hard} 項硬規則問題、${publishability.pending} 項待排課程` : "請先完成正式排課");
    }
    const sync = document.getElementById("syncTeacherUpdatesButton");
    if (sync) {
      sync.disabled = state.syncingUpdates || !adminReady || !state.draftReady || !state.activeRevision;
      sync.textContent = state.syncingUpdates ? "正在讀取…" : "讀取導師存檔";
      sync.title = state.activeRevision ? "" : "請先發布正式教師課表";
    }
    const versions = document.getElementById("versionHistoryButton");
    if (versions) {
      versions.disabled = state.loadingVersions || state.restoringVersion || !adminReady;
      versions.textContent = state.loadingVersions ? "正在載入…" : (state.restoringVersion ? "正在還原…" : "正式版本");
      versions.title = "查看與還原正式課表版本";
    }
    const createBackupButton = document.getElementById("createBackupButton");
    const createBackupDialogButton = document.getElementById("backupCreateDialogButton");
    for (const button of [createBackupButton, createBackupDialogButton].filter(Boolean)) {
      button.disabled = state.creatingBackup || state.restoringBackup || !!state.saveInFlight ||
        !adminReady || !state.draftReady || !state.hasCloudDraft || state.draftConflict;
      button.textContent = state.creatingBackup ? "正在建立…" :
        (button.id === "backupCreateDialogButton" ? "建立目前案件還原點" : "建立還原點");
    }
    const backupHistoryButton = document.getElementById("backupHistoryButton");
    if (backupHistoryButton) {
      backupHistoryButton.disabled = state.loadingBackups || state.restoringBackup || !adminReady;
      backupHistoryButton.textContent = state.loadingBackups ? "正在載入…" :
        (state.restoringBackup ? "正在還原…" : "案件還原點");
    }
    const loadDraftButton = document.getElementById("cloudContinueButton");
    if (loadDraftButton) loadDraftButton.disabled = state.loadingDraft || !!state.saveInFlight || state.deletingDraft || state.sessionExpired;
    const localBackupButton = document.getElementById("localBackupButton");
    if (localBackupButton) localBackupButton.disabled = state.loadingDraft || !!state.saveInFlight || state.deletingDraft || state.sessionExpired;
    const saveSchoolButton = document.getElementById("platformSchoolSaveButton");
    if (saveSchoolButton) {
      saveSchoolButton.disabled = state.savingSchool;
      const editingSchool = !!document.getElementById("platformSchoolRecordId")?.value;
      saveSchoolButton.textContent = state.savingSchool ? "正在儲存…" : (editingSchool ? "儲存變更" : "建立學校");
    }
    const newSchoolButton = document.getElementById("platformSchoolNewButton");
    if (newSchoolButton) newSchoolButton.disabled = state.savingSchool;
    const usageButton = document.getElementById("platformUsageRefreshButton");
    if (usageButton) {
      usageButton.disabled = state.loadingUsage;
      usageButton.textContent = state.loadingUsage ? "正在整理…" : "重新整理";
    }
    const usageExportButton = document.getElementById("platformUsageExportButton");
    if (usageExportButton) usageExportButton.disabled = state.loadingUsage || !state.usage;
    const placementButton = document.getElementById("teacherPlacementSaveButton");
    if (placementButton) {
      placementButton.disabled = state.savingPlacements || state.sessionExpired;
      placementButton.textContent = state.savingPlacements ? "正在儲存…" : "儲存課表調整";
    }
  }

  function teacherCsvImportLocked() {
    const setupStarted = !document.body.classList.contains("setup-pending");
    return !state.draftReady || state.hasCloudDraft || state.draftConflict ||
      state.sessionExpired || state.importingTeacherCsv || setupStarted;
  }

  function updateTeacherCsvImportState() {
    const button = document.getElementById("teacherCsvImportButton");
    const input = document.getElementById("teacherCsvImportInput");
    const hint = document.getElementById("teacherCsvImportHint");
    if (!button || !input) return;
    const locked = teacherCsvImportLocked();
    button.classList.toggle("csv-import-locked", locked);
    button.setAttribute("aria-disabled", locked ? "true" : "false");
    button.title = state.importingTeacherCsv ? "正在匯入教師帳號" :
      (locked ? "案件開始後請到教師與配課頁修改並同步登入名冊" : "匯入教師帳號 CSV");
    input.disabled = locked;
    if (hint) hint.textContent = state.importingTeacherCsv ? "正在匯入教師帳號，完成前請勿關閉頁面。" : (locked ?
      "案件已開始編輯，批次匯入已鎖定；請到「教師與配課」修改帳號，再按「同步教師登入名冊」。" :
      "請在建立或載入案件前匯入。CSV 欄位：教師姓名、學校Google帳號、角色、負責班級。");
  }

  function downloadTeacherCsvTemplate() {
    const rows = [
      ["教師姓名", "學校Google帳號", "角色", "負責班級"],
      ["王小明", "teacher1@school.edu.tw", "導師", "1甲"],
      ["李小華", "teacher2@school.edu.tw", "科任", ""],
    ];
    const csv = "\ufeff" + rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], {type: "text/csv;charset=utf-8"}));
    const link = document.createElement("a");
    link.href = url;
    link.download = "教師帳號匯入範本.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  const USAGE_EVENT_LABELS = {
    login: "登入系統", draft_save: "儲存雲端案件", draft_delete: "刪除雲端案件",
    solve_success: "完成排課", solve_failed: "排課失敗", publish: "發布正式課表",
    teacher_open: "教師開啟課表", teacher_save: "教師送出調整",
    teacher_import: "同步教師帳號", backup_create: "建立案件還原點",
    backup_restore: "從還原點復原",
  };
  const USAGE_PROGRESS_LABELS = {
    not_started: "尚未開始", signed_in: "已登入", building: "資料建置中",
    scheduled: "已完成排課", published: "已發布", disabled: "已停用",
    unknown: "無法取得",
  };

  function formatUsageDate(value, includeYear) {
    if (!value) return "尚無紀錄";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "尚無紀錄" : date.toLocaleString("zh-TW", {
      year: includeYear ? "numeric" : undefined,
      month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  }

  function usageProgressLabel(value) {
    return USAGE_PROGRESS_LABELS[value] || "尚未開始";
  }

  function usageCaseMetric(details, key) {
    return details.metadata_unavailable ? "—" : Number(details[key] || 0);
  }

  function renderUsage() {
    const summary = document.getElementById("platformUsageSummary");
    const body = document.getElementById("platformUsageList");
    if (!summary || !body || !state.usage) return;
    const totals = state.usage.totals || {};
    const metrics = [
      ["已開通學校", totals.enabled_schools], ["近 7 日活躍", totals.active_7d],
      ["尚未開始", totals.not_started], ["資料建置中", totals.building],
      ["已完成排課", totals.scheduled], ["已正式發布", totals.published],
      ["需關注", totals.needs_attention],
    ];
    summary.innerHTML = metrics.map(([label, value]) =>
      `<div><span>${label}</span><b>${Number(value || 0).toLocaleString("zh-TW")}</b></div>`).join("");
    body.innerHTML = (state.usage.schools || []).map((school) => {
      const events = school.events || {};
      const attention = school.attention || [];
      const progress = school.progress || "not_started";
      return `<tr><td><b>${root.esc(school.name)}</b><small>${root.esc(school.moe_code || school.school_id)}</small></td>
        <td><span class="platform-progress ${root.esc(progress)}">${root.esc(usageProgressLabel(progress))}</span></td>
        <td>${formatUsageDate(school.last_active_at)}</td>
        <td class="usage-counts">登入 ${Number(events.login || 0)}｜排課 ${Number(events.solve_success || 0)}<br>發布 ${Number(events.publish || 0)}｜教師送出 ${Number(events.teacher_save || 0)}</td>
        <td><div class="usage-attention ${attention.length ? "" : "ok"}">${attention.length ? attention.slice(0, 2).map((item) => `<span>${root.esc(item)}</span>`).join("") : "<span>目前正常</span>"}</div></td>
        <td><button class="btn soft sm" type="button" data-usage-school="${root.esc(school.school_id)}">查看</button></td></tr>`;
    }).join("") || '<tr><td colspan="6">尚無學校使用紀錄</td></tr>';
    body.querySelectorAll("[data-usage-school]").forEach((button) => {
      button.addEventListener("click", () => openUsageDetail(button.dataset.usageSchool, button));
    });
  }

  function closeUsageDetail() {
    const dialog = document.getElementById("platformUsageDetailDialog");
    if (dialog && dialog.open) dialog.close();
    if (state.usageTrigger && typeof state.usageTrigger.focus === "function") {
      state.usageTrigger.focus();
    }
  }

  function openUsageDetail(schoolId, trigger) {
    const school = (state.usage && state.usage.schools || []).find((item) => item.school_id === schoolId);
    const dialog = document.getElementById("platformUsageDetailDialog");
    if (!school || !dialog) return;
    state.usageSchoolId = schoolId;
    state.usageTrigger = trigger || document.activeElement;
    if (!dialog.dataset.usageKeyboardBound) {
      dialog.dataset.usageKeyboardBound = "true";
      dialog.addEventListener("cancel", (event) => {
        event.preventDefault();
        closeUsageDetail();
      });
      dialog.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          closeUsageDetail();
        }
      });
    }
    const details = school.case || {};
    document.getElementById("platformUsageDetailTitle").textContent = school.name;
    document.getElementById("platformUsageDetailMeta").textContent =
      `教育部代碼 ${school.moe_code || school.school_id}｜${usageProgressLabel(school.progress)}｜最後操作 ${formatUsageDate(school.last_active_at, true)}`;
    document.getElementById("platformUsageDetailSummary").innerHTML = [
      ["班級", usageCaseMetric(details, "classes")], ["教師", usageCaseMetric(details, "teachers")],
      ["科目", usageCaseMetric(details, "subjects")], ["還原點", usageCaseMetric(details, "backup_count")],
    ].map(([label, value]) => `<div><span>${label}</span><b>${value}</b></div>`).join("");
    const attention = school.attention || [];
    const attentionBox = document.getElementById("platformUsageDetailAttention");
    attentionBox.className = `usage-detail-attention ${attention.length ? "" : "ok"}`;
    attentionBox.textContent = attention.length ? `需關注：${attention.join("；")}` : "目前沒有需要處理的異常。";
    const events = school.events || {};
    const timeline = Object.entries(school.last_events || {})
      .filter(([event, value]) => USAGE_EVENT_LABELS[event] && value)
      .sort((left, right) => String(right[1]).localeCompare(String(left[1])))
      .slice(0, 10);
    document.getElementById("platformUsageTimeline").innerHTML = timeline.length ? timeline.map(([event, value]) =>
      `<div class="usage-timeline-row"><time>${root.esc(formatUsageDate(value, true))}</time><span>${root.esc(USAGE_EVENT_LABELS[event])}</span><b>近 30 日 ${Number(events[event] || 0)} 次</b></div>`).join("") :
      '<div class="backup-empty">尚無可顯示的操作紀錄。</div>';
    const editButton = document.getElementById("platformUsageEditSchoolButton");
    if (editButton) editButton.disabled = !state.schools.some((item) => item.school_id === schoolId);
    if (typeof dialog.showModal === "function") dialog.showModal();
  }

  function editUsageSchool() {
    const schoolId = state.usageSchoolId;
    closeUsageDetail();
    editSchool(schoolId);
    const field = document.getElementById("platformSchoolId");
    if (field) field.scrollIntoView({behavior: "smooth", block: "center"});
  }

  function downloadUsageCsv() {
    if (!state.usage) return;
    const rows = [["學校", "教育部代碼", "狀態", "目前進度", "最後操作", "最後登入", "最後雲端存檔",
      "最後排課完成", "最後正式發布", "最後教師送出", "班級", "教師", "科目", "還原點",
      "登入次數", "排課成功", "排課失敗", "發布次數", "教師送出", "需關注"]];
    (state.usage.schools || []).forEach((school) => {
      const events = school.events || {};
      const last = school.last_events || {};
      const details = school.case || {};
      rows.push([school.name, school.moe_code || school.school_id, school.active ? "啟用" : "停用",
        usageProgressLabel(school.progress), formatUsageDate(school.last_active_at, true),
        formatUsageDate(last.login, true), formatUsageDate(last.draft_save, true),
        formatUsageDate(last.solve_success, true), formatUsageDate(last.publish, true),
        formatUsageDate(last.teacher_save, true), usageCaseMetric(details, "classes"),
        usageCaseMetric(details, "teachers"), usageCaseMetric(details, "subjects"), usageCaseMetric(details, "backup_count"),
        Number(events.login || 0), Number(events.solve_success || 0), Number(events.solve_failed || 0),
        Number(events.publish || 0), Number(events.teacher_save || 0), (school.attention || []).join("；") || "無"]);
    });
    const csv = "\ufeff" + rows.map((row) => row.map(csvExportCell).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], {type: "text/csv;charset=utf-8"}));
    const link = document.createElement("a");
    link.href = url;
    link.download = `廣測使用概況_${new Date().toLocaleDateString("en-CA")}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function loadUsage() {
    if (state.loadingUsage) return;
    const element = document.getElementById("platformUsageStatus");
    state.loadingUsage = true;
    updateActionButtons();
    try {
      if (element) element.textContent = "正在整理近 30 日使用概況…";
      state.usage = await request("/platform/usage?days=30");
      renderUsage();
      if (element) element.textContent = "本使用概況只彙整學校、日期、角色、案件階段與操作次數；不保存姓名、Email、IP 或課表內容。";
    } catch (error) {
      if (element) element.textContent = `使用概況載入失敗：${error.message}`;
    } finally {
      state.loadingUsage = false;
      updateActionButtons();
    }
  }

  function setDraftEditingLocked(locked) {
    state.draftReady = !locked;
    if (root.setFormalEditingLocked) root.setFormalEditingLocked(locked);
    setSaveButtonsBusy(!!state.saveInFlight);
    updateTeacherCsvImportState();
    updateActionButtons();
  }

  function setSaveButtonsBusy(busy) {
    document.querySelectorAll("[data-cloud-save]").forEach((button) => {
      button.disabled = busy || !state.draftReady;
      button.textContent = busy ? "正在儲存…" : "儲存至學校雲端";
    });
    const deleteButton = document.getElementById("deleteCloudDraftButton");
    if (deleteButton) {
      deleteButton.disabled = busy || state.deletingDraft || !state.hasCloudDraft || state.sessionExpired;
      deleteButton.textContent = state.deletingDraft ? "正在刪除…" : "刪除雲端案件";
    }
    updateActionButtons();
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
    const message = "登入已逾時，請按「重新登入」後繼續；長期進度以學校雲端暫存為準。";
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
    updateActionButtons();
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
      state.hasCloudDraft = true;
      state.draftConflict = false;
      state.lastDraftHash = hash;
      const continueButton = document.getElementById("cloudContinueButton");
      if (continueButton) {
        continueButton.hidden = false;
        continueButton.textContent = "重新載入雲端案件";
      }
      element.textContent = `${manual ? "已儲存至學校雲端" : "已自動存檔"}：${new Date(result.saved_at).toLocaleString("zh-TW")}｜${result.saved_by || state.profile.email}。`;
      refreshReadiness();
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
    if (!state.profile || !state.profile.is_admin || state.loadingDraft) return;
    state.loadingDraft = true;
    updateActionButtons();
    try {
      const draft = await request("/admin/draft");
      if (!confirm(`載入 ${new Date(draft.saved_at).toLocaleString("zh-TW")} 的雲端暫存？目前畫面內容會被取代。`)) return;
      root.applyAdminDraft(draft.snapshot);
      state.draftRevision = draft.draft_revision || "";
      state.hasCloudDraft = true;
      state.draftConflict = false;
      state.activeRevision = draft.active_revision || "";
      state.updateSequence = 0;
      if (state.activeRevision) sessionStorage.setItem(userStorageKey("schedule_active_revision"), state.activeRevision);
      else sessionStorage.removeItem(userStorageKey("schedule_active_revision"));
      sessionStorage.setItem(userStorageKey("schedule_teacher_update_sequence"), "0");
      state.lastDraftHash = JSON.stringify(root.getScheduleAuthSnapshot());
      setDraftEditingLocked(false);
      const continueButton = document.getElementById("cloudContinueButton");
      const localButton = document.getElementById("localBackupButton");
      if (continueButton) continueButton.textContent = "重新載入雲端案件";
      if (localButton) localButton.hidden = true;
      document.getElementById("cloudDraftStatus").textContent = `已載入學校雲端案件：${new Date(draft.saved_at).toLocaleString("zh-TW")}｜${draft.saved_by || "管理員"}。`;
      refreshReadiness();
    } catch (error) {
      if (error.status === 404) {
        state.draftRevision = "";
        state.hasCloudDraft = false;
        state.draftConflict = false;
        setDraftEditingLocked(false);
        document.getElementById("cloudContinueButton").hidden = true;
        document.getElementById("cloudDraftStatus").textContent = "目前尚無學校雲端案件，可以開始建立新案件。";
        refreshReadiness();
      } else alert(`無法載入雲端暫存：${error.message}`);
    } finally {
      state.loadingDraft = false;
      updateActionButtons();
    }
  }

  function openDeleteDraftDialog() {
    if (!state.profile || !state.profile.is_admin || !state.hasCloudDraft || state.sessionExpired) return;
    const dialog = document.getElementById("deleteCloudDraftDialog");
    const acknowledge = document.getElementById("deleteCloudDraftAcknowledge");
    if (!dialog) return;
    if (acknowledge) acknowledge.checked = false;
    toggleDeleteDraftConfirm();
    if (typeof dialog.showModal === "function") dialog.showModal();
    else if (confirm("第一層警示：永久刪除學校雲端案件與這台電腦的本機編輯內容？已發布的教師課表會保留。")) {
      deleteDraft(true);
    }
  }

  function closeDeleteDraftDialog() {
    const dialog = document.getElementById("deleteCloudDraftDialog");
    if (dialog && dialog.open) dialog.close();
  }

  function toggleDeleteDraftConfirm() {
    const acknowledge = document.getElementById("deleteCloudDraftAcknowledge");
    const button = document.getElementById("deleteCloudDraftConfirmButton");
    if (button) button.disabled = !(acknowledge && acknowledge.checked);
  }

  async function deleteDraft(skipAcknowledgement) {
    const acknowledge = document.getElementById("deleteCloudDraftAcknowledge");
    if (!skipAcknowledgement && (!acknowledge || !acknowledge.checked)) return;
    if (!state.profile || !state.profile.is_admin || !state.hasCloudDraft ||
        state.sessionExpired || state.saveInFlight || state.deletingDraft) return;
    const schoolName = state.profile.school_name || "本校";
    const finalWarning = `最後確認：確定永久刪除「${schoolName}」目前的學校雲端案件？\n\n刪除後無法復原；已發布的教師課表會保留。`;
    if (!confirm(finalWarning)) return;

    closeDeleteDraftDialog();
    state.deletingDraft = true;
    stopSessionTimers();
    setSaveButtonsBusy(false);
    const cloudStatus = document.getElementById("cloudDraftStatus");
    if (cloudStatus) cloudStatus.textContent = "正在刪除學校雲端案件…";
    try {
      await request(`/admin/draft?expected_draft_revision=${encodeURIComponent(state.draftRevision)}`, {
        method: "DELETE",
      });
      state.hasCloudDraft = false;
      state.hasLocalBackup = false;
      state.draftRevision = "";
      state.draftConflict = false;
      state.lastDraftHash = "";
      state.activeRevision = "";
      state.updateSequence = 0;
      sessionStorage.removeItem(userStorageKey("schedule_active_revision"));
      sessionStorage.removeItem(userStorageKey("schedule_teacher_update_sequence"));
      if (root.resetFormalProjectAfterCloudDelete) root.resetFormalProjectAfterCloudDelete();
      setDraftEditingLocked(false);
      const continueButton = document.getElementById("cloudContinueButton");
      const localButton = document.getElementById("localBackupButton");
      if (continueButton) continueButton.hidden = true;
      if (localButton) localButton.hidden = true;
      if (cloudStatus) cloudStatus.textContent = "學校雲端案件已刪除；已發布的教師課表仍保留。可以建立空白案件或重新匯入 Excel。";
      const teacherStatus = document.getElementById("teacherSyncStatus");
      if (teacherStatus) teacherStatus.textContent = "目前尚未連結新案件；完成排課後可重新發布。";
      status("雲端案件已刪除，可以重新開始建置。", "ok");
      refreshReadiness();
    } catch (error) {
      if (error.status === 409) {
        state.hasCloudDraft = true;
        state.draftConflict = true;
        setDraftEditingLocked(true);
        await refreshDraftStatus();
        alert("另一位管理員已儲存較新的案件。為避免誤刪，請先重新載入最新雲端案件，再重新執行刪除。");
      } else {
        if (cloudStatus) cloudStatus.textContent = `刪除雲端案件失敗：${error.message}`;
        alert(`刪除雲端案件失敗：${error.message}`);
      }
    } finally {
      state.deletingDraft = false;
      setSaveButtonsBusy(false);
      if (!state.sessionExpired) startAdminAutomation();
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

  function closeBackups() {
    const dialog = document.getElementById("backupHistoryDialog");
    if (dialog && dialog.open) dialog.close();
  }

  function renderBackups() {
    const list = document.getElementById("backupHistoryList");
    if (!list) return;
    if (!state.backups.length) {
      list.innerHTML = '<div class="backup-empty">目前尚未建立案件還原點。</div>';
      return;
    }
    list.innerHTML = state.backups.map((backup) => {
      const summary = backup.summary || {};
      const meta = `${Number(summary.classes || 0)} 班｜${Number(summary.teachers || 0)} 位教師｜${Number(summary.subjects || 0)} 科` +
        (summary.schedule_ready ? `｜課表 ${Number(summary.scheduled_entries || 0)} 筆` : "｜尚未完成排課");
      return `<div class="backup-row"><div><b>${root.esc(summary.label || "排課案件")}</b>` +
        `<span>${root.esc(new Date(backup.created_at).toLocaleString("zh-TW"))}｜${root.esc(backup.created_by || "管理員")}</span>` +
        `<span>${root.esc(meta)}</span></div>` +
        `<button class="btn soft sm" type="button" data-restore-backup="${root.esc(backup.backup_id)}" ${state.restoringBackup ? "disabled" : ""}>還原為雲端暫存</button></div>`;
    }).join("");
    list.querySelectorAll("[data-restore-backup]").forEach((button) => {
      button.addEventListener("click", () => restoreBackup(button.dataset.restoreBackup));
    });
  }

  async function loadBackups() {
    if (!state.profile || !state.profile.is_admin || state.loadingBackups) return;
    state.loadingBackups = true;
    updateActionButtons();
    try {
      const result = await request("/admin/backups?limit=10");
      state.backups = result.backups || [];
      renderBackups();
      refreshReadiness();
    } catch (error) {
      const list = document.getElementById("backupHistoryList");
      if (list) list.innerHTML = `<div class="backup-empty">${root.esc(error.message)}</div>`;
    } finally {
      state.loadingBackups = false;
      updateActionButtons();
    }
  }

  function openBackups() {
    if (!state.profile || !state.profile.is_admin) return;
    const dialog = document.getElementById("backupHistoryDialog");
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    loadBackups();
  }

  async function createBackup() {
    if (!state.profile || !state.profile.is_admin || state.creatingBackup || state.restoringBackup) return;
    state.creatingBackup = true;
    updateActionButtons();
    try {
      await saveDraft(true);
      if (!state.hasCloudDraft || state.draftConflict) throw new Error("請先完成雲端儲存，再建立案件還原點");
      const backup = await request("/admin/backups", {method: "POST"});
      await loadBackups();
      document.getElementById("cloudDraftStatus").textContent = `已建立案件還原點：${new Date(backup.created_at).toLocaleString("zh-TW")}。`;
      status("案件還原點已建立。", "ok");
    } catch (error) {
      alert(`無法建立案件還原點：${error.message}`);
    } finally {
      state.creatingBackup = false;
      updateActionButtons();
    }
  }

  async function restoreBackup(backupId) {
    if (!backupId || state.restoringBackup || state.creatingBackup) return;
    const backup = state.backups.find((item) => item.backup_id === backupId);
    if (!backup) return;
    const summary = backup.summary || {};
    const warning = `確定將「${summary.label || "排課案件"}」還原為新的學校雲端暫存？\n\n` +
      `${Number(summary.classes || 0)} 班、${Number(summary.teachers || 0)} 位教師、${Number(summary.subjects || 0)} 科。\n` +
      "目前雲端暫存會被取代；已發布的正式教師課表不會改動。";
    if (!confirm(warning)) return;
    state.restoringBackup = true;
    updateActionButtons();
    try {
      const result = await request(`/admin/backups/${encodeURIComponent(backupId)}/restore`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({expected_draft_revision: state.draftRevision}),
      });
      root.applyAdminDraft(result.snapshot);
      state.draftRevision = result.draft_revision || "";
      state.activeRevision = result.active_revision || "";
      state.hasCloudDraft = true;
      state.draftConflict = false;
      state.lastDraftHash = JSON.stringify(root.getScheduleAuthSnapshot());
      setDraftEditingLocked(false);
      if (state.activeRevision) sessionStorage.setItem(userStorageKey("schedule_active_revision"), state.activeRevision);
      else sessionStorage.removeItem(userStorageKey("schedule_active_revision"));
      document.getElementById("cloudDraftStatus").textContent = `已從案件還原點建立新的雲端暫存：${new Date(result.restored_at).toLocaleString("zh-TW")}。`;
      closeBackups();
      status("案件已還原為新的雲端暫存；正式教師課表未變更。", "ok");
      refreshReadiness();
    } catch (error) {
      if (error.status === 409) {
        state.draftConflict = true;
        setDraftEditingLocked(true);
        alert("另一位管理員已更新雲端案件。請先載入最新案件，再重新執行還原。");
      } else alert(`案件還原失敗：${error.message}`);
    } finally {
      state.restoringBackup = false;
      updateActionButtons();
    }
  }

  async function syncTeacherUpdates() {
    if (!state.profile || !state.profile.is_admin || state.syncingUpdates) return;
    const element = document.getElementById("teacherSyncStatus");
    if (!state.activeRevision) {
      element.textContent = "發布正式課表後，可按「讀取導師存檔」取得更新。";
      return;
    }
    state.syncingUpdates = true;
    updateActionButtons();
    try {
      const query = `?revision=${encodeURIComponent(state.activeRevision)}&after=${state.updateSequence}`;
      const result = await request(`/admin/teacher-updates${query}`);
      const changed = Object.keys(result.placements || {});
      if (changed.length) {
        const preview = root.previewServerTeacherUpdates(result.placements);
        if (!preview.applied) {
          element.textContent = preview.reason || "收到導師更新，但承辦端尚未能套用。";
          return;
        }
        const approvalMap = {};
        changed.forEach((code) => { approvalMap[code] = Number((result.updates[code] || {}).sequence || 0); });
        const approved = await request("/admin/teacher-updates/approve", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({revision: result.revision, updates: approvalMap}),
        });
        const applied = root.applyServerTeacherUpdates(result.placements);
        if (!applied.applied) throw new Error(applied.reason || "承辦端未能套用已確認的導師存檔");
        element.textContent = `已確認並套用：${applied.codes.join("、")}（${new Date(approved.updated_at).toLocaleString("zh-TW")}）。`;
        state.lastDraftHash = "";
        state.updateSequence = Number(approved.update_sequence || result.update_sequence || state.updateSequence);
        sessionStorage.setItem(userStorageKey("schedule_teacher_update_sequence"), String(state.updateSequence));
        saveDraft(false);
      } else {
        element.textContent = "目前沒有等待確認的導師存檔。";
      }
    } catch (error) {
      element.textContent = error.status === 409 ? "導師存檔或正式版本已更新，請重新讀取後再確認。" : `導師課表同步失敗：${error.message}`;
    } finally {
      state.syncingUpdates = false;
      updateActionButtons();
    }
  }

  function closeVersionHistory() {
    const dialog = document.getElementById("versionHistoryDialog");
    if (dialog && dialog.open) dialog.close();
  }

  function renderVersions() {
    const list = document.getElementById("versionHistoryList");
    if (!list) return;
    if (!state.versions.length) {
      list.innerHTML = '<div class="version-history-empty">目前沒有正式版本紀錄。</div>';
      return;
    }
    list.innerHTML = state.versions.map((version, index) => {
      const current = version.revision === state.activeRevision;
      const restored = version.restored_from ? "｜由舊版還原建立" : "";
      return `<div class="version-history-row"><div><b>${current ? "目前版本" : `歷史版本 ${index + 1}`}</b>` +
        `<span>${root.esc(new Date(version.published_at).toLocaleString("zh-TW"))}｜${root.esc(version.published_by || "管理員")}${restored}</span></div>` +
        `<button class="btn soft sm" type="button" data-restore-version="${root.esc(version.revision)}" ${current || !state.draftReady || state.draftConflict ? "disabled" : ""}>還原</button></div>`;
    }).join("");
    list.querySelectorAll("[data-restore-version]").forEach((button) => {
      button.addEventListener("click", () => restoreVersion(button.dataset.restoreVersion));
    });
  }

  async function loadVersions() {
    if (!state.profile || !state.profile.is_admin || state.loadingVersions) return;
    state.loadingVersions = true;
    updateActionButtons();
    try {
      const result = await request("/admin/published-versions?limit=20");
      if (result.active_revision) {
        state.activeRevision = result.active_revision;
        sessionStorage.setItem(userStorageKey("schedule_active_revision"), state.activeRevision);
      }
      state.versions = result.versions || [];
      renderVersions();
    } catch (error) {
      document.getElementById("versionHistoryList").innerHTML = `<div class="version-history-empty">${root.esc(error.message)}</div>`;
    } finally {
      state.loadingVersions = false;
      updateActionButtons();
    }
  }

  function openVersionHistory() {
    if (!state.profile || !state.profile.is_admin) return;
    const dialog = document.getElementById("versionHistoryDialog");
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    loadVersions();
  }

  async function restoreVersion(revision) {
    if (!revision || state.restoringVersion) return;
    if (!state.draftReady || state.draftConflict) {
      alert("請先載入學校雲端案件，再執行正式版本還原。");
      return;
    }
    if (!confirm("確定還原此正式課表版本？系統會建立新的正式版本，教師目前開啟的舊版本將需要重新載入。")) return;
    state.restoringVersion = true;
    updateActionButtons();
    const versionStatus = document.getElementById("versionHistoryStatus");
    try {
      const result = await request(`/admin/published-versions/${encodeURIComponent(revision)}/restore`, {method: "POST"});
      state.activeRevision = result.revision;
      state.updateSequence = 0;
      sessionStorage.setItem(userStorageKey("schedule_active_revision"), state.activeRevision);
      sessionStorage.setItem(userStorageKey("schedule_teacher_update_sequence"), "0");
      root.applyAdminDraft(result.snapshot);
      state.lastDraftHash = "";
      await saveDraft(true);
      versionStatus.textContent = `已還原並建立新正式版本：${new Date(result.published_at).toLocaleString("zh-TW")}。`;
      status("正式課表已還原；教師重新載入後即可查看。", "ok");
      await loadVersions();
    } catch (error) {
      versionStatus.textContent = `正式版本還原失敗：${error.message}`;
    } finally {
      state.restoringVersion = false;
      updateActionButtons();
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
    if (state.savingPlacements) return;
    const submission = root.getServerTeacherSubmission();
    if (!submission) return;
    const {code, revision, placements, remaining} = submission;
    if (remaining.length) {
      alert(`尚有科目未排完：${remaining.map((item) => `${item[0]} ${item[1]}節`).join("、")}`);
      return;
    }
    state.savingPlacements = true;
    updateActionButtons();
    try {
      status("正在儲存課表調整…", "working");
      await request(`/teacher/classes/${encodeURIComponent(code)}/placements`, {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({revision, placements}),
      });
      status(`${code} 調整已送出，等待排課承辦人確認。`, "ok");
      alert("課表調整已送出；承辦人確認前，正式課表仍維持上一版。");
      await loadWorkspace();
    } catch (error) {
      status(error.message, "error");
      alert(`無法儲存：${error.message}`);
    } finally {
      state.savingPlacements = false;
      updateActionButtons();
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

  root.ScheduleAuth = {initialize, solveData, importTeacherCsv, importTeacherRecords, downloadTeacherCsvTemplate, updateTeacherCsvImportState, updateActionButtons, getReadinessState,
    publishCurrent, saveDraft, loadDraft, useLocalBackup, queueDraftSave,
    openDeleteDraftDialog, closeDeleteDraftDialog, toggleDeleteDraftConfirm, deleteDraft,
    openBackups, closeBackups, loadBackups, createBackup, restoreBackup,
    syncTeacherUpdates, openVersionHistory, closeVersionHistory, loadVersions, restoreVersion,
    savePlacements, loadSchools, loadUsage, downloadUsageCsv, openUsageDetail, closeUsageDetail, editUsageSchool,
    saveSchool, editSchool, newSchool, logout};
}(typeof globalThis !== "undefined" ? globalThis : window));
