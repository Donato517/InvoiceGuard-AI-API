"""模組名稱：app.routers.v1.showcase_references；功能說明：已登入使用者共用範例取用接口，不授予維護權。"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import Response

from app.core.deps import BearerToken, OptionalDbSession
from app.services import auth_service
from app.services import showcase_reference_service as service

router = APIRouter(prefix="/showcase-references", tags=["showcase-references"])


@router.get("")
def references(
    token: BearerToken, db: OptionalDbSession, tax_id: str, layout: str = ""
) -> list[dict[str, Any]]:
    """每次依既有 Session 核對有效帳號；不信任 caller 宣告的身分或部門。"""
    auth_service.resolve_session(db, token)
    return service.candidates(db, tax_id, layout)


@router.get("/{sample}/{revision}/file")
def reference_file(
    token: BearerToken, db: OptionalDbSession, sample: UUID, revision: UUID
) -> Response:
    """只讀當前啟用原圖，不提供歷史／草稿／測試檔案。"""
    auth_service.resolve_session(db, token)
    content, mime = service.source(db, sample, revision)
    return Response(
        content,
        media_type=mime,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
