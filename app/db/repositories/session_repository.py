"""
模組名稱：app.db.repositories.session_repository
功能說明：登入 Session 資料存取——invoiceguard_identity.user_sessions（v1.3）。
注意事項：
    - DB 只存 Session Token 的 SHA256 摘要（32 bytes），不存原始 Token。
    - 時間一律用 DB 的 now()，避免應用時鐘偏差違反 CHECK（v1.3 R3 建議）。
    - 以固定 SQL 存取，值一律綁定參數；只負責資料存取，不自行 commit（交易由 service 控制）。
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

INSERT_SESSION = text("""
    INSERT INTO invoiceguard_identity.user_sessions
        (user_id, session_token_digest, credential_version, selected_department_id, expires_at)
    VALUES (:user_id, :digest, :credential_version, :department_id,
            now() + make_interval(mins => :expire_minutes))
    RETURNING session_id, expires_at
""")
# v1.3 後續接線第 3 點：摘要、到期、撤銷、credential_version、帳號 active、profile 啟用未離職
SELECT_ACTIVE_SESSION = text("""
    SELECT s.session_id, s.user_id, s.selected_department_id, s.expires_at,
           a.email, p.display_name
    FROM invoiceguard_identity.user_sessions AS s
    JOIN invoiceguard_identity.user_accounts AS a
      ON a.user_id = s.user_id
     AND a.account_status = 'active'
     AND a.credential_version = s.credential_version
    JOIN public.user_profiles AS p
      ON p.user_id = s.user_id AND p.is_active AND p.resigned_at IS NULL
    WHERE s.session_token_digest = :digest
      AND s.revoked_at IS NULL
      AND s.expires_at > now()
""")
TOUCH_SESSION = text("""
    UPDATE invoiceguard_identity.user_sessions SET last_seen_at = now()
    WHERE session_id = :session_id
""")
REVOKE_SESSION = text("""
    UPDATE invoiceguard_identity.user_sessions SET revoked_at = GREATEST(now(), created_at)
    WHERE session_token_digest = :digest AND revoked_at IS NULL
""")


@dataclass(frozen=True)
class NewSession:
    """剛建立的 Session。"""

    session_id: UUID
    expires_at: datetime


@dataclass(frozen=True)
class ActiveSession:
    """通過到期／撤銷／憑證版本／帳號狀態核對的 Session 與登入者。"""

    session_id: UUID
    user_id: UUID
    selected_department_id: UUID | None
    expires_at: datetime
    email: str
    display_name: str


def create(
    db: Session,
    *,
    user_id: UUID,
    digest: bytes,
    credential_version: int,
    department_id: UUID,
    expire_minutes: int,
) -> NewSession:
    """新增一筆 Session（每次登入一筆，即登入紀錄）；不提交交易。"""
    params = {
        "user_id": user_id,
        "digest": digest,
        "credential_version": credential_version,
        "department_id": department_id,
        "expire_minutes": expire_minutes,
    }
    return NewSession(**db.execute(INSERT_SESSION, params).mappings().one())


def get_active(db: Session, digest: bytes) -> ActiveSession | None:
    """依 Token 摘要取得仍有效的 Session；無效、過期、已撤銷或帳號不可用時回傳 None。"""
    row = db.execute(SELECT_ACTIVE_SESSION, {"digest": digest}).mappings().one_or_none()
    return ActiveSession(**row) if row else None


def touch(db: Session, session_id: UUID) -> None:
    """記錄 Session 最後活動時間 last_seen_at；不提交交易。"""
    db.execute(TOUCH_SESSION, {"session_id": session_id})


def revoke(db: Session, digest: bytes) -> bool:
    """撤銷（登出）Session；回傳是否有撤銷到尚未撤銷的 Session。不提交交易。"""
    return db.execute(REVOKE_SESSION, {"digest": digest}).rowcount > 0
