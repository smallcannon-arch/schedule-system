# 排課輔助系統 v1.24「使用概況」審查修正資料

## 1. 專案背景簡述

本專案是提供臺灣國民小學使用的課務排程輔助系統，主要以 OR-Tools CP-SAT 執行排課求解，並提供學校案件建置、雲端暫存、備份還原、正式發布、導師自排與教師課表瀏覽等功能。

系統前端為 GitHub Pages 靜態網站，後端使用 FastAPI 並部署於 Google Cloud Run，正式資料存放於 Firestore。平台總管理員可管理已開通學校，並查看經過資料最小化處理的「使用概況」；該畫面不應回傳教師姓名、Email、IP、課表內容或案件快照。

本次工作承接 v1.24「使用概況」功能的外部 AI 審查清單，僅修正直接相關的正確性、錯誤狀態、資料隱私、Firestore 查詢與鍵盤操作問題。

## 2. 本次修改目的

1. 確認前後端統計契約一致，摘要使用 `enabled_schools`，不把停用學校誤算為已開通。
2. 讓 Firestore `backup_count` 回傳精確值，不再受 `limit(10)` 截斷，也不讀取備份快照內容。
3. 案件 metadata 讀取失敗時顯示「無法取得」與 `—`，避免將未知資料誤呈現為 0 或尚未開始。
4. 已發布後若另有較新草稿，維持「已發布」主階段，但清楚提示「有未發布草稿變更」。
5. 修正空 overview、school ID 格式差異與單校讀取失敗時的穩定性。
6. 限制舊版 draft fallback 查詢範圍，降低無界限掃描風險。
7. 補足事件白名單、最後事件時間、時區、隱私輸出鍵與原生 dialog 鍵盤操作測試。
8. 嚴守審查範圍，不新增 Firestore summary 文件、migration/backfill、廣泛 async、Dashboard 重做、dialog polyfill 或 CSV 策略改造。

## 3. 修改檔案清單

| 檔案 | 修改內容 |
| --- | --- |
| `backend/app.py` | `/platform/usage` 統一正規化 school ID、略過空 ID，保留單校錯誤隔離。 |
| `backend/schedule_store.py` | Firestore 還原點改用 count aggregation；舊 draft fallback 改為依時間排序且最多讀取 20 筆。 |
| `backend/usage_tracker.py` | 集中 school ID 正規化；補上空 overview、unknown 狀態、未發布變更與錯誤優先提示。 |
| `schedule-auth.js` | unknown 顯示、metadata 空值顯示 `—`、CSV 一致化、dialog Esc 關閉與焦點還原。 |
| `index.html` | unknown 進度標籤使用中性灰色樣式。 |
| `backend/tests/test_usage_tracking.py` | 新增統計契約、Firestore 查詢、錯誤隔離、時間、隱私與 01–12 相關測試。 |
| `backend/tests/test_schedule_auth_frontend.py` | 新增前端統計欄位、unknown、`—`、CSV 與 dialog 鍵盤 wiring 測試。 |
| `AI_REVIEW_USAGE_OVERVIEW_FIXES.md` | 本審查交付文件，不屬於執行程式。 |

## 4. 重要修改摘要

### 後端正確性與穩定性

- 新增共用 `normalize_school_id()`，在 usage 彙整、事件記錄、API 案件查詢及 enrich lookup 一致執行 `str()`、`strip()`、`lower()`。
- `enrich_overview({})` 現在會穩定回傳 `schools: []`，不再因最後排序發生 `KeyError`。
- 單校案件 metadata 失敗時：
  - 進度為 `unknown`，不計入 `not_started`、`building`、`scheduled` 或 `published`。
  - 第一則提醒固定為「案件狀態暫時無法取得」。
  - 不再根據缺失資料產生「尚未建立還原點」等假性提醒。
  - 仍保留該校已知的登入／活動時間與單校錯誤隔離。
- 同時存在正式版本與草稿時，若 `draft_saved_at > published_at`，案件增加 `has_unpublished_changes: true` 及「有未發布草稿變更」提醒；主階段仍維持 `published`。

### Firestore 查詢

- 還原點數量改用 Firestore count aggregation，12 筆會精確回傳 12，不再被上限 10 截斷。
- 計數查詢不呼叫 backup collection 的 `stream()`，因此不會下載或解碼 `snapshot_json`。
- 舊版 draft fallback 改為依 `saved_at` 由新到舊，最多掃描 20 筆，找到第一筆有效快照後停止。
- 未新增 `case_summary` 文件，未修改 save、publish、backup 寫入流程。

### 前端呈現與操作

- 新增「無法取得」進度文字與中性灰色樣式。
- metadata 無法取得時，詳情與 CSV 的班級、教師、科目、還原點統一輸出 `—`，不誤顯示 0。
- 原生 `<dialog>` 保持使用 `showModal()`；補上 `cancel`／Escape 關閉處理及關閉後回到原「查看」按鈕的焦點。
- 未加入 dialog polyfill 或自製 focus trap。

### 01–12 審查項目結論

| 項目 | 狀態 | 結論 |
| --- | --- | --- |
| 01 | 已查證並補測試 | API 與前端均使用 `totals.enabled_schools`；`configured_schools` 保留原語意。 |
| 02 | 已修正 | Firestore 使用 count aggregation，12 筆回傳 12，且不讀取備份快照。 |
| 03 | 已修正 | metadata 失敗改為 unknown、`—` 與錯誤優先提示；單校失敗不影響其他學校。 |
| 04 | 已修正 | 較新草稿會標記未發布變更，主階段仍為已發布。 |
| 05 | 已修正 | 空 overview 穩定回傳空 schools 與 0 統計。 |
| 06 | 已修正 | school ID 在記錄、彙整、API 與 lookup 使用同一正規化規則。 |
| 07 | 已修正 | legacy draft fallback 已排序、限量 20 筆並提早停止；未擴增 summary 架構。 |
| 08 | 已查證並補測試 | 動態 `last_{event}_at` 欄位只會在 event 通過白名單後建立。 |
| 09 | 已查證並補測試 | 有效事件會同時將 `last_{event}_at` 寫入 summary 與 daily。 |
| 10 | 已查證並補測試 | naive datetime、timezone-aware datetime、Firestore timestamp 與 daily fallback 均可安全轉換。 |
| 11 | 已做最小修正 | 保留原生 dialog，補 Escape／cancel 與焦點還原；瀏覽器自動化仍有一項人工複核建議。 |
| 12 | 已補測試 | API school/case 輸出採精確 key 白名單，確認不含 Email、label、snapshot 等敏感欄位。 |

## 5. Git Diff

### 審查基準

- Repository: `smallcannon-arch/schedule-system`
- Branch: `codex/usage-review-fixes`
- Base commit: `c093125cc6553fb6517f3111853b287805ba84af`
- Fix commit: `936c039b9561321e05c7674aa9240e01b4334563`
- Commit message: `Harden platform usage overview`

### Diff 統計

```text
 backend/app.py                               |   4 +-
 backend/schedule_store.py                    |  15 +-
 backend/tests/test_schedule_auth_frontend.py |  11 +
 backend/tests/test_usage_tracking.py         | 298 ++++++++++++++++++++++++++-
 backend/usage_tracker.py                     |  64 ++++--
 index.html                                   |   2 +-
 schedule-auth.js                             |  36 +++-
 7 files changed, 392 insertions(+), 38 deletions(-)
```

### 完整逐行 Diff

- GitHub commit: <https://github.com/smallcannon-arch/schedule-system/commit/936c039b9561321e05c7674aa9240e01b4334563>
- Raw diff: <https://github.com/smallcannon-arch/schedule-system/commit/936c039b9561321e05c7674aa9240e01b4334563.diff>

本機可使用：

```bash
git diff c093125cc6553fb6517f3111853b287805ba84af 936c039b9561321e05c7674aa9240e01b4334563
git show --no-ext-diff --unified=3 936c039b9561321e05c7674aa9240e01b4334563
```

## 6. 已執行的測試與結果

### 直接相關測試

```text
pytest.exe -o pythonpath=. -q tests/test_usage_tracking.py tests/test_schedule_auth_frontend.py
39 passed, 2 skipped in 0.98s
```

### 全套測試

```text
pytest.exe -o pythonpath=. tests
169 passed, 2 skipped in 3.41s
```

兩個 skipped 為既有條件式跳過項目，並非本次新增失敗。

### 語法與差異檢查

```text
node --check schedule-auth.js
passed

git diff --check 936c039^ 936c039
passed
```

### 瀏覽器檢查

以載入實際 `ScheduleAuth.loadUsage()` 的本機測試頁與代表性資料確認：

- 已開通學校摘要顯示 `enabled_schools` 的 2，而非 configured 數量。
- metadata 失敗學校顯示「無法取得」。
- 「案件狀態暫時無法取得」位於需關注訊息最前方。
- 詳情中的班級、教師、科目及還原點均顯示 `—`。
- UTC 時間在臺灣時區顯示為同一正確日期，未倒退一天。
- dialog 開啟後，焦點位於 dialog 內。

## 7. 尚未確認或可能有風險之處

1. **尚未以 Firestore emulator 或正式 Firestore 驗證 aggregation query。** 自動測試使用能記錄呼叫行為的 fake Firestore，已確認不讀 backup stream，但仍建議在合併前以 emulator 或測試專案做一次整合驗證。
2. **legacy draft 查詢只涵蓋具有 `saved_at` 的最近 20 筆文件。** Firestore `order_by("saved_at")` 不會回傳缺少該欄位的舊文件；若正式資料曾存在無 `saved_at` 的 legacy draft，可能無法被 fallback 找到。
3. **平台概況仍是逐校同步讀取 draft/state。** 本次依範圍限制未加入 summary 文件或廣泛 async；學校數與案件大小增加後，仍可能有 N+1 查詢、延遲與 Firestore 成本問題。
4. **dialog 鍵盤流程仍建議人工複核一次。** 實測已確認原生 dialog 開啟與框內焦點；修正後的 Escape／焦點還原已有靜態測試，但最後一次瀏覽器自動化鍵盤事件受到工具逾時，未取得完整 E2E 成功證據。
5. **本機 Python 命令需避開 LibreOffice 內附 Python。** 此電腦的 `python` 目前解析到 LibreOffice，正式通過測試使用的是系統 `pytest.exe` 並明確設定 `pythonpath=.`；這是開發環境差異，不是產品執行錯誤。
6. **本分支尚未合併或部署。** 正式 GitHub Pages 與 Cloud Run 仍維持原版本，方便其他 AI 先針對上述 commit 審查。

## 範圍確認

本次未新增 Firestore summary 文件、migration/backfill、廣泛 async、Dashboard 重做、dialog polyfill、CSV 策略改造或其他不相關重構；完成本文件後不接續開發下一項功能。
