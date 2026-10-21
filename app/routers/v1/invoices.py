"""
模組名稱：app.routers.v1.invoices
功能說明：前台使用者的發票 API（只能存取自己的發票）。
路由前綴：/api/v1/invoices
"""

from fastapi import APIRouter

router = APIRouter(prefix="/invoices", tags=["invoices"])

# TODO(JerryChien): GET  /invoices               我的發票列表（分頁、依狀態篩選）
# TODO(JerryChien): GET  /invoices/{id}          發票詳情（含明細與 AI 分析結果）
# TODO(JerryChien): POST /invoices/upload        上傳發票圖檔 / PDF
# TODO(JerryChien): POST /invoices/{id}/analyze  重新觸發 AI 分析
