# InvoiceGuard-AI-API

InvoiceGuard AI 的後端 API 服務：提供前台與後台的 REST API、AI 發票風險分析、第三方 API 串接與每日排程。

| 項目 | 內容 |
|---|---|
| 語言 / 框架 | Python 3.12 + FastAPI |
| 資料庫 | PostgreSQL（建議 Vercel Marketplace 的 Neon）+ SQLAlchemy 2 + Alembic |
| 部署 | Vercel Python Runtime（自動偵測 `app/main.py`） |
| 排程 | Vercel Cron Jobs（設定於 `vercel.json`） |
| 相關專案 | [InvoiceGuard-AI](https://github.com/Donato517/InvoiceGuard-AI)（前台）、[InvoiceGuard-AI-ADMIN](https://github.com/Donato517/InvoiceGuard-AI-ADMIN)（後台） |

## 快速開始（本機）

```bash
# 1. 建立虛擬環境並安裝套件（Windows 用 .venv\Scripts\activate）
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# 2. 建立環境變數檔，填入 DATABASE_URL 等設定（Windows 用 copy）
cp .env.example .env

# 3. 建立資料表並啟動
alembic upgrade head
uvicorn app.main:app --reload
```

- 健康檢查：<http://localhost:8000/health>
- API 文件（`DEBUG=true` 時）：<http://localhost:8000/docs>

## 常用指令

| 指令 | 說明 |
|---|---|
| `uvicorn app.main:app --reload` | 本機啟動（預設 port 8000） |
| `ruff check .` / `ruff format .` | 程式碼檢查 / 格式化 |
| `pytest` | 執行測試 |
| `alembic revision --autogenerate -m "說明"` | 依 Model 變更產生 migration |
| `alembic upgrade head` | 套用 migration |
| `python -m scripts.run_job sync_einvoice` | 手動執行排程工作 |

## 文件索引

| 文件 | 內容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系統全貌、分層架構、目錄說明、排程、暫存檔規則、部署 |
| [docs/CODING_CONVENTIONS.md](docs/CODING_CONVENTIONS.md) | 命名規則、**程式碼備註格式** |
| [docs/API_CONVENTIONS.md](docs/API_CONVENTIONS.md) | URL 設計、回應格式、錯誤代碼 |
| [docs/GIT_WORKFLOW.md](docs/GIT_WORKFLOW.md) | 分支、Commit 訊息、PR 規範 |
| [app/db/README.md](app/db/README.md) | **DB Schema 總覽**、命名規則、Migration 流程 |
