# 退回重送（Resubmit）API Contract 草案

> **狀態：草案，未核定，不是實作。** 2026-11-03，依 API `main`（`86a7699`）與 ADMIN `main`（`6dcf6da`）的程式整理。
> 本文件只描述「建議怎麼設計」與「還必須由團隊決定什麼」；規則欄位標「建議」者都是技術建議，不是已核定的業務規則。
> 正式資料庫目前很可能是 v1.4／v1.5；`InvoiceGuard_AI_PostgreSQL_Schema_v1_8_PortableAuth_draft.sql` 是設計草案、**尚未執行**，
> 本文件引用的欄位與約束以該草案為準，實作前必須對照實際資料庫。
> 在第 9 節的測試（含真實 PostgreSQL 的端到端案例）通過之前，**不得把重送標示為已完成驗收**。

## 0. 責任與分工（需團隊確認）

- API 放在哪個 Repository 是技術問題；誰負責開發是分工問題。團隊規則是各組依自己的業務範圍建立與維護 API，沒有 API 專責組。
- 建議拆成：欄位編修與檢核的共用邏輯（與 C 組首次提交直接相關）、更新發票與明細的服務、財務退回原因與審核處置（財會業務）、
  退回後的重送流程與狀態轉換（跨組整合）、Schema 或輪次規則調整（須團隊協調）。**本文件不代為決定誰負責。**

## 1. 範圍

**納入**：財務退回（`returned_to_applicant`）後，申請人以「修改補正」或「不修改的申覆」重新送審；退回項目的讀取；重送的查重、檢核、
歷程、輪次、冪等與權限。

**不納入（另案）**：申請人終止（ADMIN 目前已以條件更新直接寫入，見 6.3）、單位核准與會計覆核之後的轉換、申報檔與傳票、
`deduction_code`／`account_code` 欄位。

**核心原則**：「修改補正」與「申覆」是**同一個重新送審業務**的兩種情境，由同一個服務處理，不另建 ADMIN 直接寫 DB 的捷徑。
重送牽涉三件事，缺一不可：資料變更（改了什麼）、審核責任（哪些退回問題已處理、哪些要再審）、流程控制（誰可以重送、交給誰）。

## 2. 現況盤點（已對照程式）

### 2.1 現有 API（`app/routers/v1/invoices.py`）

`POST /recognize`、`POST /check-duplicate`、`POST /check-required`、`POST /check-warnings`、`POST /invoices`（首次提交）、
`GET /invoices`（我的發票）、`GET /invoices/{id}`（詳情）。**沒有**修改（PATCH／PUT）、重送或終止端點
（`docs/API_CONVENTIONS.md` 亦明寫）。

### 2.2 首次提交 `submit()` 的哪些可重用、哪些只適用首次

| 項目 | 現況（`invoice_upload_service.submit`） | 重送可否沿用 |
|---|---|---|
| 欄位與明細轉換、`tax_period_for` | 由請求組 `InvoiceHeader`／`InvoiceItem` | 可重用 |
| 檢核提醒 | `future_date_warnings`、`_consistency_warnings`（含統編檢查碼、稅額、總計、國字大寫、逐行乘積、明細合計） | 可重用，結果寫入 `validation_results` |
| 使用者修改的差異與逐次修改 | `_user_modifications(ai_invoice, header, items, sources, request)`，基準是**辨識紀錄的 AI 原值**，並要求修改紀錄「從 AI 原值接續到送出值」（否則 `INVOICE_CHANGES_INVALID`） | **不能直接用**：重送的起點是上一輪送出值，不是 AI 原值（見規則 R9） |
| 輪次 | `submission_round=1` 寫死 | 不可沿用，需 +1 |
| 新增發票與明細 | `insert_invoice`、`insert_items`（全新 `item_id`） | 不可沿用，重送是更新既有列 |
| 查重 | `lock_invoice_key` 後 `exists_duplicate`（字軌＋號碼＋賣方統編，未作廢） | 需排除本案（否則一定自己撞自己） |
| 冪等 | `recognition_id` 只能用一次（`RECOGNITION_ALREADY_SUBMITTED` 409）；ADMIN 另以 `confirm_submitted` 查證 | 沒有天然的鍵，需另設（R7） |
| 影像 | `insert_file` 指向**辨識時已上傳**的同一 Storage 物件，提交時不搬移 | 換附件需走相同模式（R4／5.3） |
| 欄位覆核 | `insert_field_reviews(... submission_round=1, recognition_id=…)` | 需每輪一批，且承接規則未定義（R1） |
| 狀態歷程 | `old_status=None → pending_accounting_review`（`SUBMITTED_STATUS`） | 需 `returned_to_applicant → …` |
| 辨識紀錄 | `link_invoice(recognition_id, invoice_id, file_id)` | 僅在換附件時需要 |

### 2.3 退回現況（ADMIN `finance_review_service.return_to_applicant`，#24 起寫入 DB）

- 退回項目若對應本輪 `invoice_field_reviews` 的欄位：原因寫入該列 `review_comment` 並維持 `is_checked=false`，
  申請人由 `v_invoice_return_fields` 讀取。
- **沒有對應欄位覆核列的項目**（未修改過的欄位、附件、其他）：以「欄位：原因」逐行**純文字**寫進 `invoice_status_history.reason`。
- 申請人的回覆（已補正／申覆）目前只有 ADMIN 的 `ResubmitPlan.reason` 純文字，**沒有結構化保存**。
- 結論：`v_invoice_return_fields` **不是完整的退件待辦清單**；現有結構無法結構化追蹤「每個退件項目→回覆→處理結果」（見 R8）。

### 2.4 Schema（v1.8 草案）相關事實

- `invoice_items`：沒有邏輯刪除欄位（只有 `item_id`、`line_no`、品名、數量、單價、金額、時間戳）。
- `invoice_changes`、`invoice_field_reviews` 對 `invoice_items` 的外鍵是 `ON DELETE RESTRICT`；`invoice_field_reviews` 對
  `ai_recognition_logs` 也是 `RESTRICT`，並有 `UNIQUE NULLS NOT DISTINCT (invoice_id, submission_round, field_scope, item_id, field_name)`。
- `invoice_files` 有 `version_no`、`is_current`（已具備檔案版本概念）。
- `v_invoice_return_fields`：`status='returned_to_applicant'` 且 `submission_round = invoices.submission_round` 且 `is_checked=false`。

## 3. 待決規則（需團隊決定）

「建議」是技術建議；**決定人**欄由團隊填寫。

| # | 規則 | 選項 | 建議 | 影響 | 決定人 |
|---|---|---|---|---|---|
| R1 | 上一輪已確認的欄位覆核 | A 全部重來／B 未修改的欄位承接確認、已修改的不承接 | B；歷史覆核一律保留不刪 | 財務重審工作量；`invoice_field_reviews` 寫入規則 | |
| R2 | 重送後的狀態 | `pending_accounting_review`（與現行首次提交 `SUBMITTED_STATUS` 一致）／`pending_department_approval`／依退件來源決定 | 依「退件來自哪個審核節點」決定，不寫死；現況團隊只留財務一層審核 | 狀態機、列表篩選 | |
| R3 | 明細刪除與新增 | A 邏輯刪除（需 Schema）／B 明細版本／C 不允許刪既有明細 | A 或 B；**保留歷史明細與覆核，不為了外鍵而刪除舊紀錄** | **Schema 需調整** | |
| R4 | 換附件 | 是否重新 AI 辨識；舊辨識結果能否代表新圖 | 換附件必須先走 `recognize`（得到新 `recognition_id`）；舊辨識不得無條件代表新圖 | Storage 一致性、費用 | |
| R5 | 誰能重送 | 僅原提交者／同部門／其他 | 最小權限：核對案件、原提交者、案件部門與目前選取部門；無權回 404（不洩漏存在，沿用 API 慣例） | 權限測試 | |
| R6 | 重送的查重 | 排除本案 | 排除本案 ID，仍檢查其他案件（含 `lock_invoice_key`） | `exists_duplicate` 需加排除條件 | |
| R7 | 冪等與版本衝突 | 只用 `expected_round`／再加重試識別 | `expected_round`（版本衝突）＋ `idempotency_key`（識別同一次操作）；兩者用途不同，不可混為一談 | 需保存已處理的 key（Schema 或既有表欄位） | |
| R8 | 退件項目與申覆回覆如何結構化保存、追蹤與再次審核 | A 維持欄位覆核＋歷史純文字（現況）／B 新增退件項目資料結構 | B（見 6.1）；A 無法驗收「每項退件都有回覆與處理結果」 | **Schema 需新增** | |
| R9 | 修改歷程的記錄粒度與起點 | 每次編輯事件／只記每次正式保存；起點是 AI 原值還是上一輪送出值 | 起點：上一輪送出值（`invoice_field_reviews` 的 AI 原值欄位仍保留 AI 原值）；粒度：先決定。**不得承諾保存從未收到的中間修改**（ADMIN 目前送空的 `changes`，API 只補一筆淨差異） | `invoice_changes` 的完整性 | |
| R10 | 重送後財務看到什麼 | 是否同時能查上一輪與本輪 | 兩輪都可查，輪次分開顯示 | 讀取端點與畫面 | |

## 4. 端點設計草案

### 4.1 讀取退件項目 `GET /api/v1/invoices/{invoice_id}/return-items`

供申請人端（前台、ADMIN）顯示「要補正什麼」。僅 `returned_to_applicant` 且有權者可讀。
**R8 未決前，回應格式只能標為暫定。**

```json
{
  "invoice_id": "UUID",
  "submission_round": 1,
  "returned_at": "2026-11-03T05:00:00Z",
  "items": [
    {
      "return_item_id": "UUID | null",
      "field_scope": "header | item | attachment | other",
      "field_name": "total_amount",
      "item_id": "UUID | null",
      "reason": "請附折讓單",
      "status": "open | corrected | appealed"
    }
  ]
}
```

### 4.2 重送 `POST /api/v1/invoices/{invoice_id}/resubmit`

認證同現行（`Authorization: Bearer <session_token>`，每次重新核對 Session）。「修改補正」與「申覆」共用同一端點與服務。

**請求（草案）**

```json
{
  "idempotency_key": "UUID（用戶端開啟編修畫面時產生，同一次操作的重試使用相同值）",
  "expected_round": 1,
  "recognition_id": "UUID | null（僅換附件時，來自新的 /recognize）",
  "invoice_track": "AB", "invoice_number": "12345678", "invoice_date": "2026-10-15",
  "seller_tax_id": "12345678", "seller_name": null, "buyer_tax_id": null, "buyer_name": null,
  "tax_type": "taxable",
  "sales_amount": "5000", "tax_amount": "250", "total_amount": "5250", "total_amount_zh": null,
  "items": [
    {"item_id": "UUID | null（既有明細帶 item_id；新增為 null）", "item_name": "…",
     "quantity": "2", "unit_price": "3000", "line_amount": "6000"}
  ],
  "changes": [],
  "responses": [
    {"return_item_id": "UUID | null", "field_scope": "header", "field_name": "total_amount",
     "item_id": null, "action": "corrected | appealed", "note": "申覆時必填"}
  ]
}
```

- 欄位格式與必填規則與 `InvoiceSubmitRequest` 相同（同一份 Pydantic 型別），不另寫一套。
- 既有明細帶 `item_id`；**未出現在請求中的既有明細視為被刪除**（需 R3 的 Schema 支援才可實作）。
- 純申覆時各欄位維持原值，只有 `responses`。
- `responses` 必須涵蓋所有 `open` 的退件項目（R8）；`appealed` 必須有 `note`；`corrected` 的項目必須實際有修改（沿用 ADMIN 現有 `prepare_resubmit` 的規則：已補正但未修改要擋）。

**成功回應 `201`（首次處理）／`200`（相同 `idempotency_key` 重送，回原結果）**

```json
{
  "invoice_id": "UUID", "status": "…", "submission_round": 2,
  "submitted_at": "…", "tax_period": "202610",
  "warnings": [{"field": "tax_amount", "code": "tax_amount_mismatch", "message": "…"}],
  "modified_fields": [{"field_scope": "header", "line_no": null, "field_name": "total_amount",
                       "ai_original_value": "…", "submitted_value": "…"}],
  "replayed": false
}
```

警示只提醒、不阻擋（與首次提交一致）。

### 4.3 查重調整 `POST /api/v1/invoices/check-duplicate`

新增選填 `exclude_invoice_id`（本案 ID），避免重送預檢時自己撞自己；其他案件的比對不變。回應仍只回 `is_duplicate`，不洩漏他人案件內容。

### 4.4 狀態轉換（建議）

```
returned_to_applicant ──resubmit（本契約）──▶ 由 R2 決定（現行首次提交為 pending_accounting_review）
returned_to_applicant ──terminate（另案，目前 ADMIN 直接寫入）──▶ voided
```

寫入條件一律「資料庫狀態仍等於預期狀態且輪次等於 `expected_round`」，否則 409，不寫任何資料。

## 5. 交易與一致性

### 5.1 資料庫交易步驟（單一交易，失敗全部 rollback）

1. 驗證 Session、依 5.4 核對權限（無權回 404）。
2. `SELECT … FOR UPDATE` 鎖定該案件列；確認 `status = returned_to_applicant`、`submission_round = expected_round`，否則 409。
3. 以 `idempotency_key` 查是否已處理過：有則直接回原結果（`200`、`replayed=true`），不再寫入。
4. 驗證請求格式與 `responses` 完整性；換附件時驗證 `recognition_id`（本人、未逾期、未使用、辨識成功）。
5. `lock_invoice_key` 後查重（排除本案）。
6. 計算檢核提醒，更新 `invoices` 欄位與 `validation_results`、`submission_round + 1`、狀態。
7. 更新既有明細、新增新明細、處理被刪除明細（依 R3）。
8. 寫 `invoice_changes`（依 R9）與新一輪 `invoice_field_reviews`（依 R1）。
9. 寫退件項目的回覆狀態（依 R8）、`invoice_status_history`（`returned_to_applicant → 新狀態`，含回覆摘要）。
10. 換附件時：`invoice_files` 新增一版（`version_no + 1`、`is_current` 切換）並 `link_invoice`。
11. 記錄 `idempotency_key` 的處理結果；`commit`。

### 5.2 `expected_round` 與冪等是兩件事

- `expected_round`：樂觀併發控制，防止使用者拿舊版本資料覆蓋新版本（例如財務已再次退回）。不同就 409。
- `idempotency_key`：識別「同一次操作」的重試。第一次已成功但回應遺失時，重送相同 key 應回 `200` 與原結果，使前端確定第一次有成功；
  單靠 `expected_round` 只能回 409，前端無從得知第一次是否成功。

### 5.2.1 需保存的資料

`idempotency_key` 與處理結果要持久化（例如重送紀錄表，或歷程列的欄位）。這需要 Schema 變更，見第 10 節。

### 5.3 Storage 一致性（不可與 PostgreSQL 交易混為一談）

PostgreSQL 交易只能保證資料表的變更一起成功或一起回復，**不能**讓 Storage 的上傳或刪除一起 rollback。

- 換附件必須沿用現行首次提交的模式：先呼叫 `POST /recognize`（Storage 上傳＋有期限的辨識紀錄），重送只在資料庫交易內**引用**該來源，
  不在交易內做任何 Storage 寫入。
- 重送失敗時，已上傳的新物件由既有逾期清理（`cleanup_expired_sources`）處理；**不提前刪除舊附件**，舊版本以 `is_current=false` 保留。
- 重送成功後舊附件不刪除。

### 5.4 權限（建議，需 R5 核定）

只有原提交者（`submitted_by`）可重送，案件部門須等於目前選取部門；其餘一律 404。財務不能代替申請人重送。
每次請求重新核對 Session（沿用現行做法）。

## 6. 資料寫入對照

| 資料表 | 重送時 | 備註 |
|---|---|---|
| `invoices` | 更新欄位、`validation_results`、`submission_round+1`、`status`、`updated_at`；保持 `submitted_by`、`created_at` | 重送者不覆蓋 `reviewed_by`／`reviewed_at` |
| `invoice_items` | 更新、新增；刪除依 R3 | **v1.8 沒有邏輯刪除欄位** |
| `invoice_changes` | 新一輪的修改紀錄（`submission_round` = 新輪次） | 起點與粒度依 R9 |
| `invoice_field_reviews` | 新一輪的欄位覆核；上一輪保留不刪 | 承接依 R1；唯一約束含輪次，不衝突 |
| `invoice_status_history` | 新增一列 | 不修改歷史列 |
| `invoice_files` | 換附件時新增一版 | `version_no`／`is_current` |
| `ai_recognition_logs` | 換附件時 `link_invoice` | 沿用 |
| 退件項目與回覆 | 見 6.1 | **R8 未決** |
| 冪等紀錄 | 見 6.2 | **R7 未決** |

### 6.1 退件項目與回覆（R8，建議方案 B）

新增資料結構（名稱暫定 `invoice_return_items`）：`return_item_id`、`invoice_id`、`submission_round`（被退回的輪次）、`field_scope`
（header／item／attachment／other）、`item_id`、`field_name`、`reason`、`status`（open／corrected／appealed／accepted）、
`response_note`、`responded_by`、`responded_at`、`created_by`（財務）、`created_at`。
財務退回時寫入；申請人重送時寫回覆；財務再審時可標示 accepted。這使「每項退件都有回覆與處理結果」可查詢、可驗收。
**需要 migration，執行須另行取得授權。** 方案 A（維持現況）無法結構化追蹤，不建議。

### 6.2 冪等紀錄（R7）

建議新增 `invoice_resubmissions(idempotency_key PK, invoice_id, from_round, to_round, requested_by, requested_at, result jsonb)`，
或在 `invoice_status_history` 增加可唯一的 `idempotency_key` 欄位。擇一，需 migration。

### 6.3 與現行 ADMIN 直接寫入的關係

ADMIN 目前對 DB 案件直接寫入「財務核准／退回」與「申請人終止」（皆為單純狀態轉換，條件更新＋歷程同交易）。
重送涉及欄位與覆核的建立語意，**不比照辦理**。終止是否也遷到 API，另案決定。

## 7. 錯誤碼（沿用 `{"error": {"code", "message", "details"}}`）

| HTTP | code | 條件 |
|---|---|---|
| 401 | `UNAUTHORIZED`（既有） | Session 無效 |
| 404 | `NOT_FOUND`（既有；`GET /invoices/{id}` 目前也用它，不存在與非本人回應相同） | 無此案件或無權（不洩漏存在） |
| 409 | `INVOICE_NOT_RETURNED`（新） | 狀態不是 `returned_to_applicant` |
| 409 | `RESUBMIT_ROUND_STALE`（新） | `expected_round` 與目前輪次不符 |
| 409 | `INVOICE_DUPLICATED`（既有） | 與其他案件重複 |
| 409 | `RECOGNITION_*`（既有） | 換附件的辨識紀錄不存在、已使用、逾期或未完成 |
| 422 | `VALIDATION_ERROR`（既有） | 格式錯誤，`details` 只回 `loc`／`type`／固定訊息 |
| 400 | `RESUBMIT_RESPONSES_INCOMPLETE`（新） | 有未回覆的退件項目、申覆缺說明、聲稱已補正但未修改 |
| 400 | `INVOICE_ITEMS_INVALID`／`INVOICE_CHANGES_INVALID`（既有） | 明細或修改紀錄與送出內容不一致 |
| 200 | （成功，`replayed=true`） | 相同 `idempotency_key` 的重試 |

新增的業務代碼依 `API_CONVENTIONS.md` 6.2 節規定，實作時需登記於該表。

重試相關：5xx 或逾時時，用戶端**重送相同的 `idempotency_key`**，不得產生新 key；回應是 `200`＋原結果或 `201`。

## 8. 對 ADMIN 與前台的影響

- 需有：待補正案件的編修畫面（預填 DB 資料、標示被退回的欄位、每項選「已補正」或「申覆」、換附件走 `recognize`）、
  重送按鈕、冪等與逾時的處理（不當成失敗）。
- ADMIN 步驟 3 的核對表單與即時檢核（`check-*`）可重用；送出改呼叫本端點。
- ADMIN 目前送空的 `changes`；若 R9 選擇保存每次編輯事件，前端需像前台一樣收集編輯歷程。
- `procurement_case_service.prepare_resubmit` 保留作前端預檢，**真正的強制檢查在 API**。
- 前台（手機）同樣呼叫本端點，不另做一套。

## 9. 測試案例（先寫，再實作）

**單元（替身）**
1. 狀態不是 `returned_to_applicant` → 409 `INVOICE_NOT_RETURNED`。
2. `expected_round` 過期 → 409，不寫任何資料。
3. 非原提交者／他部門 → 404。
4. 未回覆全部退件項目、申覆缺說明、已補正但未修改 → 400。
5. 查重排除本案；與他案重複 → 409。
6. 相同 `idempotency_key` 重試 → 200＋原結果，資料不再變動。
7. 檢核提醒與首次提交一致（重用同一函式）。
8. 換附件：`recognition_id` 逾期、已使用、非本人 → 對應錯誤。
9. 任一步驟失敗 → 整個交易 rollback。

**真實 PostgreSQL 整合（隔離測試庫）**
10. **主要情境**：首次提交 → 財務退件 → 申請人修改明細並回覆原因 → 重送 → 財務看到新一輪資料與回覆，同時能查上一輪歷史。
11. 刪除明細後，歷史覆核與修改紀錄仍可查（R3）。
12. 換附件：新版本 `is_current=true`，舊版本保留；交易失敗時舊版本不變、Storage 殘留物件由逾期清理處理。
13. 並行：財務再次退回與申請人重送同時發生，只有一方成功，另一方 409。
14. 並行：兩次相同 `idempotency_key` 同時送出，只產生一次輪次增加。
15. `v_invoice_return_fields` 與（若採 R8 方案 B）退件項目的讀取一致。
16. 唯一約束：新一輪 `invoice_field_reviews` 不與上一輪衝突。

## 10. Schema 影響（需協調，執行 migration 須明確授權）

| 項目 | 需要 | 備註 |
|---|---|---|
| 明細邏輯刪除或版本（R3） | 是（`invoice_items` 欄位或版本表） | 現有結構無法在保留歷史下表示「不再使用」 |
| 退件項目與回覆（R8 方案 B） | 是（新表） | 或維持純文字並接受無法結構化驗收 |
| 冪等紀錄（R7） | 是（新表或欄位） | |
| `idempotency`／`return_items` 的 RLS 與授權 | 是 | 比照 v1.8 預設拒絕 |
| 其餘（`invoices.submission_round`、`invoice_files.version_no`） | 否 | 已存在 |

API 是 Schema 與 Alembic 的管理者；ADMIN Model 需同步。建立 migration 檔屬一般開發，**執行須使用者明確授權**。

## 11. 建議的實作順序

1. 團隊確認 R1～R10 與分工、是否改 Schema。
2. 依本文件第 9 節先寫測試案例。
3. 在獨立功能分支實作共用重送服務與端點，優先重用 `submit()` 的驗證與保存能力（2.2 表中標「可重用」者）。
4. 在隔離 PostgreSQL 跑第 9 節的整合測試。
5. 接 ADMIN，再接前台。
6. 補齊文件、`DEVELOPMENT_STATUS` 與稽核紀錄後才標示完成。

## 12. 風險與未驗證事項

- 本文件的 Schema 事實取自 v1.8 草案，**未對照正式資料庫**；正式庫可能缺少某些欄位或約束。
- 沒有真實 PostgreSQL 可驗證交易與併發；第 9 節的整合測試是必要條件。
- R1～R10 都是建議，未經團隊核定；任何一項的決定都可能改變端點與 Schema。
- 重送完成前，申請人只能終止被退回的案件，無法修改補正。
- 退件項目若維持純文字，申覆與補正的驗收只能靠人工閱讀歷程。
