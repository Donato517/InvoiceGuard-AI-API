"""模組名稱：app.schemas.data；功能說明：明確的發票 CRUD 契約，金額不接受浮點數。"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.schemas.common import ContractModel, PageQuery, RecordId, Version

Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
InvoiceNumber = Annotated[str, Field(pattern=r"^[A-Z]{2}[0-9]{8}$")]
InvoiceTerm = Annotated[str, Field(pattern=r"^[0-9]{3}(02|04|06|08|10|12)$")]
TaxId = Annotated[str, Field(pattern=r"^[0-9]{8}$")]
InvoiceStatus = Literal["pending", "analyzing", "passed", "flagged", "rejected"]


def reject_float(value: Any) -> Any:
    """金額與數量須傳 Decimal、字串或整數，避免浮點誤差。"""
    if isinstance(value, (float, bool)):
        raise ValueError("金額與數量不可使用浮點數或布林值")
    return value


class InvoiceItemInput(ContractModel):
    """明細輸入；總額與明細的業務規則由未來 service 驗證。"""

    line_no: Annotated[int, Field(strict=True, ge=1, le=32767)]
    description: Annotated[str, Field(min_length=1, max_length=500)]
    quantity: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)]
    unit_price: Money
    amount: Money

    _reject_float = field_validator("quantity", "unit_price", "amount", mode="before")(reject_float)


class InvoiceCreate(ContractModel):
    """人工建立的可寫欄位；擁有者、狀態、風險分數不能由輸入指定。"""

    invoice_number: InvoiceNumber
    invoice_date: date
    invoice_term: InvoiceTerm
    seller_tax_id: TaxId | None = None
    seller_name: Annotated[str, Field(max_length=200)] | None = None
    buyer_tax_id: TaxId | None = None
    total_amount: Money
    tax_amount: Money | None = None
    items: Annotated[tuple[InvoiceItemInput, ...], Field(max_length=1000)] = ()

    _reject_float = field_validator("total_amount", "tax_amount", mode="before")(reject_float)

    @model_validator(mode="after")
    def validate_line_numbers(self) -> Self:
        """同一張發票的明細序號不可重複。"""
        if len({item.line_no for item in self.items}) != len(self.items):
            raise ValueError("發票明細序號不可重複")
        return self


class InvoicePatch(ContractModel):
    """只包含允許更新的欄位；未提供與明確清空可用 model_fields_set 區別。"""

    invoice_number: InvoiceNumber | None = None
    invoice_date: date | None = None
    invoice_term: InvoiceTerm | None = None
    seller_tax_id: TaxId | None = None
    seller_name: Annotated[str, Field(max_length=200)] | None = None
    buyer_tax_id: TaxId | None = None
    total_amount: Money | None = None
    tax_amount: Money | None = None

    _reject_float = field_validator("total_amount", "tax_amount", mode="before")(reject_float)

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        """拒絕空更新，以及將必要欄位設成 NULL。"""
        if not self.model_fields_set:
            raise ValueError("至少需要一個更新欄位")
        for name in {"invoice_number", "invoice_date", "invoice_term", "total_amount"}:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError("必要欄位不可清空")
        return self


class InvoiceUpdate(ContractModel):
    """以預期版本避免兩站或多人互相覆寫。"""

    patch: InvoicePatch
    expected_version: Version


class InvoiceQuery(PageQuery):
    """可用的查詢條件；擁有者範圍由伺服器授權決定。"""

    status: InvoiceStatus | None = None


class InvoiceRead(ContractModel):
    """未來 service 的回傳契約；version 尚未對應實際資料表欄位。"""

    id: RecordId
    user_id: RecordId
    invoice_number: InvoiceNumber
    invoice_date: date
    invoice_term: InvoiceTerm
    total_amount: Money
    status: InvoiceStatus
    version: Version
    created_at: AwareDatetime
    updated_at: AwareDatetime

    _reject_float = field_validator("total_amount", mode="before")(reject_float)


class DeleteResult(ContractModel):
    """邏輯刪除的回傳值，不代表實體檔案已清除。"""

    id: RecordId
    version: Version
    is_deleted: Literal[True] = True
