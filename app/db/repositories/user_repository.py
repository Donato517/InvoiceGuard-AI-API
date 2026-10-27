"""
模組名稱：app.db.repositories.user_repository
功能說明：users 資料表的資料存取（依 email 查詢、建立、更新最後登入時間）。
注意事項：
    - 只負責 ORM 操作，不含商業邏輯，不自行 commit（交易由 service 控制）。
    - 查詢預設排除軟刪除資料（deleted_at IS NULL）。
    - email 查詢前一律轉小寫，與寫入規則一致。
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.user import User, UserRole


def get_by_id(db: Session, user_id: int) -> User | None:
    """依主鍵取得使用者；不存在或已軟刪除時回傳 None。"""
    return db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))


def get_by_email(db: Session, email: str) -> User | None:
    """依 email 取得使用者（不分大小寫）；不存在或已軟刪除時回傳 None。"""
    normalized = email.strip().lower()
    return db.scalar(select(User).where(User.email == normalized, User.deleted_at.is_(None)))


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


def update_last_login(db: Session, user: User) -> None:
    """更新最後登入時間（不自行 commit）。"""
    user.last_login_at = datetime.now(UTC)
