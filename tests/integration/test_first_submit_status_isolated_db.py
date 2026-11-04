"""
測試目標：W1——首次提交的目標狀態為 pending_accounting_review，並在隔離 PostgreSQL 上以真實 SQL 驗證。
涵蓋：資料庫、回應與狀態歷程一致；原始資料、影像、修改紀錄與欄位複核仍完整保存；
既有 pending_department_approval 案件不被修改且列表與詳情仍可讀取；查重與併發由 W15 同目錄測試涵蓋。
需要 ISOLATED_DB_URL（限本機回送位址，見 conftest）；未設定則略過。
"""

from decimal import Decimal

import pytest
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

from app.db.repositories import resubmit_repository
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


def _snapshots(engine: Engine, invoice_id: object) -> list[dict[str, object]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT submission_round, submission_kind, header, items, file_id, submitted_by"
                " FROM public.invoice_submission_snapshots WHERE invoice_id = :i"
            ),
            {"i": invoice_id},
        ).mappings()
        return [dict(row) for row in rows]


def test_first_submit_writes_round_one_snapshot_with_header_items_and_image(
    engine: Engine, world: World
) -> None:
    key = new_key()
    with Session(engine) as db:
        response = service.submit(
            db, session_for(world), build_request(make_recognition(world), key)
        )
    (snap,) = _snapshots(engine, response.invoice_id)
    saved = snapshot(engine, response.invoice_id)
    (stored_file,) = saved["invoice_files"]
    (item,) = saved["invoice_items"]

    assert (snap["submission_round"], snap["submission_kind"]) == (1, "first")
    assert snap["file_id"] == stored_file["file_id"]
    assert snap["submitted_by"] == world.user_id
    header = snap["header"]
    assert isinstance(header, dict)
    assert header["invoice_track"] == key["invoice_track"]
    assert (header["sales_amount"], header["tax_amount"], header["total_amount"]) == (
        "1000",
        "50",
        "1050",
    )
    (snap_item,) = snap["items"]  # type: ignore[misc]
    assert snap_item["item_id"] == str(item["item_id"]) and snap_item["line_no"] == 1


def test_first_submit_without_snapshot_table_still_succeeds(
    engine: Engine, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Migration 尚未套用的資料庫：略過快照，其餘資料照常保存。"""
    monkeypatch.setattr(resubmit_repository, "snapshot_table_exists", lambda db: False)
    with Session(engine) as db:
        response = service.submit(
            db, session_for(world), build_request(make_recognition(world), new_key())
        )
    assert response.status == FIRST_SUBMIT_STATUS
    assert _snapshots(engine, response.invoice_id) == []
    assert snapshot(engine, response.invoice_id)["invoice_items"]


def test_snapshot_failure_rolls_back_the_whole_first_submission(
    engine: Engine, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """快照表存在但寫入失敗：不得靜默成功，整筆交易回滾，辨識紀錄維持未送出且可重試。"""

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated snapshot failure")

    key = new_key()
    recognition_id = make_recognition(world)
    request = build_request(recognition_id, key)
    monkeypatch.setattr(resubmit_repository, "insert_snapshot", boom)
    with Session(engine) as db, pytest.raises(RuntimeError):
        service.submit(db, session_for(world), request)

    with engine.connect() as conn:
        counts = conn.execute(
            text(
                "SELECT (SELECT count(*) FROM public.invoices WHERE submitted_by = :u),"
                " (SELECT count(*) FROM public.invoice_files f JOIN public.invoices i USING (invoice_id)"
                "   WHERE i.submitted_by = :u),"
                " (SELECT count(*) FROM public.invoice_status_history h JOIN public.invoices i USING (invoice_id)"
                "   WHERE i.submitted_by = :u),"
                " (SELECT invoice_id FROM public.ai_recognition_logs WHERE recognition_id = :r)"
            ),
            {"u": world.user_id, "r": recognition_id},
        ).one()
    assert tuple(counts) == (0, 0, 0, None)

    monkeypatch.undo()  # 回復後同一筆辨識可重試成功，且有第 1 輪快照
    with Session(engine) as db:
        response = service.submit(db, session_for(world), request)
    assert response.status == FIRST_SUBMIT_STATUS
    assert [s["submission_round"] for s in _snapshots(engine, response.invoice_id)] == [1]
