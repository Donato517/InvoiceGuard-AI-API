"""
模組名稱：app.services.db_connection_service
功能說明：以 DB 模組執行唯讀 SELECT 1 連線檢查，控制 Session 的開啟與清理（與 ADMIN DB 模組相同）。
注意事項：所有查詢由 repository 執行；成功與失敗都 close（rollback），絕不 commit。
"""

from contextlib import suppress

from app.db.repositories import db_connection_repository as repository
from app.db.repositories.db_connection_repository import HealthCheckError

__all__ = ["HealthCheckError", "check_connection"]


def check_connection() -> int:
    """以 DB 模組的 Engine／Session 執行唯讀 SELECT 1 並回傳結果；失敗只拋出固定代碼。"""
    try:
        session = repository.open_session()
        try:
            return repository.ping(session)
        finally:
            # close 會 rollback 並歸還連線；清理失敗不可蓋掉原本的檢查結果。
            with suppress(Exception):
                session.close()
    except HealthCheckError:
        raise
    except Exception:
        raise HealthCheckError("query_failed") from None
