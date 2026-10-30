"""
模組名稱：app.schemas.invoice_upload
功能說明：手機上傳發票流程（辨識 → 核對 → 查重 → 送出）的請求／回應模型，欄位對應 v1.4 public.invoices、
    public.invoice_items。
注意事項：
    - 金額與數量以字串輸出（API_CONVENTIONS 第 4 節），送出時接受字串或整數，不接受浮點數。
    - 日期、期別由 API 程式換算；tax_period 以 YYYYMM 表示（偶數月），送出時由 invoice_date 換算，不由前台指定。
    - 送出時一併帶核對頁的修改紀錄（changes）與明細來源（source_line_no），API 據以標記使用者修改的欄位
      （invoice_field_reviews）並保存逐次修改（invoice_changes）。
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BeforeValidator, Field, field_validator

from app.schemas.common import ContractModel
from app.schemas.data import reject_float
from app.utils.invoice_format import strip_spaces

TaxType = Literal["taxable", "zero_rated", "tax_exempt"]
RecognitionStatus = Literal["success", "partial"]


def blank_to_none(value: Any) -> Any:
    """文字去除前後空白（與前台相同的空白集合）；空字串視為未填（None）。"""
    if isinstance(value, str):
        value = strip_spaces(value)
        return value or None
    return value


# 可選欄位：空白轉 None 後，長度／格式只套用在字串上（None 不檢查）
Text = Annotated[Annotated[str, Field(max_length=200)] | None, BeforeValidator(blank_to_none)]
TaxId = Annotated[str, BeforeValidator(blank_to_none), Field(pattern=r"^[0-9]{8}$")]
OptionalTaxId = Annotated[
    Annotated[str, Field(pattern=r"^[0-9]{8}$")] | None, BeforeValidator(blank_to_none)
]
LineNo = Annotated[int, Field(strict=True, ge=1, le=50)]
ChangeValue = Annotated[str, Field(max_length=200)] | None
Amount = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2)]
Quantity = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4)]


class FieldWarning(ContractModel):
    """程式檢核提醒；不阻擋送出，送出時寫入 invoices.validation_results 供審核參考。"""

    field: str = Field(description="欄位名稱，例如 seller_tax_id、tax_amount、items")
    code: str = Field(description="固定代碼，例如 tax_id_invalid、tax_amount_mismatch")
    message: str = Field(description="給使用者看的中文說明")


class RecognizedItem(ContractModel):
    """AI 辨識的品名明細（對應 invoice_items）。"""

    line_no: int = Field(description="明細序號，從 1 開始")
    item_name: str | None = Field(description="品名")
    quantity: str | None = Field(description="數量")
    unit_price: str | None = Field(description="單價")
    line_amount: str | None = Field(description="明細金額")


class RecognizedInvoice(ContractModel):
    """AI 辨識並經程式換算的發票表頭（對應 invoices 欄位）與明細。"""

    invoice_track: str | None = Field(description="字軌（2 碼英文）")
    invoice_number: str | None = Field(description="號碼（8 碼數字）")
    invoice_date: date | None = Field(description="發票日期（西元）")
    tax_period: str | None = Field(description="發票期別 YYYYMM（偶數月）")
    seller_tax_id: str | None = Field(description="賣方（銷貨人）統一編號")
    seller_name: str | None = Field(description="賣方名稱")
    buyer_tax_id: str | None = Field(description="買受人統一編號")
    buyer_name: str | None = Field(description="買受人名稱")
    tax_type: TaxType | None = Field(
        description="課稅別：taxable 應稅／zero_rated 零稅率／tax_exempt 免稅"
    )
    sales_amount: str | None = Field(description="銷售額合計")
    tax_amount: str | None = Field(description="營業稅額")
    total_amount: str | None = Field(description="總計")
    total_amount_zh: str | None = Field(description="總計新臺幣（國字大寫）")
    items: tuple[RecognizedItem, ...] = Field(description="品名明細")


class PrintedText(ContractModel):
    """模型抄錄的票面原文（日期、期別由程式換算前的文字），供核對。"""

    invoice_date: str | None = Field(description="票面日期原文，例如 115年8月15日")
    tax_period: str | None = Field(description="票面期別原文，例如 一一五年七、八月份")


class RecognitionInfo(ContractModel):
    """本次辨識使用的服務與模型。"""

    ocr_provider: str = Field(description="OCR 服務（google_document_ai）")
    ocr_confidence: float | None = Field(description="OCR 信心值 0～1")
    ai_provider: str = Field(description="欄位整理模型服務（groq）")
    model: str = Field(description="實際使用的模型")
    fallback_used: bool = Field(description="是否改用進階備用模型（120B）")


class InvoiceRecognitionRead(ContractModel):
    """辨識結果；同時寫入 ai_recognition_logs.extracted_fields。"""

    recognition_id: UUID = Field(description="辨識紀錄 UUID；送出發票時帶回")
    result_status: RecognitionStatus = Field(description="success：無提醒；partial：有欄位需核對")
    is_triplicate: bool | None = Field(description="是否為三聯式統一發票")
    invoice: RecognizedInvoice
    printed: PrintedText
    warnings: tuple[FieldWarning, ...] = Field(description="程式檢核提醒")
    recognition: RecognitionInfo
    expires_at: datetime = Field(description="影像保留期限；逾時未送出即不可送出並刪除影像")


class DuplicateCheckRequest(ContractModel):
    """查重條件：字軌＋號碼＋賣方統一編號（對應索引 ix_invoices_number_supplier）。"""

    invoice_track: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    invoice_number: Annotated[str, Field(pattern=r"^[0-9]{8}$")]
    seller_tax_id: TaxId


class DuplicateCheckRead(ContractModel):
    """查重結果；不回傳其他使用者或部門的發票內容。"""

    is_duplicate: bool = Field(description="系統內已有相同發票（已作廢者不計）")


class InvoiceItemSubmit(ContractModel):
    """使用者確認後的品名明細；source_line_no 為對應的 AI 辨識明細序號，使用者新增的明細為 None。"""

    source_line_no: LineNo | None = None
    item_name: Annotated[str, BeforeValidator(blank_to_none), Field(min_length=1, max_length=200)]
    quantity: Quantity | None = None
    unit_price: Quantity | None = None
    line_amount: Amount

    _reject_float = field_validator("quantity", "unit_price", "line_amount", mode="before")(
        reject_float
    )


class FieldChangeSubmit(ContractModel):
    """核對頁的一次欄位修改（依時間順序）；line_no 為送出時的明細序號，表頭欄位為 None。"""

    field_scope: Literal["header", "item"]
    line_no: LineNo | None = None
    field_name: Annotated[str, Field(max_length=40)]
    old_value: ChangeValue = None
    new_value: ChangeValue = None


class InvoiceSubmitRequest(ContractModel):
    """使用者核對、查重後送出的發票；影像沿用辨識時保存的檔案。"""

    recognition_id: UUID
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
    items: tuple[InvoiceItemSubmit, ...] = Field(min_length=1, max_length=50)
    changes: tuple[FieldChangeSubmit, ...] = Field(default=(), max_length=500)

    _reject_float = field_validator("sales_amount", "tax_amount", "total_amount", mode="before")(
        reject_float
    )


class MissingField(ContractModel):
    """必填缺漏的一個欄位；明細欄位以 line_no 指出第幾筆（送出內容的順序，從 1 開始）。"""

    field: str = Field(description="欄位名稱，例如 invoice_number、item_name、items")
    code: Literal["required_missing"] = Field(description="固定代碼：required_missing")
    message: str = Field(description="給使用者看的中文提示")
    line_no: int | None = Field(description="明細序號；表頭欄位為 None")


class RequiredCheckRead(ContractModel):
    """必填檢核結果；不寫入任何資料。"""

    required_complete: bool = Field(
        description="沒有任何必填缺漏。只代表必填欄位都有值，不代表格式、金額或整體資料有效，也不代表可以提交"
    )
    missing: tuple[MissingField, ...] = Field(description="全部必填缺漏；完整時為空")


class WarningCheckRead(ContractModel):
    """業務警示預覽結果；不寫入任何資料，警示只是人工核對提醒，不阻擋送出。"""

    warnings: tuple[FieldWarning, ...] = Field(
        description="目前欄位值可判斷出的警示（代碼同送出後寫入 validation_results 的 warnings）；欄位不足或格式錯誤的部分不判斷"
    )
    checked_on: date = Field(description="判斷「晚於今天」所用的台灣當天日期 YYYY-MM-DD")


class ModifiedField(ContractModel):
    """使用者修改過的欄位（AI 原值與送出值不同）；同時寫入 invoice_field_reviews 待審核勾選。"""

    field_scope: Literal["header", "item"] = Field(description="header 表頭／item 明細")
    line_no: int | None = Field(description="明細序號；表頭欄位為 None")
    field_name: str = Field(description="欄位名稱；刪除 AI 明細時為 deleted_item_{AI 明細序號}")
    ai_original_value: Any = Field(description="AI 辨識值")
    submitted_value: Any = Field(description="使用者送出值")


class InvoiceSubmitRead(ContractModel):
    """送出結果。"""

    invoice_id: UUID = Field(description="發票 UUID")
    status: str = Field(description="簽核狀態：pending_department_approval（待單位核准）")
    tax_period: str = Field(description="依發票日期換算的期別 YYYYMM")
    submitted_at: datetime = Field(description="送出時間")
    warnings: tuple[FieldWarning, ...] = Field(
        description="送出值的程式檢核提醒（已寫入 validation_results）"
    )
    modified_fields: tuple[ModifiedField, ...] = Field(
        description="使用者修改過的欄位（已寫入 invoice_field_reviews，待審核）"
    )
