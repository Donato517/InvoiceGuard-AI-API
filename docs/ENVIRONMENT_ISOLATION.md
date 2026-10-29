# 開發／雲端環境與 URL 隔離

三站共用同一套 `app/core/environment.py` 邊界；每個 Repository 保留自己的副本，修改時需同步測試。
本文件適用 InvoiceGuard-AI、InvoiceGuard-AI-ADMIN、InvoiceGuard-AI-API，三站內容相同。

## 本機 DB／Storage 例外（2026-10-25 使用者核定）

- ADMIN／API 的 Settings 精確排除 `DATABASE_URL` 的本機機密拒絕，仍驗證 PostgreSQL 格式與 TLS；`S3_ENDPOINT_URL`、`S3_REGION`、`S3_ACCESS_KEY_ID`、`S3_SECRET_ACCESS_KEY`、`SUPABASE_STORAGE_BUCKET` 不在核定機密清單，本機可載入。
- 這些值由 START 以團隊的 `VERCEL_TOKEN.txt` 經 Vercel CLI 從 ADMIN／API 各自專案的 **Production** 設定讀取，只注入本機該站程序記憶體；前台不取得，也不產生 `.env`。
- 因此本機 ADMIN／API 連到正式 DB／Storage，本機寫入就是正式資料寫入。
- ADMIN 與 API 另由 START 各自注入自己專案的 Google Document AI／Gemini 五項：`GOOGLE_CLOUD_PROJECT_ID`、`GOOGLE_CLOUD_LOCATION`、`DOCUMENT_AI_PROCESSOR_ID`、`GOOGLE_SERVICE_ACCOUNT_JSON`（多行 JSON 由 START 壓成單行）、`GEMINI_API_KEY`，以及 Groq 金鑰 `GROQ_API_KEY`（API 2026-10-28、ADMIN 2026-10-29 核定：START 注入站程序的雲端設定是必要設定，不視為本機禁用機密）。前台不取得；ADMIN 只有 DB／S3 為啟動必要，AI 設定缺少時 START 只提示、照常啟動。ADMIN／API Settings 的 `LOCAL_INJECTED_FIELDS`（`DATABASE_URL`、`GEMINI_API_KEY`、`GOOGLE_SERVICE_ACCOUNT_JSON`、`GROQ_API_KEY`）不回本機機密拒絕；其餘三項 Google 設定不是機密欄位。
- 其他機密（`SESSION_SECRET_KEY`、`CRON_SECRET`、`JWT_SECRET_KEY`、`OPENAI_API_KEY` 等其他模型 Key、`SUPABASE_SECRET_KEY`、`DATABASE_URL_UNPOOLED` 等）出現在本機程序環境時，站台仍拒絕啟動；所以 ADMIN 依 `SESSION_SECRET_KEY` 簽署的舊管理者 cookie 登入（`require_admin` 路徑）在本機無法使用、API 本機無法通過 Cron 驗證。

## 設定來源

- 永遠不讀 `.env`、`.env.local` 或秘密目錄，即使呼叫 `Settings(_env_file=..., _secrets_dir=...)` 也不讀。
- 公開設定優先序：程序環境變數 → Settings 建構參數 → 本機公開 URL JSON → 本機預設值。
- 本機 JSON 固定為 `<專案根目錄>/InvoiceGuard-STARTUP/dev-urls.local.json`；根目錄由各 Repository 的實際父目錄推導，不重複硬編絕對路徑。
- 任一設定來源出現非空的 `VERCEL`、`VERCEL_ENV`，或 `APP_ENV` 不是 local，便完全略過本機 JSON（不先檢查檔案存在、不先解析）。旗標不完整時拒絕啟動。
- 即使本機 JSON／dotenv 被誤提交，雲端也不將它當設定來源。`.gitignore` 是額外防呆，並非隔離保證本身。
- `LOCAL_SECRET_FIELDS` 是 source 產生的內部欄位，僅記錄誤繼承的核定機密欄位名稱，不保存其值；無法由 JSON／建構參數覆蓋，亦不輸出至 model dump。
- 本機機密檢查分兩級：本站會讀取的機密欄位（例如 ADMIN／API 的 OPENAI_API_KEY；DATABASE_URL 例外見上）出現在程序環境時為錯誤並拒絕啟動；本站沒有的機密名稱（例如前台的 OPENAI_API_KEY）只列為 `inherited_secret_unused` 警告，值不會載入，也不影響結束碼。

## 三種環境

| 設定 | 本機 | Vercel Preview | Vercel Production |
|---|---|---|---|
| APP_ENV | local（預設） | preview | production |
| VERCEL | 留空 | 平台注入 1 | 平台注入 1 |
| VERCEL_ENV | 留空 | 平台注入 preview | 平台注入 production |
| DEBUG | false（預設） | false | false |
| MODULE_BACKEND（ADMIN/API） | auto→remote | auto→cloud | auto→cloud |
| 本機 URL JSON | 可讀 | 完全不讀 | 完全不讀 |

`APP_ENV` 與 `VERCEL_ENV` 必須一致，不一致時站台拒絕啟動（連 `/health` 也無法使用）；`APP_ENV=local` 不會關閉登入、授權或現有 DB 防護，唯一例外是 ADMIN 本機 `/dev` 示範檔案。
本流程不要求開發者執行 `vercel login`、`vercel dev` 或 `vercel env pull`；本機只由 START 讀取上方例外段的核定設定。

## 本機公開 URL

通常不需要此檔。第一次有需要時，在 `InvoiceGuard-STARTUP` 資料夾執行（已有檔案不覆蓋）：

```powershell
if (-not (Test-Path -LiteralPath '.\dev-urls.local.json')) {
    Copy-Item -LiteralPath '.\config\dev-urls.example.json' -Destination '.\dev-urls.local.json'
}
```

```json
{
  "schema_version": 1,
  "frontend": {"API_BASE_URL": "http://127.0.0.1:8000/api/v1"},
  "admin": {"REMOTE_ADMIN_BASE_URL": ""},
  "api": {"REMOTE_API_BASE_URL": ""}
}
```

三個 section 必須存在，section 內只允許上列欄位（可留空物件），欄位值留空等同未設定；拒絕未知欄位、重複鍵、錯誤型別、超大檔案與越界連結。
不得在這裡加入 APP_ENV、VERCEL、DATABASE_URL、SESSION/JWT/模型 Key 或其他機密。
新增未核定欄位仍需更新核定 schema 與消費端程式，不能靠任意 JSON 欄位繞過檢查。

本機前端的 API_BASE_URL 未設定或留空時預設 `http://127.0.0.1:8000/api/v1`；雲端沒有此預設。
API_BASE_URL 是前端 Python 伺服器的出站目標，並非手機瀏覽器的 localhost。
START 會以當次埠號注入前台的 API_BASE_URL（日常 `http://127.0.0.1:8100/api/v1`），優先於 JSON 與預設值。
REMOTE_ADMIN_BASE_URL／REMOTE_API_BASE_URL 是保留的本機遠端模式欄位：ADMIN 的 `remote_admin_client` 沒有呼叫端、API 沒有消費端，START 啟動時兩者為空值；本機改為直接使用 START 注入的 DB／Storage 設定。

## 管理者在下次部署前確認

1. 分別選擇三個 Vercel Project → Settings → Environment Variables。
2. 確認平台系統變數可供執行程序使用；VERCEL 與 VERCEL_ENV 由平台提供，不把它們寫入本機檔案。
3. APP_ENV 依 scope 分開填：Preview=preview，Production=production；兩者 DEBUG=false。
4. **前端**：各 scope 都必須設定 API_BASE_URL（包含實際 `/api/v1` 路徑）；Production 指向核定正式 API，Preview 指向核定測試 API。
5. **ADMIN/API**：MODULE_BACKEND 使用 auto 或 cloud；雲端不設定本機專用的 REMOTE_ADMIN_BASE_URL／REMOTE_API_BASE_URL，已有非空值時需先由管理者確認並清除。
6. DB、Storage、模型、Session/JWT/Cron 等既有機密仍由各雲端 scope 保存。Preview 必須選擇核定的測試資料／檔案範圍，不能僅改網址就宣稱資料已隔離。
7. 部署需使用者明確授權；環境變數變更不會自動套用至既有部署。

雲端 API URL 必須是無帳密、query、fragment 的公開 HTTPS；拒絕 loopback、私有／保留／多播 IP、會解析到 loopback 的公開網域（如 nip.io、sslip.io、localtest.me、lvh.me）、已知臨時隧道網域（清單無法完整）及不合規連接埠。SUPABASE_URL 非空時亦做公開 HTTPS 檢查。
驗證不解析 DNS，不能證明遠端服務身分、DNS rebinding 防護、資料庫用途或開發域名是否屬於正式站；管理者仍需核定真正的目標網址。

## PowerShell：不需密鑰的檢查

三站各自需要已安裝 requirements-dev.txt 的 Python 3.12 venv。在任一站根目錄的 PowerShell 執行：

```powershell
$projectRoot = (Resolve-Path ..).Path
$runId = [guid]::NewGuid().ToString('N')
foreach ($repoName in @('InvoiceGuard-AI', 'InvoiceGuard-AI-ADMIN', 'InvoiceGuard-AI-API')) {
    Push-Location -LiteralPath (Join-Path $projectRoot $repoName)
    try {
        $pythonPath = Join-Path (Get-Location).Path '.venv\Scripts\python.exe'
        & $pythonPath -B -m app.core.environment --check
        if ($LASTEXITCODE -ne 0) { throw "$repoName 環境檢查失敗；請依欄位及代碼修正，勿貼出密鑰" }
        $testTemp = Join-Path $env:TEMP "ig-env-$repoName-$runId"
        & $pythonPath -B -m pytest -q -p no:cacheprovider "--basetemp=$testTemp"
        if ($LASTEXITCODE -ne 0) { throw "$repoName 測試失敗" }
        & $pythonPath -B -m ruff check app tests scripts
        if ($LASTEXITCODE -ne 0) { throw "$repoName lint 失敗" }
        & $pythonPath -B -m ruff format --check app tests scripts
        if ($LASTEXITCODE -ne 0) { throw "$repoName 格式檢查失敗" }
    } finally {
        Pop-Location
    }
}
```

若檢查出現 `cloud_secret_in_local`，而該值其實是開發者 shell 原有的個人 Key（例如 `OPENAI_API_KEY`），只在目前 PowerShell 移除後再執行；不影響其他視窗或使用者設定：

```powershell
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
```

環境 CLI 有效回傳 0，無效回傳 2；警告（例如 `inherited_secret_unused`）不影響結束碼。輸出只有環境名稱、欄位、固定代碼與訊息，不包含 URL 或密鑰值。
`configuration_valid=true` 僅代表靜態檢查通過；`connectivity_checked=false` 明確表示未驗連線。
單元測試使用合成資料、封鎖外部網路／DB；真正 `-m` 子程序案例只載入暫存的設定模組，不載入 app.main 或業務服務。
目前單元測試會出現既有 Starlette/httpx deprecation warning；不代表雲端或三站業務串接已驗收。

歷史檢驗指令與實測結果見各站 `docs/REVIEW_FIX_LOG.md`、`docs/TEST_REPORT.md`。

官方參考：[Vercel 環境變數](https://vercel.com/docs/environment-variables)、[系統環境變數](https://vercel.com/docs/environment-variables/system-environment-variables)。
