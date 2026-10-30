# InvoiceGuard-AI-API

> 2026-10-30：已由 ADMIN 同步 Document AI 三模組，維持相同內容與既有 OCR 介面，補上 Pillow 依賴。evidence／Few-Shot 尚未接線上傳流程；詳見 [同步檢驗](docs/DOCUMENT_AI_SYNC_20261030.md)。

InvoiceGuard AI 的後端 API 服務：提供前台（伺服器端）的 REST API、AI 發票風險分析、第三方 API 串接與每日排程；ADMIN 使用自己的 DB 模組，不經本站。

| 項目 | 內容 |
|---|---|
| 語言 / 框架 | Python 3.12 + FastAPI |
| 資料庫 | PostgreSQL + SQLAlchemy 2 + Alembic；連線與功能完成度見 [開發狀態](docs/DEVELOPMENT_STATUS.md) |
| 部署 | Vercel Python Runtime（自動偵測 `app/main.py`） |
| 排程 | Vercel Cron Jobs（設定於 `vercel.json`） |
| 相關專案 | [InvoiceGuard-AI](https://github.com/Donato517/InvoiceGuard-AI)（前台）、[InvoiceGuard-AI-ADMIN](https://github.com/Donato517/InvoiceGuard-AI-ADMIN)（後台） |

## 快速開始（Windows 團隊開發）

先閱讀 [AGENTS.md](AGENTS.md)；Claude 入口為 [CLAUDE.md](CLAUDE.md)。
目前已完成、僅有契約與尚未實作的能力，以 [開發狀態](docs/DEVELOPMENT_STATUS.md) 為準。

三站放在同一個根目錄，啟動器放在同層 `InvoiceGuard-STARTUP`。
啟動器的 `SETUP.cmd` 從三站共同上層推導並記錄 `PROJECT_ROOT`，不要在三站重複寫死路徑。
在 PowerShell 切換到 `InvoiceGuard-STARTUP` 後執行：

```powershell
# 初次設定：建立或重用三站各自的 Python 3.12 venv，安裝開發依賴（相容指令 .\START.cmd setup）
.\SETUP.cmd

# 日常啟動：三站、電腦別名及電腦／手機共用的臨時 HTTPS；不需 --mobile
.\START.cmd
```

START 最後自動開啟當次 HTTPS 的 `/login`，電腦與手機都直接看到前台原有 Email／密碼登入表單，
不需要開發存取碼，也不會出現額外的瀏覽器帳密視窗；網站登入與權限照舊。電腦另有本機別名：

- 前台：<http://invoiceguard-ai.localhost:8080/login>（307 轉至同一次 HTTPS 的 /login）
- ADMIN：<http://invoiceguard-ai-admin.localhost:8080/>（僅開發電腦）
- API 健康檢查：<http://invoiceguard-ai-api.localhost:8080/health>（僅開發電腦）

內部服務埠（日常 8100／8101／8002；離線診斷 `--local-only` 為 8000／8001／8002）不作為日常辨識入口。
三站各在自己的 CMD 視窗執行：某站視窗 Ctrl+C 只停止該站，START 總控視窗 Ctrl+C 停止全部。
若啟動器未隨 clone 取得，先向團隊取得核定啟動器，不自行建置另一套網站或下載公司機密。

本機預設不讀 `.env`、不執行 `vercel env pull`。START 依 2026-10-25 核定，只把本站 Production 的
`DATABASE_URL`、`S3_*`、`SUPABASE_STORAGE_BUCKET` 注入本機程序記憶體：本機連的是正式 DB／Storage，寫入即正式資料。
模型、Session、Cron 等其他公司密鑰不在本機；出現在本機程序環境時本站拒絕啟動。
開啟頁面及 `/health` 只表示程序正常，不能視為登入、CRUD、Storage 或雲端連線通過。

## 本站無密鑰檢查

在本站根目錄使用既有 `.venv`：

```powershell
.\.venv\Scripts\python.exe -B scripts/check_project.py
.\.venv\Scripts\python.exe -B -m app.core.environment --check
.\.venv\Scripts\python.exe -B -m pytest -q --basetemp=tmp/pytest
```

共同檢查不需要兄弟 Repository 或公司密鑰；同時持有三站時可加 `--project-root` 比對契約。
檢查範圍、限制與指令見 [PROJECT_CHECKS.md](docs/PROJECT_CHECKS.md)。
`tmp/pytest` 只作測試暫存，不能放要保留的檔案。

## 常用指令

| 指令 | 說明 |
|---|---|
| `uvicorn app.main:app --reload` | 單站診斷（預設 port 8000）；日常使用 `START.cmd` |
| `ruff check app tests scripts` / `ruff format app tests scripts` | 程式碼檢查 / 格式化 |
| `pytest` | 執行測試 |
| `alembic revision --autogenerate -m "說明"` | 建立 migration 檔（一般開發）；結構需同步 ADMIN Model 與契約快照 |
| `alembic upgrade head` | 套用 migration：連正式 DB，需使用者明確授權後才執行 |
| `python -m scripts.run_job sync_einvoice` | 手動執行排程：job 目前為 stub，會連正式 DB，需使用者授權 |

## 文件索引

| 文件 | 內容 |
|---|---|
| [AGENTS.md](AGENTS.md) / [CLAUDE.md](CLAUDE.md) | AI 固定閱讀入口：三站架構、共同規則、本站現況與授權邊界 |
| [docs/DEVELOPMENT_STATUS.md](docs/DEVELOPMENT_STATUS.md) | 已完成、契約與尚未實作的能力 |
| [docs/PROJECT_CHECKS.md](docs/PROJECT_CHECKS.md) | 無密鑰契約／分層檢查、跨站同步與限制 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系統全貌、分層架構、目錄說明、排程、暫存檔規則、部署 |
| [docs/CODING_CONVENTIONS.md](docs/CODING_CONVENTIONS.md) | 命名規則、**程式碼備註格式** |
| [docs/API_CONVENTIONS.md](docs/API_CONVENTIONS.md) | URL 設計、回應格式、錯誤代碼 |
| [docs/GIT_WORKFLOW.md](docs/GIT_WORKFLOW.md) | 分支、Commit 訊息、PR 規範 |
| [app/db/README.md](app/db/README.md) | **DB Schema 總覽**、命名規則、Migration 流程 |
| [docs/MODULE_CONTRACT.md](docs/MODULE_CONTRACT.md) | Vercel / DB 模組第一階段、機密邊界、契約與離線驗證 |

環境與 URL 的來源、管理者檢查及 PowerShell 驗證方式見 [開發／雲端環境隔離](docs/ENVIRONMENT_ISOLATION.md)。

`docs/CLAUDE_REVIEW_PROMPT.md` 是歷史檢驗指令，不是現行規則。
