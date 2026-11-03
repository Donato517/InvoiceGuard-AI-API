"""
模組名稱：tests.unit.test_invoice_resubmit_rules
功能說明：測試退回重送的純規則（不連 DB、Storage 或外部服務）。這些是單元測試，不能取代真實 PostgreSQL 的交易與併發測試。
"""

import pytest

from app.core.exceptions import AppError
from app.services.invoice_resubmit_rules import (
    EditEvent,
    Response,
    ReturnItem,
    allowed_fields,
    ensure_edits_authorized,
    ensure_resubmit_allowed,
    modified_fields,
    request_fingerprint,
    review_scope,
    validate_event_chain,
    validate_responses,
)

TOTAL = ("header", None, "total_amount")
SALES = ("header", None, "sales_amount")
TAX = ("header", None, "tax_amount")
SELLER = ("header", None, "seller_tax_id")
PREV = {TOTAL: "1050", SALES: "1000", TAX: "50", SELLER: "12345675"}

FIELD = ReturnItem("r1", "field", "總計錯", TOTAL, frozenset({SALES, TAX}))
IMAGE = ReturnItem("r2", "image", "模糊")


def code(exc: pytest.ExceptionInfo[AppError]) -> str:
    return exc.value.code


def test_image_problem_blocks_resubmit_even_with_field_problem() -> None:
    with pytest.raises(AppError) as exc:
        ensure_resubmit_allowed([FIELD, IMAGE])
    assert code(exc) == "RESUBMIT_IMAGE_REQUIRES_VOID"
    ensure_resubmit_allowed([FIELD])


def test_allowed_fields_includes_target_and_dependents_only() -> None:
    assert allowed_fields([FIELD, IMAGE]) == {TOTAL, SALES, TAX}


def test_unauthorized_edit_rejected_and_authorized_passes() -> None:
    final = {**PREV, SELLER: "99999999"}
    modified = modified_fields(PREV, final)
    with pytest.raises(AppError) as exc:
        ensure_edits_authorized(modified, allowed_fields([FIELD]))
    assert code(exc) == "RESUBMIT_FIELD_NOT_ALLOWED"
    ensure_edits_authorized(modified_fields(PREV, {**PREV, TOTAL: "1100"}), allowed_fields([FIELD]))


def test_item_structure_change_rejected() -> None:
    with pytest.raises(AppError) as exc:
        modified_fields(PREV, {**PREV, ("item", 1, "item_name"): "x"})
    assert code(exc) == "RESUBMIT_ITEMS_STRUCTURE_CHANGED"


def test_event_chain_starts_from_previous_submission_not_ai_value() -> None:
    final = {**PREV, TOTAL: "1100"}
    chain = [EditEvent(TOTAL, "1050", "1060"), EditEvent(TOTAL, "1060", "1100")]
    assert validate_event_chain(PREV, final, chain) == tuple(chain)
    for bad in (
        [EditEvent(TOTAL, "999", "1100")],  # 起點不是上一輪提交值
        [EditEvent(TOTAL, "1050", "1060")],  # 終點不等於送出值
        [EditEvent(TOTAL, "1050", "1050")],  # 無變動
        [EditEvent(("header", None, "nope"), "a", "b")],  # 欄位不存在
    ):
        with pytest.raises(AppError) as exc:
            validate_event_chain(PREV, final, bad)
        assert code(exc) == "RESUBMIT_EVENTS_INVALID"


def test_pure_appeal_without_changes_is_valid() -> None:
    responses = validate_responses([FIELD], [Response("r1", "appealed", "金額正確")], frozenset())
    assert len(responses) == 1


@pytest.mark.parametrize(
    "responses,modified",
    [
        ([], frozenset()),  # 未回覆
        ([Response("r1", "appealed", " ")], frozenset()),  # 申覆缺說明
        ([Response("r1", "corrected")], frozenset()),  # 聲稱補正卻沒改
        ([Response("rX", "appealed", "x")], frozenset()),  # 不存在的項目
        ([Response("r1", "appealed", "x"), Response("r1", "appealed", "y")], frozenset()),
        ([Response("r1", "ignored")], frozenset()),
    ],
)
def test_incomplete_responses_rejected(
    responses: list[Response], modified: frozenset[tuple[str, int | None, str]]
) -> None:
    with pytest.raises(AppError) as exc:
        validate_responses([FIELD], responses, modified)
    assert code(exc) == "RESUBMIT_RESPONSES_INCOMPLETE"


def test_review_scope_separates_rereview_from_carried() -> None:
    scope = review_scope(
        [FIELD], [Response("r1", "corrected")], frozenset({TOTAL, TAX}), PREV.keys()
    )
    assert scope.rereview == {TOTAL, TAX}
    assert scope.carried == {SALES, SELLER}
    assert not scope.rereview & scope.carried


def test_pure_appeal_rereviews_target_and_dependents() -> None:
    scope = review_scope([FIELD], [Response("r1", "appealed", "x")], frozenset(), PREV.keys())
    assert scope.rereview == {TOTAL, SALES, TAX}
    assert scope.carried == {SELLER}


def test_fingerprint_ignores_key_and_detects_content_change() -> None:
    a = request_fingerprint({"idempotency_key": "k1", "expected_round": 1, "total": "1"})
    assert a == request_fingerprint({"total": "1", "expected_round": 1, "idempotency_key": "k2"})
    assert a != request_fingerprint({"idempotency_key": "k1", "expected_round": 1, "total": "2"})
