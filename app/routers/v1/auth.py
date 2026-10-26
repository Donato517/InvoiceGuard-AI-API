"""
模組名稱：app.routers.v1.auth
功能說明：供前台呼叫的登入／登出／目前使用者 API TODO 骨架；ADMIN 使用自己的登入，不呼叫本 API。
路由前綴：/api/v1/auth
"""

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])

# TODO(JerryChien): POST /auth/login   帳號密碼登入，回傳 access token
# TODO(JerryChien): POST /auth/logout  登出
# TODO(JerryChien): GET  /auth/me      取得目前登入者資料
