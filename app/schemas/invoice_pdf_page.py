"""
模組名稱：app.schemas.invoice_pdf_page
功能說明：多頁 PDF 找發票頁（POST /invoices/pdf-pages/classify）的回應模型。
注意事項：
    - 前台在瀏覽器把 PDF 每頁轉成縮圖後分批送來；API 只判斷每張是不是三聯式統一發票與聯別，不存檔、不寫 DB。
    - copy 為票面印的聯別：1＝第一聯（存根聯，不能報帳）、2＝第二聯（扣抵聯）、3＝第三聯（收執聯）；看不清楚時為 None。
"""

from typing import Literal

from pydantic import Field

from app.schemas.common import ContractModel

InvoiceCopy = Literal[1, 2, 3]


class PdfPageClassification(ContractModel):
    """單張頁面縮圖的判斷結果。"""

    index: int = Field(ge=1, description="本次請求中的圖片序號（依上傳順序，從 1 起算）")
    is_triplicate_invoice: bool = Field(description="是否為三聯式統一發票")
    copy_no: InvoiceCopy | None = Field(
        default=None, description="聯別：1 存根聯、2 扣抵聯、3 收執聯；看不清楚為 null"
    )


class PdfPageClassifyRead(ContractModel):
    """本批頁面的判斷結果，依上傳順序排列。"""

    pages: tuple[PdfPageClassification, ...]
    model: str = Field(description="判斷使用的模型名稱")
