"""
模組名稱：app.db.repositories.user_repository
功能說明：登入用的帳號資料存取——invoiceguard_identity.user_accounts、public.user_profiles
    與 public.v_user_departments（v1.3；帳號與部門關聯由 ADMIN /accounts 維護）。
注意事項：
    - 資料表依 v1.3，本站尚無對應 ORM Model，以固定 SQL 存取，值一律綁定參數
      （與 ADMIN user_account_repository 相同做法）；不讀寫舊 ORM 的 public.users。
    - 只負責資料存取，不含商業邏輯，不自行 commit（交易由 service 控制）。
    - password_hash 只供 service 驗證密碼，不得回傳、記錄或輸出。
    - email 須由呼叫端先 strip／lower（DB CHECK 要求已正規化）。
"""

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

SELECT_LOGIN_ACCOUNT = text("""
    SELECT a.user_id, a.email, a.password_hash, a.account_status, a.credential_version,
           (a.locked_until IS NOT NULL AND a.locked_until > now()) AS is_locked,
           p.display_name,
           (p.user_id IS NOT NULL AND p.is_active AND p.resigned_at IS NULL) AS profile_active
    FROM invoiceguard_identity.user_accounts AS a
    LEFT JOIN public.user_profiles AS p ON p.user_id = a.user_id
    WHERE a.email = :email
""")
# v_user_departments 只列 active 帳號、啟用未離職 profile 的現行且啟用部門；is_primary 由主要部門推導
SELECT_DEPARTMENTS = text("""
    SELECT department_id, department_code, department_name, is_primary
    FROM public.v_user_departments
    WHERE user_id = :user_id
    ORDER BY is_primary DESC, department_code
""")
RECORD_LOGIN_SUCCESS = text("""
    UPDATE invoiceguard_identity.user_accounts
    SET last_login_at = now(), failed_login_count = 0
    WHERE user_id = :user_id
""")
RECORD_LOGIN_FAILURE = text("""
    UPDATE invoiceguard_identity.user_accounts
    SET failed_login_count = failed_login_count + 1
    WHERE user_id = :user_id
""")


@dataclass(frozen=True)
class LoginAccount:
    """登入驗證所需的帳號欄位；password_hash 不得離開 service。"""

    user_id: UUID
    email: str
    password_hash: str = field(repr=False)
    account_status: str
    credential_version: int
    is_locked: bool
    display_name: str | None
    profile_active: bool


@dataclass(frozen=True)
class DepartmentRow:
    """使用者目前所屬且啟用的部門。"""

    department_id: UUID
    department_code: str
    department_name: str
    is_primary: bool


def get_login_account(db: Session, email: str) -> LoginAccount | None:
    """依已正規化的 email 取得登入驗證所需欄位；不存在時回傳 None。"""
    row = db.execute(SELECT_LOGIN_ACCOUNT, {"email": email}).mappings().one_or_none()
    return LoginAccount(**row) if row else None


def list_departments(db: Session, user_id: UUID) -> list[DepartmentRow]:
    """列出使用者目前所屬且啟用的部門，主要部門排第一；帳號或 profile 不可用時為空。"""
    rows = db.execute(SELECT_DEPARTMENTS, {"user_id": user_id}).mappings()
    return [DepartmentRow(**row) for row in rows]


def record_login_success(db: Session, user_id: UUID) -> None:
    """登入成功：記錄 last_login_at 並將 failed_login_count 歸零（不提交交易）。"""
    db.execute(RECORD_LOGIN_SUCCESS, {"user_id": user_id})


def record_login_failure(db: Session, user_id: UUID) -> None:
    """密碼錯誤：failed_login_count 加 1（只記錄，不鎖定；不提交交易）。"""
    db.execute(RECORD_LOGIN_FAILURE, {"user_id": user_id})
