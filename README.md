# 正式排課系統

這是排課系統的正式前後端倉庫。前端以靜態網站部署，後端位於 `backend/`，處理 Google 登入、雲端暫存、排課、審核與正式發布。

## 主要入口

- `index.html`：正式前端。
- `app-config.js`：正式模式設定。
- `auth-config.js`：Cloud Run API 網址。
- `backend/`：FastAPI、Firestore、Google OAuth 與排課引擎。
- `docs/`：版本紀錄與營運文件。
- `README上架步驟.md`：正式部署與本機預覽步驟。

## 本機預覽

```powershell
python -m http.server 8768 --bind 127.0.0.1
```

前端使用 `http://127.0.0.1:8768/`，後端預設使用 `http://127.0.0.1:8766`。

## 安全原則

- 前端不得放入 OAuth Client Secret、API key、教師帳號表或服務帳戶金鑰。
- 私密設定使用 Google Secret Manager 與部署環境變數。
- 支援素材、DEMO、舊版備份與歷史模版位於私人 `schedule-system-support` 倉庫。
