# API Vercel / DB 模組：第一階段

本階段只完成設定驗證、介面契約與不需公司密鑰的單元測試。
未部署、未執行 migration / seed / 真實排程，未存取正式 DB 或 Storage。
ADMIN、採購前台與啟動器沒有在本次變更中修改。

## 能力狀態

| 能力 | 狀態 |
|---|---|
| `get_platform()` 執行描述 | 已實作，沒有密鑰或 SDK 用戶端 |
| `check_configuration()` / CLI | 已實作靜態檢查，不連網 |
| DB Engine 參數與 Session 關閉 | 已實作設定保護；真實連線未驗證 |
| 檔案與發票 CRUD DTO / Protocol | 已定義，不能直接操作真實資料 |
| Storage / FileService / DataService 工廠 | 拋出 ModuleNotReadyError，不假裝成功 |
| 既有 Cron 驗證 | 保留 hmac.compare_digest；SecretStr 只在內部解封，沒有密鑰時仍拒絕 |
| 422 驗證錯誤 | 不回傳 input / ctx，不反射原始機密值 |
| JWT 使用者登入、部門權限 | 尚未實作；CRON_SECRET 不能當使用者登入憑證 |
| 真實 CRUD、Storage adapter、遠端傳輸 | 尚未實作，沒有新增可寫入業務資料的 HTTP 端點 |
| StoredFile 表、發票 version 欄位 | 尚未建立，API 後續統一規劃 Schema；ADMIN 同步 |

`vercel.json`、Alembic 設定與 ORM 模型保持原樣。
原有 Blob 僅為 TODO；本次先定義供應商中立契約，未實作或部署 Storage 遷移。

## 匯入方式

```python
from app.integrations.vercel import get_platform, check_configuration
from app.schemas.invoice import InvoiceCreate, InvoicePatch, InvoiceUpdate
from app.schemas.files import UploadFileRequest, MoveFileRequest, DeleteFileRequest
from app.services.data_service import DataService, get_data_service
from app.services.file_service import FileService, get_file_service
```

匯入不建立連線。工廠目前一律明確拒絕取得可操作的服務，直到授權、Repository、
Storage 及交易協調接線完成。不要將 Protocol 的存在或測試替身當成正式服務已實作。

## 設定

執行期設定集中在 `app.core.config.settings`；預設不讀 `.env` 或 secrets 目錄。
所有機密以 SecretStr 保護 repr / JSON，這不是加密，也不允許記錄 get_secret_value()。
`.env.example` 的密鑰保持空白；禁止 vercel env pull 或將公司連線字串填入本機。

| 設定 | 適用能力／預設 |
|---|---|
| APP_ENV / DEBUG | local / false；雲端需 preview 或 production 且 DEBUG=false。Vercel 不會自動設定 APP_ENV，未設定時 Cron 一律 401，並以 warning 記錄欄位與代碼（不含值） |
| MODULE_BACKEND | auto；在 Vercel 選 cloud，其餘 remote，不替代身分驗證 |
| REMOTE_API_BASE_URL | 公開 HTTPS 基底網址，需指向 API 自己的受控雲端服務；傳輸尚未接線 |
| DATABASE_URL | 雲端 DB 必填機密；不自動使用 POSTGRES_URL |
| DATABASE_URL_UNPOOLED | 保留既有 migration 設定與優先順序；本階段不執行 migration |
| DB_POOL_MODE | transaction / session / direct；預設 transaction，管理者需確認實際模式 |
| DB_SSL_MODE | require / verify-full；預設 require；verify-full 的 CA 另由管理者確認 |
| DB_CONNECT_TIMEOUT_SECONDS | 預設 5 秒，允許 1–30 秒 |
| SUPABASE_URL / SUPABASE_STORAGE_BUCKET | 雲端 Storage 必填公開設定，尚未驗證 Bucket 存在或私有政策 |
| SUPABASE_SECRET_KEY | 雲端 Storage 必填機密，尚未驗證憑證與權限 |
| JWT_SECRET_KEY / JWT_EXPIRE_MINUTES | auth 能力驗證：至少 32 字元／1–1440 分鐘，預設 60；JWT 使用者登入仍是 TODO |
| CRON_SECRET | cron 能力：至少 16 字元；本機模式也不略過請求驗證 |
| GEMINI_API_KEY / OPENAI_API_KEY | 雲端選填，本階段不使用模型服務 |
| AI_API_KEY / EINVOICE_APP_ID / EINVOICE_API_KEY / BLOB_READ_WRITE_TOKEN | 保留既有名稱並遮罩，未啟用的整合不要求填寫 |
| VERCEL | 平台自動標記，不是認證憑證，不得用來保護公開 API |

API 不需要 ADMIN 的 SESSION_SECRET_KEY。雲端設定是否已儲存、憑證是否有效，均未連線核對。
一般開發者不取得 Vercel / Supabase 管理員權限，也不持有公司密鑰。
本機已知機密欄位非空會使 local 檢查失敗；本機經 `app.db.session` 直接建立 DB Engine 會被阻擋。
Alembic migration 不經此阻擋（只由管理者於受控環境執行），但與應用程式共用 `resolve_ssl_mode()`，不得降級為明文。

可檢查 local / database / storage / auth / cron / cloud；cloud 彙整 database、storage、auth、cron。
各能力檢查只要求該能力必要設定，例如 database 不要求模型、JWT 或 Cron 密鑰。
雲端機密變更仍需後續新部署套用，不改七位開發者的本機啟動檔。
本次沒有修改啟動器 PUBLIC_ENV；不能假設任意公開 JSON 欄位已獲允許。

## 契約與相容性

發票操作為 `DataService.invoices.create/get/list/update/delete`，不接受任意 SQL 或資料表名稱。
新增輸入不接受 user_id、status、risk_score 或 ai_result；更新只允許核定欄位且需要 expected_version。
金額使用 Decimal / JSON 字串，不接受 float；分頁每頁最多 100 筆。
ID 與版本上限為 PostgreSQL BIGINT，頁碼 1–10,000；HTTP query / path 可接受數字字串，但拒絕布林與浮點數。
`app.schemas.invoice` 從 `app.schemas.data` 匯出已完成的 CRUD 契約；詳情／複核等其他 DTO 仍待業務實作。
原有 ErrorDetail / ErrorResponse 與錯誤 JSON 外層格式保留。
Python Page.items 使用不可變 tuple，JSON 輸出仍為陣列；不變更既有 HTTP 分頁欄位。

檔案操作為 upload_file / get_file / list_files / create_download / move_file / delete_file。
上傳描述限制 JPEG / PNG / PDF、最多 4 MiB；未來 service 必須另驗證實際串流大小與內容。
移動只接受邏輯資料夾；移動與刪除需版本及 UUID 冪等識別碼，不接受任意 Bucket / object_key。
檔名不可含路徑、控制或格式字元（含雙向覆寫、零寬字元）、Windows 保留名與結尾空白 / 句點，UTF-8 不超過 255 bytes。
下載憑證需 HTTPS，URL 不顯示於 repr，未來實作須限制有效期且禁止記錄完整 URL。

OperationContext 只是內部授權上下文契約，不能從請求自行宣告，也不代表已實作登入或部門隔離。
Repository 不 commit；Service 未來管理交易與稽核。
Storage 與 PostgreSQL 不能共用單一原子交易，未來必須實作狀態、冪等性、失敗補償及重試。
AuditLog 不開放修改／刪除，JobRun 寫入由排程服務控制。

本次與 ADMIN 沿用同一版資料／檔案契約；兩站各自有雲端 DB 與 Storage 模組。
未來本機 ADMIN 呼叫 ADMIN 雲端，本機 API 呼叫 API 雲端，不將 ADMIN 改為只依賴 API 的資料層。

## PowerShell 驗證

使用 Python 3.12；首次準備可用 py -3.12，未註冊者請改用 Python 3.12 的完整路徑：

```powershell
Set-Location 'C:\InvoiceGuard_project\InvoiceGuard-AI-API'
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

已有 `.venv` 時不重建，直接執行：

```powershell
.\.venv\Scripts\python.exe -m app.integrations.vercel --check local
$LASTEXITCODE
.\.venv\Scripts\python.exe -m pytest -q --basetemp=tmp/pytest
.\.venv\Scripts\python.exe -m ruff check app tests scripts
.\.venv\Scripts\python.exe -m ruff format --check app tests scripts
```

local 設定正常時 exit 0；靜態設定檢查失敗 exit 2。型別／列舉錯誤可在載入設定時直接拒絕。
預期 configuration_valid=true、connectivity_checked=false、operations_implemented=false。
remote_not_configured / contracts_only 警告屬預期，不能當成雲端連線或業務功能已通過。
若出現 cloud_secret_in_local，只回報欄位名稱，不要輸出或傳送原值。
`tmp/pytest` 是 pytest 專用暫存目錄，可在重跑時清理，勿存放其他檔案。

測試程序會清除已知繼承設定，使用合成假值、網路與 DB 阻擋器；Cron 工作使用 MagicMock。
Windows asyncio 僅放行 socketpair 的程序內 loopback，仍阻擋一般 localhost DB 與外部連線。
Windows AppContainer 可能阻擋程序內 socketpair；請在一般 PowerShell 執行，不放寬外部連線限制。
目前 Starlette 對 httpx 的淘汰警告另行列示，不視為測試失敗，也不擅自變更全站依賴版本。

頁面只需驗證 API 健康檢查，不啟動排程：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

開啟 http://127.0.0.1:8000/health 應顯示 status=ok。
根路徑 `/` 無首頁，預設 DEBUG=false 時 `/docs` 不開放；404 是正常行為。
以上不代表 DB / Storage 連線通過。

## 下一階段

由管理者控制的雲端測試環境處理真實連線，依序完成使用者授權、共用 Schema、
Repository / Service、Storage adapter、受控 JSON 端點與 localhost 遠端傳輸。
須另驗證跨使用者／部門拒絕、版本衝突、檔案內容、稽核與補償。
本階段沒有授權部署、migration、seed 或正式資料寫入。

## 官方依據

- [Supabase 連線模式](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Psycopg prepared statements](https://www.psycopg.org/psycopg3/docs/advanced/prepare.html)
- [Vercel 環境變數](https://vercel.com/docs/environment-variables)

獨立檢驗用指令見 [CLAUDE_REVIEW_PROMPT.md](CLAUDE_REVIEW_PROMPT.md)。
