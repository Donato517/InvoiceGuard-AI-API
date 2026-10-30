# InvoiceGuard-AI-API：AI 開發入口

> 2026-10-30 使用者核定：新增 `app/integrations/vertex_embedding.py`（Agent Platform 向量），以現有服務帳號呼叫 `gemini-embedding-2`、1536 維，不使用 GEMINI_API_KEY；ADMIN 與 API 逐位元組相同，由 `tests/unit/test_shared_integrations.py` 比對，取代下文「四個 AI 模組檔」的範圍。只提供模組，尚未接線功能；Vercel 與 START 不需新增設定。開發 RAG 前先讀 [RAG 開發說明](docs/RAG_DEVELOPMENT.md)。

> 2026-10-30 最新核定：依使用者要求由 ADMIN 同步 Document AI 呼叫、影像證據與 Few-Shot 三模組，兩站三檔須逐位元組相同；新增 Pillow，沿用本站既有設定。舊上傳 OCR→Groq 流程保留，evidence／Few-Shot 尚未接線業務功能。見 [同步檢驗](docs/DOCUMENT_AI_SYNC_20261030.md)。

本站是後端 API，使用 Python 3.12、FastAPI、SQLAlchemy／psycopg；ASGI 入口為 `app.main:app`。負責前台 API、第三方串接與排程，並擁有自己的 Vercel／DB 模組。登入授權與一般資料／檔案服務的完成狀態須讀狀態文件，不能把契約或 TODO 當成實作。

依序閱讀：`README.md` → `docs/DEVELOPMENT_STATUS.md` → `docs/ARCHITECTURE.md` → `docs/CODING_CONVENTIONS.md` → `docs/MODULE_CONTRACT.md` → `docs/API_CONVENTIONS.md`。資料存取另讀 `app/db/README.md`；環境設定另讀 `docs/ENVIRONMENT_ISOLATION.md`。

本站分層為 `routers → services → db/repositories → db/models`，第三方呼叫集中 `app/integrations/`，排程入口沿用 `app/jobs/`。Service 控制交易與權限邊界，repository 不 commit。API 是共用 Schema 與 Alembic 的唯一管理者；結構修改須先同步 ADMIN Model／契約；建立 migration 檔屬一般開發，執行需使用者明確授權。DB 模組與設定檢查不代表真實 DB／Storage 連線已通過。

## API 現況（2026-10-29）

- DB：程序有合法 `DATABASE_URL` 即可使用（本機與雲端皆可，仍驗證格式與 TLS）；本機值由 START 注入，連的是正式 DB。`db_connection_repository`／`db_connection_service` 提供唯讀 SELECT 1 檢查（目前只有測試呼叫，沒有路由）。
- Vercel 模組（檔案存取）：`app/integrations/supabase_storage.py`，與 ADMIN 相同，修改時兩站同步；本機值由 START 注入，連的是正式 Storage。
- 前台登入：`/api/v1/auth/login`、`/me`、`/logout` 依 v1.3 建立、核對、撤銷 `user_sessions`（DB 只存 Token 的 SHA256 摘要），密碼以 pwdlib Argon2id 驗證；帳號與部門關聯沿用 ADMIN `/accounts` 維護的資料。2026-10-28 離線測試通過，使用者以手機經 START 實測登入成功（正式 DB）。
- Google AI 模組（2026-10-28）：`app/integrations/document_ai.py`（Document AI OCR）、`app/integrations/gemini.py`（Gemini 對話），只負責呼叫與解析、不寫 DB；Document AI 由手機上傳辨識使用，Gemini 尚無端點。Document AI 實測成功；Gemini 因 AI Studio 預付額度用完，對話實測尚未完成。另有 `app/integrations/groq.py`（Groq gpt-oss：預設／識別 20B，RAG／討論／進階備用 120B），OCR→20B 發票 JSON 已實測；START 把 Google AI 五項與 GROQ_API_KEY 注入本機 API（2026-10-29 起 ADMIN 也由 START 注入自己 Vercel 專案的值，兩站各用各的；ADMIN 有同版 AI 模組，與本站由 tests/unit/test_shared_integrations.py 比對）。
- 手機上傳發票（2026-10-29，v1.4 結構）：`POST /api/v1/invoices/recognize`（JPG／PNG 或單頁 PDF，4 MB 以內；檔案存 invoices bucket `{user_id}/INVOICES_{台灣時間 YYYYMMDDHHMMSS}_{recognition_id}.{副檔名}` → Document AI → Groq 20B，失敗且剩餘時間足夠時 120B 再試一次，OCR＋模型總時限 25 秒 → 程式換算與檢核，寫 `ai_recognition_logs`）、`POST /api/v1/invoices/check-duplicate`、`POST /api/v1/invoices`（建立發票，狀態 pending_department_approval；使用者修改過的欄位寫 `invoice_field_reviews` 供審核標示，核對頁的逐次修改寫 `invoice_changes`）。未送出的影像保留 1 小時，之後的辨識請求順帶清理。部門功能權限尚未接線。發票列表／詳情仍為 TODO；`app/jobs/` 的排程為 stub。
- Cron：`CRON_SECRET` 在本機屬禁用機密，本機無法以 Authorization 標頭呼叫 `/api/cron/*`，以測試替身驗證。
- Migration：建立 migration 檔屬一般開發；執行（`alembic upgrade`）需使用者明確授權。結構變更須同步 ADMIN Model 與契約快照。

<!-- shared-rules:start -->
## 三站架構

- 能串聯雲端 DB／Storage 的只有 ADMIN 與 API。
- `InvoiceGuard-AI`（前台）：使用者網站；不連 DB、Storage 或模型服務，伺服器端經 `app/clients/` 以 `API_BASE_URL` 呼叫 API 平台串聯雲端；不持有公司機密。
- `InvoiceGuard-AI-ADMIN`（後台）：管理網站；以自己的 DB 模組與 Vercel 模組直接串聯雲端，不經 API 平台。
- `InvoiceGuard-AI-API`（後端 API）：供前台伺服器呼叫的 REST API、第三方串接與排程；以自己的 DB 模組與 Vercel 模組串聯雲端；共用 DB Schema 與 Alembic 的唯一管理者。
- ADMIN／API 的模組：DB 模組 `app/db`；Vercel 模組（檔案存取）`app/integrations/supabase_storage.py`；AI 模組 `app/integrations/document_ai.py`（Document AI OCR）、`gemini.py`、`groq.py` 與共用的 `chat_models.py`（2026-10-29 起兩站同版；ADMIN 只提供模組，尚未接線功能）。`app/integrations/vercel.py` 只是執行環境資訊與設定檢查。
- `/dev` 是示範檔案，不是串聯路徑；示範的就是上述模組：ADMIN `/dev/accounts` 示範 DB 模組、`/dev/files` 示範 Vercel 模組，只在本機開放。API 也可以有 `/dev` 示範檔案，但本機開發與前台都不串接 API 的 `/dev`。
- 三站各自部署於 Vercel：前台 `https://invoice-guard-ai.vercel.app`、API `https://invoice-guard-ai-api.vercel.app`、ADMIN `https://invoice-guard-ai-admin.vercel.app`。三站共用的公開網址、網站名稱、圖示與搜尋引擎設定集中在 `app/core/constants.py`。
- 三站可互相連結，但一律不被搜尋引擎收錄：網頁 `<meta name="robots">` 與 `vercel.json` 的 `X-Robots-Tag` 為 `noindex, nofollow`；`/robots.txt` 不封鎖抓取，否則搜尋引擎讀不到 noindex。
- 三站內容相同、修改時須同步三站的檔案：`app/core/environment.py`（由 `check_project` 快照比對）、`app/core/constants.py`、`app/routers/robots.py`、`tests/unit/test_constants.py`（後三者手動同步，檢查程式不比對）；ADMIN 與 API 的 `app/integrations/supabase_storage.py` 與四個 AI 模組檔亦相同，由兩站相同的 `tests/unit/test_shared_integrations.py` 在兩站同目錄時逐位元組比對。
- 功能完成度以各站 `docs/DEVELOPMENT_STATUS.md` 與實際程式為準；本機日常啟動見下方「本機入口」。

## 共同規則

- 使用者最新的明確指令優先；先讀此入口，再讀上述文件與目標程式。文件若與程式衝突，指出差異並修正對齊，不能把規劃或範例當成已完成功能。
- 三個 Repository 固定命名為 `InvoiceGuard-AI`、`InvoiceGuard-AI-ADMIN`、`InvoiceGuard-AI-API`。沿用既有 Python 3.12／FastAPI 架構，UI 沿用 Jinja2／HTMX；不得另建框架或假設新的 API 入口。
- ADMIN 與 API 各自保有 Vercel／DB 模組。ADMIN 依既有分層使用自己的 DB，不擅自改為 API 代理；API 是共用 DB Schema 與 Alembic 的唯一管理者。ADMIN Model 必須與 API 一致，不能自行更改表結構。
- ADMIN／API 的第一階段契約 `DataService`、`FileService`、`get_storage_client()` 尚未接線，呼叫時拋出 `ModuleNotReadyError`；不得用假成功代替實作。

## 設定與安全邊界

- 業務程式一律從 `app.core.config.settings` 取得設定，不自行讀取 `.env`、列印環境變數或新增任意設定透傳。公開設定須依核定欄位與驗證規則擴充。
- 公司機密（DB 密碼、S3 Key、模型 Key、Supabase secret key、session／cron secret）由雲端管理，不放 Git、測試報告、日誌、URL 或公開設定端點；測試只用明確的合成假值與替身。
- 本機例外（2026-10-25 使用者核定，2026-10-28、2026-10-29 擴充）：START 以 Vercel CLI 讀取 ADMIN／API 各自專案的 Production 設定，把 `DATABASE_URL`、`S3_*`、`SUPABASE_STORAGE_BUCKET` 注入本機該站程序記憶體；ADMIN 與 API 另各自注入自己專案的 Google Document AI／Gemini 設定（`GOOGLE_CLOUD_PROJECT_ID`、`GOOGLE_CLOUD_LOCATION`、`DOCUMENT_AI_PROCESSOR_ID`、`GOOGLE_SERVICE_ACCOUNT_JSON`、`GEMINI_API_KEY`）與 Groq 金鑰（`GROQ_API_KEY`）（API 2026-10-28、ADMIN 2026-10-29 核定；ADMIN 只有 DB／S3 為啟動必要，AI 設定缺少時 START 只提示）；前台不取得。這些是必要設定，值只存在 START 啟動的該站程序記憶體（不經 START、不在該站 venv 程序內就取不到），不視為本機禁用機密；START 未注入的其他公司機密出現在本機程序環境時，站台仍拒絕啟動。
- 因此本機 ADMIN／API 連到的是正式（Production）DB 與 Storage，本機寫入就是正式資料寫入。`APP_ENV=local` 不能繞過登入、部門權限或正式 API 驗證；唯一例外是 ADMIN 只在本機開放的 `/dev` 示範檔案。
- 未經使用者明確授權，不部署、不執行 migration、不修改正式資料、不 Commit／Merge／Push；保留既有分支、未提交修改及索引，不執行 reset 或覆蓋他人工作。建立 migration 檔屬 API 的一般開發，執行仍需授權。

## 檔案與格式

- 僅在本站核定的既有目錄與分層內擴充：HTTP 入口放 `app/routers/`，無狀態工具放 `app/utils/`；ADMIN／API 的資料契約放 `app/schemas/`、業務放 `app/services/`、外部服務放 `app/integrations/`。前台只使用 core、utils、clients、routers、static、templates，不建立 schemas、DB 或 service 目錄，不因其他站有此目錄就自行新增。
- ADMIN／API 的 DB 查詢放 `app/db/repositories/`、定義放 `app/db/models/`；交易由 service 控制，repository 不 `commit`。Router 不直接操作 DB／Storage／模型；core／utils 原則上不反向依賴 router／service，既有 DI／例外適配等精確例外以 `docs/PROJECT_CHECKS.md` 為準，不得擴大允許範圍。
- 前台與 ADMIN 的 UI 樣板放 `app/templates/`，公開 CSS／JS／圖片才放 `app/static/`；API 只回 JSON，沒有樣板與靜態檔目錄。實際上傳、機密、私人文件及 runtime 檔不得放 static 或版本控制。
- 暫存檔沿用 `app/utils/file_utils.py` 的受控暫存生命週期，不自行拼接使用者路徑；永久檔案的 key／權限／刪除政策須先依契約明確定義，不自行決定。
- Python 模組／函式／變數用英文 snake_case，類別用 PascalCase；中文說明使用繁體中文。Python 檔頭須有用途與模組 docstring，所有函式參數與回傳值加型別；公開函式寫繁中 docstring，格式依 `CODING_CONVENTIONS.md`。樣板使用 Jinja 備註描述 route／context。
- 契約變動須同步 Schema、Protocol、文件與測試；不可直接改快照、fixture 或允許清單來掩蓋失敗。跨站副本先確認來源，再同步及檢查差異。

## 本機入口

啟動器的 `SETUP.cmd` 從三個固定名稱 Repository 的共同上層推導並記錄 `PROJECT_ROOT`，不在程式中寫死個人絕對路徑。從本站 PowerShell 執行：

```powershell
# 初次設定：建立／使用三站各自的 venv 並安裝依賴（相容指令：..\InvoiceGuard-STARTUP\START.cmd setup）
..\InvoiceGuard-STARTUP\SETUP.cmd
# 日常啟動：三站、本機別名及電腦／手機共用的臨時 HTTPS；不需 --mobile，保留視窗直到停止
..\InvoiceGuard-STARTUP\START.cmd
```

START 就緒後自動開啟當次 HTTPS 的 `/login`，電腦與手機都直接看到前台原有的 Email／密碼登入表單；不需要開發存取碼，也不會出現額外的瀏覽器帳密視窗，網站登入、部門權限與 API 驗證照舊。開發電腦另有本機別名 `http://invoiceguard-ai.localhost:8080/login`（307 轉至同一次 HTTPS 的 /login）、`http://invoiceguard-ai-admin.localhost:8080/`、`http://invoiceguard-ai-api.localhost:8080/health`；ADMIN／API 只供開發電腦，手機不能使用電腦的 localhost 或 `.localhost`。

三站各在自己的 CMD 視窗執行，存檔 `app/` 內的 Python 只重載該站。在某站視窗按 Ctrl+C 只停止該站，貼上視窗顯示的啟動指令即可重啟；在 START 總控視窗按 Ctrl+C 才停止全部。啟動器只停止自己啟動的服務，不終止其他 Python 或 cloudflared 程序。

## 無公司密鑰驗證

從本站根目錄依序執行；所有測試不得呼叫正式服務：

```powershell
.\.venv\Scripts\python.exe -B scripts/check_project.py
.\.venv\Scripts\python.exe -B -m pytest -q
.\.venv\Scripts\python.exe -B -m ruff check app tests scripts
.\.venv\Scripts\python.exe -B -m ruff format --check app tests scripts
.\.venv\Scripts\python.exe -B -m app.core.environment --check
```

`check_project.py` 可在只有本站時獨立檢查；若三站都在同一根目錄，可加 `--project-root <root>`，比對跨站非機密契約快照。這是額外一致性檢查，不是下載或掃描公司機密。失敗時先查原因、補有意義的回歸測試，再修正；不能任意放寬規則。

完成後回報目標檔案、行為差異、實際執行的指令與結果、未驗證部分。發現問題並修正時，在既有 `docs/REVIEW_FIX_LOG.md` 記錄問題、原因、處理檔案與驗證結果；沒有跑過的測試不能寫通過。
<!-- shared-rules:end -->
