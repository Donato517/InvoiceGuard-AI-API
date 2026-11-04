"""
測試目標：發票查重規則在隔離 PostgreSQL 上以真實 SQL 驗證（不使用 Mock）。
涵蓋：已作廢（voided）案件不阻擋同查重鍵的新案；新舊 invoice_id 不同且舊案資料完全不變；
未作廢的任何狀態仍阻擋；voided 沒有任何可重新啟用的寫入路徑；同鍵並發送出只會成功一筆。
需要 ISOLATED_DB_URL（限本機回送位址，見 conftest）；未設定則略過。不修改任何業務規則。
"""

import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from isolated_db import World
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.db.repositories import invoice_repository
from app.schemas.auth import DepartmentRead, SessionRead
from app.schemas.invoice_upload import (
    DuplicateCheckRequest,
    FieldChangeSubmit,
    InvoiceItemSubmit,
    InvoiceSubmitRequest,
)
from app.services import invoice_upload_service as service

SELLER_TAX_ID = "04595257"  # 通過統編檢查碼的合成值
NON_VOIDED_STATUSES = [
    "draft",
    "pending_department_approval",
    "pending_accounting_review",
    "pending_accounting_approval",
    "approved",
    "returned_to_applicant",
    "returned_to_accounting",
    "rejected",
]
CASE_TABLES = {
    "invoices": "SELECT * FROM public.invoices WHERE invoice_id = :i",
    "invoice_items": "SELECT * FROM public.invoice_items WHERE invoice_id = :i ORDER BY line_no",
    "invoice_files": "SELECT * FROM public.invoice_files WHERE invoice_id = :i ORDER BY version_no",
    "invoice_changes": (
        "SELECT * FROM public.invoice_changes WHERE invoice_id = :i ORDER BY changed_at, change_id"
    ),
    "invoice_field_reviews": (
        "SELECT * FROM public.invoice_field_reviews WHERE invoice_id = :i"
        " ORDER BY submission_round, field_scope, field_name, field_review_id"
    ),
    "invoice_status_history": (
        "SELECT * FROM public.invoice_status_history WHERE invoice_id = :i"
        " ORDER BY changed_at, history_id"
    ),
}


def new_key() -> dict[str, str]:
    """每個測試用獨立的查重鍵，避免彼此干擾。"""
    digits = f"{uuid4().int % 10**8:08d}"
    return {"invoice_track": "ZZ", "invoice_number": digits, "seller_tax_id": SELLER_TAX_ID}


def session_for(world: World) -> SessionRead:
    from datetime import UTC, datetime, timedelta

    department = DepartmentRead(
        department_id=world.department_id,
        department_code=world.department_code,
        department_name="W15 測試部",
        is_primary=True,
    )
    return SessionRead(
        user_id=world.user_id,
        email=world.email,
        display_name="W15",
        department=department,
        departments=(department,),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def make_recognition(world: World) -> UUID:
    """寫入一筆可供送出的成功辨識紀錄（合成資料；影像路徑只是字串，不連 Storage）。"""
    recognition_id = uuid4()
    path = f"{world.user_id}/INVOICES_20261102000000_{recognition_id}.jpg"
    with world.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.ai_recognition_logs"
                "(recognition_id, source_storage_path, ai_provider, result_status, requested_by,"
                " extracted_fields, raw_response)"
                " VALUES (:r, :p, 'w15-test', 'success', :u, CAST(:e AS jsonb), CAST(:w AS jsonb))"
            ),
            {
                "r": recognition_id,
                "p": path,
                "u": world.user_id,
                "e": json.dumps({"invoice": {}}),
                "w": json.dumps({"source": {"filename": "w15.jpg", "size_bytes": 1234}}),
            },
        )
    return recognition_id


def build_request(recognition_id: UUID, key: dict[str, str]) -> InvoiceSubmitRequest:
    return InvoiceSubmitRequest(
        recognition_id=recognition_id,
        invoice_date=date(2026, 10, 15),
        seller_name="W15 賣方",
        tax_type="taxable",
        sales_amount=Decimal("1000"),
        tax_amount=Decimal("50"),
        total_amount=Decimal("1050"),
        items=(InvoiceItemSubmit(item_name="W15 品名", line_amount=Decimal("1000")),),
        changes=(
            FieldChangeSubmit(
                field_scope="header", field_name="seller_name", old_value=None, new_value="W15 賣方"
            ),
        ),
        **key,
    )


def submit(engine: Engine, world: World, key: dict[str, str]) -> UUID:
    request = build_request(make_recognition(world), key)
    with Session(engine) as db:
        return service.submit(db, session_for(world), request).invoice_id


def is_duplicate(engine: Engine, key: dict[str, str]) -> bool:
    with Session(engine) as db:
        return service.check_duplicate(db, DuplicateCheckRequest(**key)).is_duplicate


def snapshot(engine: Engine, invoice_id: UUID) -> dict[str, list[dict[str, Any]]]:
    with engine.connect() as conn:
        return {
            name: [dict(row) for row in conn.execute(text(sql), {"i": invoice_id}).mappings()]
            for name, sql in CASE_TABLES.items()
        }


def set_status(engine: Engine, invoice_id: UUID, status: str) -> None:
    """測試中以 SQL 模擬狀態（作廢端點尚不存在，W2 之前沒有正式的寫入路徑）。"""
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE public.invoices SET status = :s WHERE invoice_id = :i"),
            {"s": status, "i": invoice_id},
        )
        conn.execute(
            text(
                "INSERT INTO public.invoice_status_history(invoice_id, old_status, new_status,"
                " reason, changed_by) VALUES (:i, NULL, :s, 'w15 test', NULL)"
            ),
            {"i": invoice_id, "s": status},
        )


def count_same_key(engine: Engine, key: dict[str, str]) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT count(*) FROM public.invoices WHERE invoice_track = :invoice_track"
                " AND invoice_number = :invoice_number AND seller_tax_id = :seller_tax_id"
            ),
            key,
        ).scalar_one()


def test_baseline_a_live_case_blocks_the_same_key(engine: Engine, world: World) -> None:
    key = new_key()
    submit(engine, world, key)

    assert is_duplicate(engine, key) is True
    with pytest.raises(ConflictError) as error:
        submit(engine, world, key)
    assert error.value.code == "INVOICE_DUPLICATED"
    assert count_same_key(engine, key) == 1


def test_voided_case_does_not_block_a_new_case_with_a_new_invoice_id(
    engine: Engine, world: World
) -> None:
    key = new_key()
    old_id = submit(engine, world, key)
    set_status(engine, old_id, "voided")

    assert is_duplicate(engine, key) is False
    new_id = submit(engine, world, key)

    assert new_id != old_id
    assert count_same_key(engine, key) == 2
    with engine.connect() as conn:
        statuses = dict(
            conn.execute(
                text("SELECT invoice_id, status FROM public.invoices WHERE invoice_id = ANY(:i)"),
                {"i": [old_id, new_id]},
            ).all()
        )
    assert statuses[old_id] == "voided"
    assert statuses[new_id] == "pending_accounting_review"  # W1：首次提交狀態


def test_old_voided_case_is_untouched_by_the_new_case(engine: Engine, world: World) -> None:
    key = new_key()
    old_id = submit(engine, world, key)
    set_status(engine, old_id, "voided")
    before = snapshot(engine, old_id)
    assert all(before[name] for name in ("invoices", "invoice_items", "invoice_files"))
    assert before["invoice_changes"] and before["invoice_field_reviews"]

    new_id = submit(engine, world, key)

    assert snapshot(engine, old_id) == before  # 舊案所有表逐欄相同（含 updated_at）
    assert new_id != old_id


def test_new_case_has_its_own_files_history_and_round(engine: Engine, world: World) -> None:
    key = new_key()
    old_id = submit(engine, world, key)
    set_status(engine, old_id, "voided")
    old = snapshot(engine, old_id)

    new_id = submit(engine, world, key)
    new = snapshot(engine, new_id)

    old_paths = {row["storage_path"] for row in old["invoice_files"]}
    new_paths = {row["storage_path"] for row in new["invoice_files"]}
    assert old_paths.isdisjoint(new_paths)  # 影像物件各自獨立
    assert [row["is_current"] for row in old["invoice_files"]] == [True]
    assert [row["is_current"] for row in new["invoice_files"]] == [True]
    assert {row["submission_round"] for row in new["invoice_changes"]} == {1}
    assert {row["submission_round"] for row in new["invoice_field_reviews"]} == {1}
    assert new["invoices"][0]["submission_round"] == 1
    assert {row["invoice_id"] for row in new["invoice_status_history"]} == {new_id}
    assert [row["new_status"] for row in new["invoice_status_history"]] == [
        "pending_accounting_review"
    ]
    # 兩案的修改紀錄與欄位複核互不共用
    assert {row["change_id"] for row in old["invoice_changes"]}.isdisjoint(
        {row["change_id"] for row in new["invoice_changes"]}
    )


@pytest.mark.parametrize("status", NON_VOIDED_STATUSES)
def test_every_non_voided_status_still_blocks_the_same_key(
    engine: Engine, world: World, status: str
) -> None:
    key = new_key()
    first_id = submit(engine, world, key)
    set_status(engine, first_id, status)
    before = snapshot(engine, first_id)

    assert is_duplicate(engine, key) is True
    with pytest.raises(ConflictError) as error:
        submit(engine, world, key)

    assert error.value.code == "INVOICE_DUPLICATED"
    assert count_same_key(engine, key) == 1
    assert snapshot(engine, first_id) == before  # 被擋下的送出不改動既有案件


def test_a_different_seller_tax_id_is_not_a_duplicate(engine: Engine, world: World) -> None:
    key = new_key()
    submit(engine, world, key)
    other = {**key, "seller_tax_id": "10458570"}

    assert is_duplicate(engine, other) is False
    submit(engine, world, other)
    assert count_same_key(engine, key) == 1
    assert count_same_key(engine, other) == 1


def test_rejected_submit_on_voided_key_never_reactivates_the_old_id(
    engine: Engine, world: World
) -> None:
    """目前唯一能對相同鍵「再送出」的路徑是 POST /invoices：它只會 INSERT 新案，不會更新舊列。"""
    key = new_key()
    old_id = submit(engine, world, key)
    set_status(engine, old_id, "voided")
    before = snapshot(engine, old_id)

    submit(engine, world, key)
    submit_blocked = False
    try:
        submit(engine, world, key)  # 第三次：此時新案未作廢，應被擋下
    except ConflictError:
        submit_blocked = True

    assert submit_blocked
    assert snapshot(engine, old_id) == before
    assert before["invoices"][0]["status"] == "voided"


def run_concurrently(jobs: list[Callable[[], Any]]) -> list[Any]:
    """讓所有工作在同一時間點開始；回傳每個工作的結果或例外。"""
    barrier = threading.Barrier(len(jobs))

    def wrap(job: Callable[[], Any]) -> Any:
        barrier.wait(timeout=10)
        try:
            return job()
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        return [future.result(timeout=60) for future in [pool.submit(wrap, job) for job in jobs]]


@pytest.mark.parametrize("round_no", range(5))
def test_concurrent_submits_of_the_same_key_create_exactly_one_case(
    engine: Engine, world: World, round_no: int
) -> None:
    key = new_key()
    requests = [build_request(make_recognition(world), key) for _ in range(2)]

    def job(request: InvoiceSubmitRequest) -> Callable[[], UUID]:
        def run() -> UUID:
            with Session(engine) as db:
                return service.submit(db, session_for(world), request).invoice_id

        return run

    results = run_concurrently([job(request) for request in requests])

    successes = [item for item in results if isinstance(item, UUID)]
    failures = [item for item in results if isinstance(item, ConflictError)]
    assert len(successes) == 1 and len(failures) == 1, results
    assert failures[0].code == "INVOICE_DUPLICATED"
    assert count_same_key(engine, key) == 1


def test_control_without_the_key_lock_duplicates_can_slip_through(
    engine: Engine, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """對照組：拿掉查重鍵的鎖並讓檢查後稍待，兩筆同鍵送出會同時通過——證明上面的測試確實在驗證鎖。

    資料庫沒有號碼唯一約束，所以防線只有 lock_invoice_key（pg_advisory_xact_lock）。
    """
    key = new_key()
    original_exists = invoice_repository.exists_duplicate

    def slow_exists(db: Session, **identity: str) -> bool:
        found = original_exists(db, **identity)
        time.sleep(0.4)  # 讓另一個交易也完成檢查
        return found

    monkeypatch.setattr(invoice_repository, "lock_invoice_key", lambda db, **identity: None)
    monkeypatch.setattr(invoice_repository, "exists_duplicate", slow_exists)
    requests = [build_request(make_recognition(world), key) for _ in range(2)]

    def job(request: InvoiceSubmitRequest) -> Callable[[], UUID]:
        def run() -> UUID:
            with Session(engine) as db:
                return service.submit(db, session_for(world), request).invoice_id

        return run

    results = run_concurrently([job(request) for request in requests])

    assert all(isinstance(item, UUID) for item in results), results
    assert count_same_key(engine, key) == 2
