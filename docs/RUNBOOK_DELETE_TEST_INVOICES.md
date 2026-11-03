# 手動作業：刪除正式 DB 的人工測試發票資料

> 2026-11-03。**此文件只供人工執行，AI 助手不執行刪除**（永久刪除正式資料）。SQL 依 repository 實際使用的資料表與
> v1.8 草案的外鍵整理，**v1.8 草案尚未在正式 DB 執行**，正式 DB 現行為 v1.4：執行前請在 Supabase SQL Editor
> 先看實際欄位與外鍵（`\d+ public.invoices` 等），與下面不同時以實際為準。

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
