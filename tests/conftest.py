"""
pytest 共用 fixture。
規則：
    - tests/unit/：不連資料庫、不呼叫外部服務，必要時以 monkeypatch 替換。
    - tests/integration/：需要測試資料庫（DATABASE_URL 指向測試庫），不可指向正式環境。
"""

import os
import socket
from contextvars import ContextVar
from typing import Any

import pytest
from fastapi.testclient import TestClient

# 在測試模組匯入 app 前清除已知繼承設定；只檢查名稱，不保存或列印原值。
_CONFIGURATION_NAMES = {
    "APP_NAME",
    "LOCAL_SECRET_FIELDS",
    "SUPABASE_SERVICE_ROLE_KEY",
    "GOOGLE_API_KEY",
    "VERCEL_TOKEN",
    "SESSION_SECRET_KEY",
    "APP_ENV",
    "DEBUG",
    "MODULE_BACKEND",
    "REMOTE_API_BASE_URL",
    "VERCEL",
    "VERCEL_ENV",
    "DATABASE_URL",
    "DATABASE_URL_UNPOOLED",
    "JWT_SECRET_KEY",
    "SESSION_EXPIRE_MINUTES",
    "CRON_SECRET",
    "AI_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "EINVOICE_APP_ID",
    "EINVOICE_API_KEY",
    "BLOB_READ_WRITE_TOKEN",
    "SUPABASE_URL",
    "SUPABASE_STORAGE_BUCKET",
    "SUPABASE_SECRET_KEY",
    "GEMINI_MODEL",
    "GROQ_API_KEY",
    "GROQ_DEFAULT_MODEL",
    "GROQ_ADVANCED_MODEL",
    "GOOGLE_CLOUD_PROJECT_ID",
    "GOOGLE_CLOUD_LOCATION",
    "DOCUMENT_AI_PROCESSOR_ID",
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "DB_POOL_MODE",
    "DB_SSL_MODE",
    "DB_CONNECT_TIMEOUT_SECONDS",
}
for _name in tuple(os.environ):
    if _name.upper() in _CONFIGURATION_NAMES:
        del os.environ[_name]


@pytest.fixture(autouse=True)
def block_external_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """單元測試禁止網路與真實 DB，只放行 Windows 程序內 socketpair 通道。"""
    import psycopg
    from sqlalchemy.engine import Engine

    original_connect = socket.socket.connect
    original_socketpair = socket.socketpair
    inside_socketpair: ContextVar[bool] = ContextVar("inside_socketpair", default=False)

    def deny_connection(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("單元測試禁止外部網路或真實資料庫連線")

    def guarded_connect(connection: socket.socket, address: Any) -> Any:
        if inside_socketpair.get() and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(connection, address)
        return deny_connection()

    def guarded_socketpair(*args: Any, **kwargs: Any) -> tuple[socket.socket, socket.socket]:
        token = inside_socketpair.set(True)
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            inside_socketpair.reset(token)

    monkeypatch.setattr(socket, "create_connection", deny_connection)
    monkeypatch.setattr(socket, "getaddrinfo", deny_connection)
    monkeypatch.setattr(socket, "socketpair", guarded_socketpair)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_connection)
    monkeypatch.setattr(socket.socket, "sendto", deny_connection)
    monkeypatch.setattr(Engine, "connect", deny_connection)
    monkeypatch.setattr(Engine, "raw_connection", deny_connection)
    monkeypatch.setattr(psycopg, "connect", deny_connection)
    monkeypatch.setattr(psycopg.Connection, "connect", deny_connection)
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", deny_connection)


@pytest.fixture
def client() -> TestClient:
    """API 測試用 client。"""
    from app.main import app

    return TestClient(app)
