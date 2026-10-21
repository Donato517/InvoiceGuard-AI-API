"""
模組名稱：app.routers.v1.admin.invoices
功能說明：後台發票審核 API（可存取全部使用者的發票）。
路由前綴：/api/v1/admin/invoices
"""

from fastapi import APIRouter

router = APIRouter(prefix="/invoices", tags=["admin-invoices"])

# TODO(JerryChien): GET  /admin/invoices              全部發票列表（依狀態 / 風險分數篩選）
# TODO(JerryChien): GET  /admin/invoices/{id}         發票詳情
# TODO(JerryChien): POST /admin/invoices/{id}/review  人工複核（passed / rejected，寫入 audit_logs）
