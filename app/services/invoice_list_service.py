"""
模組名稱：app.services.invoice_list_service
功能說明：提交者本人的發票列表——分頁、可依簽核狀態篩選，最新送出的在前。
相依模組：app.db.repositories.invoice_repository、app.schemas.invoice_list
注意事項：
    - 只讀取：不 INSERT／UPDATE／DELETE，也不 commit；總筆數與資料列在同一個 REPEATABLE READ 唯讀交易內取得，
      兩者使用相同的本人條件，數字與列表不會互相矛盾。
    - 授權在 repository 查詢落實（submitted_by = 目前登入者），不使用 Session 選取部門。
    - 超出最後一頁時回傳空 items，total 仍是本人的總筆數。
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import ServiceUnavailableError
from app.db.repositories import invoice_repository
from app.schemas.auth import SessionRead
from app.schemas.invoice_list import InvoiceListItem, InvoiceListRead

_DB_UNAVAILABLE = "發票服務暫時無法使用，請稍後再試"


def list_my_invoices(
    db: Session | None, current: SessionRead, *, page: int, page_size: int, status: str | None
) -> InvoiceListRead:
    """讀取登入者本人提交的發票列表。

    Args:
        db: 資料庫 Session；未設定資料庫時為 None。
        current: 已核對的登入者；只使用 user_id。
        page: 頁碼，從 1 開始。
        page_size: 每頁筆數（1～100，由路由驗證）。
        status: 簽核狀態代碼（已由路由驗證為九個合法值之一）；None 表示全部。

    Returns:
        InvoiceListRead: {items, total, page, page_size}。

    Raises:
        ServiceUnavailableError: 資料庫未設定。
        UnexpectedTransactionStateError: Session 進入本函式時已在交易中（500；不清除該交易）。
    """
    if db is None:
        raise ServiceUnavailableError(_DB_UNAVAILABLE)
    try:
        invoice_repository.begin_read_snapshot(db)
    except invoice_repository.UnexpectedTransactionStateError:
        # 交易不是本函式開的，不 rollback；以 500 回報，避免誤清呼叫端的交易
        raise
    except Exception:
        # SET TRANSACTION 本身失敗：此時交易已由本函式的第一個陳述式開啟，屬於本函式
        db.rollback()
        raise
    try:
        total = invoice_repository.count_owned(db, user_id=current.user_id, status=status)
        rows = invoice_repository.list_owned_page(
            db,
            user_id=current.user_id,
            status=status,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
    finally:
        # 唯讀交易，沒有可提交的內容；成功與例外路徑都結束這個交易
        db.rollback()
    return InvoiceListRead(
        items=tuple(
            InvoiceListItem(
                invoice_id=row["invoice_id"],
                status=row["status"],
                submission_round=row["submission_round"],
                submitted_at=_utc(row["submitted_at"]),
                invoice_track=row["invoice_track"],
                invoice_number=row["invoice_number"],
                invoice_date=row["invoice_date"],
                seller_name=row["seller_name"],
                total_amount=_decimal_text(row["total_amount"]),
            )
            for row in rows
        ),
        total=total,
        page=page,
        page_size=page_size,
    )


def _decimal_text(value: Decimal | None) -> str | None:
    """十進位轉字串（不用科學記號、不經浮點數）；None 保持 None。"""
    return None if value is None else format(value, "f")


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)
