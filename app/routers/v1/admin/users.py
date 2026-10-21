"""
模組名稱：app.routers.v1.admin.users
功能說明：後台使用者管理 API。
路由前綴：/api/v1/admin/users
"""

from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["admin-users"])

# TODO(JerryChien): GET   /admin/users              使用者列表（分頁、搜尋）
# TODO(JerryChien): PATCH /admin/users/{id}/status  啟用 / 停用帳號（寫入 audit_logs）
