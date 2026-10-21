# 系統架構說明 — InvoiceGuard-AI-API

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
│ PostgreSQL (Neon)    │◀─────────────────────┘
└──────────────────────┘
```

| Repository | 角色 | 技術 | 資料存取 |
|---|---|---|---|
| InvoiceGuard-AI | 前台網站：使用者上傳發票、查看 AI 分析結果 | FastAPI + Jinja2 | 由伺服器端呼叫本 API，不直接連資料庫 |
| InvoiceGuard-AI-ADMIN | 後台網站：發票審核、使用者管理、排程與稽核紀錄 | FastAPI + Jinja2 | 自有 DB 模組，直接連同一個 PostgreSQL |
| **InvoiceGuard-AI-API**（本專案） | 後端 API：AI 分析、第三方串接、排程 | FastAPI | 自有 DB 模組 + Alembic |

外部服務：PostgreSQL（Neon）、AI 模型服務、財政部電子發票整合服務平台（MOF e-Invoice）、檔案儲存（Vercel Blob）。

**資料庫共用規則**：後台直接存取同一個資料庫，但**資料表結構只能由本專案的 Alembic migration 變更**；
後台的 Model 是對應定義，需同步更新。流程見 [`app/db/README.md` 第 9 節](../app/db/README.md#9-共用此資料庫的專案)。

---

## 2. 分層架構

```
routers ──▶ services ──▶ db/repositories ──▶ db/models
               │
               └──▶ integrations（AI / 財政部 / Blob）

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
│   │   ├── config.py             #   環境變數設定（唯一讀取環境變數的地方）
│   │   ├── deps.py               #   FastAPI 相依注入型別（DbSession、CurrentUser…）
│   │   ├── exceptions.py         #   業務例外類別 + 全域錯誤處理（統一錯誤格式）
│   │   ├── logging_config.py     #   日誌格式
│   │   └── security.py           #   Cron 驗證、JWT、密碼雜湊
│   ├── routers/                  # HTTP 路由層
│   │   ├── health.py             #   GET /health
│   │   ├── cron.py               #   GET /api/cron/*（僅供 Vercel Cron）
│   │   └── v1/                   #   /api/v1/*
│   │       ├── auth.py           #     登入 / 登出 / 目前使用者
│   │       └── invoices.py       #     前台發票
│   ├── schemas/                  # Pydantic 請求 / 回應模型（DTO）
│   │   └── common.py             #   分頁、錯誤格式
│   ├── services/                 # 商業邏輯層
│   ├── integrations/             # 第三方 API 串接（ai_client / einvoice_client / storage_client）
│   ├── jobs/                     # 排程工作（runner.py 為共用執行機制）
│   ├── db/                       # ★ 資料庫模組（說明見 app/db/README.md）
│   │   ├── README.md             #   Schema 總覽、ERD、命名規則、Migration 流程
│   │   ├── base.py               #   Base、約束命名規則、共用欄位 Mixin
│   │   ├── session.py            #   Engine / Session / get_db
│   │   ├── models/               #   ORM Model，每個檔案開頭備註完整 Schema
│   │   ├── repositories/         #   資料存取層
│   │   └── migrations/           #   Alembic（env.py、script.py.mako、versions/）
│   └── utils/                    # 無狀態工具（datetime_utils、file_utils）
├── tests/
│   ├── conftest.py               # 共用 fixture
│   ├── unit/                     # 單元測試（不連資料庫）
│   └── integration/              # 整合測試（需測試資料庫）
├── scripts/                      # 維運 / 開發腳本（python -m scripts.<名稱>）
├── docs/                         # 專案文件
├── tmp/                          # 本機暫存（不進版控；Vercel 上改用 /tmp）
├── .github/pull_request_template.md
├── .vscode/extensions.json       # 建議安裝的 VS Code 擴充套件
├── alembic.ini                   # Alembic 設定
├── vercel.json                   # Vercel Function 設定 + Cron 排程
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

## 4. 請求處理流程（範例：上傳發票）

```
POST /api/v1/invoices/upload
  │
  ├─ routers/v1/invoices.py      驗證檔案類型與大小、取得登入者（CurrentUser）
  ├─ services/invoice_service.py
  │    ├─ integrations/storage_client.py   原始檔上傳到 Vercel Blob，取得 file_key
  │    ├─ db/repositories/invoice_repository.py   建立 invoices（status=pending）
  │    └─ commit
  └─ 回傳 InvoiceRead（schemas/invoice.py）

之後由 daily_risk_scan 排程（或使用者手動觸發 /analyze）進行 AI 分析
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
| 本機測試 | `python -m scripts.run_job <job>`，或帶 Authorization 標頭呼叫 `/api/cron/*` |

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
| 使用者上傳的原始檔 | Vercel Blob | Vercel Blob | 永久保存，資料庫只存 `file_key` |
| 日誌 | console | Vercel Runtime Logs | 不寫入檔案 |
| 測試 / 除錯輸出 | `tmp/` | — | `tmp/` 已列入 `.gitignore`，只保留 `.gitkeep` |

暫存目錄由 `settings.temp_dir` 自動判斷（依 Vercel 注入的 `VERCEL=1`），程式中**不要寫死路徑**。

---

## 7. 環境變數

完整範本見 [`.env.example`](../.env.example)，讀取統一透過 `app/core/config.py`。

| 變數 | 說明 | 必填 |
|---|---|---|
| `APP_ENV` | `local` / `preview` / `production` | ✓ |
| `DEBUG` | `true` 時開放 `/docs`；正式環境必須為 `false` | |
| `DATABASE_URL` | PostgreSQL pooled 連線字串（應用程式使用） | ✓ |
| `DATABASE_URL_UNPOOLED` | PostgreSQL 直連字串（Alembic 使用） | migration 時 |
| `JWT_SECRET_KEY` / `JWT_EXPIRE_MINUTES` | 登入 token 簽章金鑰 / 有效分鐘數 | ✓ |
| `CRON_SECRET` | Vercel Cron 驗證密鑰（至少 16 字元） | ✓ |
| `AI_API_KEY` | AI 模型服務金鑰 | ✓ |
| `EINVOICE_APP_ID` / `EINVOICE_API_KEY` | 財政部電子發票平台憑證 | ✓ |
| `BLOB_READ_WRITE_TOKEN` | Vercel Blob 存取權杖 | ✓ |

新增變數時：`.env.example`、`app/core/config.py`、本表、Vercel Project Settings 四處同步。

---

## 8. 部署（Vercel）

| 項目 | 設定 |
|---|---|
| Framework Preset | FastAPI（Vercel 由 `requirements.txt` 的 fastapi 與 `app/main.py` 自動偵測） |
| Python 版本 | `.python-version`（3.12） |
| 依賴安裝 | `requirements.txt`（只放執行期套件，控制 bundle 大小） |
| Function 設定 | `vercel.json` → `functions["app/main.py"]`：`maxDuration`、`excludeFiles` |
| Production | `main` 分支自動部署 |
| Preview | 其他分支 / PR 自動部署；環境變數另設，**資料庫使用獨立的測試庫或 Neon branch** |
| Cron | 只在 Production 觸發 |
| Migration | **不在部署時自動執行**；PR 合併後由負責人手動 `alembic upgrade head`，再部署 |

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
