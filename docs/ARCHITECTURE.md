# 系統架構說明 — InvoiceGuard-AI-API

> 2026-10-30：integrations 新增與 ADMIN 相同的 document_ai_evidence／document_ai_fewshot，document_ai 升級為同一副本。既有 router／service／DB 分層與上傳流程未改；新增兩模組尚未接線。見 [同步檢驗](DOCUMENT_AI_SYNC_20261030.md)。

AI 先讀根目錄 [AGENTS.md](../AGENTS.md)（Claude 見 [CLAUDE.md](../CLAUDE.md)），
再依 [開發狀態](DEVELOPMENT_STATUS.md) 區分已完成能力與目標設計。
本文件描述分工，不代表外部服務或每個流程均已接線。日常三站啟動與全名別名見 [README](../README.md)，
無密鑰分層與契約檢查見 [PROJECT_CHECKS.md](PROJECT_CHECKS.md)。

## 1. 系統全貌

InvoiceGuard AI 由三個獨立的 Git repository 組成，**全部以 Python 撰寫**，各自部署為一個 Vercel Python Function：

```
      User                              Admin
       |                                  |
       v                                  v
┌──────────────────────┐        ┌──────────────────────────┐
│ InvoiceGuard-AI      │        │ InvoiceGuard-AI-ADMIN    │
│ FastAPI + Jinja2     │        │ FastAPI + Jinja2         │
│ Vercel Function (Py) │        │ Vercel Function (Py)     │
└──────────┬───────────┘        └─────────────┬────────────┘
           │ HTTPS + JSON (server side)       │
           ▼                                  │
┌──────────────────────┐                      │ SQL
│ InvoiceGuard-AI-API  │◀── Vercel Cron       │ (own DB module)
│ FastAPI              │                      │
│ Vercel Function (Py) │──▶ AI Model          │
└──────────┬───────────┘──▶ MOF e-Invoice API │
           │ SQL                              │
           ▼                                  │
┌──────────────────────┐                      │
│ PostgreSQL           │◀─────────────────────┘
└──────────────────────┘
```

| Repository | 角色 | 技術 | 資料存取 |
|---|---|---|---|
| InvoiceGuard-AI | 前台網站：使用者上傳發票、查看 AI 分析結果 | FastAPI + Jinja2 | 由伺服器端呼叫本 API，不直接連資料庫 |
| InvoiceGuard-AI-ADMIN | 後台網站：發票審核、使用者管理、排程與稽核紀錄 | FastAPI + Jinja2 | 自有 DB 模組，直接連同一個 PostgreSQL |
| **InvoiceGuard-AI-API**（本專案） | 後端 API：AI 分析、第三方串接、排程 | FastAPI | 自有 DB 模組 + Alembic |

外部服務規劃：PostgreSQL、AI 模型服務、財政部電子發票整合服務平台（MOF e-Invoice）。
原有 Vercel Blob 只是 TODO 骨架；Storage 改接 Supabase：Vercel 模組（檔案存取）`integrations/supabase_storage.py` 已有；第一階段契約 `storage_client` 工廠尚未接線。
保留原有 Blob 設定名稱，不代表已經執行供應商遷移或部署。

**資料庫共用規則**：後台直接存取同一個資料庫，但**資料表結構只能由本專案的 Alembic migration 變更**；
後台的 Model 是對應定義，需同步更新。流程見 [`app/db/README.md` 第 9 節](../app/db/README.md#9-共用此資料庫的專案)。

---

## 2. 分層架構

```
routers ──▶ services ──▶ db/repositories ──▶ db/models
               │
               └──▶ integrations（AI / 財政部 / Storage adapter）

jobs ──▶ services                 （排程重用同一套商業邏輯）
schemas：routers 與 services 之間傳遞的資料格式
core、utils：任何層都可使用
```

| 層 | 職責 | 不可以做的事 |
|---|---|---|
| `routers` | 接收參數、驗證、權限、呼叫 service、回傳 schema | 寫商業邏輯、直接查資料庫 |
| `services` | 商業邏輯、狀態流轉、**控制交易**（commit / rollback） | 處理 HTTP 細節（Request / Response） |
| `db/repositories` | ORM 查詢與寫入 | 商業判斷、`commit` |
| `db/models` | 資料表定義與 **Schema 備註** | 商業邏輯 |
| `integrations` | 呼叫外部 API、轉換格式 | 存取資料庫 |
| `jobs` | 排程流程（鎖、紀錄、分批） | 重寫 service 已有的邏輯 |
| `schemas` | Pydantic 請求 / 回應模型 | 存取資料庫 |
| `core` | 設定、安全、例外、日誌、相依注入 | 相依 services / routers |
| `utils` | 無狀態工具函式 | 相依 db / services |

**相依方向只能由上往下**，禁止反向 import（例如 repository 不得 import service）。

---

## 3. 目錄結構

```
InvoiceGuard-AI-API/
├── app/                          # 應用程式主套件
│   ├── main.py                   # ★ 進入點：建立 FastAPI app、註冊 middleware / 例外 / 路由（Vercel 自動偵測）
│   ├── core/                     # 全域核心
│   │   ├── config.py             #   設定公開入口（環境隔離由 core/environment.py 處理）
│   │   ├── constants.py          #   三站共用：網址（Vercel 用正式、本機用開發）、網站名稱、圖示、搜尋引擎 noindex
│   │   ├── environment.py        #   三站相同：環境隔離、本機機密拒絕（check_project 快照比對）
│   │   ├── module_errors.py      #   模組未就緒／設定錯誤例外（ModuleNotReadyError 等）
│   │   ├── deps.py               #   FastAPI 相依注入型別（DbSession、CurrentUser…）
│   │   ├── exceptions.py         #   業務例外類別 + 全域錯誤處理（統一錯誤格式）
│   │   ├── logging_config.py     #   日誌格式
│   │   └── security.py           #   Cron 驗證、JWT、密碼雜湊
│   ├── routers/                  # HTTP 路由層
│   │   ├── health.py             #   GET /health
│   │   ├── robots.py             #   GET /robots.txt（內容取自 core/constants.py；不收錄靠 X-Robots-Tag）
│   │   ├── cron.py               #   GET /api/cron/*（僅供 Vercel Cron）
│   │   └── v1/                   #   /api/v1/*
│   │       ├── auth.py           #     登入 / 登出 / 目前使用者（v1.3 Session）
│   │       └── invoices.py       #     前台發票（TODO）
│   ├── schemas/                  # Pydantic 請求 / 回應模型（common 分頁／錯誤格式、auth、user、invoice、data、files）
│   ├── services/                 # 商業邏輯層（data / file 為第一階段契約，未接線；db_connection 為唯讀 SELECT 1 檢查）
│   ├── integrations/             # ai_client、einvoice_client、document_ai（Google Document AI OCR）、gemini（Gemini 對話）、groq（Groq gpt-oss 對話，20B／120B 依情境）、chat_models（對話共用型別）、vertex_embedding（Agent Platform 向量，與 ADMIN 相同；尚未接線功能）、supabase_storage（Vercel 模組：檔案存取，與 ADMIN 相同）、storage_client（第一階段契約，未接線）、vercel（執行環境資訊與設定檢查）
│   ├── jobs/                     # 排程工作（runner.py 為共用執行機制；目前為 stub）
│   ├── db/                       # ★ 資料庫模組（說明見 app/db/README.md）
│   │   ├── README.md             #   Schema 總覽、ERD、命名規則、Migration 流程
│   │   ├── base.py               #   Base、約束命名規則、共用欄位 Mixin
│   │   ├── session.py            #   Engine / Session / get_db
│   │   ├── contracts.py          #   Repository 介面契約（Protocol）
│   │   ├── models/               #   ORM Model，每個檔案開頭備註完整 Schema
│   │   ├── repositories/         #   資料存取層
│   │   └── migrations/           #   Alembic（env.py、script.py.mako、versions/）
│   └── utils/                    # 無狀態工具（datetime_utils、file_utils）
├── tests/
│   ├── conftest.py               # 共用 fixture
│   ├── unit/                     # 單元測試（不連資料庫）
│   └── integration/              # 整合測試（需測試資料庫）
├── scripts/                      # check_project.py（無密鑰檢查）、run_job.py、seed_dev_data.py（TODO）（python -m scripts.<名稱>）
├── contracts/project-contract.json # 跨站非機密契約快照（check_project 使用）
├── docs/                         # 專案文件
├── tmp/                          # 本機暫存（不進版控；Vercel 上改用 /tmp）
├── .github/pull_request_template.md
├── .vscode/extensions.json       # 建議安裝的 VS Code 擴充套件
├── alembic.ini                   # Alembic 設定
├── vercel.json                   # Vercel Function 設定、Cron 排程、X-Robots-Tag noindex
├── requirements.txt              # 正式環境依賴（Vercel 安裝）
├── requirements-dev.txt          # 開發 / 測試依賴
├── ruff.toml                     # Lint / Format 設定
├── pytest.ini                    # 測試設定
├── .python-version               # Python 版本（Vercel 依此選擇執行版本）
├── .env.example                  # 環境變數範本
├── .editorconfig / .gitattributes / .gitignore
└── README.md
```

---

## 4. 請求處理流程（手機上傳發票，2026-10-29）

前台手機頁經本站轉呼叫；每個請求都以 Bearer Session 經 auth_service 核對。部門功能權限尚未接線；
發票列表／詳情與排程 job 仍為 TODO。

```
POST /api/v1/invoices/recognize（multipart file）
  ├─ routers/v1/invoices.py        核對 Session、讀取檔案（最多 4 MB＋1 byte）
  └─ services/invoice_upload_service.recognize
       ├─ 檢查 JPG／PNG／PDF 檔頭與宣告類型；確認 Storage／Document AI／Groq 已設定（未設定時不寫任何資料）
       ├─ recognition_repository.insert（ai_recognition_logs，pending）→ commit
       ├─ supabase_storage（bucket=invoices）put {user_id}/INVOICES_{台灣時間}_{recognition_id}.jpg|png|pdf
       ├─ document_ai.process；PDF 超過一頁 → 400 INVOICE_PDF_MULTIPAGE（記 failed，不呼叫模型）
       ├─ 沒有文字 → 400 INVOICE_TEXT_NOT_FOUND；否則 groq.chat（recognition，20B；失敗時 120B 再試一次）　總時限 25 秒，逾時以剩餘時間傳入
       ├─ utils/invoice_format 換算日期／期別／金額／字軌號碼／統編，產生檢核提醒
       ├─ recognition_repository.complete（success／partial；失敗記 failed＋固定代碼）→ commit
       └─ cleanup_expired_sources：刪除逾 1 小時未送出的影像，記 source_deleted_at

POST /api/v1/invoices/check-duplicate   字軌＋號碼＋賣方統編，已作廢不計

POST /api/v1/invoices（JSON）
  └─ services/invoice_upload_service.submit（單一交易）
       ├─ 鎖定本人辨識紀錄：1 小時內、未送出、辨識成功
       ├─ invoice_repository.lock_invoice_key（advisory lock）→ exists_duplicate（重複回 409）
       ├─ insert invoices（pending_department_approval）／invoice_items／invoice_files（同一物件，不搬移）
       ├─ 核對 changes（須從 AI 原值接續到送出值）與明細 source_line_no
       ├─ 與 AI 原值不同的欄位 → invoice_field_reviews（審核標示）；逐次修改 → invoice_changes
       ├─ invoice_status_history
       └─ recognition_repository.link_invoice → commit
```

---

## 5. 排程（Vercel Cron Jobs）

### 5.1 運作方式

1. `vercel.json` 的 `crons` 定義「路徑 + cron 表達式」。
2. 時間到時，Vercel 以 **GET** 呼叫 **Production** 部署的該路徑，並帶入 `Authorization: Bearer <CRON_SECRET>`。
3. `routers/cron.py` 透過 `verify_cron_secret` 驗證後，呼叫 `app/jobs/` 對應模組的 `run()`。

### 5.2 排程工作一覽

| Job | 端點 | 排程（UTC） | 台灣時間 | 說明 |
|---|---|---|---|---|
| `sync_einvoice` | `/api/cron/sync-einvoice` | `0 18 * * *` | 每日 02:00 | 同步財政部電子發票資料 |
| `daily_risk_scan` | `/api/cron/daily-risk-scan` | `0 19 * * *` | 每日 03:00 | 待分析發票批次 AI 分析 |

### 5.3 規則

| 項目 | 規則 |
|---|---|
| 時區 | cron 表達式**固定為 UTC**，台灣時間 = UTC + 8 |
| 方案限制 | Hobby：每個 cron 每天最多一次，且觸發時間可能落在該小時內任一分鐘；Pro：可每分鐘、準時到分 |
| 失敗處理 | Vercel **不會自動重試**，也可能漏觸發或重複觸發 → job 必須**冪等**，並以「上次成功時間之後」為處理範圍 |
| 防止重複執行 | 以 PostgreSQL advisory lock 確保同一 job 同時只有一個在跑（`jobs/runner.py`） |
| 執行紀錄 | 每次執行寫入 `job_runs`，後台可查看 |
| 執行時間 | 受 `vercel.json` 的 `maxDuration`（目前 60 秒）限制 → 大量資料要分批，剩餘留待下次 |
| 本機測試 | `CRON_SECRET` 屬本機禁用機密，本機不能帶 Authorization 呼叫 `/api/cron/*`，以測試替身驗證；`python -m scripts.run_job <job>` 會連正式 DB，需使用者授權 |

### 5.4 新增排程步驟

1. `app/jobs/` 新增模組（提供 `JOB_NAME`、`run()`）
2. `app/routers/cron.py` 新增端點
3. `vercel.json` → `crons` 新增設定
4. `scripts/run_job.py` 的 `JOBS` 加入名稱
5. 更新本文件 5.2 表格

---

## 6. 暫存檔與檔案儲存

Vercel Function 的檔案系統**只有 `/tmp` 可寫入**，且執行個體結束後內容會消失，因此：

| 類型 | 本機 | Vercel | 規則 |
|---|---|---|---|
| 處理中暫存檔（PDF 解析、影像轉檔） | `tmp/` | `/tmp/invoiceguard` | 一律用 `app.utils.file_utils.temp_file_path()`，離開區塊自動刪除 |
| 手機上傳的發票影像（已實作，2026-10-29） | START 注入 S3_*，invoices bucket（正式資料） | 同左，經 Vercel 模組 | `{user_id}/INVOICES_{台灣時間 YYYYMMDDHHMMSS}_{recognition_id}.{副檔名}`；辨識時記在 `ai_recognition_logs.source_storage_path`，送出後為 `invoice_files.storage_path`（bucket_name='invoices'，不搬移）；未送出超過 1 小時刪除並記 `source_deleted_at` |
| 其他使用者上傳檔（通用檔案契約） | 同上；bucket 依領域各自指定 | 同上 | `FileService`／`get_storage_client()` 尚未接線；RAG 等其他領域的檔案表（例如 `rag_files.bucket_name`）另行規劃 |
| 日誌 | console | Vercel Runtime Logs | 不寫入檔案 |
| 測試 / 除錯輸出 | `tmp/` | — | `tmp/` 已列入 `.gitignore`，只保留 `.gitkeep` |

暫存目錄由 `settings.temp_dir` 自動判斷（依 Vercel 注入的 `VERCEL=1`），程式中**不要寫死路徑**。

---

## 7. 環境變數

完整範本見 [`.env.example`](../.env.example)，讀取統一透過 `app/core/config.py`。

本機 JSON、Vercel Preview／Production 的實際來源與啟動驗證以 [環境與 URL 隔離](ENVIRONMENT_ISOLATION.md) 為準；dotenv 與 secrets 目錄永遠不載入。

預設不讀 `.env`。本機只由 START 注入核定的 `DATABASE_URL`、`S3_*`、`SUPABASE_STORAGE_BUCKET` 、Google Document AI／Gemini 五項與 `GROQ_API_KEY`（Production 值，連正式 DB／Storage／Google／Groq；2026-10-28 核定）；其他機密（例如 `CRON_SECRET`、`JWT_SECRET_KEY`）出現在本機即拒絕啟動。`APP_ENV=local` 不跳過既有 Cron 驗證。
完整能力別驗證與未完成項目見 [MODULE_CONTRACT.md](MODULE_CONTRACT.md)。

| 變數 | 說明 | 必填 |
|---|---|---|
| `APP_ENV` | `local` / `preview` / `production`；須與 `VERCEL_ENV` 一致，否則拒絕啟動。Vercel 不會自動設定，必須明確設為 preview / production | ✓ |
| `DEBUG` | `true` 時開放 `/docs`；正式環境必須為 `false` | |
| `DATABASE_URL` | PostgreSQL pooled 連線字串（應用程式使用）；本機由 START 注入 | ✓ |
| `DATABASE_URL_UNPOOLED` | PostgreSQL 直連字串（Alembic 優先使用，未設定時沿用 `DATABASE_URL`）；本機屬禁用機密 | migration 時 |
| `SESSION_EXPIRE_MINUTES` | 登入 Session 有效分鐘數（1–1440） | `60` |
| `JWT_SECRET_KEY` | 舊 JWT 簽章金鑰；登入改用 v1.3 Session 後不再使用，名稱保留供本機機密檢查（本機屬禁用機密） | 不需 |
| `CRON_SECRET` | Vercel Cron 驗證密鑰（至少 16 字元）；本機屬禁用機密 | 雲端 ✓ |
| `AI_API_KEY` | 保留既有 AI 設定名稱；模型服務尚未串接 | 選填 |
| `GEMINI_API_KEY` | Gemini（Google AI Studio）金鑰；本機由 START 注入；`integrations/gemini.py` 使用 | 雲端 ✓ |
| `GEMINI_MODEL` | Gemini 對話模型名稱（不是機密） | `gemini-3.8-flash` |
| `GROQ_API_KEY` | Groq 金鑰；`integrations/groq.py` 使用；本機由 START 注入 | 雲端 ✓ |
| `GROQ_DEFAULT_MODEL` / `GROQ_ADVANCED_MODEL` | Groq 預設（預設／識別）與進階（RAG／討論／進階備用）模型 | `openai/gpt-oss-20b` / `openai/gpt-oss-120b` |
| `GOOGLE_CLOUD_PROJECT_ID` / `GOOGLE_CLOUD_LOCATION` / `DOCUMENT_AI_PROCESSOR_ID` / `GOOGLE_SERVICE_ACCOUNT_JSON` | Google Document AI（OCR）專案、區域、Processor ID、服務帳號完整 JSON；本機由 START 注入；`integrations/document_ai.py` 使用 | 雲端 ✓ |
| `VERTEX_EMBEDDING_MODEL` / `VERTEX_EMBEDDING_DIMENSIONS` | Agent Platform 向量模型與維度（不是機密）；`integrations/vertex_embedding.py` 使用，沿用上方專案與服務帳號 | `gemini-embedding-2` / `1536` |
| `OPENAI_API_KEY` | 雲端模型設定；尚未串接 | 選填 |
| `EINVOICE_APP_ID` / `EINVOICE_API_KEY` | 財政部平台憑證；僅啟用該整合才需要 | 選填 |
| `BLOB_READ_WRITE_TOKEN` | 保留既有 Blob 設定名稱，不自動選用 | 選填 |
| `MODULE_BACKEND` / `REMOTE_API_BASE_URL` | 保留的模式欄位；只有 `integrations/vercel.get_platform()` 讀取，沒有遠端傳輸消費端 | 本機無機密 |
| `DB_POOL_MODE` / `DB_SSL_MODE` / `DB_CONNECT_TIMEOUT_SECONDS` | 預設 transaction / require / 5 秒；需核對實際連線模式 | 有預設 |
| `SUPABASE_URL` | 第一階段 storage 設定檢查使用；S3StorageClient 不讀此欄位 | 第一階段靜態檢查要求 |
| `SUPABASE_STORAGE_BUCKET` | S3StorageClient 使用的 Bucket，亦由第一階段靜態檢查驗證 | Storage 用戶端必填 |
| `SUPABASE_SECRET_KEY` | 第一階段 storage 設定檢查使用；S3StorageClient 改讀 S3 金鑰，不讀此欄位 | 第一階段靜態檢查要求 |
| `S3_ENDPOINT_URL` / `S3_REGION` / `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | Supabase S3 相容端點與金鑰（`integrations/supabase_storage.py`）；本機由 START 注入 | Storage 用戶端必填 |

新增設定需先分類並核定；公開設定同步 `app/core/config.py`、`app/core/environment.py` 的允許集合／驗證、空值範本及文件，不能任意新增 JSON 欄位。公司機密只由管理者存於雲端；只新增或輪替雲端機密不改本機啟動器。

---

## 8. 部署（Vercel）

| 項目 | 設定 |
|---|---|
| Framework Preset | FastAPI（Vercel 由 `requirements.txt` 的 fastapi 與 `app/main.py` 自動偵測） |
| Python 版本 | `.python-version`（3.12） |
| 依賴安裝 | `requirements.txt`（只放執行期套件，控制 bundle 大小） |
| Function 設定 | `vercel.json` → `functions["app/main.py"]`：`maxDuration`、`excludeFiles` |
| Production | `main` 分支自動部署 |
| Preview | 其他分支 / PR 自動部署；環境變數另設，**資料庫使用獨立的測試庫或核定的隔離分支** |
| Cron | 只在 Production 觸發 |
| Migration | **不在部署時自動執行**；`alembic upgrade head` 需使用者明確授權，完成後再部署 |

---

## 9. 新增一個業務模組的檢查清單（以 `xxx` 為例）

1. `app/db/models/xxx.py` — Model + 檔頭 Schema 備註；在 `models/__init__.py` 匯入
2. `alembic revision --autogenerate -m "create xxx"`，檢查版本檔
3. `app/db/repositories/xxx_repository.py`
4. `app/schemas/xxx.py` — `XxxCreate` / `XxxUpdate` / `XxxRead`
5. `app/services/xxx_service.py`
6. `app/routers/v1/xxx.py`，並在 `routers/v1/__init__.py` 註冊
7. `tests/unit/test_xxx_service.py`
8. 更新 `app/db/README.md`「資料表索引」與本文件
