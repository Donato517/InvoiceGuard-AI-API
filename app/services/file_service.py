"""模組名稱：app.services.file_service；功能說明：檔案服務契約與尚未接線的安全入口。"""

from typing import BinaryIO, Protocol, runtime_checkable

from app.core.module_errors import ModuleNotReadyError
from app.schemas.common import OperationContext, Page
from app.schemas.data import DeleteResult
from app.schemas.files import (
    DeleteFileRequest,
    DownloadGrant,
    FileInfo,
    FileQuery,
    MoveFileRequest,
    UploadFileRequest,
)


@runtime_checkable
class FileService(Protocol):
    """所有操作都需真實登入授權；宣告此介面不等於已實作權限檢查。"""

    def upload_file(
        self, context: OperationContext, data: UploadFileRequest, stream: BinaryIO
    ) -> FileInfo:
        """驗證內容、授權及冪等性後上傳並協調 DB 中繼資料。"""
        ...

    def get_file(self, context: OperationContext, file_id: int) -> FileInfo:
        """讀取授權範圍內的檔案資訊。"""
        ...

    def list_files(self, context: OperationContext, query: FileQuery) -> Page[FileInfo]:
        """列出授權範圍內的檔案。"""
        ...

    def create_download(
        self, context: OperationContext, file_id: int, *, expires_in: int = 60
    ) -> DownloadGrant:
        """建立短效下載憑證，未來實作必須限制有效期間。"""
        ...

    def move_file(self, context: OperationContext, file_id: int, data: MoveFileRequest) -> FileInfo:
        """移動物件並同步中繼資料，失敗時執行補償。"""
        ...

    def delete_file(
        self, context: OperationContext, file_id: int, data: DeleteFileRequest
    ) -> DeleteResult:
        """依授權、版本及保留政策刪除。"""
        ...


def get_file_service() -> FileService:
    """實際 Storage、metadata 與授權尚未接線，拒絕執行操作。"""
    raise ModuleNotReadyError
