"""
模組名稱：app.core.deps
功能說明：集中定義 FastAPI 相依注入（Depends）的型別別名，供 routers 使用。
使用方式：
    @router.get("/invoices")
    def list_invoices(db: DbSession) -> ...:
        ...
"""

import contextlib
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.module_errors import ModuleConfigurationError
from app.db.session import get_db

# 資料庫 Session：每個請求一個，請求結束自動關閉
DbSession = Annotated[Session, Depends(get_db)]


def get_optional_db() -> Iterator[Session | None]:
    """FastAPI 相依注入：取得資料庫 Session；未設定資料庫時回傳 None（支援無雲端 DB 的本機開發／示範模式）。"""
    try:
        gen = get_db()
        session = next(gen)
    except ModuleConfigurationError:
        yield None
        return
    except Exception:
        yield None
        return

    try:
        yield session
    finally:
        with contextlib.suppress(Exception):
            next(gen, None)


OptionalDbSession = Annotated[Session | None, Depends(get_optional_db)]
