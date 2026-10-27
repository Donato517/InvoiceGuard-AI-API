"""
模組名稱：app.schemas.auth
功能說明：登入相關的請求 / 回應模型。
"""

from pydantic import Field

from app.schemas.common import ContractModel


class LoginRequest(ContractModel):
    """登入請求模型。"""

    email: str = Field(min_length=3, max_length=255, description="登入電子郵件")
    password: str = Field(min_length=1, max_length=128, repr=False, description="密碼")


class TokenResponse(ContractModel):
    """JWT 權杖回應模型。"""

    access_token: str = Field(description="JWT Access Token")
    token_type: str = Field(default="bearer", description="權杖類型")
    expires_in: int = Field(description="權杖有效秒數")
