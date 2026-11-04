# 重送資料結構：ADMIN 跨組整合清單

> 2026-11-03，API 分支 `feature/resubmit-core-rules`（未 Commit）。依據 ADMIN 分支 `feature/applicant-return-flow-db`（`d7b20f9`）的**唯讀**檢查；
> 沒有修改 ADMIN 任何檔案。Migration `7c1d4e9a2b30` 的結構**正式 DB 已於 2026-11-04 以手動 SQL 建立相同結構（Schema v2.1）**，以下皆為需與 ADMIN 組員協調的事項，不是已完成的整合。

## 先說結論

ADMIN 現行程式**不會被 Migration 弄壞**（沒有任何程式寫入四張新歷史表；ADMIN 沒有 ORM Model，全部是原生 SQL；它的 v1.4 SQL 副本與
API 測試基線的發票段逐行相同，diff 0 行）。但要支援 R1／R8 的功能，下列幾項必須由 ADMIN 配合調整。

| # | 問題 | 證據（ADMIN 檔案） | 影響 | 需要 ADMIN 做的事 | 狀態 |
|---|---|---|---|---|---|
| 1 | `LIST_REVIEW_FIELD_REVIEWS` 只讀 `invoice_field_reviews`，不認識承接列 | `app/db/repositories/finance_review_repository.py:28-35` | 被承接確認的欄位在新一輪沒有覆核列，畫面會顯示成「沒有紀錄／未確認」，無法分辨「承接前輪確認」與「本輪待覆核」 | 查詢加入 `invoice_field_review_carryovers`（join 來源覆核列取原確認者、確認時間、來源輪次），並在畫面標示「承接自第 N 輪」 | 待協調 |
| 2 | 退回已承接欄位會無聲失敗 | 同檔 `UPDATE_FIELD_REVIEW`：以「本輪＋欄位」定位列並 `UPDATE`，0 筆時不報錯 | 被承接欄位本輪沒有覆核列，退回原因只會落到 `invoice_status_history.reason` 純文字，沒有結構化退件項目，且不會讓該欄位回到待覆核 | 退回時改寫 `invoice_return_items`（欄位、原因、授權欄位），並對 UPDATE 的筆數做檢查，0 筆要明確處理而非忽略 | 待協調 |
| 3 | 退件原因與 `invoice_return_items` 契約 | `app/schemas/finance_review.py:189-197`（原因放 `reason`、欄位覆核 `review_comment`） | 現行契約是純文字＋`v_invoice_return_fields`；R8 要求結構化（類型、定位、原因、允許欄位集合、回覆、處理結果） | 以 API 的 Migration 定義為準對齊 Schema／Repository；`allowed_fields` 的 JSON 格式見 Migration 的 CHECK；圖片類型不可有回覆 | 待協調 |
| 4 | R2 退件來源 `old_status` | `app/services/finance_review_service.py:303`（`old_status=case.status`）；`INSERT_HISTORY` 有寫 `old_status` | 程式有寫入來源狀態，但 `case.status` 來自示範資料或 DB 取決於分支；目前團隊只有財務一層，正式值應為 `pending_accounting_review` | 確認 DB 案件路徑退回時寫入的 `old_status` 非 NULL 且為實際來源；API 重送時依此回到來源節點 | 待驗證（未在 DB 實測） |
| 5 | `invoice_field_reviews` 上新增的 Trigger 是否擋既有合法操作 | `UPDATE_FIELD_REVIEW` 把本輪列設為未確認 | Trigger 只擋「已被後續輪次承接的確認列」被取消或更動；本輪列不可能已被未來輪次承接，所以既有退回 UPDATE **不受影響**（API 專屬庫測試已驗證：未被承接的列可正常勾選／取消）。ADMIN 沒有 `INSERT INTO invoice_field_reviews`，也不受「同輪承接與覆核列互斥」影響 | 無需修改；請 ADMIN 在隔離庫跑一次自己的退回流程確認 | 低風險，待 ADMIN 確認 |
| 6 | ADMIN 的 SQL 副本、Model 與新結構 | ADMIN `docs/InvoiceGuard_AI_PostgreSQL_Schema_v1_4_PortableAuth_draft.sql`；`app/db/models/` 為空；`app/db/contracts.py` | v1.4 副本發票段與 API 測試基線相同；但副本沒有四張新表與 `invoice_changes.event_seq`；ADMIN 無 ORM Model，無需同步 Model，但文件／契約快照需補 | 取得核定後在 ADMIN 文件補新結構；`app/schemas/case.py` 的修改紀錄顯示（`invoice_changes`）需依 `event_seq` 排序，且不可假設 `event_seq` 一定非 NULL（舊資料為 NULL） | 待協調 |

## 其他須知

- 歷史表（快照、冪等、承接、退件項目）禁止 UPDATE／DELETE／TRUNCATE（退件項目只有回覆與處理結果欄位可更新），`invoices` 對它們為 RESTRICT：ADMIN 不得新增刪除發票或測試資料的程式路徑，作廢只轉狀態為 `voided`。
- ADMIN 若在共用或正式庫直接寫入新表，必須先取得正式庫 Schema 核對與 Migration 執行授權；本清單不授權任何此類操作。
- 前台不連資料庫，只受未來 API 契約影響。
