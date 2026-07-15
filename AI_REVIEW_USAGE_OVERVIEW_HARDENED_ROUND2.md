# 排課輔助系統 v1.24「使用概況」Hardened 第二輪審查資料

## 1. 專案背景簡述

本專案是提供臺灣國民小學使用的課務排程輔助系統，前端部署於 GitHub Pages，後端使用 FastAPI、Google Cloud Run 與 Firestore。平台總管理員可在「使用概況」查看各校排課進度與彙整操作紀錄，但不得取得教師姓名、Email、IP、課表內容或案件快照。

本輪承接目標 commit `936c039` 的第二輪外部 AI 審查，只處理 Firestore count aggregation 契約、legacy draft 查詢相容性，以及停用學校的狀態與不必要 metadata 查詢。

## 2. 本次修改目的

1. 以部署鎖定的 Firestore SDK 實測 `count().get()`，解決扁平／巢狀回傳結構的衝突意見。
2. 讓測試 fake 真正對應部署 SDK，並覆蓋 12、0、空結果及 malformed result。
3. 確認 `.count()` 支援狀態、乾淨安裝及 Python 3.12 CI。
4. 讓缺少 `saved_at` 的 legacy draft 仍可透過有限量相容查詢取得。
5. 實測 legacy query 是否需要額外 Firestore index。
6. 讓停用學校優先維持 `disabled`，不產生 metadata attention，也不呼叫案件 store。

## 3. 修改檔案清單

| 檔案 | 修改內容 |
| --- | --- |
| `backend/app.py` | `/platform/usage` 略過停用學校的 `get_case_overview()`。 |
| `backend/schedule_store.py` | 新增局部 aggregation extraction helper；加入 bounded legacy compatibility fallback 與不含個資的 warning。 |
| `backend/usage_tracker.py` | `disabled` 判斷優先於 `metadata_unavailable`，停用學校不產生案件 attention。 |
| `backend/tests/test_usage_tracking.py` | 更新 Firestore 2.28.0 fake，新增 count、malformed、legacy fallback、停用學校與 API spy 測試。 |
| `AI_REVIEW_USAGE_OVERVIEW_HARDENED_ROUND2.md` | 本審查交付文件，不屬於執行程式。 |

## 4. 重要修改摘要

### B01：真實 Count aggregation 契約

部署設定：

- `backend/Dockerfile`：`python:3.12-slim`
- `backend/requirements.txt`：`google-cloud-firestore==2.28.0`
- `backend/requirements.txt`：`google-auth==2.55.2`
- 完整依賴解析後：`protobuf==6.33.6`

使用同一組鎖定依賴，於 Firestore Native 測試集合寫入 12 個無個資 backup 文件後實測：

```text
firestore_version=2.28.0
google_auth_version=2.55.2
protobuf_version=6.33.6
outer_type=google.cloud.firestore_v1.query_results.QueryResultsList
first_type=builtins.list
nested_type=google.cloud.firestore_v1.base_aggregation.AggregationResult
nested_value=12
actual_store_backup_count=12
backup_snapshot_decode=not_attempted
metadata_unavailable_triggered=False
cleanup_deleted=12
```

結論：部署 SDK 的正確值位於 `results[0][0].value`，不是 `results[0].value`。正式程式使用小型 `_extract_aggregation_count()`，以部署的巢狀結構為主要契約，同時容許其他版本可能出現的扁平列；malformed 結果會拋出 `TypeError`，交由既有單校錯誤隔離處理，不會默默回傳錯誤數字。

### B02：測試可信度

- `FakeCountQuery.get()` 已改為 `[[SimpleNamespace(value=...)]]`，對應 2.28.0 的 `QueryResultsList -> list -> AggregationResult`。
- 若程式誤改回 `results[0].value`，案件摘要測試會立即失敗。
- 已覆蓋 12、0、空 outer result、空 result row、缺少 value、`None` 及字串 value。
- Fake backup collection 的 `stream()` 會直接失敗；真實測試另以故意無效的 `snapshot_json` 驗證 count 不會下載或解碼 backup snapshot。

### B03：Dependency 支援與乾淨安裝

- `google-cloud-firestore==2.28.0` 的 `CollectionReference.count()` 實際存在且可呼叫。
- requirements 已明確固定版本，不需修改 dependency。
- 未更新任何 Google Cloud 或其他套件。
- 在全新暫存 virtual environment 依 `requirements-dev.txt` 完整安裝後，全套測試通過。
- 草稿 PR 的 GitHub Actions 使用 Python 3.12 重新安裝 requirements，test job 通過。

### B04：Legacy draft 缺少 `saved_at`

歷史程式的 migration 已使用 `value.get("saved_at") or utc_now()`，表示舊資料缺少該欄位原本就是被容許修復的情境。

實際 Firestore 測試確認：

```text
legacy_query=order_by(saved_at,DESCENDING).limit(20)
legacy_ordered_count=2
legacy_compatibility_count=3
legacy_missing_in_ordered=True
```

修正後流程：

1. 第一階段維持 `order_by("saved_at", DESCENDING).limit(20)`，優先取得最新正常文件。
2. 只有第一階段找不到可用 draft，才執行 `limit(20)` 的第二階段相容查詢。
3. 第二階段只接受有 snapshot 且缺少 `saved_at` 的文件。
4. 使用相容資料時記錄 school ID 與原因，不記錄 document ID、saved_by、snapshot 或其他個資。

真實應用程式路徑輸出：

```text
legacy_has_draft=True
legacy_draft_saved_at=''
legacy_classes=1
ordered_query_index_error=none
compatibility_query_limit=20
cleanup_deleted=1
```

### B05：Firestore Index

完整第一階段 query 為：

```python
drafts.order_by(
    "saved_at", direction=firestore.Query.DESCENDING
).limit(20).stream()
```

沒有 `where` 條件。該 query 已在 Firestore Native 專案實際成功執行，未出現 `FailedPrecondition` 或索引提示，因此未新增或修改 Firestore index。

### B06：停用學校狀態

- `active == false` 現在優先於 `metadata_unavailable`。
- 停用學校維持 `progress: disabled`。
- 不產生「案件狀態暫時無法取得」、「有未發布草稿變更」或其他案件 attention。
- 不計入 `needs_attention`；啟用學校的 unknown 邏輯保持不變。

### B07：停用學校查詢

- `/platform/usage` 在取得 store 前先檢查 `active`。
- 停用學校仍保留於 overview 與管理清單，但不呼叫 `get_store()` 或 `get_case_overview()`。
- Spy 測試證明一個啟用學校呼叫一次，停用學校呼叫零次。
- `configured_schools` 與 `enabled_schools` 既有定義未變更。

## 5. Git Diff

### 審查基準

- Repository: `smallcannon-arch/schedule-system`
- Branch: `codex/usage-review-fixes`
- 第二輪目標 commit: `936c039b9561321e05c7674aa9240e01b4334563`
- 中間文件 commit: `49b476b`，只加入第一輪審查 Markdown，未修改執行程式。
- 第二輪程式 commit: `c38400683e939799c806a43d75411c9605c412f8`
- Commit message: `Verify Firestore usage contracts`

### Diff 統計

```text
 backend/app.py                       |   2 +
 backend/schedule_store.py            |  33 ++++++++-
 backend/tests/test_usage_tracking.py | 127 ++++++++++++++++++++++++++++++++---
 backend/usage_tracker.py             |  11 +--
 4 files changed, 159 insertions(+), 14 deletions(-)
```

### 完整逐行 Diff

- GitHub commit: <https://github.com/smallcannon-arch/schedule-system/commit/c38400683e939799c806a43d75411c9605c412f8>
- Raw diff: <https://github.com/smallcannon-arch/schedule-system/commit/c38400683e939799c806a43d75411c9605c412f8.diff>
- Draft PR: <https://github.com/smallcannon-arch/schedule-system/pull/1>

本機可使用：

```bash
git show --no-ext-diff --unified=3 c38400683e939799c806a43d75411c9605c412f8
```

## 6. 已執行的測試與結果

### Firestore 真實契約測試

執行方式：建立全新暫存 virtual environment，安裝 repository 的 `requirements-dev.txt`，以 `google.cloud.firestore.Client` 在隔離測試集合寫入資料，執行 raw aggregation、`FirestoreScheduleStore.get_case_overview()` 與 legacy query，最後在 `finally` 刪除所有測試文件。

結果：

- 12 個 backup aggregation：12。
- 實際回傳：`QueryResultsList -> list -> AggregationResult.value`。
- 故意無效 backup `snapshot_json` 未被解碼。
- 缺少 `saved_at` 的 legacy draft 可由第二階段找到。
- 查詢未出現索引錯誤。
- 三輪測試文件分別刪除 15、12、1 筆，沒有保留測試資料。

### 直接相關測試

```text
<clean-venv>\Scripts\python.exe -m pytest -q \
  tests/test_usage_tracking.py tests/test_schedule_auth_frontend.py

46 passed, 2 skipped, 1 warning in 1.08s
```

### 乾淨環境全套測試

```text
<clean-venv>\Scripts\python.exe -m pip install -r requirements-dev.txt
<clean-venv>\Scripts\python.exe -m pytest -q

176 passed, 2 skipped, 1 warning in 3.91s
```

warning 是既有 Starlette TestClient 對 httpx 的 deprecation warning，不是本次失敗，也未依本輪範圍升級套件。

### GitHub Actions

- Workflow: `Verify and deploy`
- Python: `3.12`
- Test job: `pass`，55 秒
- Deploy job: `skipping`
- Run: <https://github.com/smallcannon-arch/schedule-system/actions/runs/29378292146>

## 7. 尚未確認或可能有風險之處

1. 第二階段 compatibility fallback 面對多個都缺少 `saved_at` 的文件時，沒有可靠時間欄位可判斷何者較新，只能在最多 20 筆內採用第一個有效文件。這是舊資料相容措施，不應作為正常儲存路徑。
2. 本輪使用真實 Firestore Native 測試集合，而非 emulator；所有建立的測試文件均已刪除，但會留下極少量 Firestore 操作計費與平台稽核紀錄。
3. malformed aggregation 會使該校依既有流程標記 `metadata_unavailable`，不會拖垮整份 overview；若正式環境真的發生，仍應查看 Cloud Run 錯誤紀錄追查 SDK 或資料服務異常。
4. N+1 查詢、summary 文件、全面 async、時間軸排序與摘要卡片語意均依範圍明確未處理。

## 合併條件結論

B01 的真實 SDK 驗證、12 筆 aggregation、legacy query、index、乾淨環境與 Python 3.12 CI 均已通過。第二輪技術門檻已滿足，可進入人工審查與合併決策；目前 PR 維持 Draft，尚未合併或部署。

本輪未新增 summary 文件、async Firestore client、`asyncio.gather`、資料 migration、全面回填、Dashboard stage 重做、索引變更或其他範圍外修改。
