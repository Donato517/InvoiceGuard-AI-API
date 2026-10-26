"""模組名稱：tests.unit.test_db_connection_check；功能說明：以替身驗證 DB 模組的唯讀 SELECT 1 連線檢查（repository／service，與 ADMIN 相同），不連 DB。"""

from typing import Any
from unittest.mock import MagicMock, call

import pytest
from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.module_errors import ConfigurationIssue, ConfigurationReport, ModuleConfigurationError
from app.db.repositories import db_connection_repository as repository
from app.services import db_connection_service as service

SECRET = "synthetic-password-never-returned"


def test_service_runs_ping_returns_result_and_always_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    ping = MagicMock(return_value=1)
    monkeypatch.setattr(repository, "open_session", lambda: session)
    monkeypatch.setattr(repository, "ping", ping)
    assert service.check_connection() == 1
    ping.assert_called_once_with(session)
    session.close.assert_called_once()
    session.commit.assert_not_called()


def test_service_keeps_ping_error_when_close_also_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    session.close.side_effect = RuntimeError(SECRET)

    def fail(_: Any) -> None:
        raise repository.HealthCheckError("auth_failed")

    monkeypatch.setattr(repository, "open_session", lambda: session)
    monkeypatch.setattr(repository, "ping", fail)
    with pytest.raises(service.HealthCheckError) as caught:
        service.check_connection()
    assert caught.value.code == "auth_failed"
    session.close.assert_called_once()


def test_service_redacts_unexpected_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode() -> None:
        raise RuntimeError(SECRET)

    monkeypatch.setattr(repository, "open_session", explode)
    with pytest.raises(service.HealthCheckError) as caught:
        service.check_connection()
    assert caught.value.code == "query_failed"
    assert SECRET not in str(caught.value)


def test_open_session_uses_db_module_engine_and_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = object()
    factory = MagicMock()
    monkeypatch.setattr(repository, "get_engine", lambda: engine)
    monkeypatch.setattr(repository, "SessionLocal", factory)
    assert repository.open_session() is factory.return_value
    factory.assert_called_once_with(bind=engine)


def test_missing_database_url_reports_field_and_code_only() -> None:
    with pytest.raises(repository.HealthCheckError) as caught:
        repository.open_session()
    assert caught.value.code == "configuration_unavailable"
    assert "DATABASE_URL:required" in caught.value.issues


def test_open_session_issues_never_include_values(monkeypatch: pytest.MonkeyPatch) -> None:
    report = ConfigurationReport(
        "database",
        (
            ConfigurationIssue("DATABASE_URL", "unsupported_url_option", "固定訊息"),
            ConfigurationIssue("modules", "contracts_only", "固定訊息", "warning"),
        ),
    )

    def fail() -> None:
        raise ModuleConfigurationError(report)

    monkeypatch.setattr(repository, "get_engine", fail)
    with pytest.raises(repository.HealthCheckError) as caught:
        repository.open_session()
    assert caught.value.issues == ("DATABASE_URL:unsupported_url_option",)


def test_ping_connects_then_runs_only_read_only_select_one() -> None:
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = 1
    assert repository.ping(session) == 1
    session.connection.assert_called_once_with()
    statements = [str(item.args[0]) for item in session.execute.call_args_list]
    assert statements == [
        "SET TRANSACTION READ ONLY",
        "SET LOCAL statement_timeout = '4000ms'",
        "SELECT 1",
    ]
    session.commit.assert_not_called()
    assert session.mock_calls[0] == call.connection()


def query_error(state: str) -> DBAPIError:
    """帶 SQLSTATE 的合成查詢錯誤。"""
    original = Exception(SECRET)
    original.sqlstate = state  # type: ignore[attr-defined]
    return DBAPIError("SELECT 1", None, original)


@pytest.mark.parametrize("state,code", [("57014", "query_timeout"), ("42501", "query_failed")])
def test_ping_query_errors_use_sqlstate_only(state: str, code: str) -> None:
    session = MagicMock()
    session.execute.side_effect = query_error(state)
    with pytest.raises(repository.HealthCheckError) as caught:
        repository.ping(session)
    assert caught.value.code == code
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize(
    "message,code",
    [
        ('FATAL:  password authentication failed for user "u"', "auth_failed"),
        ("FATAL:  Tenant or user not found", "auth_failed"),
        ('FATAL:  role "u" does not exist', "auth_failed"),
        ('FATAL:  database "d" does not exist', "database_not_found"),
        ('FATAL:  no pg_hba.conf entry for host "1.2.3.4"', "access_denied"),
        (
            'could not translate host name "h" to address: Name or service not known',
            "host_not_found",
        ),
        ("connection to server failed: Network is unreachable", "network_unreachable"),
        ("connection timeout expired", "connect_timeout"),
        ("server does not support SSL, but SSL was required", "tls_failed"),
        ("FATAL:  sorry, too many connections already", "too_many_connections"),
        ("Connection refused", "db_unavailable"),
    ],
)
def test_connect_failures_map_to_fixed_codes_without_echo(message: str, code: str) -> None:
    session = MagicMock()
    session.connection.side_effect = OperationalError(None, None, Exception(message + SECRET))
    with pytest.raises(repository.HealthCheckError) as caught:
        repository.ping(session)
    assert caught.value.code == code
    assert SECRET not in str(caught.value)
    session.execute.assert_not_called()
