"""模組名稱：app.services.data_service；功能說明：具型別的資料 CRUD 服務契約與安全入口。"""

from typing import Protocol, runtime_checkable

from app.core.module_errors import ModuleNotReadyError
from app.schemas.common import OperationContext, Page
from app.schemas.data import DeleteResult, InvoiceCreate, InvoiceQuery, InvoiceRead, InvoiceUpdate


@runtime_checkable
class InvoiceService(Protocol):
    """僅處理核定發票資源，交易與稽核由實作負責，不提供原始 SQL。"""

    def create(self, context: OperationContext, data: InvoiceCreate) -> InvoiceRead:
        """驗證授權與業務規則後建立資料。"""
        ...

    def get(self, context: OperationContext, invoice_id: int) -> InvoiceRead:
        """讀取授權範圍內的發票。"""
        ...

    def list(self, context: OperationContext, query: InvoiceQuery) -> Page[InvoiceRead]:
        """回傳授權範圍內的分頁。"""
        ...

    def update(
        self, context: OperationContext, invoice_id: int, data: InvoiceUpdate
    ) -> InvoiceRead:
        """以版本條件更新並記錄稽核。"""
        ...

    def delete(
        self, context: OperationContext, invoice_id: int, *, expected_version: int
    ) -> DeleteResult:
        """以版本條件軟刪除並記錄稽核。"""
        ...


class DataService(Protocol):
    """明確列出核定資源，禁止以任意資料表名稱執行 CRUD。"""

    @property
    def invoices(self) -> InvoiceService:
        """發票資料服務。"""
        ...


def get_data_service() -> DataService:
    """實際 Repository、交易與授權尚未接線，拒絕執行操作。"""
    raise ModuleNotReadyError
