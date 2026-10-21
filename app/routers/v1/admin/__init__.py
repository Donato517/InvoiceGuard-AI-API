"""
模組名稱：app.routers.v1.admin
功能說明：後台（InvoiceGuard-AI-ADMIN）專用路由，彙整後以 /api/v1/admin 前綴掛載。
注意事項：
    - 此處所有路由都必須通過管理員權限檢查。
"""

from fastapi import APIRouter

from app.routers.v1.admin import invoices, system, users

# TODO(JerryChien): 加上 dependencies=[Depends(require_admin)]
router = APIRouter(prefix="/admin")
router.include_router(users.router)
router.include_router(invoices.router)
router.include_router(system.router)
