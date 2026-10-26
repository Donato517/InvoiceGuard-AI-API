"""模組名稱：app.schemas.common；功能說明：共用契約、分頁及內部授權上下文。"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictInt, model_validator

# PostgreSQL BIGINT 上限；超過者在驗證階段拒絕，不留到資料庫才失敗
MAX_BIGINT = 2**63 - 1
# 分頁頁碼上限，避免過深分頁造成 OFFSET 溢位或大量掃描
MAX_PAGE = 10_000


class ErrorDetail(BaseModel):
    """保留既有 API 錯誤格式。code 供程式判斷，message 供畫面顯示。"""

    code: str
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    """統一錯誤回應格式，與既有 HTTP 契約相容。"""

    error: ErrorDetail


def reject_bool_and_float(value: Any) -> Any:
    """整數欄位接受整數或 HTTP query / path 的數字字串，但不接受布林與浮點數。"""
    if isinstance(value, (bool, float)):
        raise ValueError("需為整數")
    return value


# HTTP query / path 的值一律是字串，StrictInt 會全部拒絕；改以前置驗證排除布林與浮點數
RecordId = Annotated[int, BeforeValidator(reject_bool_and_float), Field(gt=0, le=MAX_BIGINT)]
Version = Annotated[int, BeforeValidator(reject_bool_and_float), Field(gt=0, le=MAX_BIGINT)]
PageNumber = Annotated[int, BeforeValidator(reject_bool_and_float), Field(ge=1, le=MAX_PAGE)]
PageSize = Annotated[int, BeforeValidator(reject_bool_and_float), Field(ge=1, le=100)]


class ContractModel(BaseModel):
    """拒絕未核定欄位並禁止原地修改；不得加入密鑰欄位。"""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class PageQuery(ContractModel):
    """分頁大小有界，不能傳入原始 SQL、資料表名稱或任意排序字串。"""

    page: PageNumber = 1
    page_size: PageSize = 20


class Page[T](ContractModel):
    """泛型分頁結果。"""

    items: tuple[T, ...]
    total: Annotated[StrictInt, Field(ge=0)]
    page: Annotated[StrictInt, Field(ge=1)]
    page_size: Annotated[StrictInt, Field(ge=1, le=100)]

    @model_validator(mode="after")
    def validate_item_count(self) -> "Page[T]":
        """防止頁面內容超出宣告的頁數或總數。"""
        if len(self.items) > min(self.page_size, self.total):
            raise ValueError("分頁內容超出宣告的筆數")
        return self


class Permission(StrEnum):
    """將來須由雲端登入及權限服務核發，不能從請求 JSON 自行宣告。"""

    FILE_READ = "files:read"
    FILE_WRITE = "files:write"
    INVOICE_READ = "invoices:read"
    INVOICE_WRITE = "invoices:write"


@dataclass(frozen=True)
class OperationContext:
    """內部已驗證身分的契約，並非驗證器，也不是 HTTP 輸入模型。

    未來只能由真實登入／權限相依建立；本階段沒有授權或部門權限實作。
    """

    actor_id: int
    allowed_owner_ids: frozenset[int]
    permissions: frozenset[Permission]
