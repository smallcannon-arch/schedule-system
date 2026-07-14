# 正式排課系統上架步驟

本資料夾固定使用 `mode: "formal"`。未完成學校 Google 登入前，只顯示登入閘門，不會顯示 DEMO、側欄或排課工作區。

## 上架前設定
1. 先依 `backend/README部署步驟.md` 部署 FastAPI、Firestore 與 Google OAuth。
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
- 初次使用匯入教師帳號 CSV 與排課母版；後續可載入學校共用的雲端暫存。
- 停止操作 10 秒後自動存檔，另有每 60 秒的保險存檔；同校主任與組長以版本號避免互相覆蓋。
- 按「發布正式教師課表」後，教師才看得到課表。
- 導師儲存自排結果後會進入待審，承辦人按「讀取導師存檔」並通過全校檢核後才更新正式課表。
- 每次正式發布與還原都保留版本紀錄；科任與資源班教師只能查看個人課表。
- 加密 JSON 教師調整檔僅保留為離線備援。

## 自動檢核與部署

`main` 的每次推送會先執行後端／前端測試、Python 套件漏洞掃描與 JavaScript 語法檢查；全部通過後，才由 GitHub Actions 發布 GitHub Pages。Cloud Run 後端原始碼與測試均位於 `backend/`，應與前端版本一起提交。

## 本機預覽
在本資料夾啟動靜態伺服器：

```powershell
python -m http.server 8768 --bind 127.0.0.1
```

再開啟 `http://127.0.0.1:8768/`。後端預設為 `http://127.0.0.1:8766`。
