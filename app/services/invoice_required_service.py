"""
模組名稱：app.services.invoice_required_service
功能說明：上傳核對頁按下「上傳者確認」時的必填欄位檢核——一次列出正式提交 `InvoiceSubmitRequest` 的所有必填缺漏。
相依模組：app.schemas.invoice_upload、app.utils.invoice_format
注意事項：
    - 必填規則只有一份：`InvoiceSubmitRequest` 的欄位宣告。本模組不另建必填清單，只用該模型驗證，
      再回頭看原始請求在錯誤位置的值，把「不存在、null、空白字串（含全形空白）」歸為缺漏，
      其餘（有值但格式或型別不符）不算缺漏，仍由正式提交的 Pydantic 驗證（422 VALIDATION_ERROR）處理。
    - 因此回應的 required_complete 只代表「沒有必填缺漏」，不代表格式、金額或整體資料有效，也不代表可以提交。
    - 純函式：不連 DB、Storage 或外部服務，不寫入任何資料，不記錄請求內容。
    - recognition_id 與 changes 是前台程式帶的內部欄位，使用者看不到也無法補填，不列入缺漏。
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.schemas.invoice_upload import (
    InvoiceItemSubmit,
    InvoiceSubmitRequest,
    MissingField,
    RequiredCheckRead,
)
from app.utils.invoice_format import strip_spaces

# 使用者看不到、也無法在核對頁補填的欄位（由前台程式帶入）
_INTERNAL_FIELDS = frozenset({"recognition_id", "changes"})
# 欄位 → 缺漏時給使用者看的中文提示；沒列到的必填欄位（日後新增）仍會回報，訊息用預設文字
_MESSAGES = {
    "invoice_track": "請填寫字軌",
    "invoice_number": "請填寫發票號碼",
    "invoice_date": "請填寫發票日期",
    "seller_tax_id": "請填寫賣方統一編號",
    "tax_type": "請選擇課稅別",
    "sales_amount": "請填寫銷售額合計",
    "tax_amount": "請填寫營業稅額",
    "total_amount": "請填寫總計",
    "items": "請至少填寫一筆品名明細",
    "item_name": "請填寫品名",
    "line_amount": "請填寫明細金額",
}
_DEFAULT_MESSAGE = "請填寫此欄位"


def _lookup(body: Any, loc: tuple[Any, ...]) -> tuple[bool, Any]:
    """沿著錯誤位置取出原始請求中的值。

    Args:
        body: 原始請求（JSON 解析後的 dict）。
        loc: Pydantic 錯誤位置，例如 ("items", 0, "item_name")。

    Returns:
        (是否找得到, 值)；路徑中任何一層不存在都回傳 (False, None)。
    """
    current = body
    for key in loc:
        if isinstance(current, Mapping):
            if not isinstance(key, str) or key not in current:
                return False, None
        elif isinstance(current, list | tuple):
            if not isinstance(key, int) or not 0 <= key < len(current):
                return False, None
        else:
            return False, None
        current = current[key]
    return True, current


def _is_required(model: type[InvoiceSubmitRequest] | type[InvoiceItemSubmit], name: str) -> bool:
    """欄位在模型中是否必填（沒有預設值）；選填欄位即使格式不符也不是「缺漏」。"""
    info = model.model_fields.get(name)
    return info is not None and info.is_required()


def _is_blank(found: bool, value: Any) -> bool:
    """不存在、null、空字串或只含空白（含全形空白）視為未填。"""
    if not found or value is None:
        return True
    return isinstance(value, str) and strip_spaces(value) == ""


def find_missing(body: Mapping[str, Any]) -> tuple[MissingField, ...]:
    """列出請求中所有必填缺漏（依 InvoiceSubmitRequest 的欄位順序）。

    Args:
        body: 前台核對頁目前的欄位值（欄位同 POST /invoices，允許缺漏或空白）。

    Returns:
        缺漏清單；沒有缺漏時為空。同一欄位（同一明細列）只回報一次。
    """
    try:
        InvoiceSubmitRequest.model_validate(body)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_url=False, include_context=False)
    else:
        return ()

    missing: list[MissingField] = []
    seen: set[tuple[str, int | None]] = set()
    for error in errors:
        loc = tuple(error["loc"])
        if not loc or not isinstance(loc[0], str) or loc[0] in _INTERNAL_FIELDS:
            continue
        if loc[0] == "items" and len(loc) == 1:
            # 明細整體：不存在、null 或空清單才是缺漏。Pydantic 會在某筆明細格式錯誤時，
            # 另外回報「清單少於 1 筆」，所以不能只看錯誤類型，要看原始清單
            found, value = _lookup(body, loc)
            if not (_is_blank(found, value) or (isinstance(value, list | tuple) and not value)):
                continue
            field, line_no = "items", None
        elif loc[0] == "items":
            if (
                len(loc) < 3
                or not isinstance(loc[1], int)
                or not _is_required(InvoiceItemSubmit, str(loc[2]))
            ):
                continue
            found, value = _lookup(body, loc[:3])
            if not _is_blank(found, value):
                continue
            field, line_no = str(loc[2]), loc[1] + 1
        else:
            if not _is_required(InvoiceSubmitRequest, loc[0]):
                continue
            found, value = _lookup(body, loc[:1])
            if not _is_blank(found, value):
                continue
            field, line_no = loc[0], None
        if (field, line_no) in seen:
            continue
        seen.add((field, line_no))
        missing.append(
            MissingField(
                field=field,
                code="required_missing",
                message=_MESSAGES.get(field, _DEFAULT_MESSAGE),
                line_no=line_no,
            )
        )
    return tuple(missing)


def check_required(body: Mapping[str, Any]) -> RequiredCheckRead:
    """必填欄位檢核：回傳是否沒有必填缺漏與缺漏清單。

    Args:
        body: 前台核對頁目前的欄位值。

    Returns:
        RequiredCheckRead；required_complete 只表示沒有必填缺漏，不代表格式或金額正確。
    """
    missing = find_missing(body)
    return RequiredCheckRead(required_complete=not missing, missing=missing)
