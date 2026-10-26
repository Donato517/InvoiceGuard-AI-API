"""模組名稱：tests.unit.test_db_session；功能說明：以替身測試 Engine 參數及 Session 關閉，不連 DB。"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.module_errors import ModuleConfigurationError
from app.db import session


@pytest.fixture(autouse=True)
def clear_engine_cache() -> Iterator[None]:
    """避免替身 Engine 或設定跨測試共用。"""
    cached_get_engine = session._get_engine
    cached_get_engine.cache_clear()
    yield
    cached_get_engine.cache_clear()


def fake_cloud(**values: Any) -> Settings:
    """僅供參數驗證的假 DSN，不建立真實連線。"""
    defaults = {
        "VERCEL": "1",
        "VERCEL_ENV": "preview",
        "APP_ENV": "preview",
        "DATABASE_URL": "postgresql://user:synthetic@db.example.invalid:6543/test?sslmode=require",
    }
    return Settings(_env_file=None, _env_prefix="IG_UNIT_TEST_", **(defaults | values))


def test_local_mode_blocks_engine_before_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = MagicMock()
    monkeypatch.setattr(session, "settings", Settings(_env_file=None, _env_prefix="IG_UNIT_TEST_"))
    monkeypatch.setattr(session, "create_engine", factory)
    with pytest.raises(ModuleConfigurationError):
        session.get_engine()
    factory.assert_not_called()


@pytest.mark.parametrize("pool_mode", ["transaction", "session", "direct"])
def test_engine_tls_pooling_timeout_and_prepared_statements(
    monkeypatch: pytest.MonkeyPatch, pool_mode: str
) -> None:
    factory = MagicMock()
    monkeypatch.setattr(session, "settings", fake_cloud(DB_POOL_MODE=pool_mode))
    monkeypatch.setattr(session, "create_engine", factory)
    engine = session.get_engine()
    assert session.get_engine() is engine
    factory.assert_called_once()
    options = factory.call_args.kwargs
    assert options["poolclass"] is NullPool
    assert options["hide_parameters"] is True
    assert options["connect_args"]["sslmode"] == "require"
    assert options["connect_args"]["connect_timeout"] == 5
    assert ("prepare_threshold" in options["connect_args"]) == (pool_mode == "transaction")
    if pool_mode == "transaction":
        assert options["connect_args"]["prepare_threshold"] is None


def test_verify_full_is_never_downgraded(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = MagicMock()
    configuration = fake_cloud(DB_SSL_MODE="verify-full")
    monkeypatch.setattr(session, "settings", configuration)
    monkeypatch.setattr(session, "create_engine", factory)
    session.get_engine()
    assert factory.call_args.kwargs["connect_args"]["sslmode"] == "verify-full"


@pytest.mark.parametrize(
    "query,db_ssl_mode,expected",
    [
        ("", "require", "require"),
        ("?sslmode=verify-ca", "require", "verify-ca"),
        ("?sslmode=require", "verify-full", "verify-full"),
    ],
)
def test_resolve_ssl_mode_keeps_tls(
    monkeypatch: pytest.MonkeyPatch, query: str, db_ssl_mode: str, expected: str
) -> None:
    monkeypatch.setattr(session, "settings", fake_cloud(DB_SSL_MODE=db_ssl_mode))
    url = make_url("postgresql+psycopg://user:synthetic@db.example.invalid/test" + query)
    assert session.resolve_ssl_mode(url) == expected


@pytest.mark.parametrize(
    "query",
    ["?sslmode=disable", "?sslmode=allow", "?sslmode=prefer", "?sslmode=require&sslmode=disable"],
)
def test_resolve_ssl_mode_rejects_downgrade_without_echoing_url(
    monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    monkeypatch.setattr(session, "settings", fake_cloud())
    url = make_url("postgresql+psycopg://user:synthetic-password@db.example.invalid/test" + query)
    with pytest.raises(ValueError) as caught:
        session.resolve_ssl_mode(url)
    assert "synthetic-password" not in str(caught.value)


def test_cached_engine_does_not_bypass_runtime_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = MagicMock()
    configuration = fake_cloud()
    monkeypatch.setattr(session, "settings", configuration)
    monkeypatch.setattr(session, "create_engine", factory)
    session.get_engine()
    configuration.VERCEL = ""
    with pytest.raises(ModuleConfigurationError):
        session.get_engine()
    factory.assert_called_once()


def test_get_db_closes_session_without_committing(monkeypatch: pytest.MonkeyPatch) -> None:
    db = MagicMock()
    engine = object()
    factory = MagicMock(return_value=db)
    monkeypatch.setattr(session, "get_engine", lambda: engine)
    monkeypatch.setattr(session, "SessionLocal", factory)
    dependency = session.get_db()
    assert next(dependency) is db
    dependency.close()
    factory.assert_called_once_with(bind=engine)
    db.close.assert_called_once()
    db.commit.assert_not_called()


def test_get_db_closes_session_when_service_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    db = MagicMock()
    monkeypatch.setattr(session, "get_engine", lambda: object())
    monkeypatch.setattr(session, "SessionLocal", MagicMock(return_value=db))
    dependency = session.get_db()
    next(dependency)
    with pytest.raises(RuntimeError, match="合成測試錯誤"):
        dependency.throw(RuntimeError("合成測試錯誤"))
    db.close.assert_called_once()
    db.commit.assert_not_called()
