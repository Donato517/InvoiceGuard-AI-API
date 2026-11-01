"""
模組名稱：app.db.repositories.invoice_repository
功能說明：發票資料存取（v1.4）——查重、建立發票表頭／明細／影像檔、欄位複核（使用者修改過的欄位，每輪一筆）、
    修改歷程（逐次修改，含中間修改）與狀態歷程。
注意事項：
    - 以固定 SQL 存取，值一律綁定參數；只負責資料存取，不自行 commit（交易由 service 控制）。
    - 查重以字軌＋號碼＋賣方統一編號（索引 ix_invoices_number_supplier），已作廢（voided）者不計。
    - 前台查詢必須帶 user_id 條件，避免越權讀取他人發票；詳情（get_owned_*）只依 submitted_by 過濾，
      不使用 Session 選取部門（列表尚未實作）。
"""

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# 同一張發票（字軌＋號碼＋賣方統編）的送出在交易內序列化；交易結束自動釋放
LOCK_INVOICE_KEY = text("SELECT pg_advisory_xact_lock(hashtextextended(:invoice_key, 0))")
EXISTS_DUPLICATE = text("""
    SELECT EXISTS (
        SELECT 1 FROM public.invoices
        WHERE invoice_track = :invoice_track
          AND invoice_number = :invoice_number
          AND seller_tax_id = :seller_tax_id
          AND status <> 'voided'
    )
""")
INSERT_INVOICE = text("""
    INSERT INTO public.invoices
        (invoice_track, invoice_number, invoice_date, tax_period, seller_tax_id, seller_name,
         buyer_tax_id, buyer_name, sales_amount, tax_amount, total_amount, total_amount_zh, tax_type,
         submission_round, status, validation_results, submitted_by, department_id, submitted_at)
    VALUES
        (:invoice_track, :invoice_number, :invoice_date, :tax_period, :seller_tax_id, :seller_name,
         :buyer_tax_id, :buyer_name, :sales_amount, :tax_amount, :total_amount, :total_amount_zh,
         :tax_type, :submission_round, :status, CAST(:validation_results AS jsonb), :submitted_by,
         :department_id, now())
    RETURNING invoice_id, submitted_at
""")
INSERT_ITEM = text("""
    INSERT INTO public.invoice_items
        (invoice_id, line_no, item_name, quantity, unit_price, line_amount)
    VALUES (:invoice_id, :line_no, :item_name, :quantity, :unit_price, :line_amount)
    RETURNING item_id
""")
INSERT_FILE = text("""
    INSERT INTO public.invoice_files
        (invoice_id, bucket_name, storage_path, original_filename, mime_type, size_bytes, uploaded_by)
    VALUES (:invoice_id, :bucket_name, :storage_path, :original_filename, :mime_type, :size_bytes,
            :uploaded_by)
    RETURNING file_id
""")
INSERT_FIELD_REVIEW = text("""
    INSERT INTO public.invoice_field_reviews
        (invoice_id, submission_round, field_scope, item_id, field_name, recognition_id,
         ai_original_value, submitted_value)
    VALUES (:invoice_id, :submission_round, :field_scope, :item_id, :field_name, :recognition_id,
            CAST(:ai_original_value AS jsonb), CAST(:submitted_value AS jsonb))
""")
INSERT_CHANGE = text("""
    INSERT INTO public.invoice_changes
        (invoice_id, item_id, submission_round, field_name, old_value, new_value, change_source,
         changed_by, changed_at)
    VALUES (:invoice_id, :item_id, :submission_round, :field_name, CAST(:old_value AS jsonb),
            CAST(:new_value AS jsonb), :change_source, :changed_by, clock_timestamp())
""")
INSERT_STATUS_HISTORY = text("""
    INSERT INTO public.invoice_status_history (invoice_id, old_status, new_status, reason, changed_by)
    VALUES (:invoice_id, :old_status, :new_status, :reason, :changed_by)
""")

# 詳情讀取：多次 SELECT 之間以 REPEATABLE READ 取得同一個資料快照（必須是交易的第一個陳述式）
SET_READ_SNAPSHOT = text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
SELECT_OWNED_INVOICE = text("""
    SELECT invoice_id, status, submission_round, submitted_at, tax_period, invoice_track,
           invoice_number, invoice_date, seller_tax_id, seller_name, buyer_tax_id, buyer_name,
           tax_type, sales_amount, tax_amount, total_amount, total_amount_zh, validation_results
    FROM public.invoices
    WHERE invoice_id = :invoice_id AND submitted_by = :user_id
""")
SELECT_INVOICE_ITEMS = text("""
    SELECT line_no, item_name, quantity, unit_price, line_amount
    FROM public.invoice_items
    WHERE invoice_id = :invoice_id
    ORDER BY line_no
""")
SELECT_FIELD_REVIEWS = text("""
    SELECT r.field_scope, i.line_no, r.field_name, r.ai_original_value, r.submitted_value
    FROM public.invoice_field_reviews AS r
    LEFT JOIN public.invoice_items AS i
      ON i.invoice_id = r.invoice_id AND i.item_id = r.item_id
    WHERE r.invoice_id = :invoice_id AND r.submission_round = :submission_round
    ORDER BY (r.field_scope = 'item'), i.line_no, r.field_name, r.field_review_id
""")
SELECT_CURRENT_FILE = text("""
    SELECT mime_type, original_filename, size_bytes, version_no
    FROM public.invoice_files
    WHERE invoice_id = :invoice_id AND is_current = true
""")


@dataclass(frozen=True)
class InvoiceHeader:
    """寫入 invoices 的表頭欄位。"""

    invoice_track: str
    invoice_number: str
    invoice_date: date
    tax_period: str
    seller_tax_id: str
    seller_name: str | None
    buyer_tax_id: str | None
    buyer_name: str | None
    sales_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    total_amount_zh: str | None
    tax_type: str


@dataclass(frozen=True)
class InvoiceItem:
    """寫入 invoice_items 的一筆明細。"""

    line_no: int
    item_name: str
    quantity: Decimal | None
    unit_price: Decimal | None
    line_amount: Decimal


@dataclass(frozen=True)
class FieldDifference:
    """AI 原始值與使用者送出值不同的欄位（每輪一筆，寫入 invoice_field_reviews）。"""

    field_scope: str  # header／item
    line_no: int | None  # item 時為明細序號
    field_name: str
    ai_original_value: Any
    submitted_value: Any


@dataclass(frozen=True)
class FieldChange:
    """使用者的一次欄位修改（含中間修改，寫入 invoice_changes）。"""

    field_scope: str  # header／item
    line_no: int | None  # item 時為明細序號
    field_name: str
    old_value: Any
    new_value: Any


def lock_invoice_key(
    db: Session, *, invoice_track: str, invoice_number: str, seller_tax_id: str
) -> None:
    """鎖定同一張發票的送出（交易層級 advisory lock），避免並行送出都通過查重。"""
    invoice_key = f"invoice:{invoice_track}{invoice_number}:{seller_tax_id}"
    db.execute(LOCK_INVOICE_KEY, {"invoice_key": invoice_key})


def exists_duplicate(
    db: Session, *, invoice_track: str, invoice_number: str, seller_tax_id: str
) -> bool:
    """系統內是否已有相同字軌、號碼與賣方統編且未作廢的發票。"""
    params = {
        "invoice_track": invoice_track,
        "invoice_number": invoice_number,
        "seller_tax_id": seller_tax_id,
    }
    return bool(db.execute(EXISTS_DUPLICATE, params).scalar_one())


def insert_invoice(
    db: Session,
    header: InvoiceHeader,
    *,
    submission_round: int,
    status: str,
    validation_results: dict[str, Any],
    submitted_by: UUID,
    department_id: UUID,
) -> tuple[UUID, datetime]:
    """新增發票表頭，回傳 (invoice_id, submitted_at)；不提交交易。"""
    row = db.execute(
        INSERT_INVOICE,
        {
            **header.__dict__,
            "submission_round": submission_round,
            "status": status,
            "validation_results": _json(validation_results),
            "submitted_by": submitted_by,
            "department_id": department_id,
        },
    ).one()
    return row[0], row[1]


def insert_items(db: Session, invoice_id: UUID, items: tuple[InvoiceItem, ...]) -> dict[int, UUID]:
    """新增明細，回傳 {line_no: item_id}；不提交交易。"""
    return {
        item.line_no: db.execute(
            INSERT_ITEM, {"invoice_id": invoice_id, **item.__dict__}
        ).scalar_one()
        for item in items
    }


def insert_file(
    db: Session,
    invoice_id: UUID,
    *,
    bucket_name: str,
    storage_path: str,
    original_filename: str | None,
    mime_type: str,
    size_bytes: int | None,
    uploaded_by: UUID,
) -> UUID:
    """新增發票影像檔資訊（第 1 版、目前版本），回傳 file_id；不提交交易。"""
    return db.execute(
        INSERT_FILE,
        {
            "invoice_id": invoice_id,
            "bucket_name": bucket_name,
            "storage_path": storage_path,
            "original_filename": original_filename,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "uploaded_by": uploaded_by,
        },
    ).scalar_one()


def insert_field_reviews(
    db: Session,
    invoice_id: UUID,
    differences: tuple[FieldDifference, ...],
    *,
    item_ids: dict[int, UUID],
    submission_round: int,
    recognition_id: UUID,
) -> None:
    """每個使用者修改過的欄位（AI 原值與送出值不同）寫一筆本輪欄位複核，供審核勾選；不提交交易。"""
    for difference in differences:
        db.execute(
            INSERT_FIELD_REVIEW,
            {
                "invoice_id": invoice_id,
                "submission_round": submission_round,
                "field_scope": difference.field_scope,
                "item_id": _item_id(item_ids, difference.field_scope, difference.line_no),
                "field_name": difference.field_name,
                "recognition_id": recognition_id,
                "ai_original_value": _json(difference.ai_original_value),
                "submitted_value": _json(difference.submitted_value),
            },
        )


def insert_changes(
    db: Session,
    invoice_id: UUID,
    changes: tuple[FieldChange, ...],
    *,
    item_ids: dict[int, UUID],
    submission_round: int,
    changed_by: UUID,
) -> None:
    """依序寫入使用者的逐次修改（含中間修改）；changed_at 用 clock_timestamp() 保留先後順序。不提交交易。"""
    for change in changes:
        db.execute(
            INSERT_CHANGE,
            {
                "invoice_id": invoice_id,
                "item_id": _item_id(item_ids, change.field_scope, change.line_no),
                "submission_round": submission_round,
                "field_name": change.field_name,
                "old_value": _json(change.old_value),
                "new_value": _json(change.new_value),
                "change_source": "user",
                "changed_by": changed_by,
            },
        )


def insert_status_history(
    db: Session,
    invoice_id: UUID,
    *,
    old_status: str | None,
    new_status: str,
    reason: str | None,
    changed_by: UUID,
) -> None:
    """新增一筆狀態歷程；不提交交易。"""
    db.execute(
        INSERT_STATUS_HISTORY,
        {
            "invoice_id": invoice_id,
            "old_status": old_status,
            "new_status": new_status,
            "reason": reason,
            "changed_by": changed_by,
        },
    )


def _item_id(item_ids: dict[int, UUID], field_scope: str, line_no: int | None) -> UUID | None:
    return item_ids[line_no] if field_scope == "item" and line_no is not None else None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


class UnexpectedTransactionStateError(RuntimeError):
    """呼叫端已在交易中，無法再設定隔離等級；repository 不處理（不 rollback）別人的交易。"""


def begin_read_snapshot(db: Session) -> None:
    """開始唯讀的 REPEATABLE READ 交易，後續 SELECT 看到同一份快照；須在全新的交易中呼叫。

    PostgreSQL 要求 SET TRANSACTION 是交易的第一個陳述式。若 Session 已有進行中的交易（呼叫端
    先前執行過陳述式且尚未結束），本函式不清除它，直接拋出 UnexpectedTransactionStateError，
    由呼叫端決定如何處理。

    Raises:
        UnexpectedTransactionStateError: Session 已在交易中。
    """
    if db.in_transaction():
        raise UnexpectedTransactionStateError("讀取快照必須在新的交易開始，但 Session 已在交易中")
    db.execute(SET_READ_SNAPSHOT)


def get_owned_invoice(db: Session, invoice_id: UUID, *, user_id: UUID) -> dict[str, Any] | None:
    """讀取提交者本人的發票表頭；不存在或不是本人提交的回傳 None（兩者不可區分）。"""
    row = (
        db.execute(SELECT_OWNED_INVOICE, {"invoice_id": invoice_id, "user_id": user_id})
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def list_items(db: Session, invoice_id: UUID) -> list[dict[str, Any]]:
    """讀取發票明細，依 line_no 排序；呼叫前須已確認發票屬於本人。"""
    rows = db.execute(SELECT_INVOICE_ITEMS, {"invoice_id": invoice_id}).mappings().all()
    return [dict(row) for row in rows]


def list_field_reviews(
    db: Session, invoice_id: UUID, *, submission_round: int
) -> list[dict[str, Any]]:
    """讀取指定輪次的欄位複核（使用者修改過的欄位）；明細欄位以 JOIN 取得 line_no，表頭欄位為 None。"""
    params = {"invoice_id": invoice_id, "submission_round": submission_round}
    return [dict(row) for row in db.execute(SELECT_FIELD_REVIEWS, params).mappings().all()]


def get_current_file(db: Session, invoice_id: UUID) -> dict[str, Any] | None:
    """讀取目前（is_current）的影像檔中繼資料；不含 bucket 與物件路徑。"""
    row = db.execute(SELECT_CURRENT_FILE, {"invoice_id": invoice_id}).mappings().one_or_none()
    return dict(row) if row else None


# TODO(JerryChien): list_page(db, *, user_id, department_id, status, page, page_size) 我的發票列表
