"""
模組名稱：app.core.exceptions
功能說明：定義業務例外類別，並註冊全域例外處理器，將所有錯誤轉為統一回應格式。
回應格式：{"error": {"code": "...", "message": "...", "details": ...}}
         （錯誤代碼一覽見 docs/API_CONVENTIONS.md）
注意事項：
    - service 層遇到可預期的錯誤時，拋出 AppError 子類別，不要直接組 HTTP 回應。
    - message 會直接顯示給使用者，請使用易懂的中文，不要放內部錯誤細節。
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """業務例外基底類別。子類別以 status_code / code 定義 HTTP 狀態與錯誤代碼。"""

    status_code: int = 400
    code: str = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None) -> None:
        """
        Args:
            message: 給使用者看的錯誤訊息。
            code: 覆寫預設錯誤代碼，例如 "INVOICE_DUPLICATED"。
            details: 額外資訊（例如欄位錯誤清單），需可轉為 JSON。
        """
        super().__init__(message)
        self.message = message
        self.details = details
        if code is not None:
            self.code = code


class UnauthorizedError(AppError):
    """未登入或憑證無效。"""

    status_code = 401
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    """已登入但沒有權限。"""

    status_code = 403
    code = "FORBIDDEN"


class NotFoundError(AppError):
    """資源不存在。"""

    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    """資料衝突，例如重複建立。"""

    status_code = 409
    code = "CONFLICT"


class ExternalServiceError(AppError):
    """第三方服務（AI、財政部平台等）呼叫失敗。"""

    status_code = 502
    code = "EXTERNAL_SERVICE_ERROR"


# 框架層 HTTP 錯誤對應的錯誤代碼（例如路由不存在 → NOT_FOUND）
_HTTP_STATUS_CODES = {
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
}


def _error_response(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    """組出統一格式的錯誤回應。"""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": jsonable_encoder(details)}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """在 FastAPI app 上註冊全域例外處理器（於 app.main 呼叫）。"""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(422, "VALIDATION_ERROR", "請求參數格式錯誤", exc.errors())

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_STATUS_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        return _error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # 未預期錯誤：完整堆疊寫入日誌，回應中不暴露內部細節
        logger.exception("未預期錯誤：%s %s", request.method, request.url.path)
        return _error_response(500, "INTERNAL_ERROR", "系統發生錯誤，請稍後再試")
