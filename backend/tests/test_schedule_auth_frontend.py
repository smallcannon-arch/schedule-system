import subprocess
import json
import pytest

from support_paths import FORMAL, ONLINE, SEPARATE_DEMO


def test_google_teacher_portal_assets_and_views_are_wired():
    html = (ONLINE / "index.html").read_text(encoding="utf-8")

    assert 'id="googleSignInButton"' in html
    assert 'id="myScheduleTable"' in html
    assert 'data-v="my"' in html
    assert 'src="schedule-auth.js' in html
    assert "openServerTeacherPackage" in html
    assert "getServerTeacherSubmission" in html
    assert 'id="cloudDraftStatus"' in html
    assert 'id="teacherSyncStatus"' in html
    assert "applyServerTeacherUpdates" in html


def test_auth_config_does_not_contain_credentials():
    config = (ONLINE / "auth-config.js").read_text(encoding="utf-8")

    assert "apiBaseUrl:" in config
    assert "client_secret" not in config.lower()
    assert "private_key" not in config.lower()


def test_schedule_auth_javascript_has_valid_syntax():
    subprocess.run(
        ["node", "--check", str(ONLINE / "schedule-auth.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_formal_release_check_bypasses_cached_homepage():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script_text = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")
    app_config = (FORMAL / "app-config.js").read_text(encoding="utf-8")
    workflow = (FORMAL / ".github" / "workflows" / "verify-and-deploy.yml").read_text(
        encoding="utf-8")

    assert 'release: "__APP_RELEASE__"' in app_config
    assert 'onclick="ScheduleAuth.reloadLatest()">載入最新版' in html
    assert 'schedule-auth.js?v=20260716-3' in html
    assert 'new URL("release.json", root.location.href)' in script_text
    assert '{cache: "no-store"}' in script_text
    assert 'root.setInterval(checkForUpdates, 5 * 60 * 1000)' in script_text
    assert 'url.searchParams.set("release"' in script_text
    assert 'sed -i "s/__APP_RELEASE__/${GITHUB_SHA}/g"' in workflow
    assert '_site/release.json' in workflow

    script = r"""
const fs=require('fs'),vm=require('vm');
const assigned=[];
const context={URL,location:{href:'https://smallcannon-arch.github.io/schedule-system/',assign:value=>assigned.push(value)},
  confirm:()=>true,setInterval,clearInterval};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
context.ScheduleAuth.reloadLatest();
process.stdout.write(JSON.stringify(assigned));
"""
    result = subprocess.run(
        ["node", "-e", script, str(FORMAL / "schedule-auth.js")],
        check=True, capture_output=True, text=True, encoding="utf-8")
    assigned = json.loads(result.stdout)
    assert len(assigned) == 1
    assert assigned[0].startswith(
        "https://smallcannon-arch.github.io/schedule-system/?release=")


def test_local_file_login_points_to_hosted_formal_site():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert 'id="formalHostedLink"' in html
    assert 'href="https://smallcannon-arch.github.io/schedule-system/"' in html
    assert 'root.location.protocol === "file:"' in script
    assert "本機檔案" in script
    assert 'hostedLink.hidden = false' in script

    node_script = r"""
const fs=require('fs'),vm=require('vm');
const elements={formalAuthStatus:{textContent:'',dataset:{}},formalHostedLink:{hidden:true}};
const context={SCHEDULE_APP_CONFIG:{mode:'formal'},location:{protocol:'file:'},
  document:{getElementById:id=>elements[id]||null},console};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
context.ScheduleAuth.initialize().then(()=>process.stdout.write(JSON.stringify({
  status:elements.formalAuthStatus.textContent,kind:elements.formalAuthStatus.dataset.kind,
  linkHidden:elements.formalHostedLink.hidden
})));
"""
    result = subprocess.run(
        ["node", "-e", node_script, str(FORMAL / "schedule-auth.js")],
        check=True, capture_output=True, text=True, encoding="utf-8")
    output = json.loads(result.stdout)
    assert "本機檔案" in output["status"]
    assert output["kind"] == "error"
    assert output["linkHidden"] is False


@pytest.mark.skipif(not SEPARATE_DEMO, reason="monorepo contains the formal frontend only")
def test_admin_autosave_and_teacher_auto_import_are_wired():
    script = (ONLINE / "schedule-auth.js").read_text(encoding="utf-8")

    assert 'setInterval(() => saveDraft(false), 30000)' in script
    assert 'setInterval(syncTeacherUpdates, 10000)' in script
    assert 'request("/admin/draft"' in script
    assert 'request(`/admin/teacher-updates${query}`)' in script
    assert "承辦端會自動匯入" in script
    assert "authorizationHeaders" in script


@pytest.mark.skipif(not SEPARATE_DEMO, reason="monorepo contains the formal frontend only")
def test_demo_progress_download_contains_full_schedule_state():
    html = (ONLINE / "index.html").read_text(encoding="utf-8")
    app_config = (ONLINE / "app-config.js").read_text(encoding="utf-8")

    assert 'mode: "demo"' in app_config
    assert "下載工作進度" in html
    assert "載入工作進度" in html
    assert "schedule-demo-progress-v2" in html
    assert "...snapshot" in html
    assert "30 天內可回來繼續" in html
    assert "const LSKEY=APP_MODE==='formal'?'schedule_formal_local_v1':'schedule_demo_progress_v2'" in html


def test_google_identity_script_loads_only_in_formal_mode():
    html = (ONLINE / "index.html").read_text(encoding="utf-8")
    script = (ONLINE / "schedule-auth.js").read_text(encoding="utf-8")

    assert '<script src="https://accounts.google.com/gsi/client"' not in html
    assert 'if ((root.SCHEDULE_APP_CONFIG || {}).mode !== "formal") return;' in script
    assert 'script.src = "https://accounts.google.com/gsi/client"' in script


def test_formal_bundle_is_separate_and_login_gated():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    config = (FORMAL / "app-config.js").read_text(encoding="utf-8")

    assert 'mode: "formal"' in config
    assert 'class="formal-gate formal-only"' in html
    assert "formal-locked" in html
    assert "if(APP_MODE==='formal')applyData(emptyFormalData(),'尚未載入學校資料')" in html
    assert "schedule_formal_local_v2" in html
    assert "setFormalStorageIdentity(profile)" in html
    assert "currentLocalStorageKey()" in html
    assert (FORMAL / "schedule-auth.js").is_file()
    assert (FORMAL / "auth-config.js").is_file()


def test_formal_editor_lists_every_class_and_teacher_in_selects():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")

    assert '<select class="edit" id="editClassSearch"' in html
    assert '<select class="edit" id="editTeacherSearch"' in html
    assert 'value="${esc(c.code)}"' in html
    assert 'list="editClassList"' not in html


def test_formal_browser_backup_is_scoped_to_school_account_and_cleared_on_logout():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert "FORMAL_KEY_PREFIX='schedule_formal_local_v2:'" in html
    assert "APP_MODE==='formal'?sessionStorage:localStorage" in html
    assert "purgeLegacyFormalBackups()" in html
    assert "if(FORMAL_LSKEY)sessionStorage.removeItem(FORMAL_LSKEY)" in html
    assert "window.setFormalStorageIdentity=setFormalStorageIdentity" in html
    assert "window.clearFormalSessionData=clearFormalSessionData" in html
    assert "root.setFormalStorageIdentity(state.profile)" in script
    assert "root.clearFormalSessionData()" in script
    assert 'state.profile = null' in script


def test_formal_solver_uses_only_configured_api_and_does_not_export_bearer_token():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert 'id="formalApiUrl"' not in html
    assert 'id="formalApiKey"' not in html
    assert "ScheduleAuth.solveData(payload)" in html
    assert "function authorizationHeaders" not in script
    assert "root.ScheduleAuth = {initialize, reloadLatest, solveData" in script


def test_formal_shared_cloud_draft_has_clear_save_and_conflict_protection():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert "儲存至學校雲端" in html
    assert "繼續上次雲端案件" in html
    assert 'id="clearProjectDialog"' in html
    assert "不會刪除學校雲端暫存" in html
    assert "expected_draft_revision" in script
    assert "draftConflict" in script
    assert "saveInFlight" in script
    assert "useLocalBackup" in script
    assert "setFormalEditingLocked" in html
    assert 'id="localBackupButton"' in html
    assert "setTimeout(() => saveDraft(false), 10000)" in script
    assert "state.autoSaveInterval = setInterval(() => saveDraft(false), 60000)" in script


def test_formal_cloud_draft_delete_has_two_warnings_and_preserves_published_schedule():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert 'id="deleteCloudDraftButton"' in html
    assert 'id="deleteCloudDraftDialog"' in html
    assert 'id="deleteCloudDraftAcknowledge"' in html
    assert "前往最後確認" in html
    assert "不會刪除已發布給教師查看的正式課表" in html
    assert "最後確認：確定永久刪除" in script
    assert "expected_draft_revision=${encodeURIComponent(state.draftRevision)}" in script
    assert 'method: "DELETE"' in script
    assert "root.resetFormalProjectAfterCloudDelete()" in script
    assert "window.resetFormalProjectAfterCloudDelete=resetFormalProjectAfterCloudDelete" in html


def test_teacher_csv_template_remains_available_but_import_locks_after_case_start():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert "下載教師帳號 CSV 範本" in html
    assert 'class="btn soft sm always-available"' in html
    assert 'id="teacherCsvImportButton"' in html
    assert 'id="teacherCsvImportInput"' in html
    assert 'id="teacherCsvImportHint"' in html
    assert "downloadTeacherCsvTemplate" in script
    assert 'link.download = "教師帳號匯入範本.csv"' in script
    assert 'const setupStarted = !document.body.classList.contains("setup-pending")' in script
    assert "state.hasCloudDraft" in script
    assert "input.disabled = locked" in script
    assert "案件已開始編輯，批次匯入已鎖定" in script
    assert "同步教師登入名冊" in script
    assert "ScheduleAuth.updateTeacherCsvImportState" in html


def test_formal_session_expiry_stops_autosave_and_locks_editing():
    script = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert "function handleSessionExpired()" in script
    assert "response.status === 401 && state.profile" in script
    assert "clearInterval(state.autoSaveInterval)" in script
    assert "登入已逾時" in script
    assert 'logoutButton.textContent = "重新登入"' in script
    assert "state.sessionExpired || state.draftConflict" in script


def test_platform_admin_usage_overview_is_wired_without_personal_fields():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert 'id="platformUsageSummary"' in html
    assert 'id="platformUsageList"' in html
    assert 'id="platformUsageExportButton"' in html
    assert 'id="platformUsageDetailDialog"' in html
    assert "不保存姓名、Email、IP 或課表內容" in html
    assert 'request("/platform/usage?days=30")' in script
    assert "loadUsage" in script
    assert "downloadUsageCsv" in script
    assert "openUsageDetail" in script
    assert "usageProgressLabel" in script
    assert "csvExportCell" in script
    assert '["已開通學校", totals.enabled_schools]' in script
    assert 'unknown: "無法取得"' in script
    assert 'return details.metadata_unavailable ? "—"' in script
    assert 'usageCaseMetric(details, "classes")' in script
    assert script.count('usageCaseMetric(details, "backup_count")') == 2
    assert ".platform-progress.unknown" in html
    assert 'if (typeof dialog.showModal === "function") dialog.showModal();' in script
    assert 'openUsageDetail(button.dataset.usageSchool, button)' in script
    assert 'dialog.addEventListener("cancel"' in script
    assert 'event.key === "Escape"' in script
    assert 'state.usageTrigger.focus()' in script


def test_beta_feedback_button_does_not_collapse_into_vertical_text():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")

    assert ".beta-feedback-notice .btn,.formal-beta-feedback .btn" in html
    assert "min-width:96px;white-space:nowrap" in html


def test_formal_network_errors_are_localized_and_school_save_status_persists():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert '<script src="app-config.js?v=20260716-1"></script>' in html
    assert "目前無法連線至雲端服務，請確認網路後重新整理再試。" in script
    assert "目前無法連線至排課引擎，請確認網路後再試。" in script
    assert "async function loadSchools(statusMessage)" in script
    assert "statusMessage || `共 ${state.schools.length} 間學校。`" in script
    assert "await loadSchools(`${payload.name}（${schoolCode}）已儲存。`);" in script


def test_formal_network_action_buttons_prevent_duplicate_submissions():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    for button_id in [
        "publishScheduleButton", "syncTeacherUpdatesButton", "versionHistoryButton",
        "platformUsageRefreshButton", "platformSchoolSaveButton",
        "teacherPlacementSaveButton",
    ]:
        assert f'id="{button_id}"' in html
    assert "function updateActionButtons()" in script
    assert "if (state.publishing) return" in script
    assert "state.syncingUpdates) return" in script
    assert "if (state.loadingUsage) return" in script
    assert "if (state.savingSchool) return" in script
    assert "if (state.savingPlacements) return" in script
    assert "state.loadingDraft" in script
    assert 'publish.textContent = state.publishing ? "正在發布…"' in script
    assert 'sync.textContent = state.syncingUpdates ? "正在讀取…"' in script


def test_teacher_updates_require_admin_approval_and_versions_can_be_restored():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert 'id="versionHistoryDialog"' in html
    assert 'id="versionHistoryList"' in html
    assert "previewServerTeacherUpdates" in html
    assert 'request("/admin/teacher-updates/approve"' in script
    assert "等待排課承辦人確認" in script
    assert 'request("/admin/published-versions?limit=20")' in script
    assert "/admin/published-versions/${encodeURIComponent(revision)}/restore" in script
    assert "還原會建立一個新的正式版本" in html


def test_beta_feedback_collects_diagnostics_without_background_upload():
    html = (FORMAL / "index.html").read_text(encoding="utf-8")
    script = (FORMAL / "feedback.js").read_text(encoding="utf-8")

    assert 'id="feedbackDialog"' in html
    assert 'id="feedbackSummary"' in html
    assert 'id="feedbackSteps"' in html
    assert 'id="feedbackPrivacy"' in html
    assert "BETA 廣測中" in html
    assert "複製回報內容" in html
    assert "開啟 Email" in html
    assert "系統版本" in script
    assert "操作頁面" in script
    assert "使用角色" in script
    assert "navigator.userAgent" in script
    assert "mailto:" in script
    assert "fetch(" not in script
    assert "XMLHttpRequest" not in script


def test_platform_school_save_validates_workspace_admin_accounts():
    script = (FORMAL / "schedule-auth.js").read_text(encoding="utf-8")

    assert "請填寫至少一個 Google Workspace 網域" in script
    assert "請填寫至少一位排課管理員帳號" in script
    assert "管理員帳號格式不正確" in script
    assert "管理員帳號必須使用已填寫的 Workspace 網域" in script
