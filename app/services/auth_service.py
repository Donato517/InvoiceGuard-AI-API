"""
模組名稱：app.services.auth_service
功能說明：前台登入、目前登入者與登出——驗證 Argon2id 密碼，建立、核對與撤銷 v1.3 user_sessions。
相依模組：app.db.repositories.user_repository、app.db.repositories.session_repository、app.core.security
注意事項：
    - 帳號不存在、密碼錯誤、帳號不可登入都回傳相同訊息，避免帳號被列舉。
    - 登入資格依 v1.3 後續接線第 2 點：帳號 active、未在 locked_until 期間、profile 啟用且未離職、
      有主要部門；Session 預設選取主要部門。功能權限（app_scope）於各功能操作時檢查，不是登入條件。
    - 每次請求依第 3 點重新核對 Session 摘要、到期、撤銷、credential_version、帳號／profile 及選取部門。
    - 原始 Session Token 只回傳給前台，DB 只存 SHA256 摘要；password_hash 不離開本模組。
"""

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ServiceUnavailableError, UnauthorizedError
from app.core.security import new_session_token, session_token_digest, verify_password
from app.db.repositories import session_repository, user_repository
from app.db.repositories.user_repository import DepartmentRow
from app.schemas.auth import DepartmentRead, LoginResponse, SessionRead

_LOGIN_FAILED = "帳號或密碼錯誤"
_SESSION_INVALID = "登入已失效，請重新登入"
_DB_UNAVAILABLE = "登入服務暫時無法使用，請稍後再試"


def login(db: Session | None, email: str, password: str) -> LoginResponse:
    """驗證 Email／密碼，成功時建立 Session（登入紀錄）並回傳 Token、登入者與部門。

    Args:
        db: 資料庫 Session；未設定資料庫時為 None。
        email: 使用者輸入之 email（本函式會 strip／lower）。
        password: 使用者輸入之密碼。

    Returns:
        LoginResponse: Session Token、有效時間、使用者 UUID／帳號／顯示名稱、選取部門與部門清單。

    Raises:
        UnauthorizedError: 帳號不存在、密碼錯誤或帳號不可登入（訊息相同以防列舉）。
        ServiceUnavailableError: 資料庫未設定。
    """
    db = _require_db(db)
    try:
        account = user_repository.get_login_account(db, email.strip().lower())
        if account is None:
            raise UnauthorizedError(_LOGIN_FAILED)
        if not verify_password(password, account.password_hash):
            user_repository.record_login_failure(db, account.user_id)
            db.commit()
            raise UnauthorizedError(_LOGIN_FAILED)
        if account.account_status != "active" or account.is_locked or not account.profile_active:
            raise UnauthorizedError(_LOGIN_FAILED)
        departments = user_repository.list_departments(db, account.user_id)
        primary = next((row for row in departments if row.is_primary), None)
        if primary is None:
            raise UnauthorizedError(_LOGIN_FAILED)

        token = new_session_token()
        session = session_repository.create(
            db,
            user_id=account.user_id,
            digest=session_token_digest(token),
            credential_version=account.credential_version,
            department_id=primary.department_id,
            expire_minutes=settings.SESSION_EXPIRE_MINUTES,
        )
        user_repository.record_login_success(db, account.user_id)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return LoginResponse(
        session_token=token,
        expires_in=settings.SESSION_EXPIRE_MINUTES * 60,
        user_id=account.user_id,
        email=account.email,
        display_name=account.display_name or "",
        department=_department(primary),
        departments=tuple(_department(row) for row in departments),
        expires_at=session.expires_at,
    )


def resolve_session(db: Session | None, token: str) -> SessionRead:
    """核對 Session Token，回傳目前登入者與選取部門，並記錄最後活動時間。

    Args:
        db: 資料庫 Session；未設定資料庫時為 None。
        token: 前台以 Authorization: Bearer 帶入的 Session Token。

    Returns:
        SessionRead: 使用者 UUID／帳號／顯示名稱、選取部門與部門清單、Session 到期時間。

    Raises:
        UnauthorizedError: Token 無效、過期、已登出、密碼已變更、帳號或選取部門已不可用。
        ServiceUnavailableError: 資料庫未設定。
    """
    db = _require_db(db)
    try:
        session = session_repository.get_active(db, session_token_digest(token))
        if session is None:
            raise UnauthorizedError(_SESSION_INVALID)
        departments = user_repository.list_departments(db, session.user_id)
        selected = next(
            (row for row in departments if row.department_id == session.selected_department_id),
            None,
        )
        if selected is None:
            raise UnauthorizedError(_SESSION_INVALID)
        session_repository.touch(db, session.session_id)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return SessionRead(
        user_id=session.user_id,
        email=session.email,
        display_name=session.display_name,
        department=_department(selected),
        departments=tuple(_department(row) for row in departments),
        expires_at=session.expires_at,
    )


def logout(db: Session | None, token: str) -> None:
    """撤銷 Session Token（登出）；Token 不存在或已撤銷時視為已登出，不回錯誤。

    Raises:
        ServiceUnavailableError: 資料庫未設定。
    """
    db = _require_db(db)
    try:
        session_repository.revoke(db, session_token_digest(token))
        db.commit()
    except Exception:
        db.rollback()
        raise


def _require_db(db: Session | None) -> Session:
    if db is None:
        raise ServiceUnavailableError(_DB_UNAVAILABLE)
    return db


def _department(row: DepartmentRow) -> DepartmentRead:
    return DepartmentRead(
        department_id=row.department_id,
        department_code=row.department_code,
        department_name=row.department_name,
        is_primary=row.is_primary,
    )
