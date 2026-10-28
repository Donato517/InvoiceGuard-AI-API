"""
模組名稱：app.routers.v1.auth
功能說明：供前台呼叫的登入／登出／目前使用者 API；ADMIN 使用自己的登入，不呼叫本 API。
路由前綴：/api/v1/auth
"""

from typing import Annotated

from fastapi import APIRouter, Header

from app.core.deps import OptionalDbSession
from app.core.exceptions import UnauthorizedError
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import UserRead
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: OptionalDbSession) -> TokenResponse:
    """帳號密碼登入，回傳 access token。"""
    return auth_service.authenticate(db, request.email, request.password)


@router.post("/logout")
def logout() -> dict[str, str]:
    """登出（客戶端清除 cookie 即可）。"""
    return {"status": "ok"}


@router.get("/me", response_model=UserRead)
def get_current_user(
    db: OptionalDbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> UserRead:
    """取得目前登入者資料。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError("未提供認證權杖")
    token = authorization.removeprefix("Bearer ").strip()
    return auth_service.get_current_user_profile(db, token)
