# Document AI 三模組由 ADMIN 同步至 API

> 發佈註記（2026-10-30）：本文保留同步當時的檢驗數字。後續已修正 invoice_upload_service.py，在所有結果關閉 OCR client，並避免 close 例外覆蓋辨識結果；本輪發佈前檢查記錄於 REVIEW_FIX_LOG.md。本機 docs/reviews/ 的命令、JUnit、JSON 與副本未納入版本控制。

日期：2026-10-30（Asia/Taipei）。依使用者要求，API 採用 ADMIN 已整合的三模組完整內容。

最終 API 完整離線回歸：**815 passed、15 skipped、0 failed／errors**（40.93 秒）。三檔 SHA-256 與 ADMIN 來源完全一致，6 種套件匯入順序通過；ADMIN 的跨站同步測試另有 15 項通過。

## 同步範圍與衝突處理

| 檔案 | API 原狀態 | 本次處理 |
|---|---|---|
| app/integrations/document_ai.py | 舊版 OCR client | 以 ADMIN 完整版本同步，保留原公開介面 |
| app/integrations/document_ai_evidence.py | 不存在 | 新增完整相同副本 |
| app/integrations/document_ai_fewshot.py | 不存在 | 新增完整相同副本 |

API 開始時工作樹乾淨；ADMIN 保有前兩輪尚未提交的整合成果。本次三檔以 ADMIN 作為來源，不將 API 舊版反向覆蓋 ADMIN，不改三模組邏輯，也不改 integrations/__init__.py。

需配合的差異：

- API venv／requirements 原先沒有 Pillow。已補上與 ADMIN 一致的 `Pillow==13.0.0`；其他套件版本不變，PDFium 維持選用未安裝。
- API 舊單元測試使用任意測試 OAuth URI 並要求已棄用的 skipHumanReview。同步 ADMIN 的既有離線測試，固定官方 URI 仍完全經 MockTransport，保留不傳 skipHumanReview 的新契約；沒有放寬正式驗證。
- 兩站的 shared integration 測試統一納入三個 Document AI 檔案，恢復逐位元組比對，並保留公開 OCR 建構與類別身分檢查。其他共用檔案的比對繼續保留。

## 既有 API 流程相容性

`invoice_upload_service.py` 仍用 `DocumentAIClient.from_settings()`、`process(content, mime_type, timeout_seconds=remaining)`、`text/pages/confidence` 及固定 `DocumentAIError.code/detail`。新版保留這些介面，且原先 OcrLine／OcrPage／OcrResult 的位置參數仍可使用。

既有辨識流程已對 OCR → Groq 共用 25 秒預算，傳入剩餘時間；不因同步檔案而新增一段 Gemini 推論。原有 API 回應與紀錄使用明確欄位，沒有將新增含 bytes 的 evidence dataclass 直接當 JSON 傳回瀏覽器。

新增 API 相容測試以真實同步 adapter 接既有 `/api/v1/invoices/recognize`：Google HTTP 用 MockTransport，DB／Storage／Groq 為合成替身。確認成功回覆、OCR 文字／confidence／頁數、剩餘時間，以及 Google 429 對應原 503 與失敗紀錄；不自動建立核准發票。

原 `invoice_upload_service.py`、路由、Schema、DB／Storage 層與設定來源均未修改。evidence／Few-Shot 現在可被 API 的受信任 service 匯入，但尚未接入既有上傳流程、範例管理或審批。

## 環境與檢驗紀錄

沿用 API 自己的四項 Google OCR 設定、GEMINI_API_KEY 與已有預設的 GEMINI_MODEL，不新增環境變數、不共用 ADMIN 的憑證、不修改 START 或 Vercel 設定。程式可用不代表雲端已填齊或模型額度有效。

同步前後的離線測試、命令、exit code、JUnit 及 SHA-256 保存於 `docs/reviews/document-ai-sync-20261030/`。測試副本排除真實 dotenv／憑證／Git／venv，使用清除繼承設定與禁網包裝器；Windows TestClient 的 socketpair 在一般程序權限下執行，外部網路與正式 DB 仍被禁止。

| 檢查 | 實際結果 |
|---|---|
| API 同步前完整基準 | 740 collected；724 passed、15 skipped、1 failed，exit 1；唯一失敗為當時 ADMIN／API document_ai.py 不同 |
| API 同步後完整回歸 | 830 collected；815 passed、15 skipped、0 failed／errors，exit 0；包含 83 項三模組測試與 2 項真實 adapter 接原端點測試 |
| ADMIN 共用整合測試 | 15 passed，exit 0；三模組及其他共用整合檔保留逐位元組比對 |
| 匯入、編譯 | 三模組 6 種順序及 Gemini／Groq 共存、compileall 均 exit 0；沒有匯入時建構 HTTP client |
| 跨三站架構／契約 | check_project --project-root 通過，0 issues |
| API Ruff／依賴 | lint 通過、99 檔 format 通過、pip check 無破損依賴 |
| API 環境 CLI | configuration_valid=true，connectivity_checked=false；沒有新增環境名稱 |

基準與整合版 15 項略過條件一致，均為原有的站別／環境條件與權限限制；沒有略過新增三模組測試。唯一警告為既有 Starlette/httpx 棄用警告。原始基準失敗輸出保留，未以移除同步檢查取得通過。

逐次命令與工作目錄見同名 JSON；完整輸出見 TXT；測試結果見 `baseline.xml`、`integrated.xml`、`admin-shared.xml`，完整性與執行摘要見 `manifest.json`。

真實 Google／Gemini／DB／Storage、雲端部署及辨識準確率未驗證；沒有部署、migration、訓練、正式資料操作、Commit 或 Push。
