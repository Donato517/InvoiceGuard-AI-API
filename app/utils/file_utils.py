"""
模組名稱：app.utils.file_utils
功能說明：暫存檔處理工具。所有暫存檔都必須透過本模組建立，確保放在正確位置且用完即刪。
注意事項：
    - 暫存目錄由 settings.temp_dir 決定：Vercel 上為 /tmp/invoiceguard，本機為專案內 tmp/。
    - Vercel 的 /tmp 不保證跨請求存在，不可用來保存需要留存的檔案：ADMIN／API 改用 Vercel 模組
      app.integrations.supabase_storage；前台沒有 Storage，檔案交給 API。
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from app.core.config import settings


def ensure_temp_dir() -> Path:
    """確保暫存目錄存在並回傳路徑。"""
    temp_dir = settings.temp_dir
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


@contextmanager
def temp_file_path(suffix: str = "") -> Iterator[Path]:
    """取得一個用完即刪的暫存檔路徑。

    Args:
        suffix: 副檔名，例如 ".pdf"。

    Yields:
        暫存檔路徑（檔案尚未建立，由呼叫端寫入）。離開 with 區塊時自動刪除。

    Example:
        with temp_file_path(".pdf") as path:
            path.write_bytes(content)
            text = parse_pdf(path)
    """
    path = ensure_temp_dir() / f"{uuid4().hex}{suffix}"
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
