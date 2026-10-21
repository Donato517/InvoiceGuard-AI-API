"""
模組名稱：app.services.invoice_service
功能說明：發票商業邏輯——上傳建檔、查詢、狀態流轉、人工複核。
相依模組：app.db.repositories.invoice_repository、app.integrations.storage_client
注意事項：
    - 狀態流轉：pending → analyzing → passed / flagged；flagged 經人工複核 → passed / rejected。
    - 上傳檔案存物件儲存（storage_client），資料庫只存 file_key。
"""

# TODO(JerryChien): create_from_upload(db, user, file) -> InvoiceRead
# TODO(JerryChien): list_invoices(db, user, query) -> Page[InvoiceRead]
# TODO(JerryChien): review_invoice(db, invoice_id, decision, operator) -> InvoiceRead
