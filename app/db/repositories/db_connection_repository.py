"""
模組名稱：app.db.repositories.db_connection_repository
功能說明：DB 模組的唯讀 SELECT 1 連線檢查；不讀任何資料表、不接受任意 SQL（與 ADMIN DB 模組相同）。
注意事項：交易由 service 控制；本模組不 commit，錯誤只回固定代碼，不含連線字串或驅動訊息。
"""

from typing import Literal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.module_errors import ModuleConfigurationError
from app.db.session import SessionLocal, get_engine

HealthCode = Literal[
    "configuration_unavailable",
    "auth_failed",
    "access_denied",
    "database_not_found",
    "host_not_found",
    "network_unreachable",
    "connect_timeout",
    "tls_failed",
    "too_many_connections",
    "db_unavailable",
    "query_timeout",
    "query_failed",
]


class HealthCheckError(RuntimeError):
    """連線檢查的固定代碼；issues 只含設定欄位與代碼，不含任何設定值。"""

    def __init__(self, code: HealthCode, issues: tuple[str, ...] = ()) -> None:
        self.code = code
        self.issues = issues
        super().__init__(code)


def open_session() -> Session:
    """沿用 DB 模組的 Engine 與 Session 工廠；設定不合格時只回報欄位與代碼。"""
    try:
        return SessionLocal(bind=get_engine())
    except ModuleConfigurationError as error:
        issues = tuple(
            f"{issue.field}:{issue.code}"
            for issue in error.report.issues
            if issue.severity == "error"
        )
        raise HealthCheckError("configuration_unavailable", issues) from None
    except (SQLAlchemyError, ValueError):
        raise HealthCheckError("configuration_unavailable") from None


def ping(session: Session) -> int:
    """建立連線後在唯讀交易執行 SELECT 1 並回傳結果；不讀取任何資料表、不接受外部 SQL。"""
    try:
        session.connection()
    except SQLAlchemyError as error:
        raise HealthCheckError(_connect_failure(error)) from None
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        session.execute(text("SET LOCAL statement_timeout = '4000ms'"))
        result = session.execute(text("SELECT 1")).scalar_one()
    except SQLAlchemyError as error:
        state = getattr(getattr(error, "orig", None), "sqlstate", None)
        # 僅使用 SQLSTATE 分類，從不轉字串、回傳 query、參數或原始例外。
        raise HealthCheckError(
            "query_timeout" if state in {"57014", "55P03"} else "query_failed"
        ) from None
    if result != 1:
        raise HealthCheckError("query_failed")
    return result


def _connect_failure(error: SQLAlchemyError) -> HealthCode:
    # 驅動訊息含主機與帳號名稱：只在此比對固定片段，絕不回傳、記錄或保存原文。
    message = str(getattr(error, "orig", None) or "").lower()
    if 'database "' in message and "does not exist" in message:
        return "database_not_found"
    if any(
        part in message
        for part in ("password authentication failed", "tenant or user not found", "does not exist")
    ):
        return "auth_failed"
    if "no pg_hba.conf entry" in message:
        return "access_denied"
    if any(
        part in message
        for part in ("could not translate host name", "name or service not known", "no such host")
    ):
        return "host_not_found"
    if any(part in message for part in ("network is unreachable", "cannot assign requested")):
        return "network_unreachable"
    if "timeout expired" in message or "timed out" in message:
        return "connect_timeout"
    if "ssl" in message:
        return "tls_failed"
    if any(
        part in message
        for part in ("too many connections", "remaining connection slots", "max client connections")
    ):
        return "too_many_connections"
    return "db_unavailable"
