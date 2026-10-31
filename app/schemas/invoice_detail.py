"""
模組名稱：app.schemas.invoice_detail
功能說明：GET /invoices/{invoice_id} 的回應模型——提交者本人重新讀取已送出的發票，欄位對應 v1.4
    public.invoices、invoice_items、invoice_field_reviews、invoice_files。
注意事項：
    - 金額與數量以字串輸出（API_CONVENTIONS 第 4 節），保留資料庫的小數位數（例如 "1000.00"、"2.0000"）；
      資料庫 NULL 回傳 null，不補 0 或空字串。
    - modified_fields 的 ai_original_value／submitted_value 是送出時寫入 invoice_field_reviews 的標準值
      （_canonical_value，數字去尾端 0，例如 "1000"），格式與本回應的金額欄位（"1000.00"）不同，
      不可用字串直接比較；沒有修改紀錄的欄位不代表已取得完整 AI 原值，本版也不回傳 AI 原始快照。
    - file 不含 storage_path、bucket_name，避免暴露含使用者 UUID 的私有物件鍵。
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import Field

from app.schemas.common import ContractModel
from app.schemas.invoice_upload import FieldWarning, ModifiedField, TaxType


class InvoiceItemRead(ContractModel):
    """一筆已送出的品名明細。"""

    line_no: int = Field(description="明細序號，從 1 開始")
    item_name: str | None = Field(description="品名")
    quantity: str | None = Field(description="數量")
    unit_price: str | None = Field(description="單價")
    line_amount: str | None = Field(description="明細金額")


class InvoiceFileRead(ContractModel):
    """目前使用中的發票影像中繼資料；不含物件路徑，圖片實體另由獨立端點提供。"""

    mime_type: str | None = Field(description="image/jpeg、image/png 或 application/pdf")
    original_filename: str | None = Field(description="上傳時的原始檔名；可能沒有")
    size_bytes: int | None = Field(description="檔案大小（位元組）")
    version_no: int = Field(description="影像版本，第一次上傳為 1")


class InvoiceDetailRead(ContractModel):
    """已送出發票的詳情（提交者本人）。"""

    invoice_id: UUID = Field(description="發票 UUID")
    status: str = Field(description="簽核狀態代碼，例如 pending_department_approval")
    submission_round: int = Field(description="提交輪次；第一次送出為 1")
    submitted_at: datetime | None = Field(description="送出時間（UTC）")
    tax_period: str | None = Field(description="發票期別 YYYYMM")
    invoice_track: str | None = Field(description="字軌（2 碼英文）")
    invoice_number: str | None = Field(description="號碼（8 碼數字）")
    invoice_date: date | None = Field(description="發票日期（西元）")
    seller_tax_id: str | None = Field(description="賣方統一編號")
    seller_name: str | None = Field(description="賣方名稱")
    buyer_tax_id: str | None = Field(description="買受人統一編號")
    buyer_name: str | None = Field(description="買受人名稱")
    tax_type: TaxType | None = Field(description="課稅別")
    sales_amount: str | None = Field(description="銷售額合計")
    tax_amount: str | None = Field(description="營業稅額")
    total_amount: str | None = Field(description="總計")
    total_amount_zh: str | None = Field(description="總計新臺幣（國字大寫）")
    items: tuple[InvoiceItemRead, ...] = Field(description="品名明細，依 line_no 排序")
    modified_fields: tuple[ModifiedField, ...] = Field(
        description="本輪使用者修改過的欄位（含刪除的 AI 明細）；沒有修改時為空陣列"
    )
    warnings: tuple[FieldWarning, ...] = Field(description="送出時保存的程式檢核提醒")
    file: InvoiceFileRead | None = Field(description="目前影像的中繼資料；沒有時為 null")
