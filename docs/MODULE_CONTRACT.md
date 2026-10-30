# API Vercel / DB 模組與契約

> 2026-10-30：由 ADMIN 同步 Document AI 三模組並保留原 OCR 介面；Pillow 為新增必要依賴，環境名稱不變。後續 evidence／Few-Shot 的來源版本與授權責任沿用 ADMIN 契約，未自動啟用於既有上傳。見 [同步檢驗](DOCUMENT_AI_SYNC_20261030.md)。

AI 入口見 [AGENTS.md](../AGENTS.md)／[CLAUDE.md](../CLAUDE.md)；
本文件保留第一階段的實作範圍與歷史說明，目前能力以 [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md) 為準。
新增或同步契約後執行 [無密鑰契約／分層檢查](PROJECT_CHECKS.md)。

第一階段完成設定驗證、介面契約與不需公司密鑰的單元測試；其後加入本機也可使用的 DB 模組與 Vercel 模組（檔案存取，`integrations/supabase_storage.py`）（見 DEVELOPMENT_STATUS）。
部署、migration、seed 與正式資料寫入需使用者明確授權。

## 能力狀態

| 能力 | 狀態 |
|---|---|
| `get_platform()` 執行描述 | 已實作，沒有密鑰或 SDK 用戶端 |
| `check_configuration()` / CLI | 已實作靜態檢查，不連網 |
| DB Engine 參數與 Session 關閉 | 已實作設定保護；2026-10-25 實測 SELECT 1（見 DEVELOPMENT_STATUS） |
| 檔案與發票 CRUD DTO / Protocol | 已定義，不能直接操作真實資料 |
| 手機上傳發票 | 已實作（2026-10-29）：`app/schemas/invoice_upload.py`、`services/invoice_upload_service.py`、`db/repositories/invoice_repository.py`／`recognition_repository.py`（v1.4 固定 SQL），不經 DataService／FileService；部門功能權限尚未接線 |
| 第一階段契約：Storage / FileService / DataService 工廠 | 尚未接線，拋出 ModuleNotReadyError，不假裝成功 |
| 既有 Cron 驗證 | 保留 hmac.compare_digest；SecretStr 只在內部解封，沒有密鑰時仍拒絕 |
| 422 驗證錯誤 | 不回傳 input / ctx，不反射原始機密值 |
| 前台登入、部門權限 | 登入／目前登入者／登出已改用 v1.3 Session（見 DEVELOPMENT_STATUS）；部門功能權限尚未實作；CRON_SECRET 不能當使用者登入憑證 |
| Vercel 模組（檔案存取） | `integrations/supabase_storage.py`：上傳、下載、列表、移動、刪除 |
| Google Document AI 模組（OCR） | `integrations/document_ai.py`：`DocumentAIClient.from_settings().process(content, mime_type, timeout_seconds=None)` 回傳全文、各頁各行文字／信心值／正規化位置框與原始回應；`describe_processor()` 唯讀查 Processor。服務帳號換權杖並在程序內暫存；錯誤為 `document_ai_*` 固定代碼。不寫 DB |
| Groq 模組（對話） | `integrations/groq.py`：`GroqClient.from_settings().chat(messages, system_instruction=None, purpose="default", advanced=False, json_output=False, max_tokens=None, timeout_seconds=None)`；`timeout_seconds` 為呼叫端剩餘時間，不超過預設 45 秒，0 以下直接回 `groq_timeout`。情境：default／recognition 用 `GROQ_DEFAULT_MODEL`（gpt-oss-20b），`advanced=True` 改用 `GROQ_ADVANCED_MODEL`（gpt-oss-120b，進階備用）；rag／discussion 用 120B。`json_output` 要求只回 JSON 物件；回答不含推理過程；錯誤為 `groq_*` 固定代碼。不寫 DB |
| Google Gemini 模組（對話） | `integrations/gemini.py`：`GeminiClient.from_settings().chat(messages, system_instruction=None)` 回傳回答、模型、結束原因與 token 用量；Key 只放標頭；模型由 `GEMINI_MODEL` 設定；錯誤為 `gemini_*` 固定代碼（Google status 優先於 HTTP 狀態碼）。不寫 DB |
| 真實 CRUD、業務檔案端點 | 一般 CRUD（發票列表／詳情等）尚未實作；目前會寫入業務資料的 HTTP 端點只有手機上傳發票（`POST /api/v1/invoices/recognize`、`POST /api/v1/invoices`） |
| StoredFile 表、發票 version 欄位 | 尚未建立，API 後續統一規劃 Schema；ADMIN 同步 |

第一階段未變更 ORM 模型與 migration 版本。
Alembic 的 `app/db/migrations/env.py` 已補強 TLS 與連線逾時設定，並共用 `resolve_ssl_mode()`；這是設定原始碼修正，未執行 migration，也未變更資料表或正式資料。
原有 Blob 僅為 TODO；第一階段先定義供應商中立契約，之後加入 Vercel 模組（Supabase S3）。

## 匯入方式

Vercel 模組（檔案存取；示範與正式功能都使用）：

```python
from app.integrations.supabase_storage import S3StorageClient

storage = S3StorageClient.from_settings()
```

設定檢查與第一階段契約（`get_data_service()`／`get_file_service()` 尚未接線）：

```python
from app.integrations.vercel import get_platform, check_configuration
from app.schemas.invoice import InvoiceCreate, InvoicePatch, InvoiceUpdate
from app.schemas.files import UploadFileRequest, MoveFileRequest, DeleteFileRequest
from app.services.data_service import DataService, get_data_service
from app.services.file_service import FileService, get_file_service
```

匯入不建立連線。這裡尚未接線的是第一階段 `get_data_service()`／`get_file_service()`，呼叫時明確拒絕建立服務。
`check_configuration()`／`get_platform()` 已實作設定檢查與執行描述；`S3StorageClient.from_settings()` 已可建立同一個 Vercel 檔案存取用戶端。
不要將 Protocol 的存在或測試替身當成 CRUD、授權、metadata 與交易協調已實作。

## 設定

執行期設定集中在 `app.core.config.settings`；預設不讀 `.env` 或 secrets 目錄。
所有機密以 SecretStr 保護 repr / JSON，這不是加密，也不允許記錄 get_secret_value()。
`.env.example` 的密鑰保持空白；禁止 vercel env pull 或把公司連線字串寫入檔案。本機只由 START 把核定的 DATABASE_URL／S3_* 注入程序記憶體（見 [環境隔離](ENVIRONMENT_ISOLATION.md)）。

| 設定 | 適用能力／預設 |
|---|---|
| APP_ENV / DEBUG | local / false；雲端需 preview 或 production 且 DEBUG=false。Vercel 不會自動設定 APP_ENV；與 VERCEL_ENV 不一致（含未設定）時本站拒絕啟動，所有路由都無法使用 |
| MODULE_BACKEND | auto；在 Vercel 選 cloud，其餘 remote，不替代身分驗證 |
| REMOTE_API_BASE_URL | 保留的本機遠端模式欄位，目前沒有消費端；START 啟動時為空值 |
| DATABASE_URL | DB 必填機密；本機由 START 注入 Production 值（核定例外）；不自動使用 POSTGRES_URL |
| DATABASE_URL_UNPOOLED | 保留既有 migration 設定與優先順序；本機屬禁用機密；執行 migration 需使用者明確授權 |
| DB_POOL_MODE | transaction / session / direct；預設 transaction，管理者需確認實際模式 |
| DB_SSL_MODE | require / verify-full；預設 require；verify-full 的 CA 另由管理者確認 |
| DB_CONNECT_TIMEOUT_SECONDS | 預設 5 秒，允許 1–30 秒 |
| SUPABASE_URL | 第一階段 `check_configuration("storage")` 使用的公開專案網址；S3StorageClient 不讀此欄位 |
| SUPABASE_STORAGE_BUCKET | S3StorageClient 使用的 Bucket 名稱，亦由第一階段靜態檢查驗證；真正存在與私有政策須另驗證 |
| SUPABASE_SECRET_KEY | 第一階段 storage 設定檢查要求的機密；S3StorageClient 不讀此欄位，使用 S3_ACCESS_KEY_ID／S3_SECRET_ACCESS_KEY |
| S3_ENDPOINT_URL / S3_REGION | Supabase S3 相容端點與區域；`integrations/supabase_storage.py` 使用。本機由 START 注入（2026-10-25 核定例外） |
| S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY | Supabase S3 金鑰；本機由 START 注入，不在本機機密拒絕清單。`check_configuration("storage")` 仍驗證 SUPABASE_URL／SUPABASE_STORAGE_BUCKET／SUPABASE_SECRET_KEY，不驗證 S3_*；這是第一階段靜態檢查，不是另一個 Storage 模組 |
| SESSION_EXPIRE_MINUTES | auth 能力驗證：1–1440 分鐘，預設 60；登入用 v1.3 Session，不需簽章金鑰（JWT_SECRET_KEY 不再使用） |
| CRON_SECRET | cron 能力：至少 16 字元；本機模式也不略過請求驗證 |
| GOOGLE_CLOUD_PROJECT_ID、GOOGLE_CLOUD_LOCATION、DOCUMENT_AI_PROCESSOR_ID、GOOGLE_SERVICE_ACCOUNT_JSON、GEMINI_API_KEY | Gemini 與 Document AI 設定；本機由 START 注入（2026-10-28 核定，不視為本機禁用機密，見 Settings.LOCAL_INJECTED_FIELDS）；`integrations/document_ai.py`／`gemini.py` 使用，建立用戶端時檢查格式（未新增 check_configuration 範圍） |
| GROQ_API_KEY | Groq 金鑰；`integrations/groq.py` 使用。列入 LOCAL_INJECTED_FIELDS；本機由 START 注入（2026-10-28 核定） |
| GROQ_DEFAULT_MODEL／GROQ_ADVANCED_MODEL | Groq 預設模型 openai/gpt-oss-20b、進階模型 openai/gpt-oss-120b（不是機密） |
| GEMINI_MODEL | Gemini 對話模型名稱，不是機密；預設 gemini-3.8-flash（gemini-2.5-flash 已不開放給新專案） |
| OPENAI_API_KEY | 雲端選填；模型服務尚未串接 |
| AI_API_KEY / EINVOICE_APP_ID / EINVOICE_API_KEY / BLOB_READ_WRITE_TOKEN | 保留既有名稱並遮罩，未啟用的整合不要求填寫 |
| VERCEL | 平台自動標記，不是認證憑證，不得用來保護公開 API |

API 不需要 ADMIN 的 SESSION_SECRET_KEY。雲端設定是否已儲存、憑證是否有效，均未連線核對。
一般開發者不取得 Vercel / Supabase 管理員權限。本機除 START 注入的 DATABASE_URL／S3_* 外，其他已知機密欄位非空會使本站拒絕啟動。
`app.db.session` 不限制執行位置：有合法 DATABASE_URL 即可建立 Engine（本機連的是正式 DB）。
Alembic migration 與應用程式共用 `resolve_ssl_mode()`，不得降級為明文；執行需使用者明確授權。

可檢查 local / database / storage / auth / cron / cloud；cloud 彙整 database、storage、auth、cron。
各能力檢查只要求該能力必要設定，例如 database 不要求模型、JWT 或 Cron 密鑰。
雲端變數變更需重新部署才套用；本機需重新 START 才會取得新值。
歷史第一階段未修改啟動器 PUBLIC_ENV；目前來源與允許欄位以 [環境隔離](ENVIRONMENT_ISOLATION.md) 及 `app/core/environment.py` 為準，不能任意增加公開 JSON 欄位。

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

與 ADMIN 沿用同一版資料／檔案契約；兩站各自有 DB 與 Storage 模組，本機由 START 注入各自設定直接連線，不將 ADMIN 改為只依賴 API 的資料層。


### 未來上傳傳輸的限制（尚未實作）

DTO 的檔案大小上限為 4 MiB（4,194,304 bytes），不是整個 HTTP request 的預算。
Vercel Function 請求／回應上限為 4.5 MB，multipart 邊界、欄位與 metadata 都必須計入；
未來 adapter／端點需驗證實際檔案與完整 body，不可以 Base64 編碼後仍假設 4 MiB 可以通過。
需要調整傳輸方式時另提設計。
參考 [Vercel Function 限制](https://vercel.com/docs/functions/limitations)。

## PowerShell 驗證

初次設定與日常啟動使用同層 `InvoiceGuard-STARTUP` 的 `SETUP.cmd`／`START.cmd`（手機 HTTPS 已包含在日常啟動），詳見 [README](../README.md)。
以下在 API 根目錄使用已建立的 Python 3.12 `.venv`，不必手動 activate 或每日重建：

```powershell
.\.venv\Scripts\python.exe -m app.integrations.vercel --check local
$LASTEXITCODE
.\.venv\Scripts\python.exe -B scripts/check_project.py
.\.venv\Scripts\python.exe -m pytest -q --basetemp=tmp/pytest
.\.venv\Scripts\python.exe -m ruff check app tests scripts
.\.venv\Scripts\python.exe -m ruff format --check app tests scripts
```

local 設定正常時 exit 0；靜態設定檢查失敗 exit 2。型別／列舉錯誤可在載入設定時直接拒絕。
預期 configuration_valid=true、connectivity_checked=false、operations_implemented=false。
remote_not_configured / contracts_only 警告屬預期，不能當成雲端連線或業務功能已通過。
若出現 cloud_secret_in_local，只回報欄位名稱，不要輸出或傳送原值。
`tmp/pytest` 是 pytest 專用暫存目錄，可在重跑時清理，勿存放其他檔案。

測試程序會清除已知繼承設定（S3_* 目前不在清除清單），使用合成假值、網路與 DB 阻擋器；Cron 工作使用 MagicMock。
Windows asyncio 僅放行 socketpair 的程序內 loopback，仍阻擋一般 localhost DB 與外部連線。
Windows AppContainer 可能阻擋程序內 socketpair；請在一般 PowerShell 執行，不放寬外部連線限制。
目前 Starlette 對 httpx 的淘汰警告另行列示，不視為測試失敗，也不擅自變更全站依賴版本。

日常 API 健康檢查為 <http://invoiceguard-ai-api.localhost:8080/health>。以下只供單站診斷，先關閉統一啟動器以免埠衝突；不啟動排程：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

開啟 http://127.0.0.1:8000/health 應顯示 status=ok。
根路徑 `/` 無首頁，預設 DEBUG=false 時 `/docs` 不開放；404 是正常行為。
以上不代表 DB / Storage 連線通過。

## 待完成

Google Document AI／Gemini／Groq 的業務流程（上傳辨識、欄位整理、ai_recognition_logs、知識庫問答）尚未實作。依序完成部門功能權限、共用 Schema、Repository / Service、第一階段契約（DataService／FileService）接線與受控 JSON 端點。
須另驗證跨使用者／部門拒絕、版本衝突、檔案內容、稽核與補償。
部署、migration、seed 與正式資料寫入需使用者明確授權。

## 官方依據

- [Supabase 連線模式](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Psycopg prepared statements](https://www.psycopg.org/psycopg3/docs/advanced/prepare.html)
- [Vercel 環境變數](https://vercel.com/docs/environment-variables)

歷史檢驗指令見 [CLAUDE_REVIEW_PROMPT.md](CLAUDE_REVIEW_PROMPT.md)。
