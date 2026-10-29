"""
模組名稱：app.db.repositories.recognition_repository
功能說明：發票辨識紀錄資料存取——public.ai_recognition_logs（v1.4）。
注意事項：
    - 每次辨識一筆：先記 Storage 影像路徑（source_storage_path），完成後補模型、結果與狀態；
      正式上傳時回填 invoice_id／invoice_file_id。
    - 辨識後未上傳的影像保留 1 小時，刪除 Storage 物件後記 source_deleted_at（v1.4）。
    - 以固定 SQL 存取，值一律綁定參數；只負責資料存取，不自行 commit（交易由 service 控制）。
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# 2026-10-29 使用者核定：辨識後未上傳的影像保留 1 小時
SOURCE_RETENTION_HOURS = 1
_RETENTION = f"interval '{SOURCE_RETENTION_HOURS} hours'"

INSERT_RECOGNITION = text("""
    INSERT INTO public.ai_recognition_logs
        (recognition_id, source_storage_path, ai_provider, result_status, requested_by)
    VALUES (:recognition_id, :source_storage_path, :ai_provider, 'pending', :requested_by)
    RETURNING created_at
""")
COMPLETE_RECOGNITION = text("""
    UPDATE public.ai_recognition_logs
    SET model_name = :model_name,
        is_triplicate = :is_triplicate,
        confidence_score = :confidence_score,
        extracted_fields = CAST(:extracted_fields AS jsonb),
        raw_response = CAST(:raw_response AS jsonb),
        result_status = :result_status,
        error_message = :error_message,
        completed_at = now()
    WHERE recognition_id = :recognition_id
""")
LOCK_FOR_SUBMIT = text(f"""
    SELECT recognition_id, source_storage_path, extracted_fields, raw_response, result_status,
           invoice_id, source_deleted_at,
           created_at < now() - {_RETENTION} AS expired
    FROM public.ai_recognition_logs
    WHERE recognition_id = :recognition_id AND requested_by = :user_id
    FOR UPDATE
""")
LINK_INVOICE = text("""
    UPDATE public.ai_recognition_logs
    SET invoice_id = :invoice_id, invoice_file_id = :invoice_file_id
    WHERE recognition_id = :recognition_id
""")
SELECT_EXPIRED_SOURCES = text(f"""
    SELECT recognition_id, source_storage_path
    FROM public.ai_recognition_logs
    WHERE invoice_file_id IS NULL
      AND source_storage_path IS NOT NULL
      AND source_deleted_at IS NULL
      AND source_storage_path LIKE :key_pattern
      AND created_at < now() - {_RETENTION}
    ORDER BY created_at
    LIMIT :limit
    FOR UPDATE SKIP LOCKED
""")
MARK_SOURCE_DELETED = text("""
    UPDATE public.ai_recognition_logs
    SET source_deleted_at = GREATEST(now(), created_at)
    WHERE recognition_id = :recognition_id
""")


@dataclass(frozen=True)
class RecognitionForSubmit:
    """送出時鎖定的辨識紀錄。"""

    recognition_id: UUID
    source_storage_path: str | None
    extracted_fields: dict[str, Any] | None
    raw_response: dict[str, Any] | None
    result_status: str
    invoice_id: UUID | None
    source_deleted_at: datetime | None
    expired: bool


def insert(
    db: Session,
    *,
    recognition_id: UUID,
    source_storage_path: str,
    ai_provider: str,
    requested_by: UUID,
) -> datetime:
    """新增一筆辨識中（pending）的紀錄，回傳建立時間；不提交交易。"""
    params = {
        "recognition_id": recognition_id,
        "source_storage_path": source_storage_path,
        "ai_provider": ai_provider,
        "requested_by": requested_by,
    }
    return db.execute(INSERT_RECOGNITION, params).scalar_one()


def complete(
    db: Session,
    recognition_id: UUID,
    *,
    model_name: str | None,
    is_triplicate: bool | None,
    confidence_score: float | None,
    extracted_fields: dict[str, Any] | None,
    raw_response: dict[str, Any] | None,
    result_status: str,
    error_message: str | None,
) -> None:
    """寫入辨識結果與狀態（success／partial／failed）；不提交交易。"""
    db.execute(
        COMPLETE_RECOGNITION,
        {
            "recognition_id": recognition_id,
            "model_name": model_name,
            "is_triplicate": is_triplicate,
            "confidence_score": confidence_score,
            "extracted_fields": _json(extracted_fields),
            "raw_response": _json(raw_response),
            "result_status": result_status,
            "error_message": error_message,
        },
    )


def lock_for_submit(
    db: Session, recognition_id: UUID, user_id: UUID
) -> RecognitionForSubmit | None:
    """鎖定本人的辨識紀錄供送出；不存在或不是本人的回傳 None。"""
    row = (
        db.execute(LOCK_FOR_SUBMIT, {"recognition_id": recognition_id, "user_id": user_id})
        .mappings()
        .one_or_none()
    )
    return RecognitionForSubmit(**row) if row else None


def link_invoice(
    db: Session, recognition_id: UUID, invoice_id: UUID, invoice_file_id: UUID
) -> None:
    """正式上傳後回填發票與檔案；不提交交易。"""
    db.execute(
        LINK_INVOICE,
        {
            "recognition_id": recognition_id,
            "invoice_id": invoice_id,
            "invoice_file_id": invoice_file_id,
        },
    )


def lock_expired_sources(db: Session, limit: int, *, file_prefix: str) -> list[tuple[UUID, str]]:
    """鎖定超過保留時間、尚未上傳也尚未刪除、檔名含 file_prefix 的影像（略過其他交易已鎖定者）。"""
    escaped = file_prefix.replace("\\", "\\\\").replace("_", r"\_").replace("%", r"\%")
    rows = db.execute(
        SELECT_EXPIRED_SOURCES, {"limit": limit, "key_pattern": f"%/{escaped}%"}
    ).all()
    return [(row[0], row[1]) for row in rows]


def mark_source_deleted(db: Session, recognition_id: UUID) -> None:
    """記錄影像已自 Storage 刪除；不提交交易。"""
    db.execute(MARK_SOURCE_DELETED, {"recognition_id": recognition_id})


def _json(value: dict[str, Any] | None) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)
