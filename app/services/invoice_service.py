"""
模組名稱：app.services.invoice_service
功能說明：發票商業邏輯的 TODO 骨架；上傳建檔、查詢、狀態流轉與人工複核尚未實作。
預計相依模組：app.db.repositories.invoice_repository、app.integrations.supabase_storage（本檔尚無實際匯入或呼叫）
注意事項：
    - 預計狀態流轉：pending → analyzing → passed / flagged；flagged 經人工複核 → passed / rejected。
    - 待實作的上傳流程將使用既有 Vercel 模組（app.integrations.supabase_storage），資料庫只存 file_key。
"""

# TODO(JerryChien): create_from_upload(db, user, file) -> InvoiceRead
# TODO(JerryChien): list_invoices(db, user, query) -> Page[InvoiceRead]
# TODO(JerryChien): review_invoice(db, invoice_id, decision, operator) -> InvoiceRead
