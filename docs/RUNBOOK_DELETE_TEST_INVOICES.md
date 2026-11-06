# 手動作業：刪除正式 DB 的人工測試發票資料

> 2026-11-03。**此文件只供人工執行，AI 助手不執行刪除**（永久刪除正式資料）。SQL 依 repository 實際使用的資料表與
> v1.8 草案的外鍵整理，**v1.8 草案尚未在正式 DB 執行**，正式 DB 現行為 v1.4：執行前請在 Supabase SQL Editor
> 先看實際欄位與外鍵（`\d+ public.invoices` 等），與下面不同時以實際為準。

> **2026-11-03 重要限制（重送歷史表）**：Migration `7c1d4e9a2b30` 新增的 `invoice_submission_snapshots`、`invoice_resubmissions`、
> `invoice_field_review_carryovers`、`invoice_return_items` 是不可變歷史表（禁止 UPDATE／DELETE／TRUNCATE，對 `invoices` 為 RESTRICT）。
> **2026-11-04 起此限制已對正式 DB 生效**：正式 DB 已於 2026-11-04 以手動 SQL 建立相同結構（Schema v2.1，含這四張表與保護 Trigger），下列限制適用於正式資料。
> **首次提交快照（分支 feature/first-submit-round1-snapshot，Merge 後生效）**：首次提交也會寫入不可變的第 1 輪快照，所以從該版本起提交的**每一張**發票（不只重送過的）都無法用下列步驟刪除。
> 該 Migration 套用後，凡是已有這些歷史紀錄的發票，下面的步驟 4 **一定會失敗，這是設計**；**不要**停用 Trigger、`CASCADE`、
> `session_replication_role` 或 `alembic downgrade` 來繞過。本階段不提供永久刪除有重送歷史的正式資料，使用者要作廢發票只轉換狀態為 `voided`，
> 正式資料的永久刪除另案做資料治理。本文件的刪除步驟只適用於「尚未套用該 Migration、或確定沒有重送歷史」的人工測試資料，
> 且仍需人工執行。測試清理請見文末「自動化整合測試的專屬資料庫」。

## 0. 前置條件

- 有 `postgres` 或等效角色（一般 API 角色受 RLS 與 REVOKE 限制，可能刪不掉或看不全）。
- 先**備份**：Supabase 專案做一次 Point-in-time 或手動備份；步驟 3 也會匯出要刪的列。
- 在**交易**中操作（`BEGIN` … 檢查筆數 … `COMMIT`／`ROLLBACK`），不要用自動提交的工具一行一行跑。
- 刪除前通知同事，避免有人同時提交。

## 1. 決定範圍（先填這三項，不要用「全部」）

測試資料可以用下列任一條件界定，**優先用「帳號＋時間範圍」**：

| 條件 | 範例 |
|---|---|
| 提交者 | `submitted_by = '<測試帳號的 user_id UUID>'` |
| 時間 | `created_at >= '2026-10-29' AND created_at < '2026-11-04'`（台灣時間要換成 UTC） |
| 辨識來源 | 未提交的辨識（`ai_recognition_logs.invoice_id IS NULL`）另外處理，見步驟 5 |

## 2. 先只讀：找出要刪的案件

```sql
BEGIN;

-- 暫存表只存在這個連線，結束就消失
CREATE TEMP TABLE _del_invoices ON COMMIT DROP AS
SELECT invoice_id
FROM public.invoices
WHERE submitted_by = '<測試帳號 UUID>'
  AND created_at >= '<起>' AND created_at < '<迄>';

SELECT count(*) AS invoices_to_delete FROM _del_invoices;

SELECT i.invoice_id, i.invoice_track, i.invoice_number, i.status, i.submitted_by, i.created_at
FROM public.invoices i JOIN _del_invoices d USING (invoice_id)
ORDER BY i.created_at;
```

**停下來人工核對這份清單**：筆數與預期一致、沒有正式使用者的資料、沒有別人的案件。不一致就 `ROLLBACK;`
重新縮小條件。

## 3. 匯出備份與 Storage 路徑（刪 DB 前一定要做）

```sql
-- 影像路徑：DB 刪了之後就找不到物件了，先留下來
SELECT f.bucket_name, f.storage_path
FROM public.invoice_files f JOIN _del_invoices d USING (invoice_id);

SELECT r.recognition_id, r.source_storage_path
FROM public.ai_recognition_logs r JOIN _del_invoices d ON r.invoice_id = d.invoice_id
WHERE r.source_storage_path IS NOT NULL;
```

把兩個結果另存（CSV）。需要時再匯出各表整列：`\copy (SELECT * FROM public.invoices WHERE invoice_id IN (SELECT invoice_id FROM _del_invoices)) TO 'invoices_backup.csv' CSV HEADER`
（其餘表同法）。

## 4. 依外鍵順序刪除（RESTRICT 的子表要先刪）

> v1.8 草案的外鍵：`invoice_field_reviews`、`invoice_changes` 對 `invoices` 是 **RESTRICT**，
> `invoice_field_reviews` 對 `ai_recognition_logs` 也是 RESTRICT；`invoice_items`、`invoice_files`、
> `invoice_status_history` 是 CASCADE；`ai_recognition_logs.invoice_id` 是 SET NULL。

```sql
DELETE FROM public.invoice_field_reviews WHERE invoice_id IN (SELECT invoice_id FROM _del_invoices);
DELETE FROM public.invoice_changes       WHERE invoice_id IN (SELECT invoice_id FROM _del_invoices);

-- 若同一張辨識紀錄不再需要，先刪辨識紀錄再刪案件，避免留下 invoice_id 被設成 NULL 的孤兒
DELETE FROM public.ai_recognition_logs   WHERE invoice_id IN (SELECT invoice_id FROM _del_invoices);

-- CASCADE 子表（invoice_items、invoice_files、invoice_status_history）會隨案件一併刪除
DELETE FROM public.invoices              WHERE invoice_id IN (SELECT invoice_id FROM _del_invoices);
```

每個 `DELETE` 都看一下「DELETE n」的筆數，和步驟 2 的預期相符才繼續。若遇到 `foreign key violation`，代表實際
DB 還有別的子表，**不要用 `CASCADE`、`session_replication_role = replica` 或關掉觸發器硬刪**，先查是哪張表。

驗證後再提交：

```sql
SELECT count(*) FROM public.invoices WHERE invoice_id IN (SELECT invoice_id FROM _del_invoices); -- 應為 0
COMMIT;   -- 有疑慮就 ROLLBACK;
```

## 5. 未提交的辨識紀錄（可選）

只辨識、沒提交的紀錄（`invoice_id IS NULL`）影像 1 小時後會被後續辨識請求順帶刪除（`source_deleted_at` 標記），
紀錄本身不會自動刪。要清掉的話用同樣的方式界定「測試帳號＋時間」，先 `SELECT` 再 `DELETE`：

```sql
SELECT recognition_id, requested_by, created_at, result_status
FROM public.ai_recognition_logs
WHERE invoice_id IS NULL AND requested_by = '<測試帳號 UUID>' AND created_at >= '<起>';
-- 核對後：DELETE FROM public.ai_recognition_logs WHERE recognition_id IN (...);
```

## 6. 刪 Storage 影像（DB 刪完之後）

Supabase Dashboard → Storage → `invoices` bucket → 依步驟 3 留下的 `storage_path` 逐一刪除
（路徑格式 `{user_id}/INVOICES_{時間}_{recognition_id}.{副檔名}`）。**只刪步驟 3 清單上的物件**，不要整個資料夾清空。

## 7. 完成後確認

- 步驟 2 的查詢再跑一次，筆數為 0。
- 在 ADMIN 的案件列表（`/cases`）與前台「我的發票」確認測試案件已不見。
- 記錄：誰、何時、條件、刪除筆數、備份位置，補到 `docs/REVIEW_FIX_LOG.md`。

## 不要做的事

- 不要 `TRUNCATE`、不要沒有 `WHERE` 的 `DELETE`、不要在沒有交易的情況下執行。
- 不要刪 `user_profiles`、`departments` 等主檔；測試帳號本身若要清除另案處理。
- 不要用 API 或 ADMIN 的程式去刪：目前沒有核定的刪除端點，也沒有稽核紀錄。

## 自動化整合測試的專屬資料庫（2026-11-03）

自動化整合測試**不使用上面的步驟**，也不連正式或共享資料庫。每個 pytest 工作階段建立自己的資料庫，結束時只刪除它自己建立的庫：

```bash
export ISOLATED_ADMIN_URL='postgresql+psycopg://<本機帳號>:<密碼>@127.0.0.1:<埠>/postgres'   # 可建立資料庫的本機帳號，主機必須是回送位址
# 可選：export ISOLATED_BASELINE_SQL='<其他基線 Schema SQL 檔>'；未指定則使用 tests/fixtures/sql 的 test-only 基線（不是正式 Schema，見該目錄 README）
python -B -m pytest tests/integration
```

- 資料庫名稱為 `ig_it_` 加 12 位十六進位，建立時在資料庫註解寫入本次工作階段的標記（`invoiceguard-it:<token>`）。
  刪除前必須名稱格式、註解標記與本次 token 三者都相符，否則拒絕刪除；管理連線不可位於要刪除的庫。不以名稱含 test 判斷，不用萬用字元。
- 載入基線與 Migration 的 `upgrade()` 是在這個專屬庫內執行；**不要用 `alembic downgrade` 當作清理方式**（它會刪除新表的全部資料，只能用於隔離環境的來回測試）。
- 向下相容：只設定 `ISOLATED_DB_URL`（已準備好的本機庫）時，測試維持逐筆清理，不建立也不刪除資料庫；需要寫入歷史表的測試會自動略過。**若該庫已套用重送 Migration，而某個測試寫入了歷史表，清理會被保護機制擋下，`world` fixture 會以明確訊息讓測試失敗並留下殘留測試帳號**（不可繞過保護）；請改用專屬資料庫模式，並人工處理那個庫的殘留測試資料。
- Alembic 線上模式測試需要啟用 TLS 的本機 PostgreSQL（`env.py` 強制 TLS）；伺服器沒有 TLS 時略過，`ISOLATED_REQUIRE_ALEMBIC_ONLINE=1` 則改為失敗。CI 做法見 `docs/CI_POSTGRES_INTEGRATION_PROPOSAL.md`（提案）。

### 測試中斷後的殘留排查

測試程序被強制中止時可能留下 `ig_it_*` 資料庫。**先列出，確認標記，再由人工逐一處理**：

```sql
SELECT datname, shobj_description(oid, 'pg_database') AS marker
FROM pg_database WHERE shobj_description(oid, 'pg_database') LIKE 'invoiceguard-it:%';
```

只有標記為 `invoiceguard-it:` 且確認是自己的、已無人使用的庫才可 `DROP DATABASE "<名稱>"`；名稱像 `ig_t_*` 或其他沒有標記的庫屬於別人的測試資源，不要動。
清理失敗時 pytest 會失敗並印出庫名，請依本節處理，不要擴大刪除範圍。
