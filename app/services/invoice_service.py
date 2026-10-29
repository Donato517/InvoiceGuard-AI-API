"""
模組名稱：app.services.invoice_service
功能說明：發票商業邏輯的 TODO 骨架；上傳建檔、查詢、狀態流轉與人工複核尚未實作。
預計相依模組：app.db.repositories.invoice_repository、app.integrations.supabase_storage（本檔尚無實際匯入或呼叫）
注意事項：
    - 發票狀態依 v1.4 請款單簽核狀態（9 種）；手機上傳（辨識、查重、送出）已在 invoice_upload_service 實作。
"""

# TODO(JerryChien): create_from_upload(db, user, file) -> InvoiceRead
# TODO(JerryChien): list_invoices(db, user, query) -> Page[InvoiceRead]
# TODO(JerryChien): review_invoice(db, invoice_id, decision, operator) -> InvoiceRead
