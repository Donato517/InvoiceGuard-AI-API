"""模組名稱：app.schemas.files；功能說明：檔案操作契約，不暴露 Bucket 或內部物件鍵。"""

import unicodedata
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, HttpUrl, StrictInt, field_validator

from app.schemas.common import ContractModel, PageQuery, RecordId, Version

MAX_UPLOAD_BYTES = 4 * 1024 * 1024
# 多數檔案系統與物件儲存以位元組計算檔名長度上限
MAX_FILENAME_BYTES = 255
FileContentType = Literal["image/jpeg", "image/png", "application/pdf"]
FileName = Annotated[str, Field(min_length=1, max_length=255)]

# Windows 保留裝置名稱：下載後在 Windows 存檔會失敗（不分大小寫、不論副檔名）
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
# 控制字元（含 C1）、格式字元（含雙向覆寫、零寬字元）、行 / 段落分隔、代理字元
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Cs"})


def validate_filename(value: str) -> str:
    """檔名是顯示資訊，不允許夾帶路徑、控制或格式字元、系統保留名稱。

    雙向覆寫字元（例如 U+202E）可讓 `x.exe` 顯示成 `x.png`，因此一併拒絕；
    結尾的空白與句點會被 Windows 自動去除，造成顯示與實際檔名不一致。
    """
    if (
        not value.strip()
        or value.endswith((" ", "."))
        or any(character in value for character in ("/", "\\", ":"))
        or any(unicodedata.category(character) in _FORBIDDEN_CATEGORIES for character in value)
        or value.split(".", 1)[0].strip().upper() in WINDOWS_RESERVED_NAMES
        or len(value.encode("utf-8")) > MAX_FILENAME_BYTES
    ):
        raise ValueError("檔名不可包含路徑、控制字元或系統保留名稱，且需在 255 bytes 以內")
    return value


class UploadFileRequest(ContractModel):
    """上傳描述；實際服務仍須驗證串流長度及內容特徵，不能只信任宣告。"""

    filename: FileName
    content_type: FileContentType
    size_bytes: Annotated[StrictInt, Field(gt=0, le=MAX_UPLOAD_BYTES)]
    invoice_id: RecordId | None = None
    idempotency_key: UUID

    _validate_filename = field_validator("filename")(validate_filename)


class FileQuery(PageQuery):
    """僅開放明確的檔案篩選欄位。"""

    invoice_id: RecordId | None = None


class MoveFileRequest(ContractModel):
    """移至服務核定的邏輯資料夾，不接受原始 Bucket 或任意系統路徑。"""

    destination_folder: Annotated[
        str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$")
    ]
    expected_version: Version
    idempotency_key: UUID


class DeleteFileRequest(ContractModel):
    """檔案刪除要求；保留政策不由呼叫者決定。"""

    expected_version: Version
    idempotency_key: UUID


class FileInfo(ContractModel):
    """公開檔案中繼資料，不含公司憑證、內部物件鍵或永久下載網址。"""

    id: RecordId
    owner_user_id: RecordId
    invoice_id: RecordId | None = None
    filename: FileName
    content_type: FileContentType
    size_bytes: Annotated[StrictInt, Field(gt=0)]
    status: Literal["uploading", "ready", "deleting", "deleted", "failed"]
    version: Version
    created_at: AwareDatetime
    updated_at: AwareDatetime

    _validate_filename = field_validator("filename")(validate_filename)


class DownloadGrant(ContractModel):
    """短效使用者下載憑證；網址包含能力資訊，不得寫入日誌。"""

    url: HttpUrl = Field(repr=False)
    expires_at: AwareDatetime

    @field_validator("url")
    @classmethod
    def validate_https_url(cls, value: HttpUrl) -> HttpUrl:
        """下載憑證只允許 HTTPS 且不包含帳密。"""
        if value.scheme != "https" or value.username or value.password:
            raise ValueError("下載網址需使用不含帳密的 HTTPS")
        return value
