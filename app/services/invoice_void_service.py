"""
模組名稱：app.services.invoice_void_service
功能說明：申請人自行作廢被財務退回（returned_to_applicant）的案件——圖片問題退回後的必經步驟，作廢後重新上傳建立新案件。
注意事項：
    - 只有原提交者（submitted_by＝登入者，案件部門＝目前選取部門）可作廢；其餘一律 404，不洩漏案件是否存在。
    - 只轉換狀態（returned_to_applicant → voided）並寫狀態歷程；不刪除、不修改案件資料、影像、辨識紀錄、
      退件項目與快照；不更動 reviewed_by／reviewed_at（申請人作廢不是財務審核）。
    - 與同案重送競爭時，兩者都先鎖定同一列案件並以條件更新，只有一方會成功，另一方得到 409。
    - 重複作廢回 409 INVOICE_NOT_RETURNED（已不是退回狀態）；新案件走一般首次提交，查重不計已作廢案件。
    - 這是「申請人自行作廢」，與 ADMIN 既有的管理端作廢流程分開，不改動後者。
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ServiceUnavailableError
from app.db.repositories import invoice_repository, resubmit_repository
from app.schemas.auth import SessionRead
from app.schemas.invoice_resubmit import InvoiceVoidRead, InvoiceVoidRequest

RETURNED_STATUS = "returned_to_applicant"
VOIDED_STATUS = "voided"
VOID_REASON = "申請人作廢"


def void_returned(
    db: Session | None, current: SessionRead, invoice_id: UUID, request: InvoiceVoidRequest
) -> InvoiceVoidRead:
    """原提交者作廢退回案件：條件更新狀態並寫歷程，同一個交易。

    Raises:
        NotFoundError: 案件不存在、不是本人提交或不屬於目前選取部門（回應相同）。
        ConflictError: 案件不是 returned_to_applicant（INVOICE_NOT_RETURNED，含已作廢）或輪次過期（RESUBMIT_ROUND_STALE）。
        ServiceUnavailableError: 資料庫未設定。
    """
    if db is None:
        raise ServiceUnavailableError("資料庫尚未設定，無法處理發票")
    try:
        row = resubmit_repository.get_own_invoice(
            db,
            invoice_id,
            user_id=current.user_id,
            department_id=current.department.department_id,
            lock=True,
        )
        if row is None:
            raise NotFoundError("找不到這張發票")
        if row["status"] != RETURNED_STATUS:
            raise ConflictError("案件目前不是退回申請人的狀態", code="INVOICE_NOT_RETURNED")
        if request.expected_round != row["submission_round"]:
            raise ConflictError(
                "案件已有較新的輪次，請重新讀取後再操作", code="RESUBMIT_ROUND_STALE"
            )
        voided_at = resubmit_repository.void_returned_invoice(
            db, invoice_id, submission_round=row["submission_round"]
        )
        if voided_at is None:
            raise ConflictError("案件狀態已被改變，請重新讀取", code="INVOICE_NOT_RETURNED")
        reason = VOID_REASON + (f"：{request.reason}" if request.reason else "")
        invoice_repository.insert_status_history(
            db,
            invoice_id,
            old_status=RETURNED_STATUS,
            new_status=VOIDED_STATUS,
            reason=reason,
            changed_by=current.user_id,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return InvoiceVoidRead(
        invoice_id=invoice_id,
        status=VOIDED_STATUS,
        submission_round=row["submission_round"],
        voided_at=voided_at,
    )
