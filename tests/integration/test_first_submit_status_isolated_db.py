"""
測試目標：W1——首次提交的目標狀態為 pending_accounting_review，並在隔離 PostgreSQL 上以真實 SQL 驗證。
涵蓋：資料庫、回應與狀態歷程一致；原始資料、影像、修改紀錄與欄位複核仍完整保存；
既有 pending_department_approval 案件不被修改且列表與詳情仍可讀取；查重與併發由 W15 同目錄測試涵蓋。
需要 ISOLATED_DB_URL（限本機回送位址，見 conftest）；未設定則略過。
"""

from decimal import Decimal

from isolated_db import World
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from test_invoice_duplicate_isolated_db import (
    build_request,
    make_recognition,
    new_key,
    session_for,
    set_status,
    snapshot,
    submit,
)

from app.services import invoice_detail_service, invoice_list_service
from app.services import invoice_upload_service as service

FIRST_SUBMIT_STATUS = "pending_accounting_review"
LEGACY_STATUS = "pending_department_approval"


def test_first_submit_status_is_consistent_in_response_database_and_history(
    engine: Engine, world: World
) -> None:
    key = new_key()
    recognition_id = make_recognition(world)
    with Session(engine) as db:
        response = service.submit(db, session_for(world), build_request(recognition_id, key))

    with engine.connect() as conn:
        db_status, db_round = conn.execute(
            text("SELECT status, submission_round FROM public.invoices WHERE invoice_id = :i"),
            {"i": response.invoice_id},
        ).one()
        history = conn.execute(
            text(
                "SELECT old_status, new_status, changed_by FROM public.invoice_status_history"
                " WHERE invoice_id = :i"
            ),
            {"i": response.invoice_id},
        ).all()

    assert response.status == db_status == FIRST_SUBMIT_STATUS
    assert db_round == 1
    assert history == [(None, FIRST_SUBMIT_STATUS, world.user_id)]


def test_first_submit_still_saves_data_image_and_edit_history(engine: Engine, world: World) -> None:
    key = new_key()
    recognition_id = make_recognition(world)
    with Session(engine) as db:
        response = service.submit(db, session_for(world), build_request(recognition_id, key))
    saved = snapshot(engine, response.invoice_id)

    (invoice,) = saved["invoices"]
    assert (invoice["invoice_track"], invoice["invoice_number"], invoice["seller_tax_id"]) == (
        key["invoice_track"],
        key["invoice_number"],
        key["seller_tax_id"],
    )
    assert (invoice["sales_amount"], invoice["tax_amount"], invoice["total_amount"]) == (
        Decimal("1000"),
        Decimal("50"),
        Decimal("1050"),
    )
    assert invoice["submitted_by"] == world.user_id
    assert invoice["department_id"] == world.department_id
    assert [row["item_name"] for row in saved["invoice_items"]] == ["W15 品名"]
    (stored_file,) = saved["invoice_files"]
    assert stored_file["storage_path"].endswith(f"_{recognition_id}.jpg")
    assert stored_file["is_current"] is True
    # AI 原值為空，所以每個送出欄位都有修改紀錄；其中包含測試指定的 seller_name 修改
    changed = {row["field_name"] for row in saved["invoice_changes"]}
    assert {"seller_name", "invoice_track", "invoice_number"} <= changed
    assert {row["submission_round"] for row in saved["invoice_changes"]} == {1}
    assert {row["changed_by"] for row in saved["invoice_changes"]} == {world.user_id}
    assert saved["invoice_field_reviews"]  # 與 AI 原值不同的欄位仍寫入覆核標示
    with engine.connect() as conn:
        linked = conn.execute(
            text("SELECT invoice_id FROM public.ai_recognition_logs WHERE recognition_id = :r"),
            {"r": recognition_id},
        ).scalar_one()
    assert linked == response.invoice_id


def test_legacy_status_cases_stay_untouched_and_readable(engine: Engine, world: World) -> None:
    legacy_id = submit(engine, world, new_key())
    set_status(engine, legacy_id, LEGACY_STATUS)
    before = snapshot(engine, legacy_id)

    new_id = submit(engine, world, new_key())  # 另一個查重鍵的新案
    current = session_for(world)

    assert snapshot(engine, legacy_id) == before  # 舊狀態案件不被改動
    with Session(engine) as db:
        listing = invoice_list_service.list_my_invoices(
            db, current, page=1, page_size=50, status=None
        )
        legacy_only = invoice_list_service.list_my_invoices(
            db, current, page=1, page_size=50, status=LEGACY_STATUS
        )
        new_only = invoice_list_service.list_my_invoices(
            db, current, page=1, page_size=50, status=FIRST_SUBMIT_STATUS
        )
        legacy_detail = invoice_detail_service.get_invoice_detail(db, current, legacy_id)
        new_detail = invoice_detail_service.get_invoice_detail(db, current, new_id)

    statuses = {item.invoice_id: item.status for item in listing.items}
    assert statuses == {legacy_id: LEGACY_STATUS, new_id: FIRST_SUBMIT_STATUS}
    assert [item.invoice_id for item in legacy_only.items] == [legacy_id]
    assert [item.invoice_id for item in new_only.items] == [new_id]
    assert legacy_detail.status == LEGACY_STATUS and legacy_detail.submission_round == 1
    assert new_detail.status == FIRST_SUBMIT_STATUS and new_detail.submission_round == 1
