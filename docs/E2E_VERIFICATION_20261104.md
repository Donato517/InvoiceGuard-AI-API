# 端到端整合驗證紀錄（2026-11-04，本機隔離環境）

> ⚠️ **本報告不是真實 Document AI 驗收證據**：OCR（Document AI）與 LLM（Groq）全部為 Mock 替身，Storage 為本機 S3 替身；辨識結果由測試腳本預先指定。辨識紀錄中的 `ocr_provider=google_document_ai` 只是程式常數，不代表呼叫過 Google。
> 範圍：真實前台（:8001）、ADMIN（:8002）、API（:8000）、PostgreSQL 15（Docker，僅綁 127.0.0.1，TLS 開啟，基線＋Migration 7c1d4e9a2b30）。
> **替身**：Storage 為本機 HTTPS 的 S3 相容替身（API 與 ADMIN 仍用真實 `S3StorageClient` 程式碼）；OCR 與 Groq 為 **Mock**（不是 Document AI）。
> **未驗證**：真實 Document AI（憑證只在正式環境設定，未取用）、正式 DB 的 Migration／權限／RLS、GitHub Actions、Production 部署。
> ADMIN 為了能在本機啟動，使用合成的 `SESSION_SECRET_KEY` 並以環境變數模擬 preview 標記（`APP_ENV=preview`、`VERCEL=1`、`VERCEL_ENV=preview`、`MODULE_BACKEND=cloud`）；未改任何程式。
> 帳號為合成帳號（採購×2、財務×1）；提交者與核准者必須是不同人（ADMIN 的 `SELF_APPROVAL` 實測擋下自己核准自己）。

| 案例 | 操作 | 結果（資料庫回查） |
|---|---|---|
| A 正常提交核准 | 前台登入→示範影像→(Mock)辨識→改賣方名稱→確認→查重→上傳；ADMIN 存會計欄位並核准 | 案件 approved；歷程 `NULL→pending_accounting_review→approved`；影像 1 筆；欄位覆核 1 筆；Storage 有物件；此案在加入 Round 1 快照程式前提交，無快照 |
| B 欄位退件補正 | ADMIN 退回買方統編；前台補正頁編輯 4 次後重送；ADMIN 核准 | 第 2 輪；快照 1:first(04595257)、2:resubmit_corrected(12345675)；`invoice_changes` event_seq 1–4；同一影像；退件項目 corrected；ADMIN 顯示退件原因、回覆、新舊值 |
| C 純申覆 | 退回日期；先不填說明送出被擋，再填說明重送；ADMIN 核准 | 第 2 輪 resubmit_appeal；資料未變；0 筆編輯事件；退件項目 appealed 含說明 |
| D 圖片退件作廢重傳 | ADMIN 退回 attachment；前台只顯示作廢入口（無補正表單）；作廢；以同字軌號碼重新上傳 | 舊案 voided（影像、退件項目、快照、歷程皆保留，reviewed_by 不變）；新案新 `invoice_id`、新影像路徑、新 Round 1 快照；查重未被已作廢案件擋下；ADMIN 核准新案 |
| E 再次退回 | 退賣方統編→第 2 輪→退日期→第 3 輪→核准 | 第 3 輪；快照 1,2,3；兩筆退件項目各自 corrected；ADMIN 顯示兩輪退回與前後比對 |
| F 異常與安全 | `case_f.py`（真實 HTTP）34 項檢查 | 非原提交者／財務／他部門 讀取、重送、作廢＝404；未登入 401；未授權欄位改動 400 且資料不變；過期輪次 409；6 並行重送僅 1 成功；同冪等鍵重試回放 200、不同內容 409；重複／過期／並行作廢僅 1 成功；同辨識重複提交 409；重複發票 409；統編錯、缺明細 422；金額不一致僅警示；OCR 失敗、Storage 失敗各回 502 且無案件、之後可恢復 |

DB 交易失敗：以既有隔離整合測試涵蓋（重送最後一步失敗全部 rollback；首次提交快照寫入失敗整筆回滾、辨識紀錄維持未送出並可重試；`other` 退件的作廢權限維持現行行為，列為待決議（未變更）），未在即時環境注入。

## 發現的問題
- （已由 main 修正）`test_alembic_online_isolated_db.py` 原本硬編碼 head；本 PR 採用 main 的動態 head 版本。
- P1（已修）`other` 類退回在補正頁不顯示財務原因與限制。
- 待決議（業務規則未變更）：`other` 類退回與欄位類退回，API 目前都允許原提交者作廢；若只該開放圖片問題需改 `invoice_void_service`。
- P2：會計科目／扣抵代號只寫入歷程 reason 文字（無專屬欄位）；ADMIN 本機 venv 缺 Pillow 導致 2 項測試無法通過／收集；`ocr_provider` 欄位在 Mock 下仍標示 google_document_ai（程式常數）。
