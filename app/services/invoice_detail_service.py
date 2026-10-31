"""
模組名稱：app.services.invoice_detail_service
功能說明：提交者本人讀取已送出發票的詳情——表頭、明細、欄位修改對照、檢核警示與目前影像中繼資料。
相依模組：app.db.repositories.invoice_repository、app.schemas.invoice_detail
注意事項：
    - 只讀取：不 INSERT／UPDATE／DELETE，也不 commit；多次 SELECT 在同一個 REPEATABLE READ 唯讀交易內讀取。
    - 授權在 repository 查詢落實（submitted_by = 目前登入者），不使用 Session 選取部門；
      案件不存在與不屬於本人都回相同的 404，不洩漏案件是否存在。
    - 金額與數量轉成十進位字串並保留資料庫小數位數；NULL 保持 None。
    - modified_fields 只照 invoice_field_reviews 原樣回傳，不補沒有紀錄的欄位，也不重建完整 AI 快照。
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import AppError, NotFoundError, ServiceUnavailableError
from app.db.repositories import invoice_repository
from app.schemas.auth import SessionRead
from app.schemas.invoice_detail import InvoiceDetailRead, InvoiceFileRead, InvoiceItemRead
from app.schemas.invoice_upload import FieldWarning, ModifiedField

logger = logging.getLogger(__name__)

_DB_UNAVAILABLE = "發票服務暫時無法使用，請稍後再試"
_NOT_FOUND = "找不到這張發票"
_DATA_INVALID = "發票資料格式異常，暫時無法顯示，請聯絡系統管理員"
_WARNING_KEYS = ("field", "code", "message")


class InvoiceDataError(AppError):
    """資料庫中已保存的發票資料不符契約（不是使用者輸入錯誤）；回 500，訊息不含資料內容。"""

    status_code = 500
    code = "INVOICE_DATA_INVALID"


def get_invoice_detail(
    db: Session | None, current: SessionRead, invoice_id: UUID
) -> InvoiceDetailRead:
    """讀取登入者本人提交的發票詳情。

    Args:
        db: 資料庫 Session；未設定資料庫時為 None。
        current: 已核對的登入者；只使用 user_id，不使用選取部門。
        invoice_id: 發票 UUID。

    Returns:
        InvoiceDetailRead: 表頭、明細、修改對照、警示與目前影像中繼資料。

    Raises:
        NotFoundError: 發票不存在或不是本人提交的（兩者回應相同）。
        ServiceUnavailableError: 資料庫未設定。
        InvoiceDataError: 已保存的 validation_results 結構不符（500 INVOICE_DATA_INVALID）。
        UnexpectedTransactionStateError: Session 進入本函式時已在交易中（500；不清除該交易）。
    """
    if db is None:
        raise ServiceUnavailableError(_DB_UNAVAILABLE)
    try:
        invoice_repository.begin_read_snapshot(db)
    except invoice_repository.UnexpectedTransactionStateError:
        # 交易不是本函式開的，不 rollback；以 500 回報（記錄堆疊），避免誤清呼叫端的交易
        raise
    except Exception:
        # SET TRANSACTION 本身失敗：此時交易已由本函式的第一個陳述式開啟，屬於本函式
        db.rollback()
        raise
    # 從這裡起的交易由本函式開啟，成功與例外路徑都只結束這個交易
    try:
        header = invoice_repository.get_owned_invoice(db, invoice_id, user_id=current.user_id)
        if header is None:
            raise NotFoundError(_NOT_FOUND)
        items = invoice_repository.list_items(db, invoice_id)
        reviews = invoice_repository.list_field_reviews(
            db, invoice_id, submission_round=header["submission_round"]
        )
        file_row = invoice_repository.get_current_file(db, invoice_id)
    except Exception:
        db.rollback()
        raise
    # 唯讀交易，沒有可提交的內容；結束交易以釋放連線資源
    db.rollback()

    return InvoiceDetailRead(
        invoice_id=header["invoice_id"],
        status=header["status"],
        submission_round=header["submission_round"],
        submitted_at=_utc(header["submitted_at"]),
        tax_period=header["tax_period"],
        invoice_track=header["invoice_track"],
        invoice_number=header["invoice_number"],
        invoice_date=header["invoice_date"],
        seller_tax_id=header["seller_tax_id"],
        seller_name=header["seller_name"],
        buyer_tax_id=header["buyer_tax_id"],
        buyer_name=header["buyer_name"],
        tax_type=header["tax_type"],
        sales_amount=_decimal_text(header["sales_amount"]),
        tax_amount=_decimal_text(header["tax_amount"]),
        total_amount=_decimal_text(header["total_amount"]),
        total_amount_zh=header["total_amount_zh"],
        items=tuple(
            InvoiceItemRead(
                line_no=row["line_no"],
                item_name=row["item_name"],
                quantity=_decimal_text(row["quantity"]),
                unit_price=_decimal_text(row["unit_price"]),
                line_amount=_decimal_text(row["line_amount"]),
            )
            for row in items
        ),
        modified_fields=tuple(
            ModifiedField(
                field_scope=row["field_scope"],
                line_no=row["line_no"],
                field_name=row["field_name"],
                ai_original_value=row["ai_original_value"],
                submitted_value=row["submitted_value"],
            )
            for row in reviews
        ),
        warnings=_warnings(header["validation_results"], invoice_id),
        file=_file(file_row),
    )


def _decimal_text(value: Decimal | None) -> str | None:
    """十進位轉字串（不用科學記號、不經浮點數）；None 保持 None。"""
    return None if value is None else format(value, "f")


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)


def _file(row: dict[str, Any] | None) -> InvoiceFileRead | None:
    if row is None:
        return None
    return InvoiceFileRead(
        mime_type=row["mime_type"],
        original_filename=row["original_filename"],
        size_bytes=row["size_bytes"],
        version_no=row["version_no"],
    )


def _warnings(validation_results: object, invoice_id: UUID) -> tuple[FieldWarning, ...]:
    """取 validation_results.warnings；結構不符就回報資料異常，不把壞資料當成「沒有警示」。

    - NULL 或沒有 warnings 鍵（欄位預設值 {}）：沒有警示。
    - warnings 必須是 list，每筆必須是 dict 且 field、code、message 都是字串；其他一律視為異常。
    - 合法項目中多出的鍵（例如 severity）不在 FieldWarning 契約內，不回傳。

    Raises:
        InvoiceDataError: validation_results 或其中任一警示的結構不符（500 INVOICE_DATA_INVALID）。
    """
    if validation_results is None:
        return ()
    if not isinstance(validation_results, dict):
        raise _invalid_data(invoice_id, "validation_results_not_object")
    if "warnings" not in validation_results:
        return ()
    raw = validation_results["warnings"]
    if not isinstance(raw, list):
        raise _invalid_data(invoice_id, "warnings_not_list")
    warnings: list[FieldWarning] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise _invalid_data(invoice_id, "warning_not_object", index)
        for key in _WARNING_KEYS:
            if not isinstance(entry.get(key), str):
                raise _invalid_data(invoice_id, f"warning_{key}_invalid", index)
        warnings.append(
            FieldWarning(field=entry["field"], code=entry["code"], message=entry["message"])
        )
    return tuple(warnings)


def _invalid_data(invoice_id: UUID, reason: str, index: int | None = None) -> InvoiceDataError:
    """記錄固定的異常原因（只有發票 UUID、原因代碼與項目序號，不含警示內容或發票資料）。"""
    logger.error("發票 %s 的 validation_results 格式異常：%s（項目 %s）", invoice_id, reason, index)
    return InvoiceDataError(_DATA_INVALID)
