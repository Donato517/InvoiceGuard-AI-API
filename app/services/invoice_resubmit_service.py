"""
模組名稱：app.services.invoice_resubmit_service
功能說明：財務退回（returned_to_applicant）後的同案重送——讀取結構化退件項目與上一輪提交資料，
    以及由原提交者以「欄位補正」或「附說明的純申覆」正式重送，在單一資料庫交易內保存新輪次。
注意事項：
    - 不重新辨識、不更換影像；明細只能以既有 item_id 對應，不可新增、刪除或重排。
    - 只有原提交者（且案件部門等於目前選取部門）可讀取與重送；其餘一律 404，不洩漏案件是否存在。
    - 順序：鎖定案件並核對身分 → 冪等重放（相同 key 與內容回原結果）→ 狀態與 expected_round → 退件項目
      與圖片優先 → 欄位授權、事件鏈、回覆完整性 → 查重（排除本案）→ 寫入。冪等重放不會略過權限檢查。
    - 檢核提醒、標準值與查重沿用手機送出（invoice_upload_service）的函式，不另寫第二套。
    - 圖片問題（item_kind=image）一律回 409 RESUBMIT_IMAGE_REQUIRES_VOID，須由原提交者作廢後重新上傳。
    - 重送後回到「退件來源節點」：取最近一次退回歷程列的 old_status，不寫死；來源不明則拒絕。
    - 整個重送在一個交易內；任何步驟失敗全部 rollback，不留下半套正式提交紀錄。
    - 目前不在首次送出時寫 Round 1 快照（避免 Migration 尚未套用的資料庫無法送出）；重送時若上一輪沒有快照，
      先由上一輪的案件資料補建，再保存新輪次快照。
"""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError, NotFoundError, ServiceUnavailableError
from app.db.repositories import invoice_repository, resubmit_repository
from app.db.repositories.invoice_repository import InvoiceHeader
from app.schemas.auth import SessionRead
from app.schemas.invoice_resubmit import (
    CarriedField,
    FieldRef,
    InvoiceResubmitRead,
    InvoiceResubmitRequest,
    PreviousItem,
    PreviousSubmission,
    ReturnItemRead,
    ReturnItemsRead,
)
from app.schemas.invoice_upload import ModifiedField
from app.services import invoice_resubmit_rules as rules
from app.services.invoice_resubmit_rules import FieldKey
from app.services.invoice_upload_service import (
    _HEADER_FIELDS,
    _ITEM_FIELDS,
    _canonical_value,
    _consistency_warnings,
    future_date_warnings,
)
from app.utils.invoice_format import tax_period_for

RETURNED_STATUS = "returned_to_applicant"
# 重送可回到的退件來源節點（來源必須是這些審核節點之一，否則拒絕，不憑狀態名稱猜測）
ORIGIN_STATUSES = frozenset(
    {"pending_department_approval", "pending_accounting_review", "pending_accounting_approval"}
)
_NOT_FOUND = "找不到這張發票"


def get_return_items(db: Session | None, current: SessionRead, invoice_id: UUID) -> ReturnItemsRead:
    """讀取退件項目、後端允許修改的欄位與上一輪正式提交資料；只有原提交者可讀。

    Raises:
        NotFoundError: 案件不存在、不是本人提交或不屬於目前選取部門（回應相同）。
        ConflictError: 案件目前不是 returned_to_applicant（INVOICE_NOT_RETURNED）。
    """
    db = _require_db(db)
    try:
        row = resubmit_repository.get_own_invoice(
            db,
            invoice_id,
            user_id=current.user_id,
            department_id=current.department.department_id,
            lock=False,
        )
        if row is None:
            raise NotFoundError(_NOT_FOUND)
        if row["status"] != RETURNED_STATUS:
            raise _not_returned()
        item_rows = resubmit_repository.list_items(db, invoice_id)
        line_by_item = {r["item_id"]: r["line_no"] for r in item_rows}
        item_by_line = {line: item_id for item_id, line in line_by_item.items()}
        raw_items = resubmit_repository.list_open_return_items(
            db, invoice_id, submission_round=row["submission_round"]
        )
        domain = _domain_items(raw_items, line_by_item)
        has_image = any(item.kind == rules.KIND_IMAGE for item in domain)
        reason = None
        if has_image:
            reason = "有圖片問題，請作廢後重新上傳"
        elif not any(item.kind == rules.KIND_FIELD for item in domain):
            reason = "尚無可補正或申覆的欄位退件項目"
        read = ReturnItemsRead(
            invoice_id=invoice_id,
            status=row["status"],
            submission_round=row["submission_round"],
            can_resubmit=reason is None,
            requires_void=has_image,
            resubmit_blocked_reason=reason,
            editable_fields=()
            if has_image
            else tuple(
                _ref(key, item_by_line) for key in sorted(rules.allowed_fields(domain), key=_sort)
            ),
            return_items=tuple(
                _return_item_read(raw, item, item_by_line)
                for raw, item in zip(raw_items, domain, strict=True)
            ),
            previous=_previous(row, item_rows),
        )
    finally:
        db.rollback()
    return read


def resubmit(
    db: Session | None,
    current: SessionRead,
    invoice_id: UUID,
    request: InvoiceResubmitRequest,
    *,
    today: date | None = None,
) -> InvoiceResubmitRead:
    """正式重送：在單一交易內保存新輪次並讓案件回到退件來源的審核節點。

    Returns:
        InvoiceResubmitRead: 新輪次結果；相同冪等鍵與內容的重試回傳首次成功的原結果（replayed=True）。

    Raises:
        NotFoundError: 案件不存在、不是本人提交或不屬於目前選取部門。
        ConflictError: 冪等鍵已用於不同內容、案件不是 returned_to_applicant、expected_round 過期、有圖片問題、
            來源節點不明、與其他案件重複。
        AppError: 欄位未授權、明細結構變更、事件鏈不合法、回覆不完整。
    """
    db = _require_db(db)
    fingerprint = rules.request_fingerprint(
        {"invoice_id": str(invoice_id), **request.model_dump(mode="json")}
    )
    try:
        row = resubmit_repository.get_own_invoice(
            db,
            invoice_id,
            user_id=current.user_id,
            department_id=current.department.department_id,
            lock=True,
        )
        if row is None:
            raise NotFoundError(_NOT_FOUND)

        existing = resubmit_repository.get_idempotent(
            db, invoice_id, user_id=current.user_id, key=request.idempotency_key
        )
        if existing is not None:
            if existing["request_fingerprint"] != fingerprint:
                raise ConflictError("這個冪等鍵已用於不同內容的請求", code="IDEMPOTENCY_KEY_REUSED")
            replay = InvoiceResubmitRead.model_validate(existing["result"])
            db.rollback()
            return replay.model_copy(update={"replayed": True})

        if row["status"] != RETURNED_STATUS:
            raise _not_returned()
        if request.expected_round != row["submission_round"]:
            raise ConflictError(
                "案件已有較新的輪次，請重新讀取後再送出", code="RESUBMIT_ROUND_STALE"
            )

        old_round = row["submission_round"]
        new_round = old_round + 1
        item_rows = resubmit_repository.list_items(db, invoice_id)
        line_by_item = {r["item_id"]: r["line_no"] for r in item_rows}
        item_by_line = {line: item_id for item_id, line in line_by_item.items()}

        raw_items = resubmit_repository.list_open_return_items(
            db, invoice_id, submission_round=old_round
        )
        return_items = _domain_items(raw_items, line_by_item)
        if not return_items:
            raise ConflictError("此案件沒有待處理的退件項目", code="RETURN_ITEMS_MISSING")
        rules.ensure_resubmit_allowed(return_items)  # 圖片問題優先：禁止同案重送與申覆
        origin = resubmit_repository.get_return_origin_status(db, invoice_id)
        if origin not in ORIGIN_STATUSES:
            raise ConflictError(
                "無法確認退件來源的審核節點，請聯絡財務人員", code="RESUBMIT_ORIGIN_UNKNOWN"
            )

        previous = _value_map(
            {name: row[name] for name in _HEADER_FIELDS},
            {r["line_no"]: {name: r[name] for name in _ITEM_FIELDS} for r in item_rows},
        )
        item_values = _request_items(request, line_by_item)
        final = _value_map({name: getattr(request, name) for name in _HEADER_FIELDS}, item_values)
        modified = rules.modified_fields(previous, final)
        events = rules.validate_event_chain(previous, final, _events(request))
        rules.ensure_edits_authorized(
            set(modified) | {event.key for event in events}, rules.allowed_fields(return_items)
        )
        responses = rules.validate_responses(
            return_items,
            [rules.Response(str(r.return_item_id), r.action, r.note) for r in request.responses],
            modified,
        )

        header = InvoiceHeader(
            invoice_track=request.invoice_track,
            invoice_number=request.invoice_number,
            invoice_date=request.invoice_date,
            tax_period=tax_period_for(request.invoice_date),
            seller_tax_id=request.seller_tax_id,
            seller_name=request.seller_name,
            buyer_tax_id=request.buyer_tax_id,
            buyer_name=request.buyer_name,
            sales_amount=request.sales_amount,
            tax_amount=request.tax_amount,
            total_amount=request.total_amount,
            total_amount_zh=request.total_amount_zh,
            tax_type=request.tax_type,
        )
        warnings = [
            *future_date_warnings(header.invoice_date, today),
            *_consistency_warnings(
                seller_tax_id=header.seller_tax_id,
                buyer_tax_id=header.buyer_tax_id,
                tax_type=header.tax_type,
                sales=header.sales_amount,
                tax=header.tax_amount,
                total=header.total_amount,
                line_amounts=[item.line_amount for item in request.items],
                total_zh=header.total_amount_zh,
                item_details=[
                    (item.quantity, item.unit_price, item.line_amount) for item in request.items
                ],
            ),
        ]

        identity = {
            "invoice_track": header.invoice_track,
            "invoice_number": header.invoice_number,
            "seller_tax_id": header.seller_tax_id,
        }
        invoice_repository.lock_invoice_key(db, **identity)
        if invoice_repository.exists_duplicate(db, **identity, exclude_invoice_id=invoice_id):
            raise ConflictError("此發票已存在於系統中，禁止重複上傳", code="INVOICE_DUPLICATED")

        file_id = resubmit_repository.get_current_file_id(db, invoice_id)
        if not resubmit_repository.snapshot_exists(db, invoice_id, old_round):
            resubmit_repository.insert_snapshot(
                db,
                invoice_id,
                submission_round=old_round,
                kind="first",
                header=_header_snapshot(row["tax_period"], previous),
                items=_items_snapshot(item_rows, previous),
                validation_results=row["validation_results"] or {},
                file_id=file_id,
                submitted_by=row["submitted_by"],
                submitted_at=row["submitted_at"],
            )

        validation_results = {"warnings": [w.model_dump() for w in warnings]}
        submitted_at = resubmit_repository.update_invoice_for_resubmit(
            db,
            invoice_id,
            header,
            old_round=old_round,
            new_round=new_round,
            status=origin,
            validation_results=validation_results,
        )
        if submitted_at is None:
            raise ConflictError(
                "案件已有較新的輪次，請重新讀取後再送出", code="RESUBMIT_ROUND_STALE"
            )
        modified_lines = {key[1] for key in modified if key[0] == "item"}
        for item in request.items:
            if line_by_item[item.item_id] in modified_lines:
                resubmit_repository.update_item(
                    db,
                    invoice_id,
                    item.item_id,
                    {
                        "item_name": item.item_name,
                        "quantity": item.quantity,
                        "unit_price": item.unit_price,
                        "line_amount": item.line_amount,
                    },
                )
        resubmit_repository.insert_snapshot(
            db,
            invoice_id,
            submission_round=new_round,
            kind="resubmit_corrected" if modified else "resubmit_appeal",
            header=_header_snapshot(header.tax_period, final),
            items=_items_snapshot(item_rows, final),
            validation_results=validation_results,
            file_id=file_id,
            submitted_by=current.user_id,
            submitted_at=submitted_at,
        )

        saved_events = list(events)
        covered = {event.key for event in events}
        saved_events += [  # 沒有事件的淨修改補一筆，確保每個修改欄位都有紀錄
            rules.EditEvent(key, previous[key], final[key])
            for key in sorted(modified - covered, key=_sort)
        ]
        for seq, event in enumerate(saved_events, start=1):
            scope, line_no, name = event.key
            resubmit_repository.insert_change(
                db,
                invoice_id,
                item_id=item_by_line[line_no] if scope == "item" and line_no is not None else None,
                submission_round=new_round,
                field_name=name,
                old_value=event.old,
                new_value=event.new,
                changed_by=current.user_id,
                event_seq=seq,
            )

        latest = _latest_reviews(
            resubmit_repository.list_latest_reviews(db, invoice_id, new_round=new_round),
            line_by_item,
        )
        scope = rules.review_scope(return_items, responses, modified, previous.keys())
        confirmed = {key for key, review in latest.items() if review["is_checked"]}
        carried_keys = sorted(scope.carried & confirmed, key=_sort)
        # 針對性覆核：只對被退回、實際修改與被申覆的欄位建立待審列；其餘欄位不產生任何覆核紀錄，
        # 也不推定通過（沒有逐欄確認紀錄就沒有承接，不會產生虛假的已確認狀態）
        rereview_keys = sorted(scope.rereview, key=_sort)
        for key in rereview_keys:
            kind, line_no, name = key
            resubmit_repository.insert_review(
                db,
                invoice_id,
                submission_round=new_round,
                field_scope=kind,
                item_id=item_by_line[line_no] if kind == "item" and line_no is not None else None,
                field_name=name,
                ai_original_value=latest[key]["ai_original_value"] if key in latest else None,
                submitted_value=final[key],
            )
        for key in carried_keys:
            kind, line_no, name = key
            resubmit_repository.insert_carryover(
                db,
                invoice_id,
                submission_round=new_round,
                field_scope=kind,
                item_id=item_by_line[line_no] if kind == "item" and line_no is not None else None,
                field_name=name,
                source_id=latest[key]["field_review_id"],
            )

        for response in responses:
            if not resubmit_repository.respond_return_item(
                db,
                invoice_id,
                UUID(response.return_item_id),
                status=response.action,
                action=response.action,
                note=(response.note or "").strip() or None,
                user_id=current.user_id,
                response_round=new_round,
            ):
                raise ConflictError("退件項目已被處理，請重新讀取", code="RETURN_ITEM_NOT_OPEN")
        corrected = sum(1 for r in responses if r.action == rules.ACTION_CORRECTED)
        invoice_repository.insert_status_history(
            db,
            invoice_id,
            old_status=RETURNED_STATUS,
            new_status=origin,
            reason=f"申請人重送（第 {new_round} 輪）：已補正 {corrected} 項、申覆 {len(responses) - corrected} 項",
            changed_by=current.user_id,
        )

        result = InvoiceResubmitRead(
            invoice_id=invoice_id,
            status=origin,
            submission_round=new_round,
            submitted_at=submitted_at,
            tax_period=header.tax_period,
            warnings=tuple(warnings),
            modified_fields=tuple(
                ModifiedField(
                    field_scope=key[0],
                    line_no=key[1],
                    field_name=key[2],
                    ai_original_value=previous[key],
                    submitted_value=final[key],
                )
                for key in sorted(modified, key=_sort)
            ),
            rereview_fields=tuple(_ref(key, item_by_line) for key in rereview_keys),
            carried_fields=tuple(
                CarriedField(
                    field=_ref(key, item_by_line),
                    source_round=latest[key]["submission_round"],
                    confirmed_by=latest[key]["checked_by"],
                    confirmed_at=latest[key]["checked_at"],
                )
                for key in carried_keys
            ),
        )
        resubmit_repository.insert_resubmission(
            db,
            invoice_id,
            key=request.idempotency_key,
            fingerprint=fingerprint,
            from_round=old_round,
            to_round=new_round,
            user_id=current.user_id,
            result=result.model_dump(mode="json"),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


def _require_db(db: Session | None) -> Session:
    if db is None:
        raise ServiceUnavailableError("資料庫尚未設定，無法處理發票")
    return db


def _not_returned() -> ConflictError:
    return ConflictError("案件目前不是退回申請人的狀態", code="INVOICE_NOT_RETURNED")


def _sort(key: FieldKey) -> tuple[int, int, str]:
    return (key[0] == "item", key[1] or 0, key[2])


def _ref(key: FieldKey, item_by_line: dict[int, UUID]) -> FieldRef:
    scope, line_no, name = key
    return FieldRef(
        field_scope=scope,  # type: ignore[arg-type]
        line_no=line_no,
        item_id=item_by_line.get(line_no) if scope == "item" and line_no is not None else None,
        field_name=name,
    )


def _entry_key(entry: dict[str, Any], line_by_item: dict[UUID, int]) -> FieldKey | None:
    """退件項目或授權欄位的 JSON／資料列 → 欄位鍵；明細欄位以 item_id 換成 line_no，找不到回 None。"""
    scope = entry["field_scope"]
    if scope == "header":
        return ("header", None, entry["field_name"])
    item_id = entry.get("item_id")
    line_no = line_by_item.get(UUID(str(item_id))) if item_id else None
    return ("item", line_no, entry["field_name"]) if line_no is not None else None


def _domain_items(
    raw_items: list[dict[str, Any]], line_by_item: dict[UUID, int]
) -> list[rules.ReturnItem]:
    items: list[rules.ReturnItem] = []
    for raw in raw_items:
        target = None
        allowed: set[FieldKey] = set()
        if raw["item_kind"] == rules.KIND_FIELD:
            target = _entry_key(raw, line_by_item)
            if target is None:
                raise ConflictError("退件項目的欄位定位無效", code="RETURN_ITEM_INVALID")
            for entry in raw["allowed_fields"] or []:
                key = _entry_key(entry, line_by_item)
                if key is None:
                    raise ConflictError("退件項目的授權欄位定位無效", code="RETURN_ITEM_INVALID")
                allowed.add(key)
        items.append(
            rules.ReturnItem(
                str(raw["return_item_id"]),
                raw["item_kind"],
                raw["reason"],
                target,
                frozenset(allowed),
            )
        )
    return items


def _return_item_read(
    raw: dict[str, Any], item: rules.ReturnItem, item_by_line: dict[int, UUID]
) -> ReturnItemRead:
    return ReturnItemRead(
        return_item_id=raw["return_item_id"],
        item_kind=item.kind,  # type: ignore[arg-type]
        target=_ref(item.target, item_by_line) if item.target else None,
        reason=item.reason,
        allowed_fields=tuple(_ref(key, item_by_line) for key in sorted(item.allowed, key=_sort)),
        status=raw["status"],
    )


def _value_map(
    header: dict[str, Any], items: dict[int, dict[str, Any]]
) -> dict[FieldKey, str | None]:
    values: dict[FieldKey, str | None] = {
        ("header", None, name): _canonical_value(name, header[name]) for name in _HEADER_FIELDS
    }
    for line_no, item in items.items():
        for name in _ITEM_FIELDS:
            values[("item", line_no, name)] = _canonical_value(name, item[name])
    return values


def _request_items(
    request: InvoiceResubmitRequest, line_by_item: dict[UUID, int]
) -> dict[int, dict[str, Any]]:
    ids = [item.item_id for item in request.items]
    if len(set(ids)) != len(ids) or set(ids) != set(line_by_item):
        raise AppError(
            "本次補正不允許新增、刪除或重排明細", code="RESUBMIT_ITEMS_STRUCTURE_CHANGED"
        )
    return {
        line_by_item[item.item_id]: {
            "item_name": item.item_name,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "line_amount": item.line_amount,
        }
        for item in request.items
    }


def _events(request: InvoiceResubmitRequest) -> list[rules.EditEvent]:
    return [
        rules.EditEvent(
            (change.field_scope, change.line_no, change.field_name),
            _canonical_value(change.field_name, change.old_value),
            _canonical_value(change.field_name, change.new_value),
        )
        for change in request.changes
    ]


def _latest_reviews(
    rows: list[dict[str, Any]], line_by_item: dict[UUID, int]
) -> dict[FieldKey, dict[str, Any]]:
    latest: dict[FieldKey, dict[str, Any]] = {}
    for row in rows:
        key = _entry_key(row, line_by_item)
        if key is not None:
            latest[key] = row
    return latest


def _header_snapshot(tax_period: str, values: dict[FieldKey, str | None]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {name: values[("header", None, name)] for name in _HEADER_FIELDS}
    snapshot["tax_period"] = tax_period
    return snapshot


def _items_snapshot(
    item_rows: list[dict[str, Any]], values: dict[FieldKey, str | None]
) -> list[dict[str, Any]]:
    return [
        {
            "item_id": str(row["item_id"]),
            "line_no": row["line_no"],
            **{name: values[("item", row["line_no"], name)] for name in _ITEM_FIELDS},
        }
        for row in item_rows
    ]


def _previous(row: dict[str, Any], item_rows: list[dict[str, Any]]) -> PreviousSubmission:
    def text(name: str, value: Any) -> str | None:
        return _canonical_value(name, value)

    return PreviousSubmission(
        invoice_track=row["invoice_track"],
        invoice_number=row["invoice_number"],
        invoice_date=row["invoice_date"],
        seller_tax_id=row["seller_tax_id"],
        seller_name=row["seller_name"],
        buyer_tax_id=row["buyer_tax_id"],
        buyer_name=row["buyer_name"],
        tax_type=row["tax_type"],
        sales_amount=text("sales_amount", row["sales_amount"]),
        tax_amount=text("tax_amount", row["tax_amount"]),
        total_amount=text("total_amount", row["total_amount"]),
        total_amount_zh=row["total_amount_zh"],
        items=tuple(
            PreviousItem(
                item_id=r["item_id"],
                line_no=r["line_no"],
                item_name=r["item_name"],
                quantity=text("quantity", r["quantity"]),
                unit_price=text("unit_price", r["unit_price"]),
                line_amount=text("line_amount", r["line_amount"]),
            )
            for r in item_rows
        ),
    )
