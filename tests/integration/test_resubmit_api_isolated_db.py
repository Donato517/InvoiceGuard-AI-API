"""
測試目標：同案重送 API（GET /invoices/{id}/return-items、POST /invoices/{id}/resubmit）在真實 PostgreSQL 上的行為。
做法：用 FastAPI TestClient 實際呼叫 API，登入驗證走真實的 user_sessions（不替換 auth_service），資料庫為專屬隔離庫；
    每個斷言都回頭查詢 PostgreSQL 的實際內容。
限制（請勿誤讀為端到端完成）：退件案件由本檔的 `seed_returned_case` 以明確標示的測試 Fixture 直接建立
    （等同財務退回後的資料）；ADMIN 目前尚未寫入 invoice_return_items，前台尚未接上，因此這不是 ADMIN／前台整合測試。
需要專屬資料庫模式（ISOLATED_ADMIN_URL，見 conftest）；未設定則略過，CI 設定時必須執行。
"""

import json
import secrets
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from isolated_db import World
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core import deps
from app.core.security import session_token_digest
from app.db.repositories import resubmit_repository, session_repository
from app.main import app

PREFIX = "/api/v1/invoices"


# ---------- 測試 Fixture：登入、API 客戶端、退件案件 ----------


@pytest.fixture
def client(managed_engine: Engine) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        with Session(managed_engine) as session:
            yield session

    app.dependency_overrides[deps.get_optional_db] = override
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(deps.get_optional_db, None)


def login(engine: Engine, world: World) -> dict[str, str]:
    """為合成使用者建立真實的 user_sessions，回傳 Authorization 標頭。"""
    token = secrets.token_urlsafe(32)
    with Session(engine) as db:
        version = db.execute(
            text(
                "SELECT credential_version FROM invoiceguard_identity.user_accounts WHERE user_id = :u"
            ),
            {"u": world.user_id},
        ).scalar_one()
        session_repository.create(
            db,
            user_id=world.user_id,
            digest=session_token_digest(token),
            credential_version=version,
            department_id=world.department_id,
            expire_minutes=60,
        )
        db.commit()
    return {"Authorization": f"Bearer {token}"}


@dataclass
class Case:
    invoice_id: UUID
    item_ids: list[UUID]
    number: str
    return_item_id: UUID | None
    image_item_id: UUID | None = None


def seed_returned_case(
    engine: Engine,
    world: World,
    *,
    origin: str | None = "pending_accounting_review",
    with_image_problem: bool = False,
    field_item: bool = True,
) -> Case:
    """【測試 Fixture】建立財務已退回的案件：第 1 輪、兩筆明細，發票號碼／賣方名稱／銷售額已由財務確認，
    稅額被指定退回並授權相依欄位總計。這裡直接寫入資料庫，等同財務退回後的結果。"""
    number = f"{secrets.randbelow(10**8):08d}"
    with engine.begin() as conn:
        invoice_id = conn.execute(
            text(
                "INSERT INTO public.invoices(invoice_track, invoice_number, invoice_date, tax_period,"
                " seller_tax_id, seller_name, buyer_tax_id, buyer_name, sales_amount, tax_amount, total_amount,"
                " total_amount_zh, tax_type, status, submission_round, validation_results, submitted_by,"
                " department_id, submitted_at) VALUES ('AB', :n, :d, '202610', '12345675', '甲公司',"
                " '27601907', '乙公司', 1000, 40, 1040, NULL, 'taxable', 'returned_to_applicant', 1,"
                " CAST('{}' AS jsonb), :u, :dep, now()) RETURNING invoice_id"
            ),
            {"n": number, "d": date(2026, 10, 15), "u": world.user_id, "dep": world.department_id},
        ).scalar_one()
        item_ids = [
            conn.execute(
                text(
                    "INSERT INTO public.invoice_items(invoice_id, line_no, item_name, quantity, unit_price,"
                    " line_amount) VALUES (:i, :l, :nm, 1, 500, 500) RETURNING item_id"
                ),
                {"i": invoice_id, "l": line, "nm": f"品項{line}"},
            ).scalar_one()
            for line in (1, 2)
        ]
        conn.execute(
            text(
                "INSERT INTO public.invoice_files(invoice_id, storage_path, mime_type)"
                " VALUES (:i, :p, 'image/jpeg')"
            ),
            {"i": invoice_id, "p": f"{world.user_id}/{uuid4().hex}.jpg"},
        )
        conn.execute(
            text(
                "INSERT INTO public.invoice_status_history(invoice_id, old_status, new_status, changed_by)"
                " VALUES (:i, NULL, 'pending_accounting_review', :u),"
                " (:i, :o, 'returned_to_applicant', :u)"
            ),
            {"i": invoice_id, "u": world.user_id, "o": origin},
        )
        for field in ("invoice_number", "seller_name", "sales_amount"):  # 財務已確認
            conn.execute(
                text(
                    "INSERT INTO public.invoice_field_reviews(invoice_id, submission_round, field_scope,"
                    " field_name, ai_original_value, submitted_value, is_checked, checked_by, checked_at)"
                    " VALUES (:i, 1, 'header', :f, CAST('\"ai\"' AS jsonb), CAST('\"v\"' AS jsonb), true, :u, now())"
                ),
                {"i": invoice_id, "f": field, "u": world.user_id},
            )
        conn.execute(  # 稅額：財務退回（未確認並附原因）
            text(
                "INSERT INTO public.invoice_field_reviews(invoice_id, submission_round, field_scope, field_name,"
                " ai_original_value, submitted_value, review_comment)"
                " VALUES (:i, 1, 'header', 'tax_amount', CAST('\"40\"' AS jsonb), CAST('\"40\"' AS jsonb), '稅額錯誤')"
            ),
            {"i": invoice_id},
        )
        return_item_id = None
        if field_item:
            return_item_id = conn.execute(
                text(
                    "INSERT INTO public.invoice_return_items(invoice_id, submission_round, item_kind, field_scope,"
                    " field_name, reason, allowed_fields, created_by)"
                    " VALUES (:i, 1, 'field', 'header', 'tax_amount', '稅額應為 50',"
                    " CAST(:allowed AS jsonb), :u) RETURNING return_item_id"
                ),
                {
                    "i": invoice_id,
                    "u": world.user_id,
                    "allowed": json.dumps(
                        [{"field_scope": "header", "field_name": "total_amount"}]
                    ),
                },
            ).scalar_one()
        image_id = None
        if with_image_problem:
            image_id = conn.execute(
                text(
                    "INSERT INTO public.invoice_return_items(invoice_id, submission_round, item_kind, reason)"
                    " VALUES (:i, 1, 'image', '影像模糊') RETURNING return_item_id"
                ),
                {"i": invoice_id},
            ).scalar_one()
    return Case(invoice_id, item_ids, number, return_item_id, image_id)


def rid(case: Case) -> UUID | None:
    return case.return_item_id or case.image_item_id


def body(case: Case, **overrides: Any) -> dict[str, Any]:
    """上一輪值為底的重送內容（稅額更正為 50、總計 1050），可用 overrides 改欄位。"""
    data: dict[str, Any] = {
        "idempotency_key": str(uuid4()),
        "expected_round": 1,
        "invoice_track": "AB",
        "invoice_number": case.number,
        "invoice_date": "2026-10-15",
        "seller_tax_id": "12345675",
        "seller_name": "甲公司",
        "buyer_tax_id": "27601907",
        "buyer_name": "乙公司",
        "tax_type": "taxable",
        "sales_amount": "1000",
        "tax_amount": "50",
        "total_amount": "1050",
        "total_amount_zh": None,
        "items": [
            {
                "item_id": str(item_id),
                "item_name": f"品項{line}",
                "quantity": "1",
                "unit_price": "500",
                "line_amount": "500",
            }
            for line, item_id in enumerate(case.item_ids, start=1)
        ],
        "changes": [
            {
                "field_scope": "header",
                "field_name": "tax_amount",
                "old_value": "40",
                "new_value": "50",
            },
            {
                "field_scope": "header",
                "field_name": "total_amount",
                "old_value": "1040",
                "new_value": "1050",
            },
        ],
        "responses": [{"return_item_id": str(rid(case)), "action": "corrected", "note": None}],
    }
    data.update(overrides)
    return data


def appeal_body(case: Case, **overrides: Any) -> dict[str, Any]:
    """純申覆：值與上一輪完全相同（稅額 40、總計 1040），沒有編輯事件，附說明。"""
    data = body(
        case,
        tax_amount="40",
        total_amount="1040",
        changes=[],
        responses=[
            {"return_item_id": str(rid(case)), "action": "appealed", "note": "原發票稅額即為 40"}
        ],
    )
    data.update(overrides)
    return data


def rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def state(engine: Engine, case: Case) -> dict[str, Any]:
    """案件在 PostgreSQL 的目前狀態，用來比較失敗請求前後完全沒變。"""
    return {
        "invoice": rows(
            engine,
            "SELECT status, submission_round, sales_amount, tax_amount, total_amount, seller_name"
            " FROM public.invoices WHERE invoice_id = :i",
            i=case.invoice_id,
        ),
        "snapshots": rows(
            engine,
            "SELECT submission_round FROM public.invoice_submission_snapshots WHERE invoice_id = :i",
            i=case.invoice_id,
        ),
        "changes": rows(
            engine, "SELECT 1 FROM public.invoice_changes WHERE invoice_id = :i", i=case.invoice_id
        ),
        "reviews": rows(
            engine,
            "SELECT submission_round, field_name FROM public.invoice_field_reviews WHERE invoice_id = :i ORDER BY 1, 2",
            i=case.invoice_id,
        ),
        "carryovers": rows(
            engine,
            "SELECT 1 FROM public.invoice_field_review_carryovers WHERE invoice_id = :i",
            i=case.invoice_id,
        ),
        "resubmissions": rows(
            engine,
            "SELECT 1 FROM public.invoice_resubmissions WHERE invoice_id = :i",
            i=case.invoice_id,
        ),
        "history": rows(
            engine,
            "SELECT new_status FROM public.invoice_status_history WHERE invoice_id = :i ORDER BY changed_at, history_id",
            i=case.invoice_id,
        ),
        "return_items": rows(
            engine,
            "SELECT status, response_action FROM public.invoice_return_items WHERE invoice_id = :i ORDER BY item_kind",
            i=case.invoice_id,
        ),
    }


# ---------- 讀取退件項目 ----------


def test_owner_reads_return_items_and_previous_submission(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world)
    headers = login(managed_engine, world)
    response = client.get(f"{PREFIX}/{case.invoice_id}/return-items", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "returned_to_applicant" and data["submission_round"] == 1
    assert data["can_resubmit"] is True and data["requires_void"] is False
    assert [f["field_name"] for f in data["editable_fields"]] == ["tax_amount", "total_amount"]
    assert data["return_items"][0]["reason"] == "稅額應為 50"
    assert data["previous"]["tax_amount"] == "40" and data["previous"]["total_amount"] == "1040"
    assert [i["line_no"] for i in data["previous"]["items"]] == [1, 2]


def test_non_owner_cannot_read_or_resubmit_and_data_is_untouched(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world)
    stranger = World(managed_engine)
    other = login(managed_engine, stranger)
    before = state(managed_engine, case)
    assert client.get(f"{PREFIX}/{case.invoice_id}/return-items", headers=other).status_code == 404
    response = client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=body(case), headers=other)
    assert response.status_code == 404
    assert state(managed_engine, case) == before


def test_unauthenticated_request_is_rejected(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world)
    assert client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=body(case)).status_code == 401


# ---------- 欄位補正的完整路徑 ----------


def test_owner_corrects_authorized_fields_and_new_round_is_saved_in_postgres(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world)
    headers = login(managed_engine, world)
    payload = body(case)
    response = client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["submission_round"] == 2 and result["status"] == "pending_accounting_review"
    assert result["replayed"] is False
    assert {
        (m["field_name"], m["ai_original_value"], m["submitted_value"])
        for m in result["modified_fields"]
    } == {
        ("tax_amount", "40", "50"),
        ("total_amount", "1040", "1050"),
    }

    # 案件：第 2 輪、新值、回到退件來源節點（財務待覆核）
    invoice = rows(
        managed_engine,
        "SELECT status, submission_round, tax_amount, total_amount, sales_amount FROM public.invoices WHERE invoice_id = :i",
        i=case.invoice_id,
    )[0]
    assert invoice["status"] == "pending_accounting_review" and invoice["submission_round"] == 2
    assert (str(invoice["tax_amount"]), str(invoice["total_amount"])) == ("50.00", "1050.00")

    # 快照：第 1 輪保持上一輪值（補建），第 2 輪為新值；明細快照完整且參照同一影像
    snaps = {
        s["submission_round"]: s
        for s in rows(
            managed_engine,
            "SELECT submission_round, submission_kind, header, items, file_id FROM public.invoice_submission_snapshots WHERE invoice_id = :i",
            i=case.invoice_id,
        )
    }
    assert set(snaps) == {1, 2}
    assert snaps[1]["header"]["tax_amount"] == "40" and snaps[1]["header"]["total_amount"] == "1040"
    assert snaps[2]["header"]["tax_amount"] == "50" and snaps[2]["header"]["total_amount"] == "1050"
    assert snaps[2]["submission_kind"] == "resubmit_corrected" and len(snaps[2]["items"]) == 2
    assert snaps[1]["file_id"] == snaps[2]["file_id"] and snaps[2]["file_id"] is not None

    # 編輯事件：逐筆、有順序，起點是上一輪提交值，終點等於正式提交值
    events = rows(
        managed_engine,
        "SELECT field_name, old_value, new_value, event_seq, submission_round, changed_by FROM public.invoice_changes WHERE invoice_id = :i ORDER BY event_seq",
        i=case.invoice_id,
    )
    assert [(e["event_seq"], e["field_name"], e["old_value"], e["new_value"]) for e in events] == [
        (1, "tax_amount", "40", "50"),
        (2, "total_amount", "1040", "1050"),
    ]
    assert {e["submission_round"] for e in events} == {2} and {e["changed_by"] for e in events} == {
        world.user_id
    }

    # 退件項目：原因保留、回覆與輪次已記錄
    item = rows(
        managed_engine,
        "SELECT reason, status, response_action, response_round, responded_by FROM public.invoice_return_items WHERE return_item_id = :r",
        r=case.return_item_id,
    )[0]
    assert (item["reason"], item["status"], item["response_action"], item["response_round"]) == (
        "稅額應為 50",
        "corrected",
        "corrected",
        2,
    )

    # R1：被退回與實際修改的欄位在第 2 輪待重審；其餘已確認欄位承接第 1 輪確認
    new_reviews = rows(
        managed_engine,
        "SELECT field_name, is_checked FROM public.invoice_field_reviews WHERE invoice_id = :i AND submission_round = 2 ORDER BY field_name",
        i=case.invoice_id,
    )
    assert [(r["field_name"], r["is_checked"]) for r in new_reviews] == [
        ("tax_amount", False),
        ("total_amount", False),
    ]
    carried = rows(
        managed_engine,
        "SELECT c.field_name, c.submission_round, r.submission_round AS source_round, r.is_checked, r.checked_by, r.checked_at"
        " FROM public.invoice_field_review_carryovers c JOIN public.invoice_field_reviews r"
        " ON r.field_review_id = c.source_field_review_id WHERE c.invoice_id = :i ORDER BY c.field_name",
        i=case.invoice_id,
    )
    assert [c["field_name"] for c in carried] == ["invoice_number", "sales_amount", "seller_name"]
    assert all(
        c["submission_round"] == 2
        and c["source_round"] == 1
        and c["is_checked"]
        and c["checked_by"] == world.user_id
        for c in carried
    )
    assert {c["field"]["field_name"] for c in result["carried_fields"]} == {
        "invoice_number",
        "sales_amount",
        "seller_name",
    }
    assert {f["field_name"] for f in result["rereview_fields"]} == {"tax_amount", "total_amount"}

    # 前輪覆核列沒有被改動（第 1 輪三個確認仍是確認）
    round1 = rows(
        managed_engine,
        "SELECT field_name, is_checked FROM public.invoice_field_reviews WHERE invoice_id = :i AND submission_round = 1 ORDER BY field_name",
        i=case.invoice_id,
    )
    assert [(r["field_name"], r["is_checked"]) for r in round1] == [
        ("invoice_number", True),
        ("sales_amount", True),
        ("seller_name", True),
        ("tax_amount", False),
    ]

    # 狀態歷程與冪等紀錄
    history = rows(
        managed_engine,
        "SELECT old_status, new_status FROM public.invoice_status_history WHERE invoice_id = :i ORDER BY changed_at, history_id",
        i=case.invoice_id,
    )
    assert (history[-1]["old_status"], history[-1]["new_status"]) == (
        "returned_to_applicant",
        "pending_accounting_review",
    )
    resub = rows(
        managed_engine,
        "SELECT from_round, to_round, requested_by FROM public.invoice_resubmissions WHERE invoice_id = :i",
        i=case.invoice_id,
    )
    assert resub == [{"from_round": 1, "to_round": 2, "requested_by": world.user_id}]

    # 重送後再讀退件項目：已不是退回狀態
    assert (
        client.get(f"{PREFIX}/{case.invoice_id}/return-items", headers=headers).status_code == 409
    )
    # 詳情仍可讀，且反映新輪次
    detail = client.get(f"{PREFIX}/{case.invoice_id}", headers=headers)
    assert detail.status_code == 200 and detail.json()["submission_round"] == 2


# ---------- 拒絕情境（失敗請求前後資料完全不變） ----------


def test_unauthorized_field_is_rejected_by_backend(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world)
    headers = login(managed_engine, world)
    before = state(managed_engine, case)
    payload = body(case, seller_name="被偷改的公司")
    response = client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=payload, headers=headers)
    assert (
        response.status_code == 400
        and response.json()["error"]["code"] == "RESUBMIT_FIELD_NOT_ALLOWED"
    )
    assert state(managed_engine, case) == before


def test_edit_event_on_unauthorized_field_is_rejected_even_if_reverted(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world)
    headers = login(managed_engine, world)
    before = state(managed_engine, case)
    events = body(case)["changes"] + [
        {
            "field_scope": "header",
            "field_name": "seller_name",
            "old_value": "甲公司",
            "new_value": "X",
        },
        {
            "field_scope": "header",
            "field_name": "seller_name",
            "old_value": "X",
            "new_value": "甲公司",
        },
    ]
    response = client.post(
        f"{PREFIX}/{case.invoice_id}/resubmit", json=body(case, changes=events), headers=headers
    )
    assert (
        response.status_code == 400
        and response.json()["error"]["code"] == "RESUBMIT_FIELD_NOT_ALLOWED"
    )
    assert state(managed_engine, case) == before


@pytest.mark.parametrize("mutation", ["drop_item", "add_item", "foreign_item_id"])
def test_item_structure_changes_are_rejected(
    client: TestClient, managed_engine: Engine, world: World, mutation: str
) -> None:
    case = seed_returned_case(managed_engine, world)
    headers = login(managed_engine, world)
    before = state(managed_engine, case)
    payload = body(case)
    if mutation == "drop_item":
        payload["items"] = payload["items"][:1]
    elif mutation == "add_item":
        payload["items"].append({"item_id": str(uuid4()), "item_name": "新增", "line_amount": "1"})
    else:
        payload["items"][1]["item_id"] = str(uuid4())
    response = client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=payload, headers=headers)
    assert (
        response.status_code == 400
        and response.json()["error"]["code"] == "RESUBMIT_ITEMS_STRUCTURE_CHANGED"
    )
    assert state(managed_engine, case) == before


def test_broken_edit_chain_is_rejected(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world)
    headers = login(managed_engine, world)
    before = state(managed_engine, case)
    # 事件起點是 AI 原值而不是上一輪提交值（40）
    bad = [
        {"field_scope": "header", "field_name": "tax_amount", "old_value": "35", "new_value": "50"},
        {
            "field_scope": "header",
            "field_name": "total_amount",
            "old_value": "1040",
            "new_value": "1050",
        },
    ]
    response = client.post(
        f"{PREFIX}/{case.invoice_id}/resubmit", json=body(case, changes=bad), headers=headers
    )
    assert (
        response.status_code == 400
        and response.json()["error"]["code"] == "RESUBMIT_EVENTS_INVALID"
    )
    assert state(managed_engine, case) == before


@pytest.mark.parametrize("with_field_problem", [False, True])
def test_image_problem_blocks_resubmit_and_appeal(
    client: TestClient, managed_engine: Engine, world: World, with_field_problem: bool
) -> None:
    headers = login(managed_engine, world)
    case = seed_returned_case(
        managed_engine, world, with_image_problem=True, field_item=with_field_problem
    )
    info = client.get(f"{PREFIX}/{case.invoice_id}/return-items", headers=headers).json()
    assert info["requires_void"] is True and info["can_resubmit"] is False
    assert info["editable_fields"] == []  # 圖片優先：不開放欄位補正
    assert any(
        item["item_kind"] == "image" and item["reason"] == "影像模糊"
        for item in info["return_items"]
    )
    before = state(managed_engine, case)
    for payload in (body(case), appeal_body(case)):
        response = client.post(
            f"{PREFIX}/{case.invoice_id}/resubmit", json=payload, headers=headers
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "RESUBMIT_IMAGE_REQUIRES_VOID"
    assert state(managed_engine, case) == before


def test_stale_round_unknown_origin_and_wrong_status_are_conflicts(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    headers = login(managed_engine, world)
    case = seed_returned_case(managed_engine, world)
    before = state(managed_engine, case)
    stale = client.post(
        f"{PREFIX}/{case.invoice_id}/resubmit", json=body(case, expected_round=7), headers=headers
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "RESUBMIT_ROUND_STALE"
    assert state(managed_engine, case) == before

    unknown = seed_returned_case(managed_engine, world, origin=None)
    response = client.post(
        f"{PREFIX}/{unknown.invoice_id}/resubmit", json=body(unknown), headers=headers
    )
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "RESUBMIT_ORIGIN_UNKNOWN"
    )

    done = seed_returned_case(managed_engine, world)
    with managed_engine.begin() as conn:
        conn.execute(
            text("UPDATE public.invoices SET status = 'approved' WHERE invoice_id = :i"),
            {"i": done.invoice_id},
        )
    response = client.post(f"{PREFIX}/{done.invoice_id}/resubmit", json=body(done), headers=headers)
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "INVOICE_NOT_RETURNED"
    )


def test_voided_case_cannot_be_resubmitted_with_its_original_id(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    headers = login(managed_engine, world)
    case = seed_returned_case(managed_engine, world)
    with managed_engine.begin() as conn:
        conn.execute(
            text("UPDATE public.invoices SET status = 'voided' WHERE invoice_id = :i"),
            {"i": case.invoice_id},
        )
    response = client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=body(case), headers=headers)
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "INVOICE_NOT_RETURNED"
    )
    assert (
        rows(
            managed_engine,
            "SELECT submission_round FROM public.invoices WHERE invoice_id = :i",
            i=case.invoice_id,
        )[0]["submission_round"]
        == 1
    )


def test_missing_responses_are_rejected_by_schema(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world)
    headers = login(managed_engine, world)
    response = client.post(
        f"{PREFIX}/{case.invoice_id}/resubmit", json=body(case, responses=[]), headers=headers
    )
    assert response.status_code == 422


def test_appeal_without_note_and_claimed_correction_without_change_are_rejected(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world)
    headers = login(managed_engine, world)
    before = state(managed_engine, case)
    no_note = appeal_body(
        case,
        responses=[{"return_item_id": str(rid(case)), "action": "appealed", "note": " "}],
    )
    fake_fix = appeal_body(
        case,
        responses=[{"return_item_id": str(rid(case)), "action": "corrected", "note": None}],
    )
    for payload in (no_note, fake_fix):
        response = client.post(
            f"{PREFIX}/{case.invoice_id}/resubmit", json=payload, headers=headers
        )
        assert (
            response.status_code == 400
            and response.json()["error"]["code"] == "RESUBMIT_RESPONSES_INCOMPLETE"
        )
    assert state(managed_engine, case) == before


# ---------- 純申覆 ----------


def test_pure_appeal_without_changes_creates_a_new_round_and_requires_re_review(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world)
    headers = login(managed_engine, world)
    response = client.post(
        f"{PREFIX}/{case.invoice_id}/resubmit", json=appeal_body(case), headers=headers
    )
    assert response.status_code == 201, response.text
    assert response.json()["submission_round"] == 2 and response.json()["modified_fields"] == []

    invoice = rows(
        managed_engine,
        "SELECT status, submission_round, tax_amount, total_amount FROM public.invoices WHERE invoice_id = :i",
        i=case.invoice_id,
    )[0]
    assert invoice["submission_round"] == 2 and str(invoice["tax_amount"]) == "40.00"  # 資料值不變
    assert (
        rows(
            managed_engine,
            "SELECT 1 FROM public.invoice_changes WHERE invoice_id = :i",
            i=case.invoice_id,
        )
        == []
    )
    snaps = {
        s["submission_round"]: s
        for s in rows(
            managed_engine,
            "SELECT submission_round, submission_kind, header FROM public.invoice_submission_snapshots WHERE invoice_id = :i",
            i=case.invoice_id,
        )
    }
    assert (
        snaps[2]["submission_kind"] == "resubmit_appeal"
        and snaps[2]["header"] == snaps[1]["header"]
    )
    item = rows(
        managed_engine,
        "SELECT status, response_note FROM public.invoice_return_items WHERE return_item_id = :r",
        r=case.return_item_id,
    )[0]
    assert (item["status"], item["response_note"]) == ("appealed", "原發票稅額即為 40")
    # 被申覆的項目與其授權相依欄位仍須財務重新判斷，不可直接承接
    reviews = rows(
        managed_engine,
        "SELECT field_name, is_checked FROM public.invoice_field_reviews WHERE invoice_id = :i AND submission_round = 2 ORDER BY field_name",
        i=case.invoice_id,
    )
    assert [(r["field_name"], r["is_checked"]) for r in reviews] == [
        ("tax_amount", False),
        ("total_amount", False),
    ]
    assert {
        r["field_name"]
        for r in rows(
            managed_engine,
            "SELECT field_name FROM public.invoice_field_review_carryovers WHERE invoice_id = :i",
            i=case.invoice_id,
        )
    } == {"invoice_number", "sales_amount", "seller_name"}


# ---------- 冪等、版本衝突與併發 ----------


def test_same_idempotency_key_replays_the_original_result_without_new_rows(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world)
    headers = login(managed_engine, world)
    payload = body(case)
    first = client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=payload, headers=headers)
    after_first = state(managed_engine, case)
    second = client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=payload, headers=headers)
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["replayed"] is True
    assert {k: v for k, v in second.json().items() if k != "replayed"} == {
        k: v for k, v in first.json().items() if k != "replayed"
    }
    assert state(managed_engine, case) == after_first  # 輪次、快照、事件、覆核、歷程都沒有重複


def test_same_key_with_different_content_is_rejected_and_replay_still_checks_the_user(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world)
    headers = login(managed_engine, world)
    payload = body(case)
    assert (
        client.post(
            f"{PREFIX}/{case.invoice_id}/resubmit", json=payload, headers=headers
        ).status_code
        == 201
    )
    after = state(managed_engine, case)
    changed = dict(payload, buyer_name="丙公司")
    reused = client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=changed, headers=headers)
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    other = login(managed_engine, World(managed_engine))  # 非原提交者即使帶相同 key 也不能取得回放
    assert (
        client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=payload, headers=other).status_code
        == 404
    )
    assert state(managed_engine, case) == after


def test_concurrent_identical_requests_create_exactly_one_new_round(
    managed_engine: Engine, world: World, client: TestClient
) -> None:
    case = seed_returned_case(managed_engine, world)
    headers = login(managed_engine, world)
    payload = body(case)
    barrier = threading.Barrier(4)

    def call() -> int:
        local = TestClient(app, raise_server_exceptions=False)
        barrier.wait()
        return local.post(
            f"{PREFIX}/{case.invoice_id}/resubmit", json=payload, headers=headers
        ).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = sorted(pool.map(lambda _: call(), range(4)))
    assert codes == [200, 200, 200, 201]
    snapshot = state(managed_engine, case)
    assert snapshot["invoice"][0]["submission_round"] == 2
    assert len(snapshot["resubmissions"]) == 1 and len(snapshot["changes"]) == 2
    assert sorted(s["submission_round"] for s in snapshot["snapshots"]) == [1, 2]


def test_concurrent_requests_with_different_keys_allow_only_one_to_win(
    managed_engine: Engine, world: World, client: TestClient
) -> None:
    case = seed_returned_case(managed_engine, world)
    headers = login(managed_engine, world)
    barrier = threading.Barrier(3)

    def call() -> int:
        local = TestClient(app, raise_server_exceptions=False)
        barrier.wait()
        return local.post(
            f"{PREFIX}/{case.invoice_id}/resubmit", json=body(case), headers=headers
        ).status_code

    with ThreadPoolExecutor(max_workers=3) as pool:
        codes = sorted(pool.map(lambda _: call(), range(3)))
    assert codes == [201, 409, 409]
    assert state(managed_engine, case)["invoice"][0]["submission_round"] == 2


# ---------- 查重 ----------


def test_duplicate_of_another_active_case_is_blocked_but_voided_and_self_are_not(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    headers = login(managed_engine, world)
    case = seed_returned_case(managed_engine, world)
    other = seed_returned_case(managed_engine, world)
    # 另一個有效案件與本案有相同的字軌＋號碼＋賣方統編（資料庫沒有號碼唯一約束，防線是查重）
    with managed_engine.begin() as conn:
        conn.execute(
            text("UPDATE public.invoices SET invoice_number = :n WHERE invoice_id = :i"),
            {"n": case.number, "i": other.invoice_id},
        )
    before = state(managed_engine, case)
    blocked = client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=body(case), headers=headers)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "INVOICE_DUPLICATED"
    assert state(managed_engine, case) == before
    with (
        managed_engine.begin() as conn
    ):  # 另一案作廢後不再阻擋；本案自己的列一直被排除，不會自己擋自己
        conn.execute(
            text("UPDATE public.invoices SET status = 'voided' WHERE invoice_id = :i"),
            {"i": other.invoice_id},
        )
    ok = client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=body(case), headers=headers)
    assert ok.status_code == 201, ok.text


# ---------- 交易原子性 ----------


def test_failure_in_the_last_step_leaves_no_partial_formal_submission(
    client: TestClient, managed_engine: Engine, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = seed_returned_case(managed_engine, world)
    headers = login(managed_engine, world)
    before = state(managed_engine, case)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("simulated failure after all other writes")

    monkeypatch.setattr(resubmit_repository, "insert_resubmission", boom)
    response = client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=body(case), headers=headers)
    assert response.status_code == 500
    assert (
        state(managed_engine, case) == before
    )  # 案件、快照、事件、覆核、承接、歷程、退件回覆全部沒有留下


# ---------- R1 多輪：承接後又被退回修改 ----------


def test_confirmation_is_not_carried_over_a_field_that_was_modified_in_a_later_round(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world)
    headers = login(managed_engine, world)
    assert (
        client.post(
            f"{PREFIX}/{case.invoice_id}/resubmit", json=body(case), headers=headers
        ).status_code
        == 201
    )
    # 【測試 Fixture】財務第二次退回：這次指定第 1 輪已確認並被承接的「銷售額」
    with managed_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE public.invoices SET status = 'returned_to_applicant' WHERE invoice_id = :i"
            ),
            {"i": case.invoice_id},
        )
        conn.execute(
            text(
                "INSERT INTO public.invoice_status_history(invoice_id, old_status, new_status, changed_by) VALUES (:i, 'pending_accounting_review', 'returned_to_applicant', :u)"
            ),
            {"i": case.invoice_id, "u": world.user_id},
        )
        second_item = conn.execute(
            text(
                "INSERT INTO public.invoice_return_items(invoice_id, submission_round, item_kind, field_scope, field_name, reason, created_by) VALUES (:i, 2, 'field', 'header', 'sales_amount', '銷售額應為 1100', :u) RETURNING return_item_id"
            ),
            {"i": case.invoice_id, "u": world.user_id},
        ).scalar_one()
    payload = body(
        case,
        expected_round=2,
        sales_amount="1100",
        total_amount="1150",
        changes=[
            {
                "field_scope": "header",
                "field_name": "sales_amount",
                "old_value": "1000",
                "new_value": "1100",
            }
        ],
        responses=[{"return_item_id": str(second_item), "action": "corrected", "note": None}],
    )
    response = client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=payload, headers=headers)
    # total_amount 沒有被這次退件授權：整筆被拒（銷售額與總計不是同一個授權範圍）
    assert (
        response.status_code == 400
        and response.json()["error"]["code"] == "RESUBMIT_FIELD_NOT_ALLOWED"
    )
    payload = body(
        case,
        expected_round=2,
        sales_amount="1100",
        tax_amount="50",
        total_amount="1050",
        changes=[
            {
                "field_scope": "header",
                "field_name": "sales_amount",
                "old_value": "1000",
                "new_value": "1100",
            }
        ],
        responses=[{"return_item_id": str(second_item), "action": "corrected", "note": None}],
    )
    response = client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    assert response.json()["submission_round"] == 3

    carry3 = rows(
        managed_engine,
        "SELECT c.field_name, r.submission_round AS source_round FROM public.invoice_field_review_carryovers c JOIN public.invoice_field_reviews r ON r.field_review_id = c.source_field_review_id WHERE c.invoice_id = :i AND c.submission_round = 3 ORDER BY c.field_name",
        i=case.invoice_id,
    )
    # 第 1 輪確認的號碼與賣方名稱仍承接（來源是第 1 輪）；被修改的銷售額不承接
    assert carry3 == [
        {"field_name": "invoice_number", "source_round": 1},
        {"field_name": "seller_name", "source_round": 1},
    ]
    review3 = rows(
        managed_engine,
        "SELECT field_name, is_checked FROM public.invoice_field_reviews WHERE invoice_id = :i AND submission_round = 3 ORDER BY field_name",
        i=case.invoice_id,
    )
    # 針對性覆核：只有被退回並修改的銷售額建立待審列；沒有任何欄位被推定為已確認或憑空承接
    assert [(r["field_name"], r["is_checked"]) for r in review3] == [("sales_amount", False)]


# ---------- 申請人作廢（圖片問題的必經步驟） ----------


def make_recognition(engine: Engine, world: World) -> UUID:
    """【測試 Fixture】OCR 的替身：一筆可供送出的成功辨識紀錄。"""
    recognition_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.ai_recognition_logs(recognition_id, source_storage_path, ai_provider,"
                " result_status, requested_by, extracted_fields, raw_response) VALUES (:r, :p, 'test', 'success',"
                " :u, CAST(:e AS jsonb), CAST(:w AS jsonb))"
            ),
            {
                "r": recognition_id,
                "p": f"{world.user_id}/INVOICES_20261103000000_{recognition_id}.jpg",
                "u": world.user_id,
                "e": json.dumps({"invoice": {}}),
                "w": json.dumps({"source": {"filename": "n.jpg", "size_bytes": 1}}),
            },
        )
    return recognition_id


def new_case_body(recognition_id: UUID, case: Case) -> dict[str, Any]:
    """重新上傳後的首次提交內容：與被作廢案件相同的字軌＋號碼＋賣方統編。"""
    return {
        "recognition_id": str(recognition_id),
        "invoice_track": "AB",
        "invoice_number": case.number,
        "invoice_date": "2026-10-15",
        "seller_tax_id": "12345675",
        "tax_type": "taxable",
        "sales_amount": "1000",
        "tax_amount": "50",
        "total_amount": "1050",
        "items": [{"item_name": "重新上傳", "line_amount": "1000"}],
    }


def test_owner_voids_an_image_problem_case_and_everything_is_kept(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world, with_image_problem=True)
    headers = login(managed_engine, world)
    before = state(managed_engine, case)
    files_before = rows(
        managed_engine,
        "SELECT file_id, storage_path, is_current FROM public.invoice_files WHERE invoice_id = :i",
        i=case.invoice_id,
    )
    reviewer_before = rows(
        managed_engine,
        "SELECT reviewed_by, reviewed_at FROM public.invoices WHERE invoice_id = :i",
        i=case.invoice_id,
    )

    response = client.post(
        f"{PREFIX}/{case.invoice_id}/void",
        json={"expected_round": 1, "reason": "影像模糊重拍"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "voided" and response.json()["submission_round"] == 1
    after = state(managed_engine, case)
    assert after["invoice"][0]["status"] == "voided"
    # 只轉換狀態並新增一筆歷程；其他資料（影像、退件項目、覆核、快照、事件）完全不變
    assert {k: v for k, v in after.items() if k not in ("invoice", "history")} == {
        k: v for k, v in before.items() if k not in ("invoice", "history")
    }
    assert after["history"] == before["history"] + [{"new_status": "voided"}]
    assert (
        rows(
            managed_engine,
            "SELECT file_id, storage_path, is_current FROM public.invoice_files WHERE invoice_id = :i",
            i=case.invoice_id,
        )
        == files_before
    )
    assert (
        rows(
            managed_engine,
            "SELECT reviewed_by, reviewed_at FROM public.invoices WHERE invoice_id = :i",
            i=case.invoice_id,
        )
        == reviewer_before
    )
    last = rows(
        managed_engine,
        "SELECT old_status, new_status, reason, changed_by FROM public.invoice_status_history WHERE invoice_id = :i ORDER BY changed_at DESC, history_id DESC LIMIT 1",
        i=case.invoice_id,
    )[0]
    assert (last["old_status"], last["new_status"], last["changed_by"]) == (
        "returned_to_applicant",
        "voided",
        world.user_id,
    )
    assert "影像模糊重拍" in last["reason"]


def test_void_is_owner_only_and_not_repeatable(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world, with_image_problem=True)
    headers = login(managed_engine, world)
    stranger = login(managed_engine, World(managed_engine))
    before = state(managed_engine, case)
    assert (
        client.post(
            f"{PREFIX}/{case.invoice_id}/void", json={"expected_round": 1}, headers=stranger
        ).status_code
        == 404
    )
    assert (
        client.post(f"{PREFIX}/{case.invoice_id}/void", json={"expected_round": 1}).status_code
        == 401
    )
    stale = client.post(
        f"{PREFIX}/{case.invoice_id}/void", json={"expected_round": 9}, headers=headers
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "RESUBMIT_ROUND_STALE"
    assert state(managed_engine, case) == before

    assert (
        client.post(
            f"{PREFIX}/{case.invoice_id}/void", json={"expected_round": 1}, headers=headers
        ).status_code
        == 200
    )
    again = client.post(
        f"{PREFIX}/{case.invoice_id}/void", json={"expected_round": 1}, headers=headers
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "INVOICE_NOT_RETURNED"
    assert [h["new_status"] for h in state(managed_engine, case)["history"]].count("voided") == 1
    resubmit = client.post(f"{PREFIX}/{case.invoice_id}/resubmit", json=body(case), headers=headers)
    assert (
        resubmit.status_code == 409 and resubmit.json()["error"]["code"] == "INVOICE_NOT_RETURNED"
    )


def race_resubmit_and_void(case: Case, headers: dict[str, str]) -> tuple[int, int]:
    """同時送出重送與作廢，回傳（重送狀態碼, 作廢狀態碼）。"""
    barrier = threading.Barrier(2)
    url = f"{PREFIX}/{case.invoice_id}"

    def call(path: str, payload: dict[str, Any]) -> int:
        barrier.wait()
        local = TestClient(app, raise_server_exceptions=False)
        return local.post(f"{url}/{path}", json=payload, headers=headers).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        resubmit = pool.submit(call, "resubmit", body(case))
        void = pool.submit(call, "void", {"expected_round": 1})
        return resubmit.result(), void.result()


def test_void_and_resubmit_race_has_exactly_one_winner(
    managed_engine: Engine, world: World, client: TestClient
) -> None:
    for _ in range(3):
        case = seed_returned_case(managed_engine, world)
        headers = login(managed_engine, world)
        codes = race_resubmit_and_void(case, headers)
        assert codes in {(201, 409), (409, 200)}, codes
        final = state(managed_engine, case)
        statuses = [h["new_status"] for h in final["history"]]
        if codes == (201, 409):
            assert final["invoice"][0]["status"] == "pending_accounting_review"
            assert "voided" not in statuses
        else:
            assert final["invoice"][0]["status"] == "voided"
            assert final["invoice"][0]["submission_round"] == 1
            assert final["snapshots"] == [] and final["changes"] == []


def test_new_case_after_void_gets_a_new_id_and_old_case_is_untouched(
    client: TestClient, managed_engine: Engine, world: World
) -> None:
    case = seed_returned_case(managed_engine, world, with_image_problem=True)
    headers = login(managed_engine, world)
    # 作廢前：同鍵新案被查重擋下（原案仍是有效案件）
    blocked = client.post(
        PREFIX, json=new_case_body(make_recognition(managed_engine, world), case), headers=headers
    )
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "INVOICE_DUPLICATED"

    assert (
        client.post(
            f"{PREFIX}/{case.invoice_id}/void", json={"expected_round": 1}, headers=headers
        ).status_code
        == 200
    )
    old_before = state(managed_engine, case)
    fresh = client.post(
        PREFIX, json=new_case_body(make_recognition(managed_engine, world), case), headers=headers
    )

    assert fresh.status_code == 201, fresh.text
    new_id = UUID(fresh.json()["invoice_id"])
    assert new_id != case.invoice_id and fresh.json()["status"] == "pending_accounting_review"
    assert state(managed_engine, case) == old_before  # 原案件（含影像、退件歷史）完全不變
    new_files = rows(
        managed_engine,
        "SELECT storage_path FROM public.invoice_files WHERE invoice_id = :i",
        i=new_id,
    )
    old_files = rows(
        managed_engine,
        "SELECT storage_path FROM public.invoice_files WHERE invoice_id = :i",
        i=case.invoice_id,
    )
    assert (
        new_files
        and old_files
        and {f["storage_path"] for f in new_files}.isdisjoint(
            {f["storage_path"] for f in old_files}
        )
    )
