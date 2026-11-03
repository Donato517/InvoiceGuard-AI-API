"""
模組名稱：app.services.invoice_resubmit_rules
功能說明：退回補正／申覆重送的純規則（不連 DB）：圖片優先、可編輯欄位集合、編輯事件鏈、回覆完整性、
    重新覆核範圍與冪等請求指紋。
注意事項：輸入的欄位值須已是標準值（invoice_upload_service._canonical_value）；本模組不重寫檢核算式。
    「上一輪正式提交值」才是事件鏈起點，不是 AI 原值。尚未接 Route 與 DB（需退件項目資料結構，見 Contract）。
"""

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.core.exceptions import AppError, ConflictError

# (範圍 header／item, 明細序號或 None, 欄位名稱)
FieldKey = tuple[str, int | None, str]

KIND_FIELD = "field"
KIND_IMAGE = "image"
KIND_OTHER = "other"
ACTION_CORRECTED = "corrected"
ACTION_APPEALED = "appealed"


@dataclass(frozen=True)
class ReturnItem:
    """財務退回時產生的結構化退件項目（對應 invoice_return_items 的一列）。"""

    return_item_id: str
    kind: str
    reason: str
    target: FieldKey | None = None
    allowed: frozenset[FieldKey] = frozenset()  # 財務授權的相依欄位（不含 target 本身）


@dataclass(frozen=True)
class Response:
    """申請人對單一退件項目的回覆。"""

    return_item_id: str
    action: str
    note: str | None = None


@dataclass(frozen=True)
class EditEvent:
    """前端 editLog 的一筆逐次修改（值為標準值）。"""

    key: FieldKey
    old: str | None
    new: str | None


@dataclass(frozen=True)
class ReviewScope:
    """本輪覆核範圍：需重新覆核的欄位，與承接前輪確認的欄位（兩者不相交）。"""

    rereview: frozenset[FieldKey]
    carried: frozenset[FieldKey]


def _error(message: str, code: str) -> AppError:
    return AppError(message, code=code)


def ensure_resubmit_allowed(items: Iterable[ReturnItem]) -> None:
    """有任何圖片問題時禁止同案重送與申覆，必須作廢後重新上傳。

    Raises:
        ConflictError: RESUBMIT_IMAGE_REQUIRES_VOID。
    """
    if any(item.kind == KIND_IMAGE for item in items):
        raise ConflictError(
            "此案件有圖片問題，請作廢後重新上傳，不能在原案件重送或申覆",
            code="RESUBMIT_IMAGE_REQUIRES_VOID",
        )


def allowed_fields(items: Iterable[ReturnItem]) -> frozenset[FieldKey]:
    """欄位退件項目的 target 與授權相依欄位聯集；唯讀以外的欄位一律不可改。"""
    allowed: set[FieldKey] = set()
    for item in items:
        if item.kind == KIND_FIELD and item.target is not None:
            allowed.add(item.target)
            allowed |= item.allowed
    return frozenset(allowed)


def modified_fields(
    previous: Mapping[FieldKey, str | None], final: Mapping[FieldKey, str | None]
) -> frozenset[FieldKey]:
    """比對上一輪正式提交值與本輪送出值，回傳實際有變動的欄位。

    Raises:
        AppError: RESUBMIT_ITEMS_STRUCTURE_CHANGED（明細新增、刪除或欄位集合不同）。
    """
    if set(previous) != set(final):
        raise _error("本次補正不允許新增、刪除或重排明細", "RESUBMIT_ITEMS_STRUCTURE_CHANGED")
    return frozenset(key for key in final if previous[key] != final[key])


def ensure_edits_authorized(modified: Iterable[FieldKey], allowed: frozenset[FieldKey]) -> None:
    """實際修改的欄位必須都在財務授權範圍內。

    Raises:
        AppError: RESUBMIT_FIELD_NOT_ALLOWED，details 列出未授權欄位。
    """
    denied = sorted(key for key in modified if key not in allowed)
    if denied:
        raise AppError(
            "修改了未經財務授權的欄位",
            code="RESUBMIT_FIELD_NOT_ALLOWED",
            details=[{"field_scope": s, "line_no": n, "field_name": f} for s, n, f in denied],
        )


def validate_event_chain(
    previous: Mapping[FieldKey, str | None],
    final: Mapping[FieldKey, str | None],
    events: Iterable[EditEvent],
) -> tuple[EditEvent, ...]:
    """驗證逐次編輯事件鏈：起點為上一輪正式提交值，終點為本輪送出值，且只含存在的欄位。

    沒有事件的修改欄位由呼叫端依淨差異另外處理；事件不能涵蓋未改變卻有事件的矛盾（鏈終點必須等於送出值）。

    Raises:
        AppError: RESUBMIT_EVENTS_INVALID。
    """
    last: dict[FieldKey, str | None] = {}
    result: list[EditEvent] = []
    for event in events:
        if event.key not in final:
            raise _error("編輯事件的欄位不存在", "RESUBMIT_EVENTS_INVALID")
        if event.old == event.new or event.old != last.get(event.key, previous[event.key]):
            raise _error("編輯事件無法從上一輪提交值接續", "RESUBMIT_EVENTS_INVALID")
        last[event.key] = event.new
        result.append(event)
    if any(value != final[key] for key, value in last.items()):
        raise _error("編輯事件的終點與送出值不一致", "RESUBMIT_EVENTS_INVALID")
    return tuple(result)


def validate_responses(
    items: Iterable[ReturnItem],
    responses: Iterable[Response],
    modified: frozenset[FieldKey],
) -> tuple[Response, ...]:
    """每個欄位退件項目都要有回覆；申覆必填說明；聲稱補正的項目必須實際修改其授權欄位。

    純申覆（全部為 appealed、沒有任何修改）合法，不因缺少修改事件而拒絕。

    Raises:
        AppError: RESUBMIT_RESPONSES_INCOMPLETE。
    """
    field_items = {item.return_item_id: item for item in items if item.kind == KIND_FIELD}
    by_id: dict[str, Response] = {}
    for response in responses:
        if response.return_item_id not in field_items or response.return_item_id in by_id:
            raise _error("回覆對應的退件項目不存在或重複", "RESUBMIT_RESPONSES_INCOMPLETE")
        by_id[response.return_item_id] = response
    if set(by_id) != set(field_items):
        raise _error("尚有退件項目未回覆", "RESUBMIT_RESPONSES_INCOMPLETE")
    for response in by_id.values():
        if response.action == ACTION_APPEALED:
            if not (response.note or "").strip():
                raise _error("申覆必須填寫說明", "RESUBMIT_RESPONSES_INCOMPLETE")
        elif response.action == ACTION_CORRECTED:
            item = field_items[response.return_item_id]
            scope = ({item.target} if item.target else set()) | item.allowed
            if not scope & modified:
                raise _error("標示為已補正，但相關欄位沒有修改", "RESUBMIT_RESPONSES_INCOMPLETE")
        else:
            raise _error("回覆方式不正確", "RESUBMIT_RESPONSES_INCOMPLETE")
    return tuple(by_id.values())


def review_scope(
    items: Iterable[ReturnItem],
    responses: Iterable[Response],
    modified: frozenset[FieldKey],
    all_fields: Iterable[FieldKey],
) -> ReviewScope:
    """本輪需重新覆核：被退回的欄位、實際修改的授權欄位與被申覆的項目；其餘承接前輪確認。"""
    appealed = {r.return_item_id for r in responses if r.action == ACTION_APPEALED}
    rereview: set[FieldKey] = set(modified)
    for item in items:
        if item.kind == KIND_FIELD and item.target is not None:
            rereview.add(item.target)
            if item.return_item_id in appealed:
                rereview |= item.allowed
    universe = frozenset(all_fields)
    rereview &= universe
    return ReviewScope(frozenset(rereview), universe - rereview)


def request_fingerprint(payload: Mapping[str, Any]) -> str:
    """冪等請求指紋：排除 idempotency_key 本身，其餘內容的正規化 JSON SHA-256。

    同 key 同指紋回放原結果；同 key 不同指紋必須拒絕（由呼叫端比對）。
    """
    body = {k: v for k, v in payload.items() if k != "idempotency_key"}
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()
