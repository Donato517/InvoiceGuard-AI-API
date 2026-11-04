"""
測試目標：重送歷史表（Migration 7c1d4e9a2b30）的資料保護，在專屬隔離 PostgreSQL 上以真實 SQL 驗證。
涵蓋：快照／冪等／承接／退件項目不可修改、刪除或清空；FK 阻擋刪除有歷史的發票；合法的申請人回覆、財務處理與
一般覆核勾選不受影響；承接列有效性；冪等與輪次唯一性；編輯事件序號唯一。
需要專屬資料庫模式（ISOLATED_ADMIN_URL、ISOLATED_BASELINE_SQL，見 conftest）；未設定或僅有既有資料庫則略過。
這些測試不停用任何 Trigger 或 FK，資料隨專屬資料庫一起刪除。
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from isolated_db import World
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError


def run(engine: Engine, sql: str, **params: Any) -> Any:
    with engine.begin() as conn:
        return conn.execute(text(sql), params)


def rejected(engine: Engine, sql: str, **params: Any) -> str:
    """執行應被資料庫拒絕的語句，回傳錯誤訊息。"""
    with pytest.raises(DBAPIError) as caught:
        run(engine, sql, **params)
    return str(caught.value)


def seed_invoice(engine: Engine, world: World, *, round_no: int = 1) -> UUID:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO public.invoices(invoice_track, invoice_number, status, submission_round,"
                " submitted_by, department_id) VALUES ('AB', :n, 'pending_accounting_review', :r, :u, :d)"
                " RETURNING invoice_id"
            ),
            {"n": uuid4().hex[:8], "r": round_no, "u": world.user_id, "d": world.department_id},
        ).scalar_one()


def seed_review(
    engine: Engine, world: World, invoice_id: UUID, round_no: int, field: str, *, checked: bool
) -> UUID:
    return run(
        engine,
        "INSERT INTO public.invoice_field_reviews(invoice_id, submission_round, field_scope, field_name,"
        " is_checked, checked_by, checked_at) VALUES (:i, :r, 'header', :f, :c, CASE WHEN :c THEN CAST(:u AS uuid) END,"
        " CASE WHEN :c THEN now() END) RETURNING field_review_id",
        i=invoice_id,
        r=round_no,
        f=field,
        c=checked,
        u=world.user_id,
    ).scalar_one()


CARRY = (
    "INSERT INTO public.invoice_field_review_carryovers(invoice_id, submission_round, field_scope, field_name,"
    " source_field_review_id) VALUES (:i, :r, 'header', :f, :s)"
)


def test_snapshot_is_immutable_and_blocks_invoice_deletion(
    managed_engine: Engine, world: World
) -> None:
    invoice_id = seed_invoice(managed_engine, world)
    run(
        managed_engine,
        "INSERT INTO public.invoice_submission_snapshots(invoice_id, submission_round, submission_kind, header, items)"
        " VALUES (:i, 1, 'first', '{}', '[]')",
        i=invoice_id,
    )
    for sql in (
        "UPDATE public.invoice_submission_snapshots SET header = jsonb_build_object('x', 1) WHERE invoice_id = :i",
        "DELETE FROM public.invoice_submission_snapshots WHERE invoice_id = :i",
        "TRUNCATE public.invoice_submission_snapshots",
    ):
        assert "歷史紀錄" in rejected(managed_engine, sql, i=invoice_id)
    assert "foreign key" in rejected(
        managed_engine, "DELETE FROM public.invoices WHERE invoice_id = :i", i=invoice_id
    )
    count = run(
        managed_engine, "SELECT count(*) FROM public.invoices WHERE invoice_id = :i", i=invoice_id
    ).scalar_one()
    assert count == 1


def test_snapshot_round_is_unique_and_items_must_be_an_array(
    managed_engine: Engine, world: World
) -> None:
    invoice_id = seed_invoice(managed_engine, world)
    insert = (
        "INSERT INTO public.invoice_submission_snapshots(invoice_id, submission_round, submission_kind, header, items)"
        " VALUES (:i, :r, 'first', '{}', CAST(:items AS jsonb))"
    )
    run(managed_engine, insert, i=invoice_id, r=1, items="[]")
    rejected(managed_engine, insert, i=invoice_id, r=1, items="[]")
    rejected(managed_engine, insert, i=invoice_id, r=2, items="{}")


def test_return_item_keeps_original_reason_but_accepts_response_and_resolution(
    managed_engine: Engine, world: World
) -> None:
    invoice_id = seed_invoice(managed_engine, world)
    item_id = run(
        managed_engine,
        "INSERT INTO public.invoice_return_items(invoice_id, submission_round, item_kind, field_scope, field_name,"
        " reason, allowed_fields) VALUES (:i, 1, 'field', 'header', 'total_amount', '總計錯',"
        ' \'[{"field_scope":"header","field_name":"tax_amount"}]\') RETURNING return_item_id',
        i=invoice_id,
    ).scalar_one()
    run(
        managed_engine,
        "UPDATE public.invoice_return_items SET status = 'appealed', response_action = 'appealed',"
        " response_note = '金額正確', responded_by = :u, responded_at = now(), response_round = 2 WHERE return_item_id = :r",
        u=world.user_id,
        r=item_id,
    )
    run(
        managed_engine,
        "UPDATE public.invoice_return_items SET status = 'accepted', resolved_by = :u, resolved_at = now(),"
        " resolution_note = '接受' WHERE return_item_id = :r",
        u=world.user_id,
        r=item_id,
    )
    for sql in (
        "UPDATE public.invoice_return_items SET reason = '改寫' WHERE return_item_id = :r",
        "UPDATE public.invoice_return_items SET allowed_fields = '[]' WHERE return_item_id = :r",
        "DELETE FROM public.invoice_return_items WHERE return_item_id = :r",
        "TRUNCATE public.invoice_return_items",
    ):
        rejected(managed_engine, sql, r=item_id)
    row = run(
        managed_engine,
        "SELECT reason, status, response_note FROM public.invoice_return_items WHERE return_item_id = :r",
        r=item_id,
    ).one()
    assert tuple(row) == ("總計錯", "accepted", "金額正確")


@pytest.mark.parametrize(
    "columns,values",
    [
        (
            "item_kind, field_scope, field_name, reason",
            "'field', 'header', NULL, 'x'",
        ),  # 欄位退件缺欄位名稱
        (
            "item_kind, field_scope, field_name, reason",
            "'image', 'header', 'total_amount', 'x'",
        ),  # 圖片帶欄位目標
        ("item_kind, reason", "'image', '   '"),  # 原因全空白
        (
            "item_kind, reason, status, response_action, response_note, responded_at, response_round",
            "'image', 'blur', 'appealed', 'appealed', 'n', now(), 2",  # 圖片不接受申覆
        ),
        (
            "item_kind, field_scope, field_name, reason, status, response_action, responded_at, response_round",
            "'field', 'header', 'tax_amount', 'x', 'appealed', 'appealed', now(), 2",  # 申覆缺說明
        ),
        (
            "item_kind, field_scope, field_name, reason, allowed_fields",
            "'field', 'header', 'tax_amount', 'x', '[1, \"x\"]'",  # 授權欄位格式錯誤
        ),
    ],
)
def test_invalid_return_items_are_rejected(
    managed_engine: Engine, world: World, columns: str, values: str
) -> None:
    invoice_id = seed_invoice(managed_engine, world)
    rejected(
        managed_engine,
        f"INSERT INTO public.invoice_return_items(invoice_id, submission_round, {columns}) VALUES (:i, 1, {values})",
        i=invoice_id,
    )


def test_image_reason_is_stored_and_other_kind_is_not_restricted(
    managed_engine: Engine, world: World
) -> None:
    invoice_id = seed_invoice(managed_engine, world)
    run(
        managed_engine,
        "INSERT INTO public.invoice_return_items(invoice_id, submission_round, item_kind, reason)"
        " VALUES (:i, 1, 'image', '圖片模糊'), (:i, 1, 'other', '其他')",
        i=invoice_id,
    )
    reasons = run(
        managed_engine,
        "SELECT reason FROM public.invoice_return_items WHERE invoice_id = :i ORDER BY reason",
        i=invoice_id,
    )
    assert sorted(row[0] for row in reasons) == ["其他", "圖片模糊"]


def test_carryover_keeps_original_confirmer_and_rejects_invalid_sources(
    managed_engine: Engine, world: World
) -> None:
    other_world = world  # 同一使用者即可；不同發票用另一張
    invoice_id = seed_invoice(managed_engine, world, round_no=3)
    other_invoice = seed_invoice(managed_engine, other_world, round_no=3)
    confirmed = seed_review(managed_engine, world, invoice_id, 1, "invoice_number", checked=True)
    unchecked = seed_review(managed_engine, world, invoice_id, 1, "sales_amount", checked=False)
    other_confirmed = seed_review(
        managed_engine, world, other_invoice, 1, "invoice_number", checked=True
    )

    run(managed_engine, CARRY, i=invoice_id, r=2, f="invoice_number", s=confirmed)
    run(
        managed_engine, CARRY, i=invoice_id, r=3, f="invoice_number", s=confirmed
    )  # 跨三輪仍指向第 1 輪
    source = run(
        managed_engine,
        "SELECT r.submission_round, r.checked_by, r.checked_at IS NOT NULL FROM public.invoice_field_review_carryovers c"
        " JOIN public.invoice_field_reviews r ON r.field_review_id = c.source_field_review_id"
        " WHERE c.invoice_id = :i AND c.submission_round = 3",
        i=invoice_id,
    ).one()
    assert tuple(source) == (1, world.user_id, True)

    bad = [
        dict(i=invoice_id, r=2, f="sales_amount", s=unchecked),  # 來源未確認
        dict(i=invoice_id, r=2, f="tax_amount", s=other_confirmed),  # 別張發票的確認
        dict(i=invoice_id, r=2, f="total_amount", s=confirmed),  # 欄位與來源不同
        dict(i=invoice_id, r=1, f="invoice_number", s=confirmed),  # 與來源同輪
        dict(i=invoice_id, r=4, f="invoice_number", s=confirmed),  # 超過發票目前輪次
    ]
    for params in bad:
        rejected(managed_engine, CARRY, **params)
    rejected(
        managed_engine, "UPDATE public.invoice_field_review_carryovers SET field_name = field_name"
    )
    rejected(managed_engine, "DELETE FROM public.invoice_field_review_carryovers")
    rejected(managed_engine, "TRUNCATE public.invoice_field_review_carryovers")


def test_carried_confirmation_cannot_be_withdrawn_but_other_reviews_work_normally(
    managed_engine: Engine, world: World
) -> None:
    invoice_id = seed_invoice(managed_engine, world, round_no=3)
    carried = seed_review(managed_engine, world, invoice_id, 1, "invoice_number", checked=True)
    run(managed_engine, CARRY, i=invoice_id, r=2, f="invoice_number", s=carried)
    rejected(
        managed_engine,
        "UPDATE public.invoice_field_reviews SET is_checked = false, checked_by = NULL, checked_at = NULL"
        " WHERE field_review_id = :r",
        r=carried,
    )
    rejected(
        managed_engine,
        "DELETE FROM public.invoice_field_reviews WHERE field_review_id = :r",
        r=carried,
    )
    # 同輪同欄位不可同時有承接列與新覆核列
    rejected(
        managed_engine,
        "INSERT INTO public.invoice_field_reviews(invoice_id, submission_round, field_scope, field_name)"
        " VALUES (:i, 2, 'header', 'invoice_number')",
        i=invoice_id,
    )
    # 未被承接的覆核列：財務可正常勾選與取消；被承接列的非確認欄位（備註）也可更新
    pending = seed_review(managed_engine, world, invoice_id, 3, "buyer_name", checked=False)
    run(
        managed_engine,
        "UPDATE public.invoice_field_reviews SET is_checked = true, checked_by = :u, checked_at = now() WHERE field_review_id = :r",
        u=world.user_id,
        r=pending,
    )
    run(
        managed_engine,
        "UPDATE public.invoice_field_reviews SET is_checked = false, checked_by = NULL, checked_at = NULL WHERE field_review_id = :r",
        r=pending,
    )
    run(
        managed_engine,
        "UPDATE public.invoice_field_reviews SET review_comment = '備註' WHERE field_review_id = :r",
        r=carried,
    )


def test_older_confirmation_cannot_be_carried_over_a_newer_review(
    managed_engine: Engine, world: World
) -> None:
    invoice_id = seed_invoice(managed_engine, world, round_no=3)
    old = seed_review(managed_engine, world, invoice_id, 1, "seller_name", checked=True)
    seed_review(
        managed_engine, world, invoice_id, 2, "seller_name", checked=False
    )  # 第 2 輪被退回重審
    rejected(managed_engine, CARRY, i=invoice_id, r=3, f="seller_name", s=old)


def test_idempotency_key_and_round_can_each_be_used_only_once(
    managed_engine: Engine, world: World
) -> None:
    invoice_id = seed_invoice(managed_engine, world)
    insert = (
        "INSERT INTO public.invoice_resubmissions(invoice_id, idempotency_key, request_fingerprint, from_round,"
        " to_round, requested_by, result) VALUES (:i, :k, 'fp', :f, :t, :u, '{}')"
    )
    key = uuid4()
    run(managed_engine, insert, i=invoice_id, k=key, f=1, t=2, u=world.user_id)
    rejected(managed_engine, insert, i=invoice_id, k=key, f=1, t=2, u=world.user_id)  # 同 key
    rejected(
        managed_engine, insert, i=invoice_id, k=uuid4(), f=1, t=2, u=world.user_id
    )  # 新 key 推進同一輪
    rejected(
        managed_engine, insert, i=invoice_id, k=uuid4(), f=2, t=5, u=world.user_id
    )  # 輪次不連續
    rejected(
        managed_engine,
        "UPDATE public.invoice_resubmissions SET result = jsonb_build_object('x', 1)",
    )


def test_edit_event_sequence_is_unique_per_round(managed_engine: Engine, world: World) -> None:
    invoice_id = seed_invoice(managed_engine, world)
    insert = (
        "INSERT INTO public.invoice_changes(invoice_id, submission_round, field_name, event_seq)"
        " VALUES (:i, :r, 'total_amount', :s)"
    )
    run(managed_engine, insert, i=invoice_id, r=2, s=1)
    run(managed_engine, insert, i=invoice_id, r=2, s=2)
    run(managed_engine, insert, i=invoice_id, r=3, s=1)  # 不同輪可重用序號
    rejected(managed_engine, insert, i=invoice_id, r=2, s=2)
    rejected(managed_engine, insert, i=invoice_id, r=2, s=0)
