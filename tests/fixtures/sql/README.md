# tests/fixtures/sql — 整合測試專用基線（test-only）

> **這不是團隊正式 Schema，不是已部署的資料庫基線，也不是 Alembic baseline／`alembic stamp` 的對象。**
> 正式資料庫的結構版本仍未核對；本檔只用來在**一次性的本機隔離 PostgreSQL** 建出測試用資料庫。

## 檔案

| 檔案 | 說明 |
|---|---|
| `v1_8_derived_test_baseline.sql` | 由 v1.8 設計草案衍生的測試基線（僅 DDL，無種子資料、無憑證、無個資）。標頭記錄來源與指紋。 |

## 來源與指紋

- 來源：`InvoiceGuard_AI_PostgreSQL_Schema_v1_8_PortableAuth_draft.sql`（v1.8 設計草案，2026-11-01，**從未在正式環境執行**；原檔不在本 Repo）。
- 來源整檔 SHA-256：`426f0fe0a602dd03c3ef17f519367f95451240d1ff9f7c631a2f9dc4681b0ba9`
- 衍生檔本體（標頭結束標記之後）SHA-256：`a16414c6f6c7cf7768ed421ac03f3a8fc70c829595acdf588cb624fb5ed641ca`；
  `tests/integration/test_baseline_fixture.py` 會比對，檔案被悄悄改動測試就失敗。

## 相對來源的調整（僅此二項，註解未動）

1. 移除 `CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;` 及其後的 `DO $vector_check$ … $vector_check$;` 檢查。
2. `rag_chunks.embedding` 由 `extensions.vector(1536)` 改為 `text`。

原因：測試用 `postgres:15` 映像沒有 pgvector。RAG 向量功能因此**不在此基線的驗證範圍內**。

## 檢查紀錄

- 來源檔與衍生檔皆為純 DDL：沒有 `INSERT`；搜尋信箱、金鑰／Token 樣式、雜湊值、手機與身分證樣式，只有文件網址與 Argon2 格式說明文字，無真實資料。
- 沒有此基線對應的 Alembic revision；`app/db/migrations/versions/` 的重送 Migration 是**在這個基線之上**的增量，不是它的 baseline。

## 使用

- 設定 `ISOLATED_ADMIN_URL` 即自動使用此檔；`ISOLATED_BASELINE_SQL` 可改指定其他檔（例如較新的草案；載入器在主機沒有 pgvector 時會自動移除向量欄位與擴充）。
- 更新此檔時：重新衍生、同步更新標頭與本檔的指紋、重跑 `tests/integration`，並在 PR 說明來源版本。**不得**在未經團隊核定下把它當正式 Schema 引用。

## 與正式環境的差異（必讀）

- 正式 DB 結構未驗證（可能為 v1.4／v1.5 或其他）；此基線通過測試**不代表**正式環境可直接套用 Migration。
- v1.5 與 v1.8 的身分表不同：現有整合測試的 `World` 需要 v1.8 的可延遲外鍵，v1.5 基線會在建立測試帳號時失敗。
