# Show Case 跨站交付

本輪以各站最新 main 為基底，不回退或重寫既有歷史。ADMIN 額外包含一般部門 RAG 問答的獨立提交；API 與前台只包含 Show Case 接點。

## 使用入口與相依

- ADMIN `/suppliers` → `/showcases/by-supplier/{UUID}`：正式供應商的範例維護。需 suppliers 查看及 show_case 對應操作；啟用另需 supplier.showcase-activation 修改權。
- ADMIN `/showcases/reference`：有效登入者依統編查已啟用範例，不授予維護權。
- API `/api/v1/showcase-references` 及其固定版本 file 路徑：每次驗 Session、供應商與啟用範例。圖片回應 no-store，不接受任意物件路徑。
- 前台 `/invoices/showcase-reference`：既有 clients 經 API 取用，Token 不放 URL；另開視窗查閱，不修改本次發票答案。

## 資料及發布界線

正式供應商只用 public.suppliers。supplier_invoice_examples／supplier_invoice_example_items 是目前版；invoiceguard_showcase 保留歷程、來源登錄及測試資料。原圖採既有私人 Storage，SHA-256 與固定版本重驗。新建後為待人工確認候選，不自動授權或啟用。

API 新增兩個尚未套用的結構版本草案。正式庫依目前團隊文件採手動 SQL 管理，不能把這份交付當作可直接執行的 alembic upgrade 指令；尤其已手動存在的正式範例表需先對照，避免重複建表。DB 負責人需確認私有表、最小角色權限與保留策略。

建議先審查 API 的向下相容讀取接點，再驗 ADMIN 維護，最後驗前台參考。三站 PR 互相註明相依，不在本輪直接合併 main 或執行資料搬移。既有前台辨識與正式發票轉換不改為 Few-Shot 自動填答。

## 模型與測試

ADMIN 的 Show Case 基線採與正式 API 相同的 Gemini 提示詞；API 只是抽出同值常數，原轉換與檢核保留。Few-Shot 只產生比較候選，不自動成為人工真值或正式答案。

本機已有合成單元、瀏覽器與記憶體 PostgreSQL 驗收。實際服務的 save／upload／change_status／source 已在 loopback PGlite 加記憶體 Storage 替身驗過新增、修訂、啟用、回滾與摘要，共 11 個情境；不代表真實雲端 Storage、角色或多連線鎖競爭通過。實際模型效果與部署 Preview 另待驗收。

本 PR 不包含測試發票、人工答案、模型結果、Token、雲端連線資料、私人驗收腳本或舊版 SQL 全稿。
