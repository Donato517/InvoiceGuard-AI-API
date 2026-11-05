"""模組名稱：app.services.showcase_reference_service；功能說明：有效 Session 已驗證後的範例取用白名單。"""

from typing import Any
from uuid import UUID

from app.core.exceptions import AppError, NotFoundError
from app.db.repositories import showcase_reference_repository as repository
from app.integrations.document_ai_evidence import sha256
from app.integrations.supabase_storage import S3StorageClient, StorageError


class ReferenceUnavailableError(AppError):
    """來源或必要資料服務未就緒；不洩漏連線與物件鍵。"""

    status_code = 503
    code = "SHOWCASE_UNAVAILABLE"


def candidates(db: Any, tax_id: str, layout: str) -> list[dict[str, Any]]:
    """前台依已確認賣方統編取用；答案與本次發票分離。"""
    if not db:
        raise ReferenceUnavailableError("範例服務尚未就緒")
    if len(tax_id) != 8 or not tax_id.isascii() or not tax_id.isdigit() or len(layout) > 120:
        raise AppError("請提供八碼供應商統編及有效版型條件")
    try:
        rows = repository.candidates(db, tax_id, layout)
        return [
            {
                "sample_id": row["sample_id"],
                "revision_id": row["revision"]["id"],
                **{
                    key: row["revision"].get(key, "")
                    for key in (
                        "title",
                        "supplier_name",
                        "tax_id",
                        "layout",
                        "writing",
                        "copy_type",
                        "valid_from",
                        "valid_to",
                        "key_fields",
                    )
                },
                "truths": [
                    truth
                    for truth in row["revision"].get("truths", [])
                    if truth["state"] == "readable"
                    and truth["path"] in row["revision"].get("key_fields", [])
                ],
            }
            for row in rows
        ]
    except repository.StoreError:
        raise ReferenceUnavailableError("範例服務尚未就緒") from None


def source(db: Any, sample: UUID, revision: UUID) -> tuple[bytes, str]:
    """讀取前重新檢查啟用版本；原圖 hash 不符即拒絕。"""
    if not db:
        raise ReferenceUnavailableError("範例服務尚未就緒")
    try:
        ref = repository.source(db, sample, revision)
        if ref is None:
            raise NotFoundError("找不到可用範例")
        content, _ = S3StorageClient.from_settings(bucket=ref["bucket"]).get(ref["key"])
        if sha256(content) != ref["sha256"]:
            raise ReferenceUnavailableError("範例來源需重新確認")
        return content, ref["mime"]
    except (repository.StoreError, StorageError):
        raise ReferenceUnavailableError("範例來源暫時無法取得") from None
