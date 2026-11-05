"""模組名稱：app.db.repositories.showcase_reference_repository；功能說明：前台登入者的 v2.0 範例唯讀查詢。"""

from typing import Any
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.repositories import showcase_v2_reader as v2

StoreError = SQLAlchemyError


def candidates(db: Session, tax_id: str, layout: str) -> list[dict[str, Any]]:
    """取用未到期的已驗證版本。"""
    return v2.candidates(db, tax_id, layout)


def source(db: Session, sample: UUID, revision: UUID) -> dict[str, Any] | None:
    """以當前 v2.0 版本重驗原件取用權。"""
    row = v2.get_example(db, sample, verified_only=True)
    return row["source"] if row and row["id"] == str(revision) else None
