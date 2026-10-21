# DB 模組（`app/db`）

> 本資料夾是資料庫結構的**唯一真相來源（Single Source of Truth）**：
> 每張資料表的完整 Schema 寫在 `models/*.py` 的**檔案開頭備註**，ORM 定義緊接在下方，
> 所有結構異動都透過 `migrations/` 版本化。不另外維護會與程式脫節的 Excel / Word 規格書。

---

## 1. 目錄說明

| 路徑 | 說明 |
|---|---|
| `base.py` | `Base`（DeclarativeBase）、約束命名規則 `NAMING_CONVENTION`、共用欄位 Mixin、`in_values_check()` |
| `session.py` | Engine、Session、FastAPI 相依注入 `get_db()` |
| `models/` | ORM Model。一個業務主題一個檔案，**檔案開頭必須有 Schema 備註** |
| `models/__init__.py` | 匯入全部 Model（Alembic 靠這裡偵測資料表） |
| `repositories/` | 資料存取層（查詢 / 新增 / 更新）。不含商業邏輯、不自行 `commit` |
| `migrations/` | Alembic 環境設定 `env.py`、版本檔範本 `script.py.mako` |
| `migrations/versions/` | Migration 版本檔（由 `alembic revision` 產生，合併後不得修改） |

---

## 2. 資料表索引

> 新增 / 刪除資料表時，必須同步更新此表。

| 資料表 | 說明 | 定義檔 | 狀態 |
|---|---|---|---|
| `users` | 使用者（前台 / 後台共用，以 `role` 區分） | [models/user.py](models/user.py) | 草案 |
| `invoices` | 發票主檔（含 AI 風險分析結果） | [models/invoice.py](models/invoice.py) | 草案 |
| `invoice_items` | 發票明細 | [models/invoice.py](models/invoice.py) | 草案 |
| `audit_logs` | 操作稽核紀錄（append-only） | [models/audit_log.py](models/audit_log.py) | 草案 |
| `job_runs` | 排程執行紀錄 | [models/job_run.py](models/job_run.py) | 草案 |

狀態定義：**草案**（尚未產生 migration，可自由調整）→ **已上線**（已套用至正式環境，只能透過新 migration 變更）。

---

## 3. 資料表關聯（ERD）

```
users ──1:N──> invoices ──1:N──> invoice_items
  │
  └───1:N──> audit_logs        job_runs（獨立，無外鍵）
```

---

## 4. 命名規則

| 對象 | 規則 | 範例 |
|---|---|---|
| 資料表 | snake_case、**複數** | `invoices`、`invoice_items` |
| 欄位 | snake_case、單數 | `invoice_number` |
| 主鍵 | 一律 `id BIGINT IDENTITY` | `id` |
| 外鍵欄位 | `<參照表單數>_id` | `user_id`、`invoice_id` |
| 布林欄位 | `is_` / `has_` 開頭 | `is_active` |
| 時間欄位 | `_at` 結尾，型別 `TIMESTAMPTZ`（以 UTC 儲存） | `created_at`、`last_login_at` |
| 日期欄位 | `_date` 結尾，型別 `DATE` | `invoice_date` |
| 金額欄位 | `NUMERIC(12,2)`，**禁止使用 FLOAT / REAL** | `total_amount` |
| 列舉欄位 | `VARCHAR` + `CHECK`，允許值由 Python `StrEnum` 產生 | `status` |
| JSON 欄位 | 一律 `JSONB`，只放「結構不固定」的資料 | `ai_result` |
| 主鍵約束 | `pk_<table>` | `pk_users` |
| 外鍵約束 | `fk_<table>_<column>_<referred_table>` | `fk_invoices_user_id_users` |
| 唯一約束 | `uq_<table>_<columns>` | `uq_users_email` |
| 索引 | `ix_<table>_<columns>` | `ix_invoices_status` |
| 檢查約束 | `ck_<table>_<name>` | `ck_invoices_status_valid` |

約束 / 索引名稱由 `base.py` 的 `NAMING_CONVENTION` **自動產生**，ORM 中不需手寫名稱（檢查約束只需給 `name="status_valid"` 這段）。

---

## 5. 共用欄位

| 欄位 | 來源 | 適用 |
|---|---|---|
| `id` | `IdMixin` | 所有資料表 |
| `created_at`、`updated_at` | `TimestampMixin` | 會被更新的主檔 / 明細表 |
| `deleted_at` | `SoftDeleteMixin` | 需保留歷史的主檔（查詢時必須加 `deleted_at IS NULL`） |
| 自訂時間欄位 | 各 Model 自行定義 | append-only 紀錄表（`audit_logs`、`job_runs`） |

---

## 6. Schema 備註格式（`models/*.py` 檔案開頭）

每個 Model 檔案的 module docstring 必須依下列格式撰寫；一個檔案有多張表時，**每張表一個區塊**。

```text
==============================================================================
資料表：<table_name>（<中文名稱>）                                 狀態：草案
==============================================================================
欄位             型別            NULL  預設        說明
---------------  --------------  ----  ----------  ------------------------------
id               BIGINT          NO    IDENTITY    主鍵
<column>         <PostgreSQL型別> YES/NO <預設值>   <用途、格式、允許值、範例>
created_at       TIMESTAMPTZ     NO    now()       建立時間
updated_at       TIMESTAMPTZ     NO    now()       最後更新時間
------------------------------------------------------------------------------
主鍵：pk_<table> (id)
唯一：uq_<table>_<columns> (<columns>)
檢查：ck_<table>_<name>  <條件>
索引：ix_<table>_<columns> (<columns>)
外鍵：fk_<table>_<column>_<ref>  <column> → <ref>.id  ON DELETE <RESTRICT|CASCADE|SET NULL>
關聯：<table> 1 ─ N <table>
特性：<選填，例如 append-only、需加密欄位、資料保存期限>
------------------------------------------------------------------------------
異動紀錄（新到舊；上線後須附 migration revision）
YYYY-MM-DD  <作者>  <異動說明>（revision: <revision id>）
==============================================================================
```

撰寫規則：

1. **欄位順序與 ORM 定義一致**（`id` 最前、共用時間戳最後）。
2. 型別寫 **PostgreSQL 實際型別**（`VARCHAR(255)`、`TIMESTAMPTZ`），不是 Python 型別。
3. 「說明」欄要寫出業務意義：允許值、格式、單位、範例，而不只是翻譯欄位名稱。
4. 沒有的項目寫 `—`，不要刪除該行，方便快速掃描。
5. 異動紀錄**新的寫在最上面**；上線後的每次異動都要附 Alembic revision id。
6. 程式碼檔頭一般**不**寫異動紀錄（以 git 為準），**唯獨 Model 檔例外**，因為 Schema 演進需要在檔案內一眼看懂。

---

## 7. Migration 流程（Alembic）

```bash
# 1. 修改 models/*.py（ORM 定義 + 檔頭 Schema 備註）
# 2. 依 Model 差異產生版本檔
alembic revision --autogenerate -m "add risk_score to invoices"
# 3. 人工檢查 versions/ 內產生的檔案（見下方注意事項）
# 4. 套用到本機資料庫
alembic upgrade head
# 5. 確認可以退版
alembic downgrade -1 && alembic upgrade head
```

**autogenerate 偵測不到、必須手動補寫的情況：**

- 欄位**改名**（會被誤判為刪除＋新增，造成資料遺失）
- `CHECK` 約束內容變更
- `server_default` 變更
- 資料轉換（例如舊欄位資料搬到新欄位）

**同一個 PR 內必須包含：** ORM 變更、Schema 備註更新、migration 版本檔、本文件「資料表索引」更新。

**正式環境：** PR 合併後，由負責人以 `DATABASE_URL_UNPOOLED`（直連）執行 `alembic upgrade head`，再部署 API。

**禁止事項：**

- 修改或刪除**已合併**的 migration 版本檔（要改就新增一個版本）
- 直接在正式資料庫手動 `ALTER TABLE`
- 在 migration 中寫死環境相關資料（帳號、金鑰）

---

## 8. 連線注意事項（Vercel Serverless）

| 項目 | 規則 |
|---|---|
| 連線字串 | 應用程式用 `DATABASE_URL`（pooled）；Alembic 用 `DATABASE_URL_UNPOOLED`（直連） |
| 連線池 | 應用端使用 `NullPool`，由資料庫端 pooler 管理連線 |
| Session | 每個請求一個（`DbSession` 相依注入），不可放在全域變數共用 |
| 交易 | 由 service 層 `commit` / `rollback`；repository 只做 `add` / `flush` / 查詢 |
| 長時間作業 | 不要在交易中呼叫 AI 等外部服務；先查資料、關閉交易，呼叫完再開新交易寫回 |
| 時區 | 資料庫一律存 UTC；顯示為台灣時間由前端或 `app/utils/datetime_utils.py` 轉換 |
