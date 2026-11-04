"""
模組名稱：app.db.repositories.resubmit_repository
功能說明：同案重送所需的資料存取——鎖定本人案件、冪等紀錄、退件項目、上一輪快照、新輪次寫入、
    欄位覆核與承接前輪確認。
注意事項：
    - 資料表由 Migration 7c1d4e9a2b30 新增（invoice_return_items、invoice_submission_snapshots、
      invoice_resubmissions、invoice_field_review_carryovers、invoice_changes.event_seq）；Migration 尚未套用的資料庫
      呼叫這些函式會失敗，由 service 的交易整體 rollback。
    - repository 不 commit；交易由 service 控制。
    - SQL 文字不可出現「冒號+名稱」的 JSON 寫法（會被當成綁定參數），JSON 一律用 CAST(:x AS jsonb) 傳入。
"""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.repositories.invoice_repository import InvoiceHeader

_INVOICE_COLUMNS = """
    invoice_id, status, submission_round, submitted_at, submitted_by, invoice_track, invoice_number,
    invoice_date, tax_period, seller_tax_id, seller_name, buyer_tax_id, buyer_name, tax_type,
    sales_amount, tax_amount, total_amount, total_amount_zh, validation_results
"""
SELECT_OWN_INVOICE = text(f"""
    SELECT {_INVOICE_COLUMNS} FROM public.invoices
    WHERE invoice_id = :invoice_id AND submitted_by = :user_id AND department_id = :department_id
""")
LOCK_OWN_INVOICE = text(f"""
    SELECT {_INVOICE_COLUMNS} FROM public.invoices
    WHERE invoice_id = :invoice_id AND submitted_by = :user_id AND department_id = :department_id
    FOR UPDATE
""")
SELECT_IDEMPOTENT = text("""
    SELECT request_fingerprint, from_round, to_round, result
    FROM public.invoice_resubmissions
    WHERE invoice_id = :invoice_id AND requested_by = :user_id AND idempotency_key = :key
""")
SELECT_ITEMS = text("""
    SELECT item_id, line_no, item_name, quantity, unit_price, line_amount
    FROM public.invoice_items WHERE invoice_id = :invoice_id ORDER BY line_no
""")
SELECT_OPEN_RETURN_ITEMS = text("""
    SELECT return_item_id, item_kind, field_scope, item_id, field_name, reason, allowed_fields, status
    FROM public.invoice_return_items
    WHERE invoice_id = :invoice_id AND submission_round = :submission_round AND status = 'open'
    ORDER BY created_at, return_item_id
""")
SELECT_RETURN_ORIGIN = text("""
    SELECT old_status FROM public.invoice_status_history
    WHERE invoice_id = :invoice_id AND new_status = 'returned_to_applicant'
    ORDER BY changed_at DESC, history_id DESC LIMIT 1
""")
SELECT_CURRENT_FILE_ID = text("""
    SELECT file_id FROM public.invoice_files WHERE invoice_id = :invoice_id AND is_current = true
""")
SELECT_SNAPSHOT_EXISTS = text("""
    SELECT 1 FROM public.invoice_submission_snapshots
    WHERE invoice_id = :invoice_id AND submission_round = :submission_round
""")
INSERT_SNAPSHOT = text("""
    INSERT INTO public.invoice_submission_snapshots
        (invoice_id, submission_round, submission_kind, header, items, validation_results,
         file_id, submitted_by, submitted_at)
    VALUES (:invoice_id, :submission_round, :kind, CAST(:header AS jsonb), CAST(:items AS jsonb),
            CAST(:validation_results AS jsonb), :file_id, :submitted_by, :submitted_at)
""")
UPDATE_INVOICE = text("""
    UPDATE public.invoices SET
        invoice_track = :invoice_track, invoice_number = :invoice_number, invoice_date = :invoice_date,
        tax_period = :tax_period, seller_tax_id = :seller_tax_id, seller_name = :seller_name,
        buyer_tax_id = :buyer_tax_id, buyer_name = :buyer_name, tax_type = :tax_type,
        sales_amount = :sales_amount, tax_amount = :tax_amount, total_amount = :total_amount,
        total_amount_zh = :total_amount_zh, validation_results = CAST(:validation_results AS jsonb),
        submission_round = :new_round, status = :status, submitted_at = clock_timestamp(),
        updated_at = now()
    WHERE invoice_id = :invoice_id AND status = 'returned_to_applicant'
      AND submission_round = :old_round
    RETURNING submitted_at
""")
UPDATE_ITEM = text("""
    UPDATE public.invoice_items
    SET item_name = :item_name, quantity = :quantity, unit_price = :unit_price,
        line_amount = :line_amount, updated_at = now()
    WHERE item_id = :item_id AND invoice_id = :invoice_id
""")
INSERT_CHANGE = text("""
    INSERT INTO public.invoice_changes
        (invoice_id, item_id, submission_round, field_name, old_value, new_value, change_source,
         changed_by, changed_at, event_seq)
    VALUES (:invoice_id, :item_id, :submission_round, :field_name, CAST(:old_value AS jsonb),
            CAST(:new_value AS jsonb), 'user', :changed_by, clock_timestamp(), :event_seq)
""")
SELECT_LATEST_REVIEWS = text("""
    SELECT DISTINCT ON (field_scope, item_id, field_name)
        field_review_id, submission_round, field_scope, item_id, field_name, is_checked,
        checked_by, checked_at, ai_original_value
    FROM public.invoice_field_reviews
    WHERE invoice_id = :invoice_id AND submission_round < :new_round
    ORDER BY field_scope, item_id, field_name, submission_round DESC
""")
INSERT_REVIEW = text("""
    INSERT INTO public.invoice_field_reviews
        (invoice_id, submission_round, field_scope, item_id, field_name, ai_original_value,
         submitted_value)
    VALUES (:invoice_id, :submission_round, :field_scope, :item_id, :field_name,
            CAST(:ai_original_value AS jsonb), CAST(:submitted_value AS jsonb))
""")
INSERT_CARRYOVER = text("""
    INSERT INTO public.invoice_field_review_carryovers
        (invoice_id, submission_round, field_scope, item_id, field_name, source_field_review_id)
    VALUES (:invoice_id, :submission_round, :field_scope, :item_id, :field_name, :source_id)
""")
RESPOND_RETURN_ITEM = text("""
    UPDATE public.invoice_return_items
    SET status = :status, response_action = :action, response_note = :note,
        responded_by = :user_id, responded_at = now(), response_round = :response_round
    WHERE return_item_id = :return_item_id AND invoice_id = :invoice_id AND status = 'open'
    RETURNING return_item_id
""")
INSERT_RESUBMISSION = text("""
    INSERT INTO public.invoice_resubmissions
        (invoice_id, idempotency_key, request_fingerprint, from_round, to_round, requested_by, result)
    VALUES (:invoice_id, :key, :fingerprint, :from_round, :to_round, :user_id, CAST(:result AS jsonb))
""")


VOID_RETURNED = text("""
    UPDATE public.invoices SET status = 'voided', updated_at = now()
    WHERE invoice_id = :invoice_id AND status = 'returned_to_applicant'
      AND submission_round = :submission_round
    RETURNING updated_at
""")


def void_returned_invoice(
    db: Session, invoice_id: UUID, *, submission_round: int
) -> datetime | None:
    """以「狀態仍是 returned_to_applicant 且輪次相符」為條件轉為 voided；不碰 reviewed_by／reviewed_at；條件不符回 None。"""
    params = {"invoice_id": invoice_id, "submission_round": submission_round}
    return db.execute(VOID_RETURNED, params).scalar_one_or_none()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def get_own_invoice(
    db: Session, invoice_id: UUID, *, user_id: UUID, department_id: UUID, lock: bool
) -> dict[str, Any] | None:
    """讀取（可選 FOR UPDATE 鎖定）本人提交、屬於目前選取部門的案件；否則回 None（不可區分）。"""
    params = {"invoice_id": invoice_id, "user_id": user_id, "department_id": department_id}
    row = db.execute(LOCK_OWN_INVOICE if lock else SELECT_OWN_INVOICE, params).mappings().first()
    return dict(row) if row else None


def get_idempotent(
    db: Session, invoice_id: UUID, *, user_id: UUID, key: UUID
) -> dict[str, Any] | None:
    """依（案件、操作者、冪等鍵）讀取已處理的重送紀錄。"""
    params = {"invoice_id": invoice_id, "user_id": user_id, "key": key}
    row = db.execute(SELECT_IDEMPOTENT, params).mappings().first()
    return dict(row) if row else None


def list_items(db: Session, invoice_id: UUID) -> list[dict[str, Any]]:
    """依 line_no 讀取明細（含 item_id）。"""
    return [dict(r) for r in db.execute(SELECT_ITEMS, {"invoice_id": invoice_id}).mappings().all()]


def list_open_return_items(
    db: Session, invoice_id: UUID, *, submission_round: int
) -> list[dict[str, Any]]:
    """讀取指定輪次尚未回覆（open）的結構化退件項目。"""
    params = {"invoice_id": invoice_id, "submission_round": submission_round}
    return [dict(r) for r in db.execute(SELECT_OPEN_RETURN_ITEMS, params).mappings().all()]


def get_return_origin_status(db: Session, invoice_id: UUID) -> str | None:
    """最近一次退回申請人的歷程列所記錄的來源狀態（old_status）；沒有紀錄回 None。"""
    return db.execute(SELECT_RETURN_ORIGIN, {"invoice_id": invoice_id}).scalar_one_or_none()


def get_current_file_id(db: Session, invoice_id: UUID) -> UUID | None:
    """目前影像檔的 file_id（快照以參照保存，不複製影像）。"""
    return db.execute(SELECT_CURRENT_FILE_ID, {"invoice_id": invoice_id}).scalar_one_or_none()


def snapshot_exists(db: Session, invoice_id: UUID, submission_round: int) -> bool:
    """指定輪次是否已有完整提交快照。"""
    params = {"invoice_id": invoice_id, "submission_round": submission_round}
    return db.execute(SELECT_SNAPSHOT_EXISTS, params).first() is not None


def insert_snapshot(
    db: Session,
    invoice_id: UUID,
    *,
    submission_round: int,
    kind: str,
    header: dict[str, Any],
    items: list[dict[str, Any]],
    validation_results: dict[str, Any],
    file_id: UUID | None,
    submitted_by: UUID | None,
    submitted_at: datetime | None,
) -> None:
    """新增一輪完整提交快照（建立後不可改、不可刪）；不提交交易。"""
    db.execute(
        INSERT_SNAPSHOT,
        {
            "invoice_id": invoice_id,
            "submission_round": submission_round,
            "kind": kind,
            "header": _json(header),
            "items": _json(items),
            "validation_results": _json(validation_results),
            "file_id": file_id,
            "submitted_by": submitted_by,
            "submitted_at": submitted_at,
        },
    )


def update_invoice_for_resubmit(
    db: Session,
    invoice_id: UUID,
    header: InvoiceHeader,
    *,
    old_round: int,
    new_round: int,
    status: str,
    validation_results: dict[str, Any],
) -> datetime | None:
    """以「狀態仍是 returned_to_applicant 且輪次等於 old_round」為條件更新案件；條件不符回 None。"""
    params = {
        "invoice_id": invoice_id,
        "invoice_track": header.invoice_track,
        "invoice_number": header.invoice_number,
        "invoice_date": header.invoice_date,
        "tax_period": header.tax_period,
        "seller_tax_id": header.seller_tax_id,
        "seller_name": header.seller_name,
        "buyer_tax_id": header.buyer_tax_id,
        "buyer_name": header.buyer_name,
        "tax_type": header.tax_type,
        "sales_amount": header.sales_amount,
        "tax_amount": header.tax_amount,
        "total_amount": header.total_amount,
        "total_amount_zh": header.total_amount_zh,
        "validation_results": _json(validation_results),
        "old_round": old_round,
        "new_round": new_round,
        "status": status,
    }
    return db.execute(UPDATE_INVOICE, params).scalar_one_or_none()


def update_item(db: Session, invoice_id: UUID, item_id: UUID, values: dict[str, Any]) -> None:
    """更新既有明細的內容（不新增、不刪除）；不提交交易。"""
    db.execute(UPDATE_ITEM, {"invoice_id": invoice_id, "item_id": item_id, **values})


def insert_change(
    db: Session,
    invoice_id: UUID,
    *,
    item_id: UUID | None,
    submission_round: int,
    field_name: str,
    old_value: Any,
    new_value: Any,
    changed_by: UUID,
    event_seq: int,
) -> None:
    """寫入一筆逐次編輯事件（附同輪順序 event_seq）；不提交交易。"""
    db.execute(
        INSERT_CHANGE,
        {
            "invoice_id": invoice_id,
            "item_id": item_id,
            "submission_round": submission_round,
            "field_name": field_name,
            "old_value": _json(old_value),
            "new_value": _json(new_value),
            "changed_by": changed_by,
            "event_seq": event_seq,
        },
    )


def list_latest_reviews(db: Session, invoice_id: UUID, *, new_round: int) -> list[dict[str, Any]]:
    """每個欄位在新輪次之前的最近一筆欄位覆核（含確認者與確認時間）。"""
    params = {"invoice_id": invoice_id, "new_round": new_round}
    return [dict(r) for r in db.execute(SELECT_LATEST_REVIEWS, params).mappings().all()]


def insert_review(
    db: Session,
    invoice_id: UUID,
    *,
    submission_round: int,
    field_scope: str,
    item_id: UUID | None,
    field_name: str,
    ai_original_value: Any,
    submitted_value: Any,
) -> None:
    """新增一筆本輪待覆核（未確認）的欄位覆核；不提交交易。"""
    db.execute(
        INSERT_REVIEW,
        {
            "invoice_id": invoice_id,
            "submission_round": submission_round,
            "field_scope": field_scope,
            "item_id": item_id,
            "field_name": field_name,
            "ai_original_value": _json(ai_original_value),
            "submitted_value": _json(submitted_value),
        },
    )


def insert_carryover(
    db: Session,
    invoice_id: UUID,
    *,
    submission_round: int,
    field_scope: str,
    item_id: UUID | None,
    field_name: str,
    source_id: UUID,
) -> None:
    """記錄本輪承接前輪確認效力（指向原確認列，不複製、不改前輪）；不提交交易。"""
    db.execute(
        INSERT_CARRYOVER,
        {
            "invoice_id": invoice_id,
            "submission_round": submission_round,
            "field_scope": field_scope,
            "item_id": item_id,
            "field_name": field_name,
            "source_id": source_id,
        },
    )


def respond_return_item(
    db: Session,
    invoice_id: UUID,
    return_item_id: UUID,
    *,
    status: str,
    action: str,
    note: str | None,
    user_id: UUID,
    response_round: int,
) -> bool:
    """寫入申請人對退件項目的回覆（只更新 open 的項目）；成功更新一列回 True。"""
    params = {
        "invoice_id": invoice_id,
        "return_item_id": return_item_id,
        "status": status,
        "action": action,
        "note": note,
        "user_id": user_id,
        "response_round": response_round,
    }
    return db.execute(RESPOND_RETURN_ITEM, params).first() is not None


def insert_resubmission(
    db: Session,
    invoice_id: UUID,
    *,
    key: UUID,
    fingerprint: str,
    from_round: int,
    to_round: int,
    user_id: UUID,
    result: dict[str, Any],
) -> None:
    """記錄冪等鍵、請求指紋與原結果（不可改）；不提交交易。"""
    db.execute(
        INSERT_RESUBMISSION,
        {
            "invoice_id": invoice_id,
            "key": key,
            "fingerprint": fingerprint,
            "from_round": from_round,
            "to_round": to_round,
            "user_id": user_id,
            "result": _json(result),
        },
    )
