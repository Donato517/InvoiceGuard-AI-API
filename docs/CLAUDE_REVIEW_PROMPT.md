# 提供給 Desktop Claude AI 的檢驗指令

請獨立檢驗 InvoiceGuard 的 ADMIN 與 API「第一階段 Vercel / DB 模組」，先出具報告，不修改程式。

先確認你是否具備存取本機檔案與 PowerShell 的工具。若沒有，請提供逐步指令讓管理者執行，
並請管理者回傳不含機密的輸出；不得聲稱你已讀檔、連線 Vercel 或執行測試。

## 範圍與限制

- 專案根目錄為 `C:\InvoiceGuard_project`，兩個 Repository 各自有模組，不將 ADMIN 改成只靠 API 存取資料。
- 本次驗收只涵蓋靜態設定驗證、資料與檔案介面契約、離線單元測試；不是完整業務功能驗收。
- 不讀取或輸出任何實際 `.env`、`.env.*`、`.vercel`、憑證檔、密碼、Token 或完整秘密連線字串。
  `.env.example` 只允許檢查設定名稱與空白／明確的假值；不要列印完整程序環境。
- 不登入 Vercel / Supabase 管理介面，不執行 `vercel env pull`、部署、migration、seed 或真實排程。
- 不連公司 DB / Storage / AI，不上傳、刪除或修改任何正式資料；不呼叫雲端 Cron URL。
- 不執行 Git Pull / Reset / Merge / Commit / Push，不修正程式或使用 Ruff --fix。
- 允許執行以下單元測試及檢查；僅允許產生一般測試快取與專用 `tmp/pytest` 暫存。
  不重建已有 venv；缺少依賴時先回報，不自行更換版本。
- 不將 `VERCEL=1` 或 `APP_ENV=local` 當作身分授權證明，也不在一般 Shell 偽造雲端執行成功。

## 先閱讀真實檔案

1. `C:\InvoiceGuard_project\InvoiceGuard-AI-ADMIN\docs\MODULE_CONTRACT.md`
2. `C:\InvoiceGuard_project\InvoiceGuard-AI-API\docs\MODULE_CONTRACT.md`
3. 兩站的 `docs/ARCHITECTURE.md`、`docs/CODING_CONVENTIONS.md`、`app/db/README.md`。
4. 兩站的 `app/core/config.py`、`app/core/module_errors.py`、`app/core/security.py`、`app/db/session.py`。
5. 兩站的 `app/integrations/vercel.py`、`storage_client.py`、`app/db/contracts.py`、
   `app/services/data_service.py`、`file_service.py`、`app/schemas/common.py`、`data.py`、`files.py`。
6. API 額外閱讀 `app/schemas/invoice.py`、`app/core/exceptions.py`、`docs/API_CONVENTIONS.md`。
7. 兩站的 `tests/conftest.py`、既有測試與新增 `tests/unit/test_module_*.py`、`test_db_session.py`。

可用 `git status --short` 與 `git diff --check` 作唯讀檢查。注意 `git diff` 不包含未追蹤新檔，
必須另外讀取新增模組與測試，不可只看已追蹤檔案的 diff。
不需要讀 Git 遠端認證或登入任何平台。

## 執行並記錄結果

下列指令以目前電腦的路徑為準；不同開發者只替換專案根目錄。
一次進入一個 Repository，兩站都有名為 `app` 的套件，不可在同一個 Python 程序混用匯入。

ADMIN：

```powershell
Set-Location 'C:\InvoiceGuard_project\InvoiceGuard-AI-ADMIN'
.\.venv\Scripts\python.exe -m app.integrations.vercel --check local
.\.venv\Scripts\python.exe -m pytest -q --basetemp=tmp/pytest
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m ruff format --check app tests
```

API：

```powershell
Set-Location 'C:\InvoiceGuard_project\InvoiceGuard-AI-API'
.\.venv\Scripts\python.exe -m app.integrations.vercel --check local
.\.venv\Scripts\python.exe -m pytest -q --basetemp=tmp/pytest
.\.venv\Scripts\python.exe -m ruff check app tests scripts
.\.venv\Scripts\python.exe -m ruff format --check app tests scripts
```

每條指令之後記錄 `$LASTEXITCODE`，失敗時保留不含機密的錯誤摘要。
`tmp/pytest` 是 pytest 專用暫存目錄，可能在重跑時清理；有其他資料時先停止並回報。
不使用 `scripts/run_job.py`、`scripts/seed_dev_data.py` 或 Alembic 驗證本階段。
Starlette 對 httpx 的淘汰警告應獨立記錄，不自動更換套件或當作雲端整合失敗。
若 Windows 沙箱阻擋 socketpair，請回報環境限制，在一般 PowerShell 重跑；不移除網路／DB 阻擋器。

只有在服務已啟動時，才可用 localhost GET 驗證：

- ADMIN：`http://127.0.0.1:8002/health`、`http://127.0.0.1:8002/login`。
- API：`http://127.0.0.1:8000/health`；根路徑沒有網站，預設 `/docs` 不開放。

不要因為健康檢查成功就聲稱 DB / Storage / 使用者授權可用。

## 必須核對的重點

1. 預設不讀 `.env`，本機不需要公司密鑰；設定輸出、repr、JSON、錯誤不包含秘密值。
2. API 的 DATABASE_URL_UNPOOLED、JWT、Cron、AI、Blob 等既有設定沒有因複製 ADMIN 而遺失或誤用。
   API 不要求 ADMIN 的 SESSION_SECRET_KEY；CRON_SECRET 不代替使用者登入。
3. PostgreSQL URL 轉換、TLS、NullPool、逾時、transaction 模式 prepare_threshold=None 正確；
   缺設定或本機模式在 create_engine 前被拒絕，快取 Engine 不得略過重新驗證。
4. 不因 APP_ENV=local 略過既有登入／Cron 授權，不從請求接收可信的角色或擁有者。
5. 檔案與發票 DTO 拒絕任意 SQL、表名、Bucket、object_key、角色／擁有者覆寫及未核定欄位；
   金額、分頁、版本、冪等識別碼、路徑與時區的驗證是否足夠。
6. 實際服務工廠明確拋出 ModuleNotReadyError；不以空清單、零筆或假成功冒充業務已完成。
7. OperationContext / Protocol 是契約，不是真實登入或部門授權；metadata 表及 version 欄位尚未建立。
8. 單元測試清除已知繼承設定、使用假值、阻擋網路與真實 DB；Windows socketpair 放行範圍是否合理。
   API Cron 測試只呼叫替身，不執行真實排程。
9. API 422 回應不反射 input / ctx 或合成機密值；既有錯誤 JSON 外層與分頁 JSON 欄位保持相容。
10. ADMIN 與 API 的共用檔案／CRUD 契約是否一致；沒有改 ORM、migration 或 vercel.json，沒有雲端設定變更。

## 報告格式

先列可重現問題，依嚴重度排序，附完整檔案路徑、行號、觸發方式、影響與最小修正建議。
再列各指令的實際結果、exit code、警告與未執行項目。
最後區分「已實作並通過離線測試」「只有契約」「尚未實作」「尚未進行的雲端整合驗證」。
不得把本機未配置遠端網址推論為 Vercel 缺設定，也不得將未實作的真實 CRUD / Storage 視為本階段已完成。
請先交付檢驗報告，不直接修改任何程式。
