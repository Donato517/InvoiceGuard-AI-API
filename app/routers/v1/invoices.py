"""
模組名稱：app.routers.v1.invoices
功能說明：前台使用者的發票 API——手機上傳流程（辨識、必填檢核、業務警示預覽、查重、送出）；提交者本人讀取詳情；列表尚未實作。
路由前綴：/api/v1/invoices
注意事項：
    - 全部需 Authorization: Bearer <session_token>，每次請求經 auth_service 重新核對 Session。
    - 流程：POST /recognize（影像 → 欄位與檢核提醒）→ 使用者核對 → POST /check-duplicate → POST /invoices 送出。
    - GET /{invoice_id} 只回本人提交的發票；不存在與非本人都回 404。
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, File, UploadFile, status

from app.core.deps import BearerToken, OptionalDbSession
from app.schemas.invoice_detail import InvoiceDetailRead
from app.schemas.invoice_upload import (
    DuplicateCheckRead,
    DuplicateCheckRequest,
    InvoiceRecognitionRead,
    InvoiceSubmitRead,
    InvoiceSubmitRequest,
    RequiredCheckRead,
    WarningCheckRead,
)
from app.services import (
    auth_service,
    invoice_detail_service,
    invoice_required_service,
    invoice_upload_service,
    invoice_warning_service,
)

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.post("/recognize", response_model=InvoiceRecognitionRead)
def recognize_invoice(
    token: BearerToken,
    db: OptionalDbSession,
    file: Annotated[UploadFile, File(description="發票影像或單頁 PDF（JPG／PNG／PDF，4 MB 以內）")],
) -> InvoiceRecognitionRead:
    """辨識發票影像或單頁 PDF：存入 invoices bucket、OCR、AI 整理欄位，回傳欄位、票面原文與檢核提醒。"""
    current = auth_service.resolve_session(db, token)
    # 多讀 1 byte 以判斷是否超過上限，不把過大的檔案整個讀進記憶體
    content = file.file.read(invoice_upload_service.MAX_FILE_BYTES + 1)
    return invoice_upload_service.recognize(
        db, current, content=content, content_type=file.content_type, filename=file.filename
    )


@router.post("/check-duplicate", response_model=DuplicateCheckRead)
def check_duplicate_invoice(
    request: DuplicateCheckRequest, token: BearerToken, db: OptionalDbSession
) -> DuplicateCheckRead:
    """查重：系統內是否已有相同字軌＋號碼＋賣方統編、未作廢的發票。"""
    auth_service.resolve_session(db, token)
    return invoice_upload_service.check_duplicate(db, request)


@router.post("/check-required", response_model=RequiredCheckRead)
def check_required_fields(
    body: Annotated[
        dict[str, Any], Body(description="核對頁目前的欄位值（同 POST /invoices，可缺漏）")
    ],
    token: BearerToken,
    db: OptionalDbSession,
) -> RequiredCheckRead:
    """必填欄位檢核：一次列出正式提交 InvoiceSubmitRequest 的所有必填缺漏；不寫入任何資料。

    required_complete=true 只代表沒有必填缺漏，格式與金額仍由正式提交（422）與檢核提醒處理。
    """
    auth_service.resolve_session(db, token)
    return invoice_required_service.check_required(body)


@router.post("/check-warnings", response_model=WarningCheckRead)
def check_invoice_warnings(
    body: Annotated[
        dict[str, Any],
        Body(description="核對頁目前的欄位值（同 POST /invoices，可缺漏或格式錯誤）"),
    ],
    token: BearerToken,
    db: OptionalDbSession,
) -> WarningCheckRead:
    """業務警示預覽：未來日期與金額一致性，規則與正式送出相同；只是提醒，不寫入任何資料，也不阻擋送出。"""
    auth_service.resolve_session(db, token)
    return invoice_warning_service.preview_warnings(body)


@router.post("", response_model=InvoiceSubmitRead, status_code=status.HTTP_201_CREATED)
def submit_invoice(
    request: InvoiceSubmitRequest, token: BearerToken, db: OptionalDbSession
) -> InvoiceSubmitRead:
    """送出核對後的發票：建立發票（待單位核准）並連結辨識時保存的影像。"""
    current = auth_service.resolve_session(db, token)
    return invoice_upload_service.submit(db, current, request)


@router.get("/{invoice_id}", response_model=InvoiceDetailRead)
def get_invoice(invoice_id: UUID, token: BearerToken, db: OptionalDbSession) -> InvoiceDetailRead:
    """發票詳情：提交者本人讀取已送出的表頭、明細、修改對照、檢核警示與目前影像中繼資料（唯讀）。"""
    current = auth_service.resolve_session(db, token)
    return invoice_detail_service.get_invoice_detail(db, current, invoice_id)


# TODO(JerryChien): GET  /invoices               我的發票列表（分頁、依狀態篩選）
