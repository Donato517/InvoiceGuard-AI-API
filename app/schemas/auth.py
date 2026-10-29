"""
模組名稱：app.schemas.auth
功能說明：登入相關的請求 / 回應模型（v1.3 Session：不透明 Token，DB 只存摘要）。
注意事項：
    - 回應不得包含 password_hash；session_token 只在登入回應出現一次，由前台存入 httpOnly cookie。
"""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.common import ContractModel


class LoginRequest(ContractModel):
    """登入請求模型。"""

    email: str = Field(min_length=3, max_length=320, description="登入電子郵件")
    password: str = Field(min_length=1, max_length=256, repr=False, description="密碼")


class DepartmentRead(ContractModel):
    """登入者目前所屬且啟用的部門。"""

    department_id: UUID = Field(description="部門 UUID")
    department_code: str = Field(description="部門代碼")
    department_name: str = Field(description="部門名稱")
    is_primary: bool = Field(description="是否為主要部門")


class SessionRead(ContractModel):
    """目前登入者與本次 Session 的部門情境（不含 Token 與密碼雜湊）。"""

    user_id: UUID = Field(description="使用者 UUID")
    email: str = Field(description="登入帳號（Email）")
    display_name: str = Field(description="顯示名稱")
    department: DepartmentRead = Field(description="本次 Session 的選取部門；登入時預設為主要部門")
    departments: tuple[DepartmentRead, ...] = Field(description="目前所屬且啟用的全部部門")
    expires_at: datetime = Field(description="Session 到期時間")


class LoginResponse(SessionRead):
    """登入成功回應：Session Token 與登入者資料。"""

    session_token: str = Field(repr=False, description="Session Token；放在 Authorization: Bearer")
    token_type: str = Field(default="bearer", description="權杖類型")
    expires_in: int = Field(description="Session 有效秒數")
