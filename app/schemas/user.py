"""
模組名稱：app.schemas.user
功能說明：使用者相關的請求 / 回應模型。
注意事項：
    - 回應模型禁止包含 password_hash 等敏感欄位。
"""

from datetime import datetime

from pydantic import Field

from app.schemas.common import ContractModel


class UserRead(ContractModel):
    """使用者讀取回應模型（禁止包含 password_hash 等敏感欄位）。"""

    id: str | int = Field(description="使用者 ID")
    email: str = Field(description="電子郵件")
    display_name: str = Field(description="顯示名稱")
    role: str = Field(description="角色：user / admin")
    is_active: bool = Field(description="是否啟用")
    last_login_at: datetime | None = Field(default=None, description="最後登入時間")


class UserStatusUpdate(ContractModel):
    """使用者狀態更新請求模型。"""

    is_active: bool = Field(description="是否啟用")
