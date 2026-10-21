"""
模組名稱：app.routers.v1.auth
功能說明：登入 / 登出 / 取得目前使用者。前台與後台共用。
路由前綴：/api/v1/auth
"""

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])

# TODO(JerryChien): POST /auth/login   帳號密碼登入，回傳 access token
# TODO(JerryChien): POST /auth/logout  登出
# TODO(JerryChien): GET  /auth/me      取得目前登入者資料
