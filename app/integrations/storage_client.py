"""
模組名稱：app.integrations.storage_client
功能說明：雲端 Storage 的內部介面；路徑與權限須由上層服務決定。
注意事項：本階段沒有 Supabase 實作，不可由路由直接傳入任意 Bucket 或物件路徑。
"""

from datetime import datetime
from typing import BinaryIO, Protocol, runtime_checkable

from app.core.module_errors import ModuleNotReadyError


@runtime_checkable
class StorageClient(Protocol):
    """內部物件儲存介面；呼叫前須完成授權與路徑產生。"""

    def upload(self, key: str, stream: BinaryIO, *, content_type: str, size_bytes: int) -> None:
        """上傳至服務產生的物件鍵，預設不得覆蓋既有物件。"""
        ...

    def create_download_url(self, key: str, *, expires_at: datetime) -> str:
        """建立限時下載網址；不得記錄完整網址。"""
        ...

    def move(self, source_key: str, destination_key: str) -> None:
        """移動物件；DB 協調、補償與重試由 service 負責。"""
        ...

    def delete(self, key: str) -> None:
        """刪除獲授權的物件；重複請求政策由 service 負責。"""
        ...


def get_storage_client() -> StorageClient:
    """尚未接線，明確拒絕取得可操作的 Storage 用戶端。"""
    raise ModuleNotReadyError
