"""
模組名稱：app.services.auth_service
功能說明：登入驗證、簽發 token、更新最後登入時間。
相依模組：app.db.repositories.user_repository、app.core.security
注意事項：
    - 帳號不存在與密碼錯誤回傳相同訊息，避免帳號被列舉。
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.models.user import User, UserRole
from app.db.repositories import user_repository
from app.schemas.auth import TokenResponse
from app.schemas.user import UserRead

logger = logging.getLogger(__name__)

# 本機開發／示範模式之預設測試帳號
_DEMO_USERS: dict[str, dict[str, Any]] = {
    "user@example.com": {
        "id": 1,
        "email": "user@example.com",
        "password": "password",
        "display_name": "一般使用者",
        "role": UserRole.USER.value,
        "is_active": True,
    },
    "buyer@example.com": {
        "id": 2,
        "email": "buyer@example.com",
        "password": "password",
        "display_name": "採購同仁",
        "role": UserRole.USER.value,
        "is_active": True,
    },
    "admin@example.com": {
        "id": 3,
        "email": "admin@example.com",
        "password": "password",
        "display_name": "系統管理員",
        "role": UserRole.ADMIN.value,
        "is_active": True,
    },
}


def _create_demo_user(data: dict[str, Any]) -> User:
    """產生本機示範使用者物件。"""
    return User(
        id=data["id"],
        email=data["email"],
        password_hash=hash_password(data["password"]),
        display_name=data["display_name"],
        role=data["role"],
        is_active=data["is_active"],
    )


def _find_demo_user_by_email(email: str) -> User | None:
    normalized = email.strip().lower()
    data = _DEMO_USERS.get(normalized)
    if data is None:
        return None
    return _create_demo_user(data)


def _find_demo_user_by_id(user_id: int) -> User | None:
    for data in _DEMO_USERS.values():
        if data["id"] == user_id:
            return _create_demo_user(data)
    return None


def authenticate(db: Session | None, email: str, password: str) -> TokenResponse:
    """驗證使用者帳號密碼，成功時簽發 JWT access token。

    Args:
        db: 資料庫 Session（未連線或無雲端 DB 時為 None）。
        email: 使用者輸入之 email。
        password: 使用者輸入之密碼。

    Returns:
        TokenResponse: 包含 access_token, token_type, expires_in。

    Raises:
        UnauthorizedError: 帳號不存在、密碼錯誤或已停用（訊息相同以防列舉）。
    """
    normalized_email = email.strip().lower()
    user: User | None = None

    if db is not None:
        try:
            user = user_repository.get_by_email(db, normalized_email)
        except Exception as exc:
            logger.warning("資料庫查詢使用者失敗: %s", exc)

    if user is None:
        user = _find_demo_user_by_email(normalized_email)

    if user is None or not verify_password(password, user.password_hash):
        raise UnauthorizedError("帳號或密碼錯誤")

    if not user.is_active:
        raise UnauthorizedError("帳號或密碼錯誤")

    # 若為資料庫真實使用者，更新最後登入時間並提交交易
    if db is not None and user.id not in {1, 2, 3}:
        try:
            user_repository.update_last_login(db, user)
            db.commit()
        except Exception as exc:
            logger.warning("更新使用者登入時間失敗: %s", exc)
            db.rollback()

    token, expires_in = create_access_token(
        subject=str(user.id),
        claims={
            "email": user.email,
            "role": user.role,
            "display_name": user.display_name,
        },
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in,
    )


def get_current_user_profile(db: Session | None, token: str) -> UserRead:
    """從 access token 解析使用者資訊並回傳公開資料模型。

    Args:
        db: 資料庫 Session。
        token: JWT 字串。

    Returns:
        UserRead: 使用者公開資訊（不含 password_hash 等機密）。

    Raises:
        UnauthorizedError: 權杖無效、已過期或使用者不存在。
    """
    payload = decode_access_token(token)
    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise UnauthorizedError("無效的認證權杖")

    try:
        user_id = int(user_id_raw)
    except (ValueError, TypeError):
        raise UnauthorizedError("無效的認證權杖") from None

    user: User | None = None
    if db is not None:
        try:
            user = user_repository.get_by_id(db, user_id)
        except Exception as exc:
            logger.warning("資料庫依 ID 查詢使用者失敗: %s", exc)

    if user is None:
        user = _find_demo_user_by_id(user_id)

    if user is None or not user.is_active:
        raise UnauthorizedError("使用者不存在或已停用")

    return UserRead(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
    )
