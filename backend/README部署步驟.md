# 排課引擎 Cloud Run 部署步驟

## 前置（一次性，須本人操作）
1. 到 console.cloud.google.com 以 Google 帳號建立專案（例：schedule-engine）
2. 啟用計費帳戶。實際費用依 Google Cloud 當期定價與使用量為準，請設定預算告警。
3. 啟用 API：Cloud Run、Cloud Build、Secret Manager、Firestore。
4. 在 Secret Manager 建立 `schedule-api-key`，內容使用足夠長的隨機字串。
5. 在 OpenAI API Dashboard 建立專案金鑰，存入 Secret Manager 的 `openai-api-key`；金鑰不得寫入程式碼或 Excel。

## Google 教師登入（一次性）
1. 在 Google Cloud Console 建立「Web 應用程式」OAuth Client ID。
2. 已授權的 JavaScript 來源加入 `https://smallcannon-arch.github.io`；本機測試可另加 `http://127.0.0.1:8765`。
3. 建立 Firestore Native mode 資料庫，區域建議與 Cloud Run 相同或鄰近。
4. Cloud Run 執行身分需有 `Cloud Datastore User`（`roles/datastore.user`）權限。
5. 準備第一間學校的排課管理員帳號，填入 `SCHEDULE_ADMIN_EMAILS`；平台建校帳號填入 `SCHEDULE_SUPER_ADMIN_EMAILS`。

OAuth Client ID 可公開在前端；不要建立或放入 OAuth Client Secret。教師的 Google 密碼不會進入本系統。

正式前端請使用專案根目錄的 `正式上線包`；匿名推廣站使用 `上線包`。兩者的 `app-config.js`、瀏覽器存檔與可用功能已分開，請勿把 DEMO 網址提供作正式校務入口。

## 部署（方法一：Cloud Shell，免安裝任何軟體）
1. Console 右上角開 Cloud Shell（>_ 圖示）
2. 上傳本資料夾全部部署檔案（Cloud Shell 右上「⋮」→ 上傳）
3. 先將映像建置到已授權 Cloud Run 讀取的 Artifact Registry，再部署（CPU 求解採單一請求並行）：
   gcloud builds submit . --region asia-east1 \
     --tag asia-east1-docker.pkg.dev/填入專案ID/schedule-engine-images/schedule-engine:版本號

   gcloud run deploy schedule-engine \
     --image asia-east1-docker.pkg.dev/填入專案ID/schedule-engine-images/schedule-engine:版本號 \
     --region asia-east1 \
     --allow-unauthenticated --memory 1Gi --timeout 660 --concurrency 1 \
     --max-instances 8 \
     --set-env-vars MAX_CONCURRENT_SOLVES=1,SCHEDULE_SOLVER_WORKERS=2,SCHEDULE_RANDOM_SEED=42,RATE_LIMIT_PER_MINUTE=30,OPENAI_MODEL=gpt-5.4-mini,ALLOWED_ORIGINS=https://smallcannon-arch.github.io,GOOGLE_CLIENT_ID=填入Web用戶端ID,GOOGLE_WORKSPACE_DOMAIN=填入第一間學校網域,SCHEDULE_ADMIN_EMAILS=填入第一間學校管理員,SCHEDULE_SUPER_ADMIN_EMAILS=填入平台總管理員,SCHEDULE_MULTI_TENANT=true,SCHEDULE_STORE=firestore,FIRESTORE_PROJECT_ID=填入專案ID,SCHEDULE_SCHOOL_ID=填入學校代碼,SCHEDULE_SCHOOL_NAME=填入學校名稱 \
     --set-secrets SCHEDULE_API_KEY=schedule-api-key:1,OPENAI_API_KEY=openai-api-key:1
4. 完成後顯示網址：https://schedule-engine-xxxx.a.run.app
   開啟即是上傳頁；使用者必須輸入 API 金鑰才可送出母版 xlsx。
5. 將 Cloud Run 網址填入 `正式上線包/auth-config.js` 的 `apiBaseUrl`，再部署正式前端。

## 教師帳號表
排課管理員登入系統後，可匯入 UTF-8 CSV。欄位如下：

```csv
教師姓名,學校Google帳號,角色,負責班級
王老師,teacher01@school.example.edu.tw,導師,301
李老師,teacher02@school.example.edu.tw,科任,
陳老師,teacher03@school.example.edu.tw,資源班教師,
```

CSV 角色支援「導師、科任、資源班教師」；排課管理員須由平台總管理員在學校設定中授權，不接受 CSV 自行升權。第一次登入會以核准信箱比對，再綁定 Google 的穩定帳號識別碼。導師可調整指派班級；科任與資源班教師只能查看個人課表。

## 多校管理
- 平台總管理員登入後，可在「學校管理」建立學校代碼、名稱、Workspace 網域與首位承辦人。
- 登入時後端先以 Google ID token 的 `hd` 找出候選學校，再以管理員名單或教師名冊判斷實際學校，不接受前端自行指定 `school_id`。
- 每校教師、正式課表與承辦人草稿都存放在各自的 `schedule_schools/{school_id}` 路徑。
- 同一縣市共用的 Workspace 網域可登錄多所學校；一般帳號會依學校名冊安全分流。若同一帳號確實同時隸屬多校，系統會阻擋並要求平台管理員設定主要學校。
- 停用學校後，該校所有帳號會在後端被拒絕，但資料不會刪除。

## 暫存與導師自排同步
- 排課管理員登入後，非示範資料在停止操作 10 秒後存入學校共用的 Firestore 雲端暫存，另有每 60 秒的保險存檔，也可按「儲存至學校雲端」。
- 同校主任與組長讀取同一份共用暫存；版本較舊的分頁會被阻擋覆蓋並要求重新載入。
- 雲端暫存與「發布正式教師課表」是兩套資料；暫存不會讓老師看到未完成課表。
- 導師完成自排並按「儲存課表調整」後，後端立即驗證並存入待審佇列，不會直接改動正式課表。
- 承辦人按「讀取導師存檔」後，系統先做全校硬規則預檢，再由後端確認並套用；版本不符或規則衝突時不會更新正式課表。
- 每次正式發布都保留版本紀錄；承辦人可從「正式版本」還原，還原時會建立新版本而不刪除舊紀錄。

## 部署（方法二：本機 gcloud CLI）
安裝 Google Cloud SDK 後，於本資料夾執行同上 gcloud 指令。

## 本機啟用 OpenAI
在 PowerShell 先設定目前工作階段的環境變數，再啟動服務；請勿把真實金鑰寫入 `.env.example` 或提交版本控制：

```powershell
$env:OPENAI_API_KEY="請填入 OpenAI 專案金鑰"
$env:OPENAI_MODEL="gpt-5.4-mini"
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8766
```

開啟 `/ai/status`，確認 `configured=true` 後，上傳頁才會顯示 OpenAI 勾選與自然語言目標欄位。

未設定 `OPENAI_API_KEY` 時，CP-SAT 正式排課仍可正常使用；只需不要勾選 OpenAI 規劃。正式模式預設只排科任、固定課與硬鎖，導師課保留給導師登入後安排；課程缺教師、仍有待排節數或教師週節數超過上限時會回傳 HTTP 409，不會把部分課表誤標成完成。

## 費用與安全
- 閒置縮零與免費額度仍應以 Google Cloud 控制台顯示為準，並設定預算告警。
- `--allow-unauthenticated` 只開放上傳頁；`/solve` 仍由 `SCHEDULE_API_KEY` 驗證。內部使用可改 Cloud Run IAM 並移除公開存取。
- `/auth/me`、`/teacher/*` 與 `/admin/*` 會在後端驗證 Google ID token；未列於教師帳號表的人員無法讀取正式課表。
- 教師端只取得個人課表與獲授權班級；資源班綁課、固定課及跨班修改會由後端再次拒絕。
- 承辦人雲端暫存由同校管理員共用，並以草稿 revision 防止主任與組長互相覆蓋；導師更新先待審，再依正式課表 revision 確認套用。
- API 會限制上傳大小、xlsx 解壓後大小、同執行個體求解數，且不會把 traceback 回傳給使用者。
- API 具每執行個體的基本每分鐘速率限制；若要跨執行個體精準限流，應再接 API Gateway 或其他集中式閘道。
- `ALLOWED_ORIGINS` 應只列出實際前端網址，使用逗號分隔，不要在正式環境設為萬用來源。
- 上傳檔僅存在請求期間的記憶體/暫存目錄，回應後即回收
- 勾選 OpenAI 時，只傳送匿名化統計摘要與使用者填寫的排課目標；不傳送原始 Excel、教師姓名或班級代碼。
- OpenAI 只可調整 S01-S09 軟規則權重。硬規則、實際求解及獨立檢核仍由 CP-SAT 執行。

## 檔案清單
- app.py：FastAPI 服務（排課、Google 登入、教師工作區及管理 API）
- auth_service.py：Google ID token 驗證、Workspace 網域與角色授權
- schedule_store.py：Firestore／本機記憶體儲存介面
- teacher_portal.py：個人課表過濾與導師編修的後端硬規則檢查
- openai_advisor.py：匿名化摘要、OpenAI 軟規則規劃與輸出稽核工作表
- engine.py：排課引擎 v1.6（CP-SAT，支援母版 v4/v5、完整度與求解品質指標）
- requirements.txt、requirements-dev.txt、Dockerfile、.env.example
