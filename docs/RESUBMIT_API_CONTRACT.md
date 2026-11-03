# 退回重送 API Contract（實作版）

> 2026-11-03，分支 `feature/resubmit-core-rules`（**尚未 Commit／Push／Merge**；Migration `7c1d4e9a2b30` **尚未在任何共用或正式資料庫執行**）。
> 以程式為準：`app/routers/v1/invoices.py`、`app/services/invoice_resubmit_service.py`、`app/schemas/invoice_resubmit.py`。
> 取代 `RESUBMIT_CONTRACT_DRAFT.md`（另一分支）中與 2026-11-03 正式決議衝突的舊規則（R1 全部重來、R4 同案換附件、R9 淨差異）。

## 端點

兩個端點都需要 `Authorization: Bearer <session_token>`；只有**原提交者**（`submitted_by`＝登入者，且案件部門＝目前選取部門）可用，其餘一律 404。

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/api/v1/invoices/{invoice_id}/return-items` | 退件項目、後端允許修改的欄位、上一輪正式提交資料、`can_resubmit`／`requires_void` |
| POST | `/api/v1/invoices/{invoice_id}/resubmit` | 欄位補正或附說明的純申覆；首次成功 201，相同冪等鍵重試 200（`replayed=true`） |

### POST 請求（欄位格式與手機送出相同）

`idempotency_key`（UUID）、`expected_round`（讀取時的 `submission_round`）、表頭欄位（本輪要正式提交的**完整**值）、`items`
（以上一輪既有的 `item_id` 逐筆對應，不可新增／刪除）、`changes`（前台 `editLog` 的逐次修改事件，值為修改前後）、`responses`
（每個欄位退件項目一筆：`corrected` 或 `appealed`，申覆必填 `note`）。不接受 `recognition_id`，不接受更換影像。

### 回應

`status`（回到退件來源節點）、`submission_round`、`submitted_at`、`warnings`、`modified_fields`（上一輪值→本輪值）、
`rereview_fields`（本輪待財務重審的欄位）、`carried_fields`（承接前輪確認的欄位，含 `source_round`／`confirmed_by`／`confirmed_at`）、`replayed`。

## 規則對照

| 規則 | 實作 |
|---|---|
| R1 | 重審：被退回欄位＋實際修改的授權相依欄位＋被申覆項目（及其授權欄位）；其餘已確認欄位寫 `invoice_field_review_carryovers`（指向原確認列，前輪不改）。前輪未確認的欄位補一筆待審列，**不因本輪沒有紀錄而推定通過** |
| R2 | 回到最近一次 `returned_to_applicant` 歷程列的 `old_status`；不在 `pending_department_approval／pending_accounting_review／pending_accounting_approval` 內則 409 |
| R3 | 每輪完整快照 `invoice_submission_snapshots`（表頭、全部明細、檢核、影像 `file_id` 參照）。**首次送出目前不寫 Round 1 快照**（避免 Migration 未套用的資料庫無法送出）；重送時補建上一輪快照 |
| R5 | 僅原提交者；查詢條件含 `submitted_by` 與部門，無權回 404 |
| R6 | 查重沿用 `lock_invoice_key`＋`exists_duplicate`，**以本案 `invoice_id` 排除**（`exclude_invoice_id` 只由後端傳入，前端不可指定）；已作廢案件不計 |
| R7 | 先鎖定案件並核對身分 → 冪等重放（相同 key＋內容回原結果；不同內容 409）→ 狀態與 `expected_round`；案件列 `FOR UPDATE` 序列化並行請求；`UNIQUE (invoice_id, from_round)` 兼防同輪重複推進 |
| R8 | 退件原因／授權欄位建立後不可改（DB Trigger）；回覆另存欄位；圖片退件列不接受回覆 |
| R9 | 驗證事件鏈起點＝上一輪提交值、終點＝本輪值；`invoice_changes.event_seq` 保存順序；沒有事件的淨修改補一筆；事件含未授權欄位即使改回也拒絕 |
| 圖片 | 有 `image` 退件項目一律 409 `RESUBMIT_IMAGE_REQUIRES_VOID`（即使同時有欄位問題）；作廢仍由既有流程（ADMIN 條件更新轉 `voided`）執行，**本階段 API 未提供申請人自行作廢端點** |

錯誤碼見 `API_CONVENTIONS.md` 6.2。

## 驗證狀態（誠實版）

- 專屬隔離 PostgreSQL 15（本機容器）以 TestClient 實際呼叫 API 並回查資料庫：`tests/integration/test_resubmit_api_isolated_db.py`（24 項）。
- **不是** ADMIN／前台端到端：退件案件由測試 Fixture `seed_returned_case` 直接寫入 `invoice_return_items` 等表。
- 正式 DB 結構與 Migration 相容性未驗證；GitHub Actions 尚未實際執行。

## 跨 Repo 最小必要修改（本階段未改任何其他 Repo）

### ADMIN（需與負責組員協調，勿由 API 組直接改其分支）

1. **財務退回寫入結構化退件項目**：退回時對每個問題寫 `invoice_return_items`（`item_kind`、欄位定位、`reason`、`allowed_fields`；圖片問題用 `image` 類型），同交易寫狀態歷程並確保 `old_status` 為實際來源節點（`pending_accounting_review`）。
2. **退回已承接欄位**：現行 `UPDATE_FIELD_REVIEW` 對「本輪沒有覆核列」的欄位更新 0 筆卻不報錯，須改為建立退件項目並檢查筆數。
3. **讀取承接結果**：`LIST_REVIEW_FIELD_REVIEWS` 加入 `invoice_field_review_carryovers`（join 原確認列取 `checked_by`／`checked_at`／來源輪次），畫面分別顯示「本輪重新勾選」與「承接自第 N 輪」。
4. **跨輪對照畫面**：用 `invoice_submission_snapshots` 顯示上一輪／本輪值，退件原因、申覆說明（`invoice_return_items`）、本輪編輯事件（`invoice_changes`，依 `event_seq`）。
5. 申請人作廢（圖片問題）沿用 ADMIN 既有條件更新；需限制「僅原提交者」並寫歷程。

### 前台（`InvoiceGuard-AI`）

1. 案件列表／詳情對 `returned_to_applicant` 顯示「補正」入口，呼叫 `GET /invoices/{id}/return-items`；`requires_void` 時只顯示「作廢後重新上傳」。
2. 返回既有人工修改頁（不重新辨識）：以 `previous` 預填，只開放 `editable_fields`；其他欄位唯讀（後端會再次驗證）。
3. 沿用 `mobile-camera.js` 的 `editLog`：事件起點改為上一輪值；送出時 `changes` 帶完整事件；每個退件項目選「已補正」或「申覆」（申覆必填說明）。
4. 送出時產生並保存 `idempotency_key`；逾時／5xx 重試使用**同一個** key；`409 RESUBMIT_ROUND_STALE` 提示重新讀取。
5. 顯示成功（新輪次、回到財務待覆核）與各錯誤碼的中文訊息。
6. 前台伺服器端 client（`app/clients/invoices.py`）新增上述兩個呼叫。

### API 本身尚缺

- 申請人自行作廢端點（目前只有 ADMIN 既有條件更新）。
- 首次送出寫 Round 1 快照（待 Migration 在目標資料庫確認套用後）。

## 2026-11-03 後續：ADMIN／前台分支與端到端驗證

- ADMIN 分支 `feature/resubmit-admin-integration`（自 origin/main `0ab2ca4` 新建，未動 Rayne Li／Stacie Chen 的分支）：財務退回同交易寫入 `invoice_return_items`（含授權相依欄位）、審核頁顯示承接前輪確認。
- 前台分支 `feature/resubmit-frontend`（自 origin/main `268c4bb`）：`/invoices/{uuid}/correct` 補正頁與 `invoice-correct.js`。
- 以一張測試發票在本機隔離 PostgreSQL 15 實際操作：前台登入與首次送出 → ADMIN 登入並退回（稅額，授權總計）→ 前台瀏覽器補正頁修改（含兩次稅額編輯事件）並重送 → 同識別碼重試回原結果 → ADMIN 審核頁顯示承接與待重審。OCR 以辨識紀錄替身取代；財務「逐欄確認」以 SQL 替身（ADMIN 已無此操作）。
- 仍待：申請人作廢端點、ADMIN 確認者顯示姓名、逐欄確認是否恢復（決定 R1 是否有資料可承接）、正式 DB 驗證。

## 2026-11-03 更新：R1 針對性覆核、申請人作廢

- **R1（使用者決定：不恢復逐欄確認）**：重送只對被退回、實際修改的授權相依欄位與被申覆的項目建立待審列；其餘欄位不產生任何覆核紀錄。只有存在真實的已確認覆核列時才寫承接紀錄，沒有逐欄確認紀錄就不會有承接（不產生虛假的已確認狀態）。`invoice_field_review_carryovers` 結構保留，未改 Migration。
- **申請人作廢**：`POST /api/v1/invoices/{invoice_id}/void`，body `{expected_round, reason?}`；僅原提交者（案件部門＝目前選取部門），其餘 404。只做 `returned_to_applicant → voided` 的條件更新並寫歷程，不刪除或修改案件、影像、辨識與退件歷史，不更動 reviewed_by／reviewed_at。重複作廢或已重送回 409 `INVOICE_NOT_RETURNED`，輪次過期回 409 `RESUBMIT_ROUND_STALE`。與重送競爭時兩者鎖定同一列案件並以條件更新，只有一方成功。作廢後重新上傳走既有 recognize → 首次提交，取得新的 invoice_id，查重不計已作廢案件。
- 前台補正頁在圖片問題時提供「作廢此案件並重新上傳」，成功後連到既有的手機／電腦上傳頁。
