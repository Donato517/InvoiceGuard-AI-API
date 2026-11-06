"""
測試目標：首次提交在同一交易寫入第 1 輪提交快照（invoice_submission_snapshots，kind=first），在專屬隔離
PostgreSQL 上以真實 SQL 驗證，不使用正式或共用資料庫。
涵蓋：快照內容與送出值／影像／提交者一致；寫入失敗整筆回滾且可重試；同一辨識重複送出不產生重複快照；
新案件重送不重複補建第 1 輪；舊案件（沒有第 1 輪）重送仍補建；快照資料表不存在時明確失敗（503）而非假成功；
非資料表擁有者、非 BYPASSRLS 的角色缺少 GRANT 或 RLS Policy 時明確失敗並整筆回滾，具備權限時成功。
限制：非擁有者角色測試只針對「快照表」的權限與 RLS（其他資料表給予寬鬆權限），不代表正式資料庫角色已核對。
需要專屬資料庫模式（ISOLATED_ADMIN_URL，限本機回送位址，見 conftest）；缺表測試另建自己的專屬資料庫並只刪除它。
"""

import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from db_lifecycle import (
    DEFAULT_BASELINE,
    create_database,
    drop_owned_database,
    load_baseline,
    require_loopback,
)
from isolated_db import World
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session
from test_invoice_duplicate_isolated_db import (
    build_request,
    make_recognition,
    new_key,
    session_for,
)
from test_resubmit_api_isolated_db import body as resubmit_body
from test_resubmit_api_isolated_db import seed_returned_case

from app.core.exceptions import ConflictError, ServiceUnavailableError
from app.db.repositories import resubmit_repository
from app.schemas.invoice_resubmit import InvoiceResubmitRequest
from app.services import invoice_resubmit_service
from app.services import invoice_upload_service as service

SNAPSHOT_TABLE = "public.invoice_submission_snapshots"


def rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def snapshots(engine: Engine, invoice_id: object) -> list[dict[str, Any]]:
    return rows(
        engine,
        f"SELECT * FROM {SNAPSHOT_TABLE} WHERE invoice_id = :i ORDER BY submission_round",
        i=invoice_id,
    )


def persisted_counts(engine: Engine, world: World, recognition_id: UUID) -> tuple[Any, ...]:
    """該使用者已保存的發票／影像／歷程筆數，以及辨識紀錄連到的發票（None＝未送出）。"""
    return tuple(
        rows(
            engine,
            "SELECT (SELECT count(*) FROM public.invoices WHERE submitted_by = :u) AS invoices,"
            " (SELECT count(*) FROM public.invoice_files f JOIN public.invoices i USING (invoice_id)"
            "   WHERE i.submitted_by = :u) AS files,"
            " (SELECT count(*) FROM public.invoice_status_history h JOIN public.invoices i"
            "   USING (invoice_id) WHERE i.submitted_by = :u) AS history,"
            " (SELECT invoice_id FROM public.ai_recognition_logs WHERE recognition_id = :r) AS linked",
            u=world.user_id,
            r=recognition_id,
        )[0].values()
    )


# ---------- 1. 成功路徑：內容、關聯與一致性 ----------


def test_first_submit_writes_exactly_one_round_one_snapshot_matching_submitted_data(
    managed_engine: Engine, world: World
) -> None:
    key = new_key()
    with Session(managed_engine) as db:
        response = service.submit(
            db, session_for(world), build_request(make_recognition(world), key)
        )
    (snap,) = snapshots(managed_engine, response.invoice_id)
    (invoice,) = rows(
        managed_engine,
        "SELECT * FROM public.invoices WHERE invoice_id = :i",
        i=response.invoice_id,
    )
    items = rows(
        managed_engine,
        "SELECT * FROM public.invoice_items WHERE invoice_id = :i ORDER BY line_no",
        i=response.invoice_id,
    )
    (stored_file,) = rows(
        managed_engine,
        "SELECT * FROM public.invoice_files WHERE invoice_id = :i",
        i=response.invoice_id,
    )

    assert (snap["submission_round"], snap["submission_kind"]) == (1, "first")
    assert snap["file_id"] == stored_file["file_id"]
    assert snap["submitted_by"] == world.user_id == invoice["submitted_by"]
    assert snap["submitted_at"] == invoice["submitted_at"]
    assert snap["validation_results"] == invoice["validation_results"]
    header = snap["header"]
    assert header["invoice_track"] == key["invoice_track"] == invoice["invoice_track"]
    assert header["invoice_number"] == key["invoice_number"]
    assert header["seller_tax_id"] == key["seller_tax_id"]
    assert header["seller_name"] == invoice["seller_name"] == "W15 賣方"
    assert header["tax_type"] == invoice["tax_type"] == "taxable"
    assert header["invoice_date"] == invoice["invoice_date"].isoformat()
    assert header["tax_period"] == invoice["tax_period"]
    assert (header["sales_amount"], header["tax_amount"], header["total_amount"]) == (
        "1000",
        "50",
        "1050",
    )
    (snap_item,) = snap["items"]
    assert snap_item["item_id"] == str(items[0]["item_id"]) and snap_item["line_no"] == 1
    assert snap_item["item_name"] == items[0]["item_name"] == "W15 品名"
    assert snap_item["line_amount"] == "1000"


def test_snapshot_keeps_the_submitted_value_apart_from_ai_original_and_edit_history(
    managed_engine: Engine, world: World
) -> None:
    """快照＝送出值；AI 原值在 invoice_field_reviews，逐次修改在 invoice_changes，三者分開。"""
    with Session(managed_engine) as db:
        response = service.submit(
            db, session_for(world), build_request(make_recognition(world), new_key())
        )
    (snap,) = snapshots(managed_engine, response.invoice_id)
    review = rows(
        managed_engine,
        "SELECT ai_original_value, submitted_value FROM public.invoice_field_reviews"
        " WHERE invoice_id = :i AND field_scope = 'header' AND field_name = 'seller_name'",
        i=response.invoice_id,
    )
    changes = rows(
        managed_engine,
        "SELECT field_name FROM public.invoice_changes WHERE invoice_id = :i",
        i=response.invoice_id,
    )
    assert snap["header"]["seller_name"] == "W15 賣方"
    assert review and review[0]["ai_original_value"] is None  # AI 原值為空
    assert review[0]["submitted_value"] == "W15 賣方"
    assert "seller_name" in {row["field_name"] for row in changes}
    assert "ai_original_value" not in snap["header"] and "changes" not in snap["header"]


# ---------- 2. 失敗路徑：回滾、重複 ----------


def test_snapshot_failure_rolls_back_the_whole_first_submission_and_can_be_retried(
    managed_engine: Engine, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = new_key()
    recognition_id = make_recognition(world)
    request = build_request(recognition_id, key)

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated snapshot failure")

    monkeypatch.setattr(resubmit_repository, "insert_snapshot", boom)
    with Session(managed_engine) as db, pytest.raises(RuntimeError):
        service.submit(db, session_for(world), request)
    assert persisted_counts(managed_engine, world, recognition_id) == (0, 0, 0, None)

    monkeypatch.undo()
    with Session(managed_engine) as db:
        response = service.submit(db, session_for(world), request)
    assert [s["submission_round"] for s in snapshots(managed_engine, response.invoice_id)] == [1]


def test_submitting_the_same_recognition_or_key_twice_never_duplicates_the_snapshot(
    managed_engine: Engine, world: World
) -> None:
    key = new_key()
    recognition_id = make_recognition(world)
    request = build_request(recognition_id, key)
    with Session(managed_engine) as db:
        first = service.submit(db, session_for(world), request)
    with Session(managed_engine) as db, pytest.raises(ConflictError) as same_recognition:
        service.submit(db, session_for(world), request)
    with Session(managed_engine) as db, pytest.raises(ConflictError) as same_key:
        service.submit(db, session_for(world), build_request(make_recognition(world), key))

    assert same_recognition.value.code == "RECOGNITION_ALREADY_SUBMITTED"
    assert same_key.value.code == "INVOICE_DUPLICATED"
    assert len(snapshots(managed_engine, first.invoice_id)) == 1
    # 被拒絕的兩次送出沒有留下任何其他案件或快照
    assert persisted_counts(managed_engine, world, recognition_id)[0] == 1


# ---------- 3. 與重送流程的相容性 ----------


def returned_resubmit_request(
    engine: Engine, world: World, invoice_id: UUID, key: dict[str, str]
) -> InvoiceResubmitRequest:
    """把剛首次送出的案件改成「財務已退回」（測試 Fixture：等同財務退回後的資料），回傳補正稅額的重送內容。"""
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE public.invoices SET status = 'returned_to_applicant' WHERE invoice_id = :i"
            ),
            {"i": invoice_id},
        )
        conn.execute(
            text(
                "INSERT INTO public.invoice_status_history(invoice_id, old_status, new_status,"
                " changed_by) VALUES (:i, 'pending_accounting_review', 'returned_to_applicant', :u)"
            ),
            {"i": invoice_id, "u": world.user_id},
        )
        return_item_id = conn.execute(
            text(
                "INSERT INTO public.invoice_return_items(invoice_id, submission_round, item_kind,"
                " field_scope, field_name, reason, allowed_fields, created_by)"
                " VALUES (:i, 1, 'field', 'header', 'tax_amount', '稅額應為 40',"
                ' CAST(\'[{"field_scope":"header","field_name":"total_amount"}]\' AS jsonb), :u)'
                " RETURNING return_item_id"
            ),
            {"i": invoice_id, "u": world.user_id},
        ).scalar_one()
    (item,) = rows(
        engine, "SELECT item_id FROM public.invoice_items WHERE invoice_id = :i", i=invoice_id
    )
    return InvoiceResubmitRequest.model_validate(
        {
            "idempotency_key": str(uuid4()),
            "expected_round": 1,
            "invoice_track": key["invoice_track"],
            "invoice_number": key["invoice_number"],
            "invoice_date": "2026-10-15",
            "seller_tax_id": key["seller_tax_id"],
            "seller_name": "W15 賣方",
            "buyer_tax_id": None,
            "buyer_name": None,
            "tax_type": "taxable",
            "sales_amount": "1000",
            "tax_amount": "40",
            "total_amount": "1040",
            "total_amount_zh": None,
            "items": [
                {
                    "item_id": str(item["item_id"]),
                    "item_name": "W15 品名",
                    "quantity": None,
                    "unit_price": None,
                    "line_amount": "1000",
                }
            ],
            "changes": [
                {
                    "field_scope": "header",
                    "field_name": "tax_amount",
                    "old_value": "50",
                    "new_value": "40",
                },
                {
                    "field_scope": "header",
                    "field_name": "total_amount",
                    "old_value": "1050",
                    "new_value": "1040",
                },
            ],
            "responses": [
                {"return_item_id": str(return_item_id), "action": "corrected", "note": None}
            ],
        }
    )


def test_resubmitting_a_new_case_keeps_the_original_round_one_and_adds_round_two(
    managed_engine: Engine, world: World
) -> None:
    key = new_key()
    with Session(managed_engine) as db:
        response = service.submit(
            db, session_for(world), build_request(make_recognition(world), key)
        )
    (before,) = snapshots(managed_engine, response.invoice_id)
    request = returned_resubmit_request(managed_engine, world, response.invoice_id, key)
    with Session(managed_engine) as db:
        invoice_resubmit_service.resubmit(db, session_for(world), response.invoice_id, request)

    after = snapshots(managed_engine, response.invoice_id)
    assert [(s["submission_round"], s["submission_kind"]) for s in after] == [
        (1, "first"),
        (2, "resubmit_corrected"),
    ]
    assert after[0] == before  # 第 1 輪沒有被重送重建或覆寫（歷史表本身也禁止修改）
    assert after[0]["header"]["tax_amount"] == "50"
    assert after[1]["header"]["tax_amount"] == "40"


def test_finance_changing_tax_type_before_resubmit_does_not_alter_the_round_one_snapshot(
    managed_engine: Engine, world: World
) -> None:
    """本功能要解決的問題：ADMIN 財務在重送前直接改 invoices.tax_type（不留 invoice_changes）。"""
    key = new_key()
    with Session(managed_engine) as db:
        response = service.submit(
            db, session_for(world), build_request(make_recognition(world), key)
        )
    with managed_engine.begin() as conn:  # 模擬 ADMIN finance_review_repository.UPDATE_TAX_TYPE
        conn.execute(
            text("UPDATE public.invoices SET tax_type = 'zero_rated' WHERE invoice_id = :i"),
            {"i": response.invoice_id},
        )
    (snap,) = snapshots(managed_engine, response.invoice_id)
    assert snap["header"]["tax_type"] == "taxable"  # 保留首次送出當下的值


def test_resubmitting_an_old_case_without_round_one_still_backfills_it(
    managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world)  # 舊案件：沒有任何快照
    assert snapshots(managed_engine, case.invoice_id) == []
    request = InvoiceResubmitRequest.model_validate(resubmit_body(case))
    with Session(managed_engine) as db:
        invoice_resubmit_service.resubmit(db, session_for(world), case.invoice_id, request)
    after = snapshots(managed_engine, case.invoice_id)
    assert [(s["submission_round"], s["submission_kind"]) for s in after] == [
        (1, "first"),
        (2, "resubmit_corrected"),
    ]
    assert after[0]["header"]["tax_amount"] == "40"  # 補建的是上一輪的值


# ---------- 4. 缺表：另建一個沒有套用重送 Migration 的專屬資料庫 ----------


@contextmanager
def database_without_snapshot_table(managed_engine: Engine) -> Iterator[Engine]:
    admin_url = os.environ.get("ISOLATED_ADMIN_URL", "")
    if not admin_url:
        pytest.skip("需要 ISOLATED_ADMIN_URL")
    parsed = require_loopback(admin_url)
    token = secrets.token_hex(16)
    admin = create_engine(parsed, isolation_level="AUTOCOMMIT")
    name = create_database(admin, token)
    engine = create_engine(parsed.set(database=name), pool_size=4)
    try:
        load_baseline(engine, DEFAULT_BASELINE)  # 只有基線，不套用重送 Migration
        yield engine
    finally:
        engine.dispose()
        try:
            drop_owned_database(admin, name, token)
        finally:
            admin.dispose()


def test_missing_snapshot_table_fails_explicitly_and_saves_nothing(
    managed_engine: Engine,
) -> None:
    with database_without_snapshot_table(managed_engine) as engine:
        assert rows(engine, f"SELECT to_regclass('{SNAPSHOT_TABLE}') AS t")[0]["t"] is None
        world = World(engine)
        recognition_id = make_recognition(world)
        with Session(engine) as db, pytest.raises(ServiceUnavailableError) as error:
            service.submit(db, session_for(world), build_request(recognition_id, new_key()))
        assert error.value.code == "INVOICE_SNAPSHOT_UNAVAILABLE"
        assert error.value.status_code == 503
        assert persisted_counts(engine, world, recognition_id) == (0, 0, 0, None)


# ---------- 5. 非資料表擁有者、非 BYPASSRLS 的角色：GRANT 與 RLS ----------


@contextmanager
def runtime_like_role(managed_engine: Engine) -> Iterator[tuple[Engine, str]]:
    """建立只存在於專屬資料庫工作階段的登入角色：非超級使用者、非 BYPASSRLS、不擁有任何資料表。

    其他資料表給予寬鬆的 GRANT 與 RLS Policy，讓測試只觀察「快照表」的權限差異；結束時移除所有授權與角色。
    """
    role = f"ig_it_r_{secrets.token_hex(6)}"
    password = secrets.token_hex(16)
    database = managed_engine.url.database
    assert database is not None and database.startswith("ig_it_")  # 只在專屬資料庫內操作
    with managed_engine.begin() as conn:
        conn.exec_driver_sql(
            f"CREATE ROLE {role} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"
            f" PASSWORD '{password}'"
        )
        conn.exec_driver_sql(f'GRANT CONNECT ON DATABASE "{database}" TO {role}')
        for schema in ("public", "invoiceguard_internal", "invoiceguard_identity"):
            conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA {schema} TO {role}")
            conn.exec_driver_sql(f"GRANT ALL ON ALL TABLES IN SCHEMA {schema} TO {role}")
            conn.exec_driver_sql(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA {schema} TO {role}")
        conn.exec_driver_sql(f"REVOKE ALL ON {SNAPSHOT_TABLE} FROM {role}")
        tables = conn.exec_driver_sql(
            "SELECT schemaname, tablename FROM pg_tables"
            " WHERE schemaname IN ('public','invoiceguard_internal','invoiceguard_identity')"
            " AND rowsecurity AND tablename <> 'invoice_submission_snapshots'"
        ).all()
        for schema, table in tables:
            conn.exec_driver_sql(
                f'CREATE POLICY {role}_all ON {schema}."{table}" FOR ALL TO {role}'
                " USING (true) WITH CHECK (true)"
            )
    role_engine = create_engine(managed_engine.url.set(username=role, password=password))
    try:
        attrs = rows(
            managed_engine,
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :r",
            r=role,
        )[0]
        assert (attrs["rolsuper"], attrs["rolbypassrls"]) == (False, False)
        owned = rows(
            managed_engine,
            "SELECT count(*) AS n FROM pg_tables WHERE tableowner = :r",
            r=role,
        )[0]["n"]
        assert owned == 0
        yield role_engine, role
    finally:
        role_engine.dispose()
        with managed_engine.begin() as conn:
            conn.exec_driver_sql(f"DROP OWNED BY {role}")
            conn.exec_driver_sql(f"DROP ROLE {role}")


def submit_as(role_engine: Engine, world: World) -> tuple[UUID, Any]:
    recognition_id = make_recognition(world)
    request = build_request(recognition_id, new_key())
    with Session(role_engine) as db:
        try:
            return recognition_id, service.submit(db, session_for(world), request)
        except Exception as error:  # 交給呼叫端判斷型別
            return recognition_id, error


def test_role_without_insert_privilege_on_snapshots_fails_explicitly_and_rolls_back(
    managed_engine: Engine, world: World
) -> None:
    with runtime_like_role(managed_engine) as (role_engine, _role):
        recognition_id, result = submit_as(role_engine, world)
    assert isinstance(result, ServiceUnavailableError)
    assert result.code == "INVOICE_SNAPSHOT_UNAVAILABLE"
    assert persisted_counts(managed_engine, world, recognition_id) == (0, 0, 0, None)


def test_role_with_grant_but_no_rls_policy_fails_explicitly_and_rolls_back(
    managed_engine: Engine, world: World
) -> None:
    with runtime_like_role(managed_engine) as (role_engine, role):
        with managed_engine.begin() as conn:
            conn.exec_driver_sql(f"GRANT SELECT, INSERT ON {SNAPSHOT_TABLE} TO {role}")
        recognition_id, result = submit_as(role_engine, world)
    assert isinstance(result, ServiceUnavailableError)  # RLS 預設拒絕（42501）
    assert persisted_counts(managed_engine, world, recognition_id) == (0, 0, 0, None)


def test_role_with_grant_and_policy_can_submit_and_the_snapshot_is_saved(
    managed_engine: Engine, world: World
) -> None:
    with runtime_like_role(managed_engine) as (role_engine, role):
        with managed_engine.begin() as conn:
            conn.exec_driver_sql(f"GRANT SELECT, INSERT ON {SNAPSHOT_TABLE} TO {role}")
            conn.exec_driver_sql(
                f"CREATE POLICY {role}_snap ON {SNAPSHOT_TABLE} FOR ALL TO {role}"
                " USING (true) WITH CHECK (true)"
            )
        recognition_id, result = submit_as(role_engine, world)
    assert not isinstance(result, Exception), repr(result)
    assert [s["submission_round"] for s in snapshots(managed_engine, result.invoice_id)] == [1]
    assert persisted_counts(managed_engine, world, recognition_id)[0] == 1


# ---------- 6. 測試環境安全 ----------


def test_integration_target_is_a_loopback_session_database_owned_by_this_run(
    managed_engine: Engine,
) -> None:
    url = managed_engine.url
    assert url.host in {"127.0.0.1", "::1", "localhost"}
    assert url.database is not None and url.database.startswith("ig_it_")
    comment = rows(
        managed_engine,
        "SELECT shobj_description(oid, 'pg_database') AS c FROM pg_database WHERE datname = :n",
        n=url.database,
    )[0]["c"]
    assert comment and comment.startswith("invoiceguard-it:")  # 清理只會刪除這種自己建立的資料庫
