# InvoiceGuard-AI-API

InvoiceGuard AI 的後端 API 服務：提供前台與後台的 REST API、AI 發票風險分析、第三方 API 串接與每日排程。

| 項目 | 內容 |
|---|---|
| 語言 / 框架 | Python 3.12 + FastAPI |
| 資料庫 | PostgreSQL + SQLAlchemy 2 + Alembic；實際雲端連線待驗證 |
| 部署 | Vercel Python Runtime（自動偵測 `app/main.py`） |
| 排程 | Vercel Cron Jobs（設定於 `vercel.json`） |
| 相關專案 | [InvoiceGuard-AI](https://github.com/Donato517/InvoiceGuard-AI)（前台）、[InvoiceGuard-AI-ADMIN](https://github.com/Donato517/InvoiceGuard-AI-ADMIN)（後台） |

## 快速開始（本機離線驗證）

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m app.integrations.vercel --check local
.\.venv\Scripts\python.exe -m pytest -q --basetemp=tmp/pytest
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

預設不讀 `.env`；公司 DB、Storage、模型、JWT、Cron 密鑰只保留於雲端。
本階段完成靜態設定與介面契約，實際 CRUD、Storage、JWT 使用者登入及 localhost 遠端傳輸尚未接線。
本機經 `app.db.session` 建立 DB Engine 會被阻擋（Alembic migration 例外：只由管理者於受控環境執行，同樣強制 TLS）。
不執行 migration、seed、排程、部署，也不下載 Vercel 環境變數。

- 健康檢查：<http://127.0.0.1:8000/health>（僅程序健康，不代表 DB / Storage 已驗證）
- API 文件：只有 `DEBUG=true` 時開放；預設 false，因此 `/docs` 回 404 屬預期
- `/` 沒有首頁路由，回 404 屬預期；API 不另外建立網站
- 完整設定、契約與驗證：[docs/MODULE_CONTRACT.md](docs/MODULE_CONTRACT.md)

## 常用指令

| 指令 | 說明 |
|---|---|
| `uvicorn app.main:app --reload` | 本機啟動（預設 port 8000） |
| `ruff check .` / `ruff format .` | 程式碼檢查 / 格式化 |
| `pytest` | 執行測試 |
| `alembic revision --autogenerate -m "說明"` | 維運參考：本階段不執行 |
| `alembic upgrade head` | 維運參考：本階段不執行 |
| `python -m scripts.run_job sync_einvoice` | 維運參考：本階段不執行 |

## 文件索引

| 文件 | 內容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系統全貌、分層架構、目錄說明、排程、暫存檔規則、部署 |
| [docs/CODING_CONVENTIONS.md](docs/CODING_CONVENTIONS.md) | 命名規則、**程式碼備註格式** |
| [docs/API_CONVENTIONS.md](docs/API_CONVENTIONS.md) | URL 設計、回應格式、錯誤代碼 |
| [docs/GIT_WORKFLOW.md](docs/GIT_WORKFLOW.md) | 分支、Commit 訊息、PR 規範 |
| [app/db/README.md](app/db/README.md) | **DB Schema 總覽**、命名規則、Migration 流程 |
| [docs/MODULE_CONTRACT.md](docs/MODULE_CONTRACT.md) | Vercel / DB 模組第一階段、機密邊界、契約與離線驗證 |
