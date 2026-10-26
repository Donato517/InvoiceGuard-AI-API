"""
模組名稱：app.routers.health
功能說明：健康檢查端點，供部署驗證與外部監控使用。
路由：GET /health
"""

from fastapi import APIRouter, Response

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health", summary="健康檢查")
def health(response: Response) -> dict[str, str]:
    """確認服務存活。不連線資料庫，避免資料庫異常時誤判服務整體掛掉。"""
    response.headers["X-InvoiceGuard-Service"] = "InvoiceGuard-AI-API"
    return {"status": "ok", "env": settings.APP_ENV}
