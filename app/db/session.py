"""
模組名稱：app.db.session
功能說明：建立 SQLAlchemy Engine 與 Session，並提供 FastAPI 相依注入用的 get_db()。
注意事項：
    - Vercel Serverless 執行個體生命週期短且數量會自動擴增，若應用端自行維持連線池，
      容易佔滿資料庫連線數。因此應用端使用 NullPool，連線池交給資料庫端的
      pooler（Neon pooled 連線字串）處理。
    - Engine 採延遲建立：未設定 DATABASE_URL 時，不連資料庫的端點（如 /health）仍可運作。
    - 交易（commit / rollback）由 service 層控制。
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings

SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


@lru_cache
def get_engine() -> Engine:
    """取得 Engine 單例（第一次使用資料庫時才建立）。"""
    return create_engine(settings.sqlalchemy_database_url, poolclass=NullPool)


def get_db() -> Iterator[Session]:
    """FastAPI 相依注入：每個請求一個 Session，請求結束時自動關閉。"""
    session = SessionLocal(bind=get_engine())
    try:
        yield session
    finally:
        session.close()
