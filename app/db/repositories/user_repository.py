"""
模組名稱：app.db.repositories.user_repository
功能說明：使用者資料存取（優先支援雲端 invoiceguard_identity.user_accounts，若無則支援 ORM users 表）。
注意事項：
    - 只負責資料存取，不含商業邏輯，不自行 commit（交易由 service 控制）。
    - 查詢預設排除停用或軟刪除資料。
    - email 查詢前一律轉小寫，與寫入規則一致。
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models.user import User, UserRole

logger = logging.getLogger(__name__)


@dataclass
class UserRecord:
    """統一封裝雲端帳號結構之使用者物件。"""

    id: str | int
    email: str
    password_hash: str
    display_name: str
    role: str
    is_active: bool
    last_login_at: datetime | None = None
    _is_identity: bool = True


_IDENTITY_SELECT = """
    SELECT
        a.user_id,
        a.email,
        a.password_hash,
        COALESCE(p.display_name, split_part(a.email, '@', 1)) AS display_name,
        CASE
            WHEN EXISTS (
                SELECT 1 FROM public.user_departments ud
                JOIN public.departments d ON ud.department_id = d.department_id
                WHERE ud.user_id = a.user_id AND d.department_code IN ('administration_d', 'technology_d')
            ) THEN 'admin'
            ELSE 'user'
        END AS role,
        (a.account_status = 'active' AND COALESCE(p.is_active, true)) AS is_active,
        a.last_login_at
    FROM invoiceguard_identity.user_accounts a
    LEFT JOIN public.user_profiles p ON a.user_id = p.user_id
"""


def _from_row(row: Any) -> UserRecord:
    return UserRecord(
        id=str(row[0]),
        email=str(row[1]),
        password_hash=str(row[2]),
        display_name=str(row[3]),
        role=str(row[4]),
        is_active=bool(row[5]),
        last_login_at=row[6],
        _is_identity=True,
    )


def get_by_id(db: Session, user_id: str | int | UUID) -> User | UserRecord | None:
    """依主鍵取得使用者；不存在或已軟刪除時回傳 None。"""
    try:
        uuid_str = str(user_id)
        UUID(uuid_str)
        sql = text(f"{_IDENTITY_SELECT} WHERE a.user_id = :user_id")
        row = db.execute(sql, {"user_id": uuid_str}).fetchone()
        if row is not None:
            return _from_row(row)
    except Exception:
        pass

    try:
        int_id = int(user_id)
        return db.scalar(select(User).where(User.id == int_id, User.deleted_at.is_(None)))
    except Exception:
        return None


def _log_identity_failure(action: str, exc: Exception) -> None:
    """記錄身分表查詢失敗原因（只含例外類別與 SQLSTATE，不含 SQL 參數或連線字串）。"""
    orig = getattr(exc, "orig", None)
    logger.warning(
        "身分表查詢失敗（%s）：%s sqlstate=%s detail=%s",
        action,
        type(exc).__name__,
        getattr(orig, "sqlstate", None),
        str(orig).splitlines()[0] if orig is not None else None,
    )


def get_by_email(db: Session, email: str) -> User | UserRecord | None:
    """依 email 取得使用者（不分大小寫）；不存在或已軟刪除時回傳 None。"""
    normalized = email.strip().lower()
    try:
        sql = text(f"{_IDENTITY_SELECT} WHERE LOWER(a.email) = :email")
        row = db.execute(sql, {"email": normalized}).fetchone()
        if row is not None:
            return _from_row(row)
        logger.info("身分表查無此 email（account 不存在）")
    except Exception as exc:
        _log_identity_failure("get_by_email", exc)

    try:
        return db.scalar(select(User).where(User.email == normalized, User.deleted_at.is_(None)))
    except Exception:
        return None


def create(
    db: Session,
    *,
    email: str,
    password_hash: str,
    display_name: str,
    role: str = UserRole.USER.value,
) -> User:
    """建立新使用者（不自行 commit）。"""
    user = User(
        email=email.strip().lower(),
        password_hash=password_hash,
        display_name=display_name.strip(),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def update_last_login(db: Session, user: Any) -> None:
    """更新最後登入時間（不自行 commit）。

    雲端身分帳號（invoiceguard_identity.user_accounts）不在此寫入：本機 API 連的是正式 DB，
    AGENTS.md 規定未經明確授權不得修改正式資料；待核定寫入欄位與授權後再補。
    """
    if getattr(user, "_is_identity", False) or isinstance(getattr(user, "id", None), (str, UUID)):
        return
    user.last_login_at = datetime.now(UTC)
