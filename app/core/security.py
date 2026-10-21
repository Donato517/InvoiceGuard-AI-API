"""
模組名稱：app.core.security
功能說明：安全相關工具——Vercel Cron 請求驗證；（待實作）JWT 簽發 / 驗證、密碼雜湊。
注意事項：
    - 比對密鑰一律使用 hmac.compare_digest，避免時序攻擊（timing attack）。
    - 密碼只存雜湊值，禁止以明碼或可逆加密儲存。
"""

import hmac
from typing import Annotated

from fastapi import Header

from app.core.config import settings
from app.core.exceptions import UnauthorizedError


def verify_cron_secret(authorization: Annotated[str | None, Header()] = None) -> None:
    """驗證請求是否來自 Vercel Cron（作為 FastAPI 相依注入使用）。

    Vercel 呼叫排程端點時，會自動帶入 `Authorization: Bearer <CRON_SECRET>`。
    未設定 CRON_SECRET 時一律拒絕，避免排程端點被任意觸發。

    Args:
        authorization: HTTP Authorization 標頭。

    Raises:
        UnauthorizedError: 未帶密鑰或密鑰錯誤。
    """
    expected = f"Bearer {settings.CRON_SECRET}"
    received = authorization or ""
    if not settings.CRON_SECRET or not hmac.compare_digest(received.encode(), expected.encode()):
        raise UnauthorizedError("排程驗證失敗")


# TODO(JerryChien): create_access_token / decode_access_token（建議套件：PyJWT）
# TODO(JerryChien): hash_password / verify_password（建議套件：pwdlib[argon2]）
