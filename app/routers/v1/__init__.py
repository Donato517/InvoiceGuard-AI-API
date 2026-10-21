"""
模組名稱：app.routers.v1
功能說明：彙整 v1 版所有路由，於 app.main 以 /api/v1 前綴掛載。
注意事項：
    - 新增路由模組後，必須在此 include_router。
"""

from fastapi import APIRouter

from app.routers.v1 import auth, invoices
from app.routers.v1.admin import router as admin_router

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(invoices.router)
api_router.include_router(admin_router)
