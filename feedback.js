(function (root) {
  "use strict";

  const REPORT_EMAIL = "chihhung1988@gmail.com";

  function field(id) {
    return document.getElementById(id);
  }

  function currentPage() {
    if (document.body.classList.contains("formal-locked")) return "Google 登入畫面";
    const activeNav = document.querySelector("aside nav button.on");
    if (activeNav) return activeNav.textContent.trim().replace(/\s+/g, " ");
    const heading = document.querySelector(".view.on h1");
    return heading ? heading.textContent.trim() : "未辨識頁面";
  }

  function currentRole() {
    if (document.body.classList.contains("platform-admin-mode")) return "平台總管理員";
    if (document.body.classList.contains("teacher-mode") || document.body.classList.contains("signed-teacher")) return "教師";
    const adminActions = field("googleAdminActions");
    if (adminActions && !adminActions.hidden) return "學校系統管理員";
    return "未登入";
  }

  function environmentText() {
    const version = String((root.SCHEDULE_APP_CONFIG || {}).version || "未知");
    return [
      `系統版本：${version}`,
      `操作頁面：${currentPage()}`,
      `使用角色：${currentRole()}`,
      `發生時間：${new Date().toLocaleString("zh-TW", {hour12: false})}`,
      `畫面尺寸：${root.innerWidth || 0} x ${root.innerHeight || 0}`,
      `瀏覽器：${navigator.userAgent}`,
    ].join("\n");
  }

  function reportValues() {
    return {
      type: field("feedbackType").value,
      summary: field("feedbackSummary").value.trim(),
      steps: field("feedbackSteps").value.trim(),
      result: field("feedbackResult").value.trim(),
      acknowledged: field("feedbackPrivacy").checked,
      environment: field("feedbackEnvironment").textContent.trim(),
    };
  }

  function isValid(showMessage) {
    const values = reportValues();
    const valid = values.summary.length >= 4 && values.steps.length >= 5 && values.acknowledged;
    field("feedbackCopyButton").disabled = !valid;
    field("feedbackEmailButton").disabled = !valid;
    if (showMessage && !valid) {
      field("feedbackStatus").textContent = "請填寫問題摘要與操作步驟，並確認內容不含敏感個資。";
    }
    return valid;
  }

  function reportText() {
    const values = reportValues();
    return [
      "國民小學課務排程輔助系統 BETA 問題回報",
      "",
      `問題類型：${values.type}`,
      `問題摘要：${values.summary}`,
      "",
      "操作步驟：",
      values.steps,
      "",
      "實際結果／錯誤訊息：",
      values.result || "未填寫",
      "",
      "系統環境：",
      values.environment,
      "",
      "請在寄信時另行附上問題畫面截圖；請勿附上含學生或教師敏感個資的完整資料檔。",
    ].join("\n");
  }

  function open() {
    const dialog = field("feedbackDialog");
    if (!dialog) return;
    field("feedbackEnvironment").textContent = environmentText();
    field("feedbackStatus").textContent = "回報內容只會在您選擇複製或開啟 Email 時產生，不會自動上傳。";
    isValid(false);
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    setTimeout(() => dialog.focus(), 0);
  }

  function close() {
    const dialog = field("feedbackDialog");
    if (!dialog) return;
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  function update() {
    isValid(false);
  }

  function fallbackCopy(text) {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const copied = document.execCommand("copy");
    area.remove();
    return copied;
  }

  async function copy() {
    if (!isValid(true)) return;
    const text = reportText();
    try {
      if (navigator.clipboard && root.isSecureContext) await navigator.clipboard.writeText(text);
      else if (!fallbackCopy(text)) throw new Error("copy failed");
      field("feedbackStatus").textContent = "回報內容已複製，可貼到 Email 或通訊軟體並附上截圖。";
    } catch (_) {
      field("feedbackStatus").textContent = "無法自動複製，請改用「開啟 Email」。";
    }
  }

  function email() {
    if (!isValid(true)) return;
    const values = reportValues();
    const subject = `[排課輔助系統 BETA][${values.type}] ${values.summary}`;
    field("feedbackStatus").textContent = "正在開啟 Email；請寄出前附上問題畫面截圖。";
    root.location.href = `mailto:${REPORT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(reportText())}`;
  }

  root.ScheduleFeedback = {open, close, update, copy, email};
}(typeof globalThis !== "undefined" ? globalThis : window));
