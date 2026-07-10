# 正式排課系統上架步驟

本資料夾固定使用 `mode: "formal"`。未完成學校 Google 登入前，只顯示登入閘門，不會顯示 DEMO、側欄或排課工作區。

## 上架前設定
1. 先依 `cloudrun部署包/README部署步驟.md` 部署 FastAPI、Firestore 與 Google OAuth。
2. 將 `auth-config.js` 的 `apiBaseUrl` 改成 Cloud Run 網址。
3. Google OAuth 的「已授權 JavaScript 來源」加入正式網站來源，例如 `https://schedule.example.edu.tw`。
4. Cloud Run 的 `ALLOWED_ORIGINS` 也只加入相同正式網站來源。
5. 保持 `app-config.js` 為 `mode: "formal"`。

```js
window.SCHEDULE_AUTH_CONFIG = {
  apiBaseUrl: "https://schedule-engine-xxxx.a.run.app",
};
```

前端不得放入 OAuth Client Secret、系統 API key、教師帳號表或服務帳戶金鑰。Web OAuth Client ID 由後端 `/auth/config` 提供。

## 正式流程
- 承辦人先以預先核准的學校 Google 帳號登入。
- 初次使用匯入教師帳號 CSV 與排課母版；後續可載入自己的雲端暫存。
- 非示範內容每 30 秒保存到承辦人自己的 Firestore 暫存。
- 按「發布正式教師課表」後，教師才看得到課表。
- 導師儲存自排結果後，承辦端每 10 秒自動匯入；科任與資源班教師只能查看個人課表。
- 加密 JSON 教師調整檔僅保留為離線備援。

## 本機預覽
在本資料夾啟動靜態伺服器：

```powershell
python -m http.server 8768 --bind 127.0.0.1
```

再開啟 `http://127.0.0.1:8768/`。後端預設為 `http://127.0.0.1:8766`。
