"""
模組名稱：app.main
功能說明：FastAPI 應用程式進入點；建立 app，註冊 middleware、例外處理與路由。
注意事項：
    - 本機啟動：uvicorn app.main:app --reload
    - Vercel 會自動偵測本檔的 `app` 物件作為 Serverless Function 進入點，
      函式設定（maxDuration 等）見 vercel.json → functions["app/main.py"]。
    - 本檔只做「組裝」，不放任何業務邏輯。
    - 呼叫端為前台網站的伺服器（server to server），瀏覽器不直接呼叫本 API，因此不設定 CORS。
"""

from fastapi import FastAPI

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging_config import setup_logging
from app.routers import cron, health, robots
from app.routers.v1 import api_router as v1_router

settings.require_environment()
setup_logging()

app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    # 正式環境不公開 API 文件
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

# ---- 例外處理 ----
register_exception_handlers(app)

# ---- 路由 ----
app.include_router(health.router)
app.include_router(robots.router)
app.include_router(v1_router, prefix="/api/v1")
app.include_router(cron.router, prefix="/api/cron")
