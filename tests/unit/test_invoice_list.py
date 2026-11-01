"""
模組名稱：tests.unit.test_invoice_list
功能說明：測試 GET /api/v1/invoices（提交者本人的發票列表：分頁、狀態篩選、排序、授權）。
注意事項：以模擬 SQL 結果的 DB 替身執行，不連正式 DB；替身依綁定參數（user_id、status、limit、offset）
    過濾與排序，只能證明授權與分頁參數確實進入 repository 查詢，SQL 語法本身另以隔離 PostgreSQL 驗證。
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core import deps
from app.core.exceptions import UnauthorizedError
from app.main import app
from app.schemas.auth import DepartmentRead, SessionRead
from app.schemas.invoice_list import ApprovalStatus
from app.services import auth_service

client = TestClient(app)

OWNER_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_ID = UUID("33333333-3333-4333-8333-333333333333")
DEPARTMENT = UUID("22222222-2222-4222-8222-222222222222")
EXPIRES = datetime(2026, 10, 31, 1, 0, tzinfo=UTC)
BASE_TIME = datetime(2026, 10, 20, 2, 0, tzinfo=UTC)
AUTH = {"Authorization": "Bearer synthetic-session-token"}
URL = "/api/v1/invoices"
STATUSES = [
    "draft",
    "pending_department_approval",
    "pending_accounting_review",
    "pending_accounting_approval",
    "approved",
    "returned_to_applicant",
    "returned_to_accounting",
    "rejected",
    "voided",
]


def make_session(user_id: UUID) -> SessionRead:
    department = DepartmentRead(
        department_id=DEPARTMENT, department_code="dept", department_name="部門", is_primary=True
    )
    return SessionRead(
        user_id=user_id,
        email="user@example.com",
        display_name="測試使用者",
        department=department,
        departments=(department,),
        expires_at=EXPIRES,
    )


def row(index: int, *, owner: UUID = OWNER_ID, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "invoice_id": UUID(int=index),
        "status": "pending_department_approval",
        "submission_round": 1,
        "submitted_at": BASE_TIME + timedelta(minutes=index),
        "created_at": BASE_TIME + timedelta(minutes=index),
        "invoice_track": "AB",
        "invoice_number": f"{index:08d}",
        "invoice_date": date(2026, 10, 1),
        "seller_name": "賣方",
        "total_amount": Decimal("1050.00"),
        "submitted_by": owner,
    }
    data.update(overrides)
    return data


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]], scalar: Any = None) -> None:
        self.rows = rows
        self.scalar = scalar

    def mappings(self) -> "FakeResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows

    def one_or_none(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def scalar_one(self) -> Any:
        return self.scalar


@dataclass
class FakeDb:
    """依綁定參數模擬 invoices 資料表；排序規則與實際 SQL 相同。"""

    invoices: list[dict[str, Any]] = field(default_factory=list)
    statements: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    rollback: MagicMock = field(default_factory=MagicMock)
    commit: MagicMock = field(default_factory=MagicMock)
    in_txn: bool = False
    error: Exception | None = None

    def __post_init__(self) -> None:
        self.rollback.side_effect = self._end
        self.commit.side_effect = self._end

    def _end(self) -> None:
        self.in_txn = False

    def in_transaction(self) -> bool:
        return self.in_txn

    def _matching(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            r
            for r in self.invoices
            if r["submitted_by"] == params["user_id"]
            and (params["status"] is None or r["status"] == params["status"])
        ]

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> FakeResult:
        sql = " ".join(str(statement).split())
        params = params or {}
        self.statements.append((sql, params))
        self.in_txn = True
        if self.error is not None:
            raise self.error
        if sql.startswith("SET TRANSACTION"):
            return FakeResult([])
        if sql.startswith("SELECT count(*)"):
            return FakeResult([], scalar=len(self._matching(params)))
        if "FROM public.invoices" in sql and "LIMIT" in sql:
            rows = sorted(
                self._matching(params),
                key=lambda r: (
                    r["submitted_at"] is not None,
                    r["submitted_at"] or BASE_TIME,
                    r["created_at"],
                    r["invoice_id"],
                ),
                reverse=True,
            )
            # NULLS LAST：submitted_at 為 None 的排最後（reverse 後 False 在尾端）
            return FakeResult(rows[params["offset"] : params["offset"] + params["limit"]])
        if "WHERE invoice_id = :invoice_id" in sql:  # 詳情查詢：此替身沒有詳情資料
            return FakeResult([])
        raise AssertionError(f"未預期的 SQL：{sql}")


@pytest.fixture
def fake_db() -> Iterator[FakeDb]:
    db = FakeDb()

    def override() -> Iterator[FakeDb]:
        yield db

    app.dependency_overrides[deps.get_optional_db] = override
    yield db
    app.dependency_overrides.clear()


@pytest.fixture
def as_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_service, "resolve_session", lambda db, token: make_session(OWNER_ID))


def get(params: dict[str, Any] | None = None) -> Any:
    return client.get(URL, headers=AUTH, params=params)


def numbers(response: Any) -> list[str]:
    return [item["invoice_number"] for item in response.json()["items"]]


def test_owner_with_several_invoices_gets_newest_first(fake_db: FakeDb, as_owner: None) -> None:
    fake_db.invoices = [row(1), row(3), row(2)]
    response = get()
    assert response.status_code == 200
    body = response.json()
    assert numbers(response) == ["00000003", "00000002", "00000001"]
    assert (body["total"], body["page"], body["page_size"]) == (3, 1, 20)


def test_item_fields_match_contract(fake_db: FakeDb, as_owner: None) -> None:
    fake_db.invoices = [row(7)]
    item = get().json()["items"][0]
    assert item == {
        "invoice_id": str(UUID(int=7)),
        "status": "pending_department_approval",
        "submission_round": 1,
        "submitted_at": "2026-10-20T02:07:00Z",
        "invoice_track": "AB",
        "invoice_number": "00000007",
        "invoice_date": "2026-10-01",
        "seller_name": "賣方",
        "total_amount": "1050.00",
    }
    assert "risk_score" not in item


def test_no_invoices_returns_empty_page(fake_db: FakeDb, as_owner: None) -> None:
    response = get()
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


def test_other_users_invoices_are_excluded_from_items_and_total(
    fake_db: FakeDb, as_owner: None
) -> None:
    fake_db.invoices = [row(1), row(2, owner=OTHER_ID), row(3, owner=OTHER_ID), row(4, owner=None)]
    body = get().json()
    assert [i["invoice_number"] for i in body["items"]] == ["00000001"]
    assert body["total"] == 1


def test_owner_filter_is_bound_in_both_queries(fake_db: FakeDb, as_owner: None) -> None:
    get({"status": "approved"})
    queries = [(s, p) for s, p in fake_db.statements if "FROM public.invoices" in s]
    assert len(queries) == 2
    for sql, params in queries:
        assert "submitted_by = :user_id" in sql
        assert params["user_id"] == OWNER_ID
        assert params["status"] == "approved"


def test_draft_without_submitter_is_not_listed_but_owned_draft_is(
    fake_db: FakeDb, as_owner: None
) -> None:
    fake_db.invoices = [
        row(1, status="draft", submission_round=0, submitted_at=None),
        row(2, status="draft", submission_round=0, submitted_at=None, owner=None),
    ]
    items = get().json()["items"]
    assert [i["invoice_number"] for i in items] == ["00000001"]
    assert items[0]["submitted_at"] is None


def test_null_submitted_at_sorts_last(fake_db: FakeDb, as_owner: None) -> None:
    fake_db.invoices = [row(1, submitted_at=None), row(2), row(3)]
    assert numbers(get()) == ["00000003", "00000002", "00000001"]


def test_order_sql_has_stable_tiebreakers(fake_db: FakeDb, as_owner: None) -> None:
    get()
    sql = next(s for s, _ in fake_db.statements if "LIMIT" in s)
    assert "ORDER BY submitted_at DESC NULLS LAST, created_at DESC, invoice_id DESC" in sql


def test_same_timestamp_records_have_stable_order(fake_db: FakeDb, as_owner: None) -> None:
    same = BASE_TIME
    fake_db.invoices = [row(i, submitted_at=same, created_at=same) for i in range(1, 6)]
    first = numbers(get({"page_size": 2, "page": 1}))
    second = numbers(get({"page_size": 2, "page": 2}))
    third = numbers(get({"page_size": 2, "page": 3}))
    assert first + second + third == ["00000005", "00000004", "00000003", "00000002", "00000001"]


def test_pagination_boundaries(fake_db: FakeDb, as_owner: None) -> None:
    fake_db.invoices = [row(i) for i in range(1, 6)]
    last = get({"page_size": 2, "page": 3}).json()
    assert numbers(get({"page_size": 2, "page": 3})) == ["00000001"]
    assert last["total"] == 5
    beyond = get({"page_size": 2, "page": 4}).json()
    assert beyond == {"items": [], "total": 5, "page": 4, "page_size": 2}
    exact = get({"page_size": 5}).json()
    assert len(exact["items"]) == 5


def test_offset_and_limit_are_bound(fake_db: FakeDb, as_owner: None) -> None:
    get({"page": 3, "page_size": 10})
    _, params = next((s, p) for s, p in fake_db.statements if "LIMIT" in s)
    assert (params["limit"], params["offset"]) == (10, 20)


@pytest.mark.parametrize("bad", [{"page": 0}, {"page": -1}, {"page": "x"}, {"page": 10001}])
def test_invalid_page_returns_422(fake_db: FakeDb, as_owner: None, bad: dict[str, Any]) -> None:
    response = get(bad)
    assert response.status_code == 422
    assert fake_db.statements == []


@pytest.mark.parametrize("bad", [0, 101, -5, "x", 1.5])
def test_invalid_page_size_returns_422(fake_db: FakeDb, as_owner: None, bad: Any) -> None:
    response = get({"page_size": bad})
    assert response.status_code == 422
    assert fake_db.statements == []


def test_page_size_100_is_allowed(fake_db: FakeDb, as_owner: None) -> None:
    assert get({"page_size": 100}).status_code == 200


@pytest.mark.parametrize("status", STATUSES)
def test_each_of_nine_statuses_is_accepted_and_filters(
    fake_db: FakeDb, as_owner: None, status: ApprovalStatus
) -> None:
    fake_db.invoices = [row(i, status=s) for i, s in enumerate(STATUSES, start=1)]
    response = get({"status": status})
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["status"] for i in items] == [status]
    assert response.json()["total"] == 1


@pytest.mark.parametrize("bad", ["pending", "passed", "APPROVED", "", " approved", "x; DROP TABLE"])
def test_illegal_status_returns_422_without_querying(
    fake_db: FakeDb, as_owner: None, bad: str
) -> None:
    response = get({"status": bad})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert fake_db.statements == []


def test_status_filter_with_no_match_returns_empty(fake_db: FakeDb, as_owner: None) -> None:
    fake_db.invoices = [row(1)]
    body = get({"status": "approved"}).json()
    assert body["items"] == [] and body["total"] == 0


def test_missing_authorization_is_rejected(fake_db: FakeDb) -> None:
    response = client.get(URL)
    assert response.status_code == 401
    assert fake_db.statements == []


def test_invalid_session_is_rejected(fake_db: FakeDb, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(db: Any, token: str) -> SessionRead:
        raise UnauthorizedError("登入已失效，請重新登入")

    monkeypatch.setattr(auth_service, "resolve_session", reject)
    assert get().status_code == 401
    assert fake_db.statements == []


def test_read_snapshot_opens_first_and_transaction_is_closed(
    fake_db: FakeDb, as_owner: None
) -> None:
    get()
    assert fake_db.statements[0][0].startswith("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    assert fake_db.in_txn is False
    assert fake_db.commit.call_count == 0
    assert fake_db.rollback.call_count == 1


def test_query_error_rolls_back_and_returns_500(
    fake_db: FakeDb, as_owner: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_db.error = RuntimeError("boom")
    local = TestClient(app, raise_server_exceptions=False)
    response = local.get(URL, headers=AUTH)
    assert response.status_code == 500
    assert fake_db.in_txn is False


def test_database_not_configured_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    app.dependency_overrides[deps.get_optional_db] = lambda: None
    monkeypatch.setattr(auth_service, "resolve_session", lambda db, token: make_session(OWNER_ID))
    try:
        assert get().status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_list_route_does_not_shadow_detail_route(fake_db: FakeDb, as_owner: None) -> None:
    response = client.get(f"{URL}/{uuid4()}", headers=AUTH)
    assert response.status_code == 404


def test_transaction_already_open_fails_without_clearing_it(
    fake_db: FakeDb, as_owner: None
) -> None:
    fake_db.in_txn = True
    local = TestClient(app, raise_server_exceptions=False)
    assert local.get(URL, headers=AUTH).status_code == 500
    assert fake_db.rollback.call_count == 0
    assert fake_db.statements == []
