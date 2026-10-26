# 開發規範與程式碼備註格式 — InvoiceGuard-AI-API（Python）

AI 閱讀順序與權限先見 [AGENTS.md](../AGENTS.md)／[CLAUDE.md](../CLAUDE.md)。
本文件保留命名及備註格式；[DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md) 說明真實能力，
[PROJECT_CHECKS.md](PROJECT_CHECKS.md) 說明自動檢查可驗證的規則及限制。

## 1. 基本原則

1. 遵循 PEP 8，以 **Ruff** 自動檢查與格式化（`ruff check .`、`ruff format .`），設定見 `ruff.toml`。
2. **所有函式參數與回傳值都要加型別註記**。
3. 一個函式只做一件事；超過約 50 行就考慮拆分。
4. 密碼、金鑰、連線字串**禁止寫在程式碼**，一律從 `app.core.config.settings` 讀取。
5. 識別字（變數、函式、類別）用**英文**；備註、docstring、錯誤訊息用**繁體中文**。
6. 遵守分層規則（見 `docs/ARCHITECTURE.md` 第 2 節），相依方向只能由上往下。

---

## 2. 命名規則

| 對象 | 規則 | 範例 |
|---|---|---|
| 模組 / 檔案 | snake_case | `invoice_service.py` |
| 套件 / 資料夾 | snake_case、複數 | `services/`、`models/` |
| 類別 | PascalCase | `InvoiceService`、`InvoiceRead` |
| 函式 / 變數 | snake_case，函式以動詞開頭 | `get_invoice()`、`total_amount` |
| 常數 | UPPER_SNAKE_CASE | `JOB_NAME`、`ROC_YEAR_OFFSET` |
| 列舉 | 類別 PascalCase、成員 UPPER_SNAKE_CASE | `InvoiceStatus.PENDING` |
| 私有成員 | 前綴底線 | `_to_psycopg_url()` |
| 布林 | `is_` / `has_` / `can_` 開頭 | `is_active` |
| Pydantic schema | `<名詞><用途>` | `InvoiceCreate`、`InvoiceUpdate`、`InvoiceRead`、`InvoiceQuery` |
| Repository / Service 檔 | `<名詞>_repository.py`、`<名詞>_service.py` | `invoice_repository.py` |
| 測試檔 / 函式 | `test_<模組>.py`、`test_<行為>_<預期>` | `test_cron_rejects_wrong_secret` |

---

## 3. 備註格式

### 3.1 檔案開頭（Module Docstring）— 每個 `.py` 檔必填

```python
"""
模組名稱：app.services.invoice_service
功能說明：發票商業邏輯——上傳建檔、查詢、狀態流轉、人工複核。
相依模組：app.db.repositories.invoice_repository、app.integrations.storage_client
注意事項：
    - 狀態流轉：pending → analyzing → passed / flagged。
    - 上傳檔案存物件儲存，資料庫只存 file_key。
"""
```

| 欄位 | 必填 | 說明 |
|---|---|---|
| 模組名稱 | ✓ | import 路徑 |
| 功能說明 | ✓ | 一句話講清楚「這個檔案負責什麼」 |
| 相依模組 / 相依設定 | | 主要相依的內部模組或環境變數 |
| 路由 / 路由前綴 | routers 必填 | 例：`/api/v1/invoices` |
| 觸發方式 | jobs 必填 | 例：`Vercel Cron → GET /api/cron/sync-einvoice` |
| 使用方式 | scripts 必填 | 指令範例 |
| 注意事項 | | 使用限制、副作用、效能 / 安全考量 |

`__init__.py` 與簡單檔案可用一行 docstring：`"""商業邏輯層：……"""`。

> **作者與異動歷史以 git 為準**，一般程式檔頭**不寫**異動紀錄，避免備註與實際內容不同步。
> 唯一例外是 **DB Model 檔**（見 3.7）。

### 3.2 類別 Docstring

```python
class AppError(Exception):
    """業務例外基底類別。子類別以 status_code / code 定義 HTTP 狀態與錯誤代碼。"""
```

說明「這個類別代表什麼」以及使用方式；屬性有特殊意義時再列出。

### 3.3 函式 Docstring（Google Style）

公開函式（非 `_` 開頭）必填；內容簡單到看名稱就懂的私有函式可省略。

```python
def analyze_invoice(db: Session, invoice_id: int, *, force: bool = False) -> InvoiceRead:
    """對指定發票執行 AI 風險分析，並寫回風險分數與分析結果。

    已分析過的發票預設直接回傳既有結果，force=True 時重新分析。

    Args:
        db: 資料庫 Session。
        invoice_id: 發票主鍵。
        force: 是否忽略既有結果強制重新分析。

    Returns:
        更新後的發票資料。

    Raises:
        NotFoundError: 發票不存在。
        ExternalServiceError: AI 服務呼叫失敗。

    Example:
        result = analyze_invoice(db, 123, force=True)
    """
```

| 區塊 | 何時寫 |
|---|---|
| 第一行摘要 | 必填，一句話，以句號結尾 |
| 詳細說明 | 有特殊邏輯、前置條件時 |
| `Args:` | 有參數時 |
| `Returns:` / `Yields:` | 有回傳值時 |
| `Raises:` | 會主動拋出例外時 |
| `Example:` | 用法不直覺時 |

### 3.4 行內備註 — 說明「為什麼」，不是「做什麼」

```python
# ✗ 不好：重複程式碼本身
i += 1  # i 加 1

# ✓ 好：說明原因
# 財政部 API 每秒限制 5 次請求，批次同步時需間隔
time.sleep(0.2)

# ✓ 好：說明業務規則
even_month = value.month + (value.month % 2)  # 統一發票兩個月一期，以偶數月表示期別
```

### 3.5 標記備註

格式：`# <標記>(<負責人>): <說明> [#<issue 編號>]`

| 標記 | 用途 | 範例 |
|---|---|---|
| `TODO` | 待實作 | `# TODO(JerryChien): 加入分頁 [#23]` |
| `FIXME` | 已知問題待修正 | `# FIXME(JerryChien): 跨月發票期別計算錯誤 [#31]` |
| `NOTE` | 重要提醒，修改前必讀 | `# NOTE: 順序不可調換，Alembic 依此偵測 Model` |
| `HACK` | 暫時性繞道解法，需說明何時移除 | `# HACK: 第三方套件 bug，升級到 2.x 後移除` |
| `SECURITY` | 安全相關邏輯，修改需 review | `# SECURITY: 必須使用 compare_digest 比對` |

PR 合併前應檢查新增的 `TODO` 是否都有負責人。

### 3.6 區塊分隔

檔案內有多個邏輯區塊時使用：

```python
# ---- 資料庫 ----
DATABASE_URL: str = ""

# ---- 安全 ----
JWT_SECRET_KEY: str = ""
```

### 3.7 DB Model 檔的 Schema 備註

`app/db/models/*.py` 的檔頭除了 3.1 的欄位外，**必須包含完整的資料表 Schema 區塊與異動紀錄**。
格式與規則見 [`app/db/README.md` 第 6 節](../app/db/README.md#6-schema-備註格式modelspy-檔案開頭)。

### 3.8 不要寫的備註

- 被註解掉的舊程式碼 → 直接刪除，需要時從 git 找回
- 與程式碼重複、沒有新資訊的備註
- 作者、日期、修改歷史（DB Model 檔除外）→ 交給 git
- 任何密碼、金鑰、個資

---

## 4. 其他撰寫規則

### 4.1 Import 順序（Ruff 自動排序）

```python
# 1. 標準函式庫
import logging
from datetime import date

# 2. 第三方套件
from fastapi import APIRouter

# 3. 專案內部模組（一律使用 app. 開頭的絕對路徑）
from app.core.config import settings
```

### 4.2 例外處理

- service 遇到可預期的錯誤 → 拋出 `app.core.exceptions` 中的 `AppError` 子類別
- 不要用 `except Exception: pass` 吞掉錯誤；捕捉後要處理、轉換或記錄
- 呼叫外部服務失敗 → 轉為 `ExternalServiceError`，並保留原始例外：`raise ExternalServiceError("...") from exc`

### 4.3 日誌

```python
logger = logging.getLogger(__name__)

# ✓ 使用 % 參數（未達輸出等級時不會組字串）
logger.info("發票分析完成：invoice_id=%s risk_score=%s", invoice.id, score)

# ✗ 不要用 f-string
logger.info(f"發票分析完成：{invoice.id}")
```

| 等級 | 使用時機 |
|---|---|
| `DEBUG` | 開發除錯細節 |
| `INFO` | 重要流程節點（排程開始 / 結束、外部呼叫成功） |
| `WARNING` | 可自動恢復的異常（重試、資料格式不符被略過） |
| `ERROR` / `exception` | 需人工處理的錯誤 |

禁止記錄：密碼、token、金鑰、完整身分證字號、信用卡號。

### 4.4 時間與金額

- 時間一律使用 timezone-aware `datetime`，以 UTC 儲存（`app.utils.datetime_utils.now_utc()`）
- 金額一律使用 `Decimal`，禁止 `float`

### 4.5 測試

- 新功能至少要有 service 層的單元測試
- 測試函式命名 `test_<行為>_<預期結果>`，內容依「準備 → 執行 → 驗證」三段，段落間空一行
- 單元測試不可連線正式資料庫或呼叫真實外部服務

---

## 5. 提交前檢查清單

- [ ] AGENTS.md「無公司密鑰驗證」全部通過（check_project、pytest、ruff check／format --check、environment --check）
- [ ] 新檔案都有檔頭 docstring，公開函式都有 docstring
- [ ] 新增的 `TODO` 都有負責人
- [ ] 異動 Model 時已同步 Schema 備註、異動紀錄、migration 檔、ADMIN Model 與契約快照
- [ ] 沒有寫死的密碼、金鑰、網址（三站公開網址集中在 `app/core/constants.py`）


## AI 協作與檔案管理補充

- 沿用本專案分層、資料夾及既有 API／Protocol；新增前先尋找同用途檔案，不複製第二套服務入口。
- 程式放對應 `app/` 分層；測試放 `tests/unit/`；操作腳本放 `scripts/`；文件放 `docs/`。UI 靜態資源及樣板仍遵守本文件與架構文件規則。
- 暫存、驗收證據放被忽略的 `tmp/` 或專案外；使用者原始檔、密鑰、資料庫匯出與真實發票不得放 `app/static/` 或 Git。
- 未實作功能保持明確 TODO／`ModuleNotReadyError`；不得以假成功、測試替身或 `APP_ENV=local` 取代登入與授權。
- ADMIN／API 共用契約及 ORM 的改動需同步，API 是 Schema／Alembic 唯一擁有者；Repository 不 `commit`／`rollback`，交易由 Service 協調。
- 每次交付執行 `python -B scripts/check_project.py` 與相關無密鑰測試；跨站變更加 `--project-root`。回報實際執行結果及未執行範圍，不將靜態檢查當成雲端連線通過。
- 契約／分層檢查不是通用密鑰掃描器；不能藉通過檢查就上傳任意檔案或輸出環境變數。
- 設定來源解析限既有 `app/core/config.py`／`app/core/environment.py`；一般業務模組不得自行讀取 OS 環境或 `.env`。既有經審查的開發橋接及 infrastructure 例外依 `PROJECT_CHECKS.md`，不擴張白名單來掩蓋新違規。
