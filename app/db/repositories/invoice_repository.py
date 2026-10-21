"""
模組名稱：app.db.repositories.invoice_repository
功能說明：invoices / invoice_items 的資料存取（分頁查詢、建立、更新分析結果）。
注意事項：
    - 只負責 ORM 操作，不含商業邏輯，不自行 commit（交易由 service 控制）。
    - 查詢預設排除軟刪除資料（deleted_at IS NULL）。
    - 前台查詢必須帶 user_id 條件，避免越權讀取他人發票。
"""

# TODO(JerryChien): get_by_id(db, invoice_id, *, user_id=None) -> Invoice | None
# TODO(JerryChien): list_page(db, *, user_id=None, status=None, page, page_size) -> tuple[list[Invoice], int]
# TODO(JerryChien): create(db, data) -> Invoice
# TODO(JerryChien): update_analysis(db, invoice, *, status, risk_score, ai_result) -> Invoice
