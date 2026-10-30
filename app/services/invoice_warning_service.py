"""
模組名稱：app.services.invoice_warning_service
功能說明：上傳核對頁送出前的業務警示預覽——未來日期與金額一致性，結果與正式送出時寫入 validation_results 的警示相同。
相依模組：app.services.invoice_upload_service、app.schemas.invoice_upload
注意事項：
    - 規則只有一份：直接呼叫 invoice_upload_service 的 future_date_warnings 與 _consistency_warnings，
      不另建公式、稅率或容差；正式送出（POST /invoices）同樣由這兩個函式重新計算。
    - 純函式：不連 DB、Storage 或外部服務，不寫入任何資料，不記錄請求內容。
    - 寬鬆解析：每個欄位各自驗證，缺漏、空白或格式錯誤的欄位視為「未知」（None），
      該欄位相關的警示就不判斷，避免對不完整的資料下誤導性結論；缺漏與格式錯誤仍由必填檢核與正式送出（422）處理。
    - 警示只是人工核對提醒，不代表送出會被拒絕。
"""

import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.schemas.invoice_upload import (
    Amount,
    OptionalTaxId,
    TaxType,
    WarningCheckRead,
)
from app.services.invoice_upload_service import (
    _consistency_warnings,
    future_date_warnings,
    today_taipei,
)

_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_AMOUNT = TypeAdapter(Amount)
_TAX_TYPE = TypeAdapter(TaxType)
_TAX_ID = TypeAdapter(OptionalTaxId)


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_amount(value: Any) -> Decimal | None:
    """金額：與正式送出相同的 Amount 規則；浮點數、布林、空白與格式錯誤一律視為未知。"""
    if isinstance(value, bool) or not isinstance(value, str | int):
        return None
    try:
        return _AMOUNT.validate_python(value)
    except ValidationError:
        return None


def _parse_with(adapter: TypeAdapter[Any], value: Any) -> Any:
    try:
        return adapter.validate_python(value)
    except ValidationError:
        return None


def preview_warnings(body: Mapping[str, Any], today: date | None = None) -> WarningCheckRead:
    """依目前欄位值預覽業務警示（未來日期、金額與稅額一致性、統編檢查碼）。

    Args:
        body: 核對頁目前的欄位值（欄位同 POST /invoices，可缺漏、空白或格式錯誤）。
        today: 台灣當天日期；預設取目前台灣日期，測試可注入。

    Returns:
        WarningCheckRead；只含可判斷的警示，順序與正式送出相同（日期在前）。
    """
    today = today or today_taipei()
    items = body.get("items")
    line_amounts = [
        _parse_amount(item.get("line_amount")) if isinstance(item, Mapping) else None
        for item in (items if isinstance(items, list) else [])
    ]
    seller = body.get("seller_tax_id")
    warnings = [
        *future_date_warnings(_parse_date(body.get("invoice_date")), today),
        *_consistency_warnings(
            seller_tax_id=_parse_with(_TAX_ID, seller) if isinstance(seller, str) else None,
            buyer_tax_id=_parse_with(_TAX_ID, body.get("buyer_tax_id")),
            tax_type=_parse_with(_TAX_TYPE, body.get("tax_type")),
            sales=_parse_amount(body.get("sales_amount")),
            tax=_parse_amount(body.get("tax_amount")),
            total=_parse_amount(body.get("total_amount")),
            line_amounts=line_amounts,
        ),
    ]
    return WarningCheckRead(warnings=tuple(warnings), checked_on=today)
