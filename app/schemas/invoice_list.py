"""
模組名稱：app.schemas.invoice_list
功能說明：GET /invoices 的查詢參數與回應模型——提交者本人的發票列表（唯讀、分頁、依簽核狀態篩選）。
注意事項：
    - ApprovalStatus 的九個值對應 v1.4 以後 public.invoices.invoices_status_chk；共用簽核狀態由財務組定義，
      本檔只照資料庫約束複製，不新增、不改名。資料庫約束改變時須一併檢視這裡。
    - 金額以字串輸出（API_CONVENTIONS 第 4 節）；資料庫 NULL 回傳 null。
    - 列表只含本人提交（submitted_by = 登入者）的發票；submitted_by 為 NULL 的草稿不會出現。
    - 不含風險分數（資料庫沒有這個欄位），也不含明細、影像路徑。
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import ContractModel, Page

ApprovalStatus = Literal[
    "draft",
    "pending_department_approval",
    "pending_accounting_review",
    "pending_accounting_approval",
    "approved",
    "returned_to_applicant",
    "returned_to_accounting",
    "rejected",
    "voided",
]


class InvoiceListItem(ContractModel):
    """列表中的一張發票（摘要）。"""

    invoice_id: UUID = Field(description="發票 UUID，可接 GET /invoices/{invoice_id}")
    status: ApprovalStatus = Field(description="簽核狀態代碼")
    submission_round: int = Field(description="提交輪次；0 為草稿")
    submitted_at: datetime | None = Field(description="送出時間（UTC）；草稿可能為 null")
    invoice_track: str | None = Field(description="字軌（2 碼英文）")
    invoice_number: str | None = Field(description="號碼（8 碼數字）")
    invoice_date: date | None = Field(description="發票日期（西元）")
    seller_name: str | None = Field(description="賣方名稱")
    total_amount: str | None = Field(description="總計")


InvoiceListRead = Page[InvoiceListItem]
