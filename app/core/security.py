"""
模組名稱：app.core.security
功能說明：安全相關工具——Vercel Cron 請求驗證、JWT 簽發 / 驗證、密碼雜湊。
注意事項：
    - 比對密鑰一律使用 hmac.compare_digest，避免時序攻擊（timing attack）。
    - 密碼只存雜湊值，禁止以明碼或可逆加密儲存。
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Header

from app.core.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.module_errors import ModuleConfigurationError

logger = logging.getLogger(__name__)

# 嘗試載入 pwdlib，若不可用則優雅降級為內建 PBKDF2-HMAC-SHA256
try:
    from pwdlib import PasswordHash

    _pwdlib_hasher: PasswordHash | None = PasswordHash.recommended()
except (ImportError, Exception):  # pragma: no cover
    _pwdlib_hasher = None

_DEFAULT_LOCAL_JWT_SECRET = "invoiceguard-local-dev-jwt-secret-key-32chars-min"


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


# ---- 密碼雜湊與驗證 ----
def hash_password(password: str) -> str:
    """產生密碼雜湊。

    支援 pwdlib (Argon2) 或標準庫 PBKDF2-HMAC-SHA256 (600,000 次反覆)。
    """
    if _pwdlib_hasher is not None:
        try:
            return _pwdlib_hasher.hash(password)
        except Exception:  # pragma: no cover
            pass

    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 600_000)
    return f"pbkdf2:sha256:600000${salt}${derived.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """比對密碼與雜湊值是否相符。

    支援 PBKDF2-HMAC-SHA256 與 pwdlib (Argon2)。
    """
    if not password or not password_hash:
        return False

    if password_hash.startswith("pbkdf2:sha256:"):
        try:
            parts = password_hash.split("$")
            if len(parts) == 3:
                iterations = int(parts[0].split(":")[2])
                salt = parts[1].encode("utf-8")
                expected_hash = parts[2]
                calc = hashlib.pbkdf2_hmac(
                    "sha256", password.encode("utf-8"), salt, iterations
                ).hex()
                return hmac.compare_digest(calc, expected_hash)
        except Exception:
            return False

    if _pwdlib_hasher is not None:
        try:
            return _pwdlib_hasher.verify(password, password_hash)
        except Exception:
            return False

    return False


# ---- JWT Token 簽發與驗證 ----
def _get_jwt_secret() -> str:
    """取得 JWT 簽署金鑰；雲端環境強制驗證設定。"""
    if settings.is_vercel:
        try:
            settings.require_configuration("auth")
        except ModuleConfigurationError as exc:
            logger.warning("Auth 設定驗證失敗：%s", exc)
            raise UnauthorizedError("認證設定未就緒") from None
    secret = settings.JWT_SECRET_KEY.get_secret_value()
    if not secret:
        if settings.APP_ENV == "local":
            return _DEFAULT_LOCAL_JWT_SECRET
        raise UnauthorizedError("認證設定未就緒")
    return secret


def _base64url_encode(data: bytes) -> str:
    """Base64URL 編碼（去除 padding '='）。"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(encoded_str: str) -> bytes:
    """Base64URL 解碼（自動補回 padding '='）。"""
    padding = 4 - (len(encoded_str) % 4)
    if padding != 4:
        encoded_str += "=" * padding
    return base64.urlsafe_b64decode(encoded_str.encode("ascii"))


def create_access_token(
    subject: str,
    claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> tuple[str, int]:
    """建立符合 RFC 7519 規範的 HS256 JWT access token。

    Args:
        subject: 使用者識別 ID (sub)。
        claims: 額外攜帶之宣告欄位（如 email、role 等）。
        expires_delta: 有效時間長度；若無則依 settings.JWT_EXPIRE_MINUTES 計算。

    Returns:
        tuple[str, int]: (token 字串, 有效秒數)
    """
    secret = _get_jwt_secret()
    now = int(time.time())
    if expires_delta is not None:
        expires_in = int(expires_delta.total_seconds())
    else:
        expires_in = settings.JWT_EXPIRE_MINUTES * 60

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + expires_in,
    }
    if claims:
        payload.update(claims)

    header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    header_b64 = _base64url_encode(header_bytes)
    payload_b64 = _base64url_encode(payload_bytes)

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_b64 = _base64url_encode(signature)

    token = f"{header_b64}.{payload_b64}.{signature_b64}"
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    """驗證並解碼 HS256 JWT access token。

    Args:
        token: JWT 字串。

    Returns:
        dict[str, Any]: payload 資料。

    Raises:
        UnauthorizedError: 格式錯誤、簽章不符或已過期。
    """
    secret = _get_jwt_secret()
    parts = token.split(".")
    if len(parts) != 3:
        raise UnauthorizedError("無效的認證權杖")

    header_b64, payload_b64, signature_b64 = parts
    try:
        header_bytes = _base64url_decode(header_b64)
        header = json.loads(header_bytes.decode("utf-8"))
        if not isinstance(header, dict) or header.get("alg") != "HS256":
            raise UnauthorizedError("不支援的權杖演算法")

        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        provided_sig = _base64url_decode(signature_b64)

        if not hmac.compare_digest(expected_sig, provided_sig):
            raise UnauthorizedError("無效的認證權杖")

        payload_bytes = _base64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            raise UnauthorizedError("無效的認證權杖")

        exp = payload.get("exp")
        if isinstance(exp, (int, float)) and time.time() > exp:
            raise UnauthorizedError("認證權杖已過期")

        return payload
    except UnauthorizedError:
        raise
    except Exception as exc:
        logger.debug("解碼 JWT 失敗: %s", exc)
        raise UnauthorizedError("無效的認證權杖") from None
