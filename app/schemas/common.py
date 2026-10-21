"""
模組名稱：app.schemas.common
功能說明：跨模組共用的請求 / 回應模型——分頁參數、分頁結果、錯誤格式。
注意事項：
    - 格式定義與 docs/API_CONVENTIONS.md 一致，修改時兩邊同步。
"""

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """錯誤內容。code 供程式判斷，message 供畫面顯示。"""

    code: str
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    """統一錯誤回應格式（用於 OpenAPI 文件標示 responses）。"""

    error: ErrorDetail


class PageQuery(BaseModel):
    """分頁查詢參數。"""

    page: int = Field(default=1, ge=1, description="頁碼，從 1 開始")
    page_size: int = Field(default=20, ge=1, le=100, description="每頁筆數，上限 100")


class Page[T](BaseModel):
    """分頁回應格式：{items, total, page, page_size}。"""

    items: list[T]
    total: int
    page: int
    page_size: int
