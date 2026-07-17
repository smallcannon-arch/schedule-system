(function configureScheduleApp(root) {
  const assetVersion = "20260717-3";
  const source = document.currentScript && document.currentScript.src;
  const requestedVersion = source ? new URL(source, document.baseURI).searchParams.get("v") : "";
  const assetMismatch = !!requestedVersion && requestedVersion !== assetVersion;

  root.SCHEDULE_APP_CONFIG = {
    mode: "formal",
    version: "1.28",
    release: "__APP_RELEASE__",
    assetVersion,
    assetMismatch,
  };

  if (assetMismatch) {
    root.addEventListener("DOMContentLoaded", () => {
      const notice = document.getElementById("appVersionNotice");
      const message = document.getElementById("appVersionMessage");
      if (!notice || !message) return;
      message.textContent = "網站頁面已有新版。請先儲存目前進度，再載入最新版。";
      notice.hidden = false;
    }, {once: true});
  }
})(window);
