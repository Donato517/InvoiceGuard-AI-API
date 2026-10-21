"""
模組名稱：app.db.models.user
功能說明：使用者帳號。前台使用者與後台管理者共用同一張表，以 role 區分。

==============================================================================
資料表：users（使用者）                                            狀態：草案
==============================================================================
欄位             型別            NULL  預設        說明
---------------  --------------  ----  ----------  ------------------------------
id               BIGINT          NO    IDENTITY    主鍵
email            VARCHAR(255)    NO                登入帳號（唯一，一律轉小寫儲存）
password_hash    VARCHAR(255)    NO                密碼雜湊（禁止存明碼）
display_name     VARCHAR(100)    NO                顯示名稱
role             VARCHAR(20)     NO    'user'      角色：user / admin
is_active        BOOLEAN         NO    true        是否啟用（停用後不可登入）
last_login_at    TIMESTAMPTZ     YES               最後登入時間
created_at       TIMESTAMPTZ     NO    now()       建立時間
updated_at       TIMESTAMPTZ     NO    now()       最後更新時間
deleted_at       TIMESTAMPTZ     YES               軟刪除時間（NULL＝未刪除）
------------------------------------------------------------------------------
主鍵：pk_users (id)
唯一：uq_users_email (email)
檢查：ck_users_role_valid  role IN ('user', 'admin')
外鍵：—
關聯：users 1 ─ N invoices；users 1 ─ N audit_logs
------------------------------------------------------------------------------
異動紀錄（新到舊；上線後須附 migration revision）
2026-10-21  JerryChien  初版草案（尚未產生 migration）
==============================================================================
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin, in_values_check

if TYPE_CHECKING:
    from app.db.models.invoice import Invoice


class UserRole(StrEnum):
    """使用者角色。"""

    USER = "user"  # 前台使用者
    ADMIN = "admin"  # 後台管理者


class User(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    """使用者帳號。欄位定義見本檔開頭 Schema 備註。"""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint(in_values_check("role", UserRole), name="role_valid"),)

    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), server_default=UserRole.USER.value)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    invoices: Mapped[list["Invoice"]] = relationship(back_populates="user")
