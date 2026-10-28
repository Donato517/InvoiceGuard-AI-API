"""
模組名稱：app.services.auth_service
功能說明：登入驗證、簽發 token、更新最後登入時間。
相依模組：app.db.repositories.user_repository、app.core.security
注意事項：
    - 帳號不存在與密碼錯誤回傳相同訊息，避免帳號被列舉。
"""

import logging

from sqlalchemy.orm import Session

from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    verify_password,
)
from app.db.repositories import user_repository
from app.schemas.auth import TokenResponse
from app.schemas.user import UserRead

logger = logging.getLogger(__name__)


def authenticate(db: Session | None, email: str, password: str) -> TokenResponse:
    """驗證使用者帳號密碼，成功時簽發 JWT access token。

    Args:
        db: 資料庫 Session。
        email: 使用者輸入之 email。
        password: 使用者輸入之密碼。

    Returns:
        TokenResponse: 包含 access_token, token_type, expires_in。

    Raises:
        UnauthorizedError: 帳號不存在、密碼錯誤或已停用（訊息相同以防列舉）。
    """
    if db is None:
        raise UnauthorizedError("帳號或密碼錯誤")

    normalized_email = email.strip().lower()
    user = user_repository.get_by_email(db, normalized_email)

    if user is None or not verify_password(password, user.password_hash):
        raise UnauthorizedError("帳號或密碼錯誤")

    if not user.is_active:
        raise UnauthorizedError("帳號或密碼錯誤")

    user_repository.update_last_login(db, user)
    try:
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

    user_id: str | int = user_id_raw
    try:
        user_id = int(user_id_raw)
    except (ValueError, TypeError):
        user_id = str(user_id_raw)

    if db is None:
        raise UnauthorizedError("使用者不存在或已停用")

    user = user_repository.get_by_id(db, user_id)
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
