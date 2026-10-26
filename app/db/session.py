"""
模組名稱：app.db.session
功能說明：建立 SQLAlchemy Engine 與 Session，並提供 FastAPI 相依注入用的 get_db()。
注意事項：
    - Vercel Serverless 執行個體生命週期短且數量會自動擴增，若應用端自行維持連線池，
      容易佔滿資料庫連線數。因此應用端使用 NullPool，連線池交給資料庫端的
      pooler 處理；transaction 模式停用 psycopg prepared statements。
    - Engine 採延遲建立：未設定 DATABASE_URL 時，不連資料庫的端點（如 /health）仍可運作。
    - 交易（commit / rollback）由 service 層控制。
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings

SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)

# 會加密連線的 sslmode；disable / allow / prefer 可能退回明文，一律拒絕
SAFE_SSL_MODES = frozenset({"require", "verify-ca", "verify-full"})


def resolve_ssl_mode(url: URL) -> str:
    """決定連線使用的 sslmode：URL 指定者優先；DB_SSL_MODE=verify-full 時一律 verify-full。

    應用程式 Engine 與 Alembic migration 共用此規則。

    Raises:
        ValueError: URL 指定了不加密或可退回明文的 sslmode（訊息不含連線字串）。
    """
    ssl_mode = url.query.get("sslmode", settings.DB_SSL_MODE)
    if ssl_mode not in SAFE_SSL_MODES:
        raise ValueError("資料庫連線必須使用 TLS")
    if settings.DB_SSL_MODE == "verify-full":
        return "verify-full"
    return ssl_mode


def get_engine() -> Engine:
    """每次先驗證 DB 連線設定，再取得延遲建立的 Engine 單例；不限制執行位置。"""
    settings.require_configuration("database")
    return _get_engine()


@lru_cache
def _get_engine() -> Engine:
    url = make_url(settings.sqlalchemy_database_url)
    connect_args: dict[str, object] = {
        "sslmode": resolve_ssl_mode(url),
        "connect_timeout": settings.DB_CONNECT_TIMEOUT_SECONDS,
    }
    if settings.DB_POOL_MODE == "transaction":
        connect_args["prepare_threshold"] = None
    return create_engine(url, poolclass=NullPool, hide_parameters=True, connect_args=connect_args)


def get_db() -> Iterator[Session]:
    """FastAPI 相依注入：每個請求一個 Session，請求結束時自動關閉。"""
    session = SessionLocal(bind=get_engine())
    try:
        yield session
    finally:
        session.close()
