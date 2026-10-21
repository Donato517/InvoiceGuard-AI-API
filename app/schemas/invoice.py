"""
模組名稱：app.schemas.invoice
功能說明：發票相關的請求 / 回應模型。
注意事項：
    - 金額欄位使用 Decimal，JSON 輸出為字串，避免浮點誤差。
"""

# TODO(JerryChien): InvoiceQuery（status, page, page_size）
# TODO(JerryChien): InvoiceItemRead / InvoiceRead / InvoiceDetailRead
# TODO(JerryChien): InvoiceReviewRequest（decision: passed / rejected, comment）
