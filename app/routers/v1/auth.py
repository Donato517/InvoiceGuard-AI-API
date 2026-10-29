"""
模組名稱：app.routers.v1.auth
功能說明：供前台呼叫的登入／登出／目前登入者 API；ADMIN 使用自己的登入，不呼叫本 API。
路由前綴：/api/v1/auth
注意事項：
    - 登入成功回傳 Session Token；之後的請求以 Authorization: Bearer 標頭帶入。
"""

from fastapi import APIRouter

from app.core.deps import BearerToken, OptionalDbSession
from app.schemas.auth import LoginRequest, LoginResponse, SessionRead
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: OptionalDbSession) -> LoginResponse:
    """Email＋密碼登入：建立 Session，回傳 Session Token、登入者與部門。"""
    return auth_service.login(db, request.email, request.password)


@router.post("/logout")
def logout(token: BearerToken, db: OptionalDbSession) -> dict[str, str]:
    """登出：撤銷目前的 Session Token。"""
    auth_service.logout(db, token)
    return {"status": "ok"}


@router.get("/me", response_model=SessionRead)
def get_current_session(token: BearerToken, db: OptionalDbSession) -> SessionRead:
    """取得目前登入者、選取部門與部門清單（每次都重新核對 Session）。"""
    return auth_service.resolve_session(db, token)
