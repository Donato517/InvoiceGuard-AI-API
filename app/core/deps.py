"""
模組名稱：app.core.deps
功能說明：集中定義 FastAPI 相依注入（Depends）的型別別名，供 routers 使用。
使用方式：
    @router.get("/invoices")
    def list_invoices(db: DbSession) -> ...:
        ...
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db

# 資料庫 Session：每個請求一個，請求結束自動關閉
DbSession = Annotated[Session, Depends(get_db)]

# TODO(JerryChien): CurrentUser = Annotated[User, Depends(get_current_user)]（解析 JWT 取得登入者）
