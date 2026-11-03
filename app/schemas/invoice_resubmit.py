"""
模組名稱：app.schemas.invoice_resubmit
功能說明：財務退回後的同案補正／申覆重送——讀取退件項目與上一輪提交資料，以及正式重送的請求／回應模型。
注意事項：
    - 欄位格式與必填規則沿用手機送出（invoice_upload）的型別，不另寫一套；金額與數量以字串輸出。
    - 重送不接受 recognition_id、不接受更換影像；明細只能以既有 item_id 逐筆對應，不可新增、刪除或重排。
    - idempotency_key 識別同一次操作的重試；expected_round 防止以過期輪次覆蓋最新資料。
    - 純申覆：items 與上一輪相同、changes 為空，responses 全部為 appealed 並附說明。
"""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BeforeValidator, Field, field_validator

from app.schemas.common import ContractModel
from app.schemas.data import reject_float
from app.schemas.invoice_upload import (
    Amount,
    FieldChangeSubmit,
    FieldWarning,
    ModifiedField,
    OptionalTaxId,
    Quantity,
    TaxId,
    TaxType,
    Text,
    blank_to_none,
)

ReturnItemKind = Literal["field", "image", "other"]
ResponseAction = Literal["corrected", "appealed"]


class FieldRef(ContractModel):
    """欄位定位；明細欄位以 line_no（上一輪提交的序號）與 item_id 指出。"""

    field_scope: Literal["header", "item"] = Field(description="header 表頭／item 明細")
    line_no: int | None = Field(description="明細序號；表頭欄位為 None")
    item_id: UUID | None = Field(description="明細 UUID；表頭欄位為 None")
    field_name: str = Field(description="欄位名稱")


class ReturnItemRead(ContractModel):
    """財務退回時產生的結構化退件項目。"""

    return_item_id: UUID
    item_kind: ReturnItemKind = Field(description="field 欄位／image 圖片／other 其他")
    target: FieldRef | None = Field(description="退回的欄位；圖片與其他類型為 None")
    reason: str = Field(description="財務的原始退件原因（不會被回覆覆蓋）")
    allowed_fields: tuple[FieldRef, ...] = Field(description="財務額外授權修改的相依欄位")
    status: str = Field(description="open／corrected／appealed／accepted／rejected")


class PreviousItem(ContractModel):
    """上一輪正式提交的一筆明細。"""

    item_id: UUID
    line_no: int
    item_name: str | None
    quantity: str | None
    unit_price: str | None
    line_amount: str | None


class PreviousSubmission(ContractModel):
    """上一輪正式提交的完整資料（重送預填用，不使用 AI 原始值）。"""

    invoice_track: str | None
    invoice_number: str | None
    invoice_date: date | None
    seller_tax_id: str | None
    seller_name: str | None
    buyer_tax_id: str | None
    buyer_name: str | None
    tax_type: str | None
    sales_amount: str | None
    tax_amount: str | None
    total_amount: str | None
    total_amount_zh: str | None
    items: tuple[PreviousItem, ...]


class ReturnItemsRead(ContractModel):
    """退件項目與上一輪資料；can_resubmit 為 False 時 resubmit_blocked_reason 說明原因。"""

    invoice_id: UUID
    status: str
    submission_round: int = Field(description="目前輪次；重送時帶回 expected_round")
    can_resubmit: bool = Field(description="可以在同案補正或申覆")
    requires_void: bool = Field(description="有圖片問題：只能由原提交者作廢後重新上傳")
    resubmit_blocked_reason: str | None
    editable_fields: tuple[FieldRef, ...] = Field(
        description="後端允許修改的欄位（退回欄位＋授權相依欄位）"
    )
    return_items: tuple[ReturnItemRead, ...]
    previous: PreviousSubmission


class ResubmitItem(ContractModel):
    """重送時的一筆明細；item_id 必須是上一輪既有明細，不可新增或刪除。"""

    item_id: UUID
    item_name: Annotated[str, BeforeValidator(blank_to_none), Field(min_length=1, max_length=200)]
    quantity: Quantity | None = None
    unit_price: Quantity | None = None
    line_amount: Amount

    _reject_float = field_validator("quantity", "unit_price", "line_amount", mode="before")(
        reject_float
    )


class ResubmitResponse(ContractModel):
    """申請人對一個退件項目的回覆；申覆必填說明。"""

    return_item_id: UUID
    action: ResponseAction
    note: Text = None


class InvoiceResubmitRequest(ContractModel):
    """同案重送：欄位值為本輪要正式提交的完整值（含未修改的欄位）。"""

    idempotency_key: UUID
    expected_round: Annotated[int, Field(strict=True, ge=1)]
    invoice_track: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    invoice_number: Annotated[str, Field(pattern=r"^[0-9]{8}$")]
    invoice_date: date
    seller_tax_id: TaxId
    seller_name: Text = None
    buyer_tax_id: OptionalTaxId = None
    buyer_name: Text = None
    tax_type: TaxType
    sales_amount: Amount
    tax_amount: Amount
    total_amount: Amount
    total_amount_zh: Text = None
    items: tuple[ResubmitItem, ...] = Field(min_length=1, max_length=50)
    changes: tuple[FieldChangeSubmit, ...] = Field(default=(), max_length=500)
    responses: tuple[ResubmitResponse, ...] = Field(min_length=1, max_length=100)

    _reject_float = field_validator("sales_amount", "tax_amount", "total_amount", mode="before")(
        reject_float
    )


class CarriedField(ContractModel):
    """承接前輪確認效力的欄位及其原始確認證據。"""

    field: FieldRef
    source_round: int = Field(description="原始確認所在輪次")
    confirmed_by: UUID | None = Field(description="原始確認者")
    confirmed_at: datetime | None = Field(description="原始確認時間")


class InvoiceResubmitRead(ContractModel):
    """重送結果；replayed=True 表示相同冪等鍵的重試，回傳首次成功的原結果。"""

    invoice_id: UUID
    status: str = Field(description="重送後的簽核狀態（回到退件來源的審核節點）")
    submission_round: int
    submitted_at: datetime
    tax_period: str
    warnings: tuple[FieldWarning, ...]
    modified_fields: tuple[ModifiedField, ...] = Field(
        description="本輪實際修改的欄位（上一輪提交值 → 本輪值）"
    )
    rereview_fields: tuple[FieldRef, ...] = Field(description="本輪需財務重新覆核的欄位")
    carried_fields: tuple[CarriedField, ...] = Field(
        description="承接前輪確認效力的欄位（不需重新勾選）"
    )
    replayed: bool = False


class InvoiceVoidRequest(ContractModel):
    """申請人作廢被退回的案件；expected_round 防止以過期輪次作廢（例如財務已再次退回或已重送）。"""

    expected_round: Annotated[int, Field(strict=True, ge=1)]
    reason: Text = None


class InvoiceVoidRead(ContractModel):
    """作廢結果；原案件、影像、辨識紀錄與退件歷史全部保留，重新上傳會建立新案件。"""

    invoice_id: UUID
    status: str = Field(description="固定為 voided")
    submission_round: int
    voided_at: datetime
