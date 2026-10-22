"""
模組名稱：app.db.contracts
功能說明：發票 Repository 的型別契約，保留現有 SQLAlchemy 與分層。
注意事項：service 控制交易；Repository 不 commit，所有查詢必須套用授權範圍。
"""

from typing import Protocol, runtime_checkable

from sqlalchemy.orm import Session

from app.schemas.common import OperationContext, Page
from app.schemas.data import DeleteResult, InvoiceCreate, InvoiceQuery, InvoiceRead, InvoiceUpdate


@runtime_checkable
class InvoiceRepository(Protocol):
    """未來實作必須處理範圍限制、軟刪除與版本衝突；本身不提供授權。"""

    def create(self, db: Session, context: OperationContext, data: InvoiceCreate) -> InvoiceRead:
        """建立授權範圍內的發票。"""
        ...

    def get(self, db: Session, context: OperationContext, invoice_id: int) -> InvoiceRead:
        """取得單筆，未授權或已軟刪除的資料不得回傳。"""
        ...

    def list(
        self, db: Session, context: OperationContext, query: InvoiceQuery
    ) -> Page[InvoiceRead]:
        """取得授權範圍內的分頁結果。"""
        ...

    def update(
        self, db: Session, context: OperationContext, invoice_id: int, data: InvoiceUpdate
    ) -> InvoiceRead:
        """以版本條件更新允許欄位。"""
        ...

    def delete(
        self, db: Session, context: OperationContext, invoice_id: int, *, expected_version: int
    ) -> DeleteResult:
        """以版本條件軟刪除，實際交易由 service 控制。"""
        ...
