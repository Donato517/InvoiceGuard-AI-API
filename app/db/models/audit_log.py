"""
模組名稱：app.db.models.audit_log
功能說明：操作稽核紀錄。記錄後台審核、帳號停用等重要操作，供追查使用。

==============================================================================
資料表：audit_logs（操作稽核紀錄）                                 狀態：草案
==============================================================================
欄位             型別            NULL  預設        說明
---------------  --------------  ----  ----------  ------------------------------
id               BIGINT          NO    IDENTITY    主鍵
user_id          BIGINT          YES               操作者 → users.id（系統排程為 NULL）
action           VARCHAR(50)     NO                動作代碼，格式「對象.動作」，例：invoice.review
target_type      VARCHAR(50)     YES               目標類型，例：invoice、user
target_id        BIGINT          YES               目標主鍵
detail           JSONB           YES               異動內容（例：{"before": {...}, "after": {...}}）
ip_address       VARCHAR(45)     YES               來源 IP（IPv6 最長 45 字元）
created_at       TIMESTAMPTZ     NO    now()       建立時間
------------------------------------------------------------------------------
主鍵：pk_audit_logs (id)
索引：ix_audit_logs_user_id (user_id)
      ix_audit_logs_target_type_target_id (target_type, target_id)
      ix_audit_logs_created_at (created_at)
外鍵：fk_audit_logs_user_id_users  user_id → users.id  ON DELETE SET NULL
關聯：users 1 ─ N audit_logs
特性：append-only——只新增，不更新、不刪除，因此沒有 updated_at / deleted_at
------------------------------------------------------------------------------
異動紀錄（新到舊；上線後須附 migration revision）
2026-10-21  JerryChien  初版草案（尚未產生 migration）
==============================================================================
"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin


class AuditLog(IdMixin, Base):
    """操作稽核紀錄。欄位定義見本檔開頭 Schema 備註。"""

    __tablename__ = "audit_logs"
    __table_args__ = (Index(None, "target_type", "target_id"),)

    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(50))
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
