# 開發狀態與工作邊界

> 2026-10-30：Document AI 三模組由 ADMIN 同步到 API，兩站逐位元組比對；新增 Pillow 與三模組離線回歸，環境名稱不增加。既有上傳辨識仍為 OCR→Groq、共用 25 秒預算；新增 evidence／Few-Shot 尚未接入業務流程。見 [同步檢驗](DOCUMENT_AI_SYNC_20261030.md)。

更新：2026-10-29。本文是目前狀態摘要，歷史聊天、檔名或 TODO 不代表功能完成；修改能力時必須同步本表、實作與測試。

## 本站角色

API 維持自己的 Vercel／DB 模組，是共用 Schema／Alembic 的唯一管理者。已有：DB 模組、Vercel 模組（檔案存取）、執行環境設定檢查、Cron 驗證、DTO／Protocol、前台登入 Session（/api/v1/auth）、手機上傳發票（辨識、查重、送出，見下表）；尚未完成：發票列表／詳情、一般 CRUD Repository／Service 與部門功能授權；排程 job 為 stub。

## 共同狀態（三站相同）

| 能力 | 狀態與證據 |
|---|---|
| AI 規範入口 | AGENTS.md（三站架構、共同規則、本站現況）＋ CLAUDE.md 匯入；2026-10-26 已提交並 Push 至 feature/python-web |
| 契約／分層檢查 | scripts/check_project.py + contracts/project-contract.json；只做無副作用靜態分析 |
| 本機三站／手機 HTTPS | InvoiceGuard-STARTUP 的 SETUP.cmd／START.cmd；三站各在自己的 CMD 視窗執行並自動重載本站 app/ 的 Python |
| 本機雲端設定 | START 以 Vercel CLI 讀取 ADMIN／API 各自專案的 Production 設定，把 DATABASE_URL、S3_*、SUPABASE_STORAGE_BUCKET 注入本機該站程序（2026-10-25 核定）；ADMIN 與 API 另各自注入自己專案的 GOOGLE_CLOUD_PROJECT_ID、GOOGLE_CLOUD_LOCATION、DOCUMENT_AI_PROCESSOR_ID、GOOGLE_SERVICE_ACCOUNT_JSON、GEMINI_API_KEY、GROQ_API_KEY（API 2026-10-28、ADMIN 2026-10-29 核定，不視為本機禁用機密；ADMIN 缺 AI 設定時 START 只提示、照常啟動）；前台不取得。本機 ADMIN／API 的資料就是正式資料 |
| 共用常數 | app/core/constants.py（2026-10-26，三站相同）：正式／本機網址、網站名稱、圖示、搜尋引擎設定 |
| 搜尋引擎 | 三站 noindex：網頁 meta 與 vercel.json 的 X-Robots-Tag（後者部署後生效）；robots.txt 不封鎖抓取 |
| 模組 | ADMIN／API 的 DB 模組（app/db）與 Vercel 模組（檔案存取，app/integrations/supabase_storage.py）可直接操作正式 DB／Storage；ADMIN 的 /dev 示範檔案使用的就是這兩個模組。AI 模組（integrations 的 document_ai／gemini／groq／chat_models）2026-10-29 起兩站同版，由兩站的 tests/unit/test_shared_integrations.py 比對一致。第一階段契約 DataService／FileService／get_storage_client() 尚未接線，呼叫時拋出 ModuleNotReadyError |
| Schema／部門 | 既有 ORM 為草案；StoredFile、version 與部門模型尚待設計，未與雲端結構核對 |
| 授權 | APP_ENV=local 不跳過登入（唯一例外：ADMIN 本機 /dev 示範檔案）；OperationContext 不可直接信任請求宣告的身分／權限 |
| 模型整合 | API 已串接：Document AI（OCR）與 Groq gpt-oss（20B／120B）用於手機與電腦上傳辨識（2026-10-29）；Gemini 模組已建、對話待儲值後驗證。ADMIN 有同版 AI 模組與設定（2026-10-29），尚未接線任何功能；前台不直接串接模型；舊 Blob 保留名稱不代表遷移 |
| CI | 已有單站無公司密鑰工作流程（.github/workflows/project-checks.yml）；2026-10-26 已 Push 至 feature/python-web，遠端執行結果須到 GitHub Actions 確認 |

## 本站狀態

| 能力 | 狀態與證據 |
|---|---|
| DB 模組 | 程序有合法 DATABASE_URL 即可使用（本機與雲端），TLS／NullPool 保留；`db/session.py`、`db_connection_repository`／`db_connection_service`（唯讀 SELECT 1，目前只有測試呼叫）。2026-10-25 以 START 注入的 API 自己的值實測 SELECT 1 = 1 |
| Vercel 模組（檔案存取） | `app/integrations/supabase_storage.py`（與 ADMIN 位元組相同）；API venv 實測上傳／列表／下載／移動／刪除成功。第一階段契約 FileService 尚未接線 |
| 本機取得設定 | START 經 Vercel CLI 讀取 invoice-guard-ai-api 專案並只注入 API 程序：DB／S3 六項加 Google AI 五項與 GROQ_API_KEY（服務帳號 JSON 由 START 壓成單行；ADMIN 不取得）。2026-10-28 以 START 的讀值函式實測十一項皆取得，注入獨立 API 程序後環境檢查通過、DB SELECT 1 = 1、Document AI Processor 為 OCR_PROCESSOR／ENABLED，Gemini Key 唯讀列模型 200 |
| Google AI 模組 | `app/integrations/document_ai.py`（OCR）、`app/integrations/gemini.py`（對話），2026-10-28；離線測試 45 案。以 START 相同注入實測：Document AI 辨識前台 `app/static/img/reference_invoice.jpg` 成功（1 頁、29 行、平均信心 0.915）。Gemini 的 Key、模型（gemini-3.8-flash）與請求格式經免費的 models.get／countTokens 確認正確，但 generateContent 回 402 RESOURCE_EXHAUSTED「預付額度已用完」，需在 AI Studio 儲值後再驗證對話。Document AI 由手機上傳辨識使用（見「手機上傳發票」），Gemini 尚無端點 |
| Groq 模組 | `app/integrations/groq.py`（2026-10-28）：預設／識別用 gpt-oss-20b，advanced=True 或 RAG／討論用 gpt-oss-120b；離線測試 29 案。實測：使用者範例 qwen 呼叫成功；Document AI OCR（reference_invoice.jpg）→ gpt-oss-20b（recognition、JSON 模式）回傳合法 JSON，字軌 TL、號碼 28281500、三聯式正確，空白欄位為 null，但「一〇八年九、十月份」的 tax_period 回成 202109（應為 201909），民國年換算不可直接信任模型。START 把 GROQ_API_KEY 注入 API（2026-10-28 核定；重新 SETUP／START 後生效）；2026-10-29 起 ADMIN 也由 START 從自己的 Vercel 專案注入同一組 AI 設定，兩站各用各的值 |
| 手機上傳發票 | 2026-10-29，依 v1.4（使用者已在正式 DB 執行 v1.3→v1.4 ALTER）。`/api/v1/invoices/recognize`：每次請求經 auth_service 核對 Session；JPG／PNG 或單頁 PDF（電腦上傳頁）4 MB 以內（以檔頭判斷；PDF 超過一頁回 400 INVOICE_PDF_MULTIPAGE，依 v1.4 invoice_files 每張發票一個目前檔案）；先確認 Storage／Document AI／Groq 已設定，再寫 `ai_recognition_logs`（pending）→ 檔案存 invoices bucket `{user_id}/INVOICES_{台灣時間 YYYYMMDDHHMMSS}_{recognition_id}.jpg|png|pdf` → OCR → gpt-oss-20b（JSON；OCR＋模型總時限 25 秒，每次呼叫以剩餘時間為逾時上限，剩餘 8 秒以上才改 120B 再試一次）→ `utils/invoice_format` 換算民國日期、期別（偶數月 YYYYMM）、金額、字軌號碼、統編檢查碼，產生檢核提醒（不阻擋）→ 記錄 success／partial／failed。`/check-duplicate`：字軌＋號碼＋賣方統編，已作廢（voided）不計。`POST /api/v1/invoices`：辨識 1 小時內、本人、未送出才可送出；advisory lock 後再查重，重複回 409；同交易建立 invoices（pending_department_approval、submission_round 1、部門取 Session 選取部門、validation_results）、invoice_items、invoice_files（指向辨識時的同一物件）、與 AI 原值不同欄位的 invoice_field_reviews（使用者修改過的欄位，含刪除的 AI 明細 `deleted_item_{n}`，供審核勾選）、invoice_changes（核對頁逐次修改，含改了又改回；前台紀錄須從 AI 原值接續到送出值，否則 400 INVOICE_CHANGES_INVALID；有差異沒紀錄的欄位由 API 補一筆）、invoice_status_history，回填辨識紀錄；明細以 source_line_no 對應 AI 明細，回應附 modified_fields。逾時未送出的影像在之後的辨識請求順帶刪除（每次最多 10 筆）並記 source_deleted_at，沒有排程。離線測試 95 案（替身，不連正式服務）；repository SQL 以 PostgreSQL 解析器檢查語法；尚未在正式 DB／Storage 實測，需使用者以手機經 START 測試。必填檢核（2026-10-29）：`POST /api/v1/invoices/check-required`（Bearer Session，body 為核對頁目前欄位值、可缺漏）一次回傳 InvoiceSubmitRequest 的全部必填缺漏 `{required_complete, missing:[{field, code:"required_missing", message, line_no}]}`；必填規則只有 InvoiceSubmitRequest 一份（services/invoice_required_service.py 以該模型驗證，再依原始值把不存在、null、空白字串含全形空白歸為缺漏；選填欄位、格式錯誤與內部欄位 recognition_id／changes 不列入），不新增 invalid 清單；required_complete 只代表沒有必填缺漏，不代表格式、金額或整體資料有效；必填檢核 Service 本身不進行資料庫讀寫；API 請求仍經過 Session 驗證，既有 Session 驗證流程可能更新最後活動時間並提交資料庫交易。正式提交 POST /api/v1/invoices 的 Pydantic 422 與寫入流程不變。離線測試以替身執行，不連正式 DB、Storage 或外部服務。業務警示（2026-10-30，分支 feature/c-required-fields-check）：新增 `POST /api/v1/invoices/check-warnings`（需登入；輸入同 POST /invoices、欄位可缺漏或格式錯誤，回 `{warnings:[{field,code,message}], checked_on}`；每個欄位各自驗證，缺漏或格式錯誤的欄位視為未知、相關警示不判斷；驗證 Session 仍會讀 Session 資料表，其餘不寫入任何資料）與新警示 `invoice_date_future`（發票日期晚於 Asia/Taipei 當天，訊息「發票日期晚於今天，請核對原始發票。」，`today_taipei()` 可注入時鐘）；預覽與正式送出共用 `future_date_warnings` 與既有 `_consistency_warnings`（稅率、容差與公式未改），POST /invoices 送出時重新計算並寫入既有 `invoices.validation_results.warnings`（JSON 結構不變，未改 Schema 或 migration）。警示只提醒，不阻擋送出，也不產生額外 422；`/recognize` 的辨識警示未改。ADMIN 目前沒有讀取或顯示 `validation_results` 的程式，後台審核者看到警示屬跨組待整合。離線測試通過（替身 DB、Storage、AI），未連真實 DB 驗證寫入。 |
| Cron | `/api/cron/*` 需 CRON_SECRET；本機不載入該機密，只以測試替身驗證；job 為 stub |
| 前台登入 | `/api/v1/auth/login`／`me`／`logout`：`auth_service` → `user_repository`／`session_repository`（固定 SQL；v1.3 `user_accounts`、`user_profiles`、`v_user_departments`、`user_sessions`）。Argon2id 用 pwdlib（與 ADMIN 同版）。登入資格依 v1.3 後續接線第 2 點；Session 預設主要部門，有效 `SESSION_EXPIRE_MINUTES`（預設 60）；登入成功寫 `last_login_at`、密碼錯誤 `failed_login_count`+1。`/me` 每次核對摘要、到期、撤銷、`credential_version`、帳號／profile、選取部門並更新 `last_seen_at`。2026-10-28 離線測試通過；使用者以手機經 START 實測登入成功（正式 DB） |

開發者不取得 Vercel／Supabase 管理員權限；雲端變數更新後，雲端需重新部署、本機需重新 START 才會套用。部署、執行 migration、修改正式資料、Commit／Merge／Push 需使用者明確授權。

## 文件權責

AGENTS.md 說明三站架構、閱讀順序與共同約定；README 說明使用方式；ARCHITECTURE／CODING_CONVENTIONS 管目錄與格式；ADMIN/API MODULE_CONTRACT 管型別與未實作邊界；API 的 app/db/README.md 管 Schema 權威。若文件與實際程式衝突，先指出並對齊，不能擅自繞過保護。單站 clone 無兄弟專案時仍可執行本站檢查；不得為讀取兄弟站而索取管理員 Token。

精確檢查與限制見 [PROJECT_CHECKS.md](PROJECT_CHECKS.md)，實測結果見 [TEST_REPORT.md](TEST_REPORT.md)，修正紀錄見 [REVIEW_FIX_LOG.md](REVIEW_FIX_LOG.md)。
