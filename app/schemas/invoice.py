"""
模組名稱：app.schemas.invoice
功能說明：發票相關的請求 / 回應模型。
注意事項：
    - 金額欄位使用 Decimal，JSON 輸出為字串，避免浮點誤差。
"""

from app.schemas.data import (
    InvoiceCreate,
    InvoiceItemInput,
    InvoicePatch,
    InvoiceQuery,
    InvoiceRead,
    InvoiceUpdate,
)

__all__ = [
    "InvoiceCreate",
    "InvoiceItemInput",
    "InvoicePatch",
    "InvoiceQuery",
    "InvoiceRead",
    "InvoiceUpdate",
]

# TODO(JerryChien): InvoiceItemRead / InvoiceDetailRead（配合實際業務與授權完成）
# TODO(JerryChien): InvoiceReviewRequest（decision: passed / rejected, comment）
