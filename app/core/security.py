"""
模組名稱：app.core.security
功能說明：安全相關工具——Vercel Cron 請求驗證、密碼雜湊、登入 Session Token 產生與摘要。
注意事項：
    - 比對密鑰一律使用 hmac.compare_digest，避免時序攻擊（timing attack）。
    - 密碼只存雜湊值，禁止以明碼或可逆加密儲存。
    - 密碼雜湊使用 pwdlib 建議設定（Argon2id），與 InvoiceGuard-AI-ADMIN 相同，
      兩站才能驗證同一份 invoiceguard_identity.user_accounts.password_hash。
    - Session Token 是不透明的隨機字串，只交給前台保存；DB 只存 SHA256 摘要（v1.3 user_sessions），
      不需要任何簽章金鑰。
"""

import hashlib
import hmac
import logging
import secrets
from typing import Annotated

from fastapi import Header
from pwdlib import PasswordHash

from app.core.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.module_errors import ModuleConfigurationError

logger = logging.getLogger(__name__)

_password_hash = PasswordHash.recommended()

# v1.3：原始 Token 由 CSPRNG 產生至少 32 bytes；摘要固定 32 bytes（session_token_digest CHECK）
SESSION_TOKEN_BYTES = 32


def verify_cron_secret(authorization: Annotated[str | None, Header()] = None) -> None:
    """驗證請求是否來自 Vercel Cron（作為 FastAPI 相依注入使用）。

    Vercel 呼叫排程端點時，會自動帶入 `Authorization: Bearer <CRON_SECRET>`。
    未設定 CRON_SECRET 時一律拒絕，避免排程端點被任意觸發。

    Args:
        authorization: HTTP Authorization 標頭。

    Raises:
        UnauthorizedError: 未帶密鑰或密鑰錯誤。
    """
    if settings.is_vercel:
        try:
            settings.require_configuration("cron")
        except ModuleConfigurationError as exc:
            # Vercel Cron 失敗不會重試；記錄欄位與代碼（不含設定值），否則只能從 401 推測原因
            logger.warning("Cron 設定驗證失敗，拒絕排程請求：%s", exc)
            raise UnauthorizedError("排程驗證失敗") from None
    secret = settings.CRON_SECRET.get_secret_value()
    expected = f"Bearer {secret}"
    received = authorization or ""
    if not secret or not hmac.compare_digest(received.encode(), expected.encode()):
        raise UnauthorizedError("排程驗證失敗")


# ---- 密碼 ----
def hash_password(password: str) -> str:
    """產生 Argon2id 密碼雜湊（完整 PHC 字串，含 salt 與參數）。"""
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """比對密碼與雜湊值是否相符。"""
    return _password_hash.verify(password, password_hash)


# ---- 登入 Session Token ----
def new_session_token() -> str:
    """產生新的登入 Session Token（32 bytes 隨機值的 URL-safe 字串）；只回傳給前台，不寫入 DB。"""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def session_token_digest(token: str) -> bytes:
    """計算 Session Token 的 SHA256 摘要（32 bytes）；DB 只存此值，用來查詢 Session。"""
    return hashlib.sha256(token.encode("utf-8")).digest()
