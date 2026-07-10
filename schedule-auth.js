(function (root) {
  "use strict";

  const state = {credential: "", profile: null, workspace: null, apiBaseUrl: "",
    activeRevision: "", updateSequence: 0, lastDraftHash: "", automationStarted: false};

  function apiBaseUrl() {
    const configured = String((root.SCHEDULE_AUTH_CONFIG || {}).apiBaseUrl || "").trim();
    if (configured) return configured.replace(/\/$/, "");
    if (["127.0.0.1", "localhost"].includes(location.hostname)) return "http://127.0.0.1:8766";
    return "";
  }

  function status(message, kind) {
    ["googleAuthStatus", "formalAuthStatus"].forEach((id) => {
      const element = document.getElementById(id);
      if (!element) return;
      element.textContent = message;
      element.dataset.kind = kind || "";
    });
  }

  function userStorageKey(name) {
    return `${name}:${(state.profile && state.profile.email) || "anonymous"}`;
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
      throw error;
    }
    return payload;
  }

  function roleLabel(role) {
    return ({admin: "排課管理員", homeroom_teacher: "導師", subject_teacher: "科任教師",
      resource_teacher: "資源班教師"})[role] || "教師";
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
          const suffix = item.source === "overlay" ? "・資源班" : "";
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
    document.getElementById("teacherProfile").textContent = `${workspace.profile.name}｜${roleLabel(workspace.profile.role)}`;
    if (workspace.editable_classes && workspace.editable_classes.length) {
      root.openServerTeacherPackage(workspace.editable_classes[0]);
    }
    if (root.enterFormalTeacherMode) root.enterFormalTeacherMode();
    root.go("my");
  }

  async function handleCredential(response) {
    try {
      status("正在確認學校帳號…", "working");
      state.credential = response.credential || "";
      state.profile = await request("/auth/me");
      document.getElementById("googleAdminActions").hidden = !state.profile.is_admin;
      if (state.profile.is_admin) {
        if (root.enterFormalAdminMode) root.enterFormalAdminMode();
        document.getElementById("teacherProfile").textContent = `${state.profile.name}｜排課管理員`;
        state.activeRevision = localStorage.getItem(userStorageKey("schedule_active_revision")) || "";
        state.updateSequence = Number(localStorage.getItem(userStorageKey("schedule_teacher_update_sequence")) || 0);
        status("管理員已登入；雲端暫存與導師結果同步已啟動。", "ok");
        await refreshDraftStatus();
        startAdminAutomation();
      } else {
        await loadWorkspace();
        status("已載入您的正式課表。", "ok");
      }
      document.getElementById("googleLogoutButton").hidden = false;
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
      root.google.accounts.id.renderButton(gateTarget, {
        type: "standard", theme: "outline", size: "large", text: "signin_with", shape: "rectangular",
      });
      status(config.workspace_domain ? `請使用 @${config.workspace_domain} 學校帳號登入。` : "請使用學校 Google 帳號登入。", "ready");
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

  async function publishCurrent() {
    try {
      const snapshot = root.getScheduleAuthSnapshot();
      if (!snapshot || !snapshot.sol) throw new Error("請先完成排課，再發布正式課表");
      status("正在發布教師課表…", "working");
      const result = await request("/admin/publish", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(snapshot),
      });
      state.activeRevision = result.revision;
      state.updateSequence = Number(result.update_sequence || 0);
      localStorage.setItem(userStorageKey("schedule_active_revision"), state.activeRevision);
      localStorage.setItem(userStorageKey("schedule_teacher_update_sequence"), String(state.updateSequence));
      document.getElementById("teacherSyncStatus").textContent = "已開始接收導師送出的課表調整。";
      status(`正式課表已發布（${new Date(result.published_at).toLocaleString("zh-TW")}）。`, "ok");
    } catch (error) {
      status(error.message, "error");
    }
  }

  async function refreshDraftStatus() {
    const element = document.getElementById("cloudDraftStatus");
    try {
      const draft = await request("/admin/draft");
      element.textContent = `最近雲端暫存：${new Date(draft.saved_at).toLocaleString("zh-TW")}。`;
    } catch (error) {
      element.textContent = error.status === 404 ? "目前尚無雲端暫存；修改後每 30 秒自動保存。" : `無法讀取雲端暫存：${error.message}`;
    }
  }

  async function saveDraft(manual) {
    if (!state.profile || !state.profile.is_admin) return;
    const element = document.getElementById("cloudDraftStatus");
    try {
      const snapshot = root.getScheduleAuthSnapshot();
      if (!snapshot || !snapshot.data) throw new Error("目前沒有可暫存的排課資料");
      if (!manual && String(snapshot.label || "").includes("示範")) {
        element.textContent = "示範資料不會自動存入正式雲端暫存。";
        return;
      }
      const hash = JSON.stringify(snapshot);
      if (!manual && hash === state.lastDraftHash) return;
      element.textContent = "正在保存雲端暫存…";
      const result = await request("/admin/draft", {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({...snapshot, active_revision: state.activeRevision}),
      });
      state.lastDraftHash = hash;
      element.textContent = `已自動暫存：${new Date(result.saved_at).toLocaleString("zh-TW")}。`;
    } catch (error) {
      element.textContent = `雲端暫存失敗：${error.message}`;
      if (manual) alert(element.textContent);
    }
  }

  async function loadDraft() {
    if (!state.profile || !state.profile.is_admin) return;
    try {
      const draft = await request("/admin/draft");
      if (!confirm(`載入 ${new Date(draft.saved_at).toLocaleString("zh-TW")} 的雲端暫存？目前畫面內容會被取代。`)) return;
      root.applyAdminDraft(draft.snapshot);
      state.activeRevision = draft.active_revision || "";
      state.updateSequence = 0;
      if (state.activeRevision) localStorage.setItem(userStorageKey("schedule_active_revision"), state.activeRevision);
      else localStorage.removeItem(userStorageKey("schedule_active_revision"));
      localStorage.setItem(userStorageKey("schedule_teacher_update_sequence"), "0");
      state.lastDraftHash = JSON.stringify(root.getScheduleAuthSnapshot());
      document.getElementById("cloudDraftStatus").textContent = `已載入雲端暫存：${new Date(draft.saved_at).toLocaleString("zh-TW")}。`;
      await syncTeacherUpdates();
    } catch (error) {
      alert(`無法載入雲端暫存：${error.message}`);
    }
  }

  async function syncTeacherUpdates() {
    if (!state.profile || !state.profile.is_admin) return;
    const element = document.getElementById("teacherSyncStatus");
    if (!state.activeRevision) {
      element.textContent = "發布正式課表後，導師完成結果會自動匯入。";
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
        element.textContent = `已自動匯入：${applied.codes.join("、")}（${new Date(result.updated_at).toLocaleString("zh-TW")}）。`;
        state.lastDraftHash = "";
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
    setInterval(() => saveDraft(false), 30000);
    setInterval(syncTeacherUpdates, 10000);
    syncTeacherUpdates();
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
      status(`${code} 課表已儲存，承辦端會自動匯入。`, "ok");
      alert("課表調整已儲存，承辦端會自動匯入，不需另外傳檔。");
      await loadWorkspace();
    } catch (error) {
      status(error.message, "error");
      alert(`無法儲存：${error.message}`);
    }
  }

  function logout() {
    state.credential = "";
    if (root.google && root.google.accounts && root.google.accounts.id) root.google.accounts.id.disableAutoSelect();
    location.reload();
  }

  root.ScheduleAuth = {initialize, authorizationHeaders, importTeacherCsv, publishCurrent, saveDraft, loadDraft,
    syncTeacherUpdates, savePlacements, logout};
}(typeof globalThis !== "undefined" ? globalThis : window));
