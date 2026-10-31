"""
模組名稱：tests.unit.test_invoice_detail
功能說明：測試 GET /api/v1/invoices/{invoice_id}（提交者本人讀取發票詳情）。
注意事項：以模擬 SQL 結果的 DB 替身執行，不連正式 DB 或 Storage；替身依 SQL 的 submitted_by 條件過濾，
    因此可驗證授權確實落在 repository 查詢參數，而不是只靠 service 判斷。
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
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
from app.services import auth_service

client = TestClient(app)

OWNER_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_ID = UUID("33333333-3333-4333-8333-333333333333")
DEPARTMENT_A = UUID("22222222-2222-4222-8222-222222222222")
DEPARTMENT_B = UUID("44444444-4444-4444-8444-444444444444")
INVOICE_ID = UUID("55555555-5555-4555-8555-555555555555")
ITEM_ID = UUID("66666666-6666-4666-8666-666666666666")
EXPIRES = datetime(2026, 10, 31, 1, 0, tzinfo=UTC)
AUTH = {"Authorization": "Bearer synthetic-session-token"}
URL = f"/api/v1/invoices/{INVOICE_ID}"


def make_session(user_id: UUID, department_id: UUID) -> SessionRead:
    department = DepartmentRead(
        department_id=department_id,
        department_code="dept",
        department_name="部門",
        is_primary=True,
    )
    return SessionRead(
        user_id=user_id,
        email="user@example.com",
        display_name="測試使用者",
        department=department,
        departments=(department,),
        expires_at=EXPIRES,
    )


def header_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "invoice_id": INVOICE_ID,
        "status": "pending_department_approval",
        "submission_round": 1,
        "submitted_at": datetime(2026, 10, 30, 9, 30, tzinfo=timezone(timedelta(hours=8))),
        "tax_period": "202610",
        "invoice_track": "CD",
        "invoice_number": "75670992",
        "invoice_date": date(2026, 10, 15),
        "seller_tax_id": "27601907",
        "seller_name": "範例文具行",
        "buyer_tax_id": "04595257",
        "buyer_name": "範例科技股份有限公司",
        "tax_type": "taxable",
        "sales_amount": Decimal("6000.00"),
        "tax_amount": Decimal("300.00"),
        "total_amount": Decimal("6300.00"),
        "total_amount_zh": "陸仟參佰元整",
        "validation_results": {"warnings": []},
        "submitted_by": OWNER_ID,
    }
    row.update(overrides)
    return row


ITEM_ROWS = [
    {
        "line_no": 1,
        "item_name": "辦公用品",
        "quantity": Decimal("2.0000"),
        "unit_price": Decimal("3000.0000"),
        "line_amount": Decimal("6000.00"),
    },
    {
        "line_no": 2,
        "item_name": None,
        "quantity": None,
        "unit_price": Decimal("0.0001"),
        "line_amount": None,
    },
]
FILE_ROW = {
    "mime_type": "image/jpeg",
    "original_filename": "invoice.jpg",
    "size_bytes": 12345,
    "version_no": 1,
}


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> "FakeResult":
        return self

    def one_or_none(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def all(self) -> list[dict[str, Any]]:
        return self.rows


@dataclass
class FakeDb:
    """依 SQL 片段回應；擁有者過濾與輪次過濾依實際綁定參數執行。"""

    invoice: dict[str, Any] | None = field(default_factory=header_row)
    items: list[dict[str, Any]] = field(default_factory=lambda: list(ITEM_ROWS))
    reviews: list[dict[str, Any]] = field(default_factory=list)
    file: dict[str, Any] | None = field(default_factory=lambda: dict(FILE_ROW))
    statements: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    commit: MagicMock = field(default_factory=MagicMock)
    rollback: MagicMock = field(default_factory=MagicMock)
    error: Exception | None = None
    in_txn: bool = (
        False  # 是否已有進行中的交易（第一個陳述式執行時自動開始，commit／rollback 結束）
    )

    def __post_init__(self) -> None:
        self.commit.side_effect = self._end_transaction
        self.rollback.side_effect = self._end_transaction

    def _end_transaction(self) -> None:
        self.in_txn = False

    def in_transaction(self) -> bool:
        return self.in_txn

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> FakeResult:
        sql = " ".join(str(statement).split())
        params = params or {}
        self.statements.append((sql, params))
        self.in_txn = True
        if self.error is not None:
            raise self.error
        if sql.startswith("SET TRANSACTION"):
            return FakeResult([])
        if "FROM public.invoices WHERE" in sql:
            owned = (
                self.invoice is not None
                and self.invoice["invoice_id"] == params["invoice_id"]
                and self.invoice["submitted_by"] == params["user_id"]
            )
            return FakeResult([self.invoice] if owned else [])
        if "FROM public.invoice_items" in sql:
            return FakeResult(self.items)
        if "FROM public.invoice_field_reviews" in sql:
            return FakeResult(self.reviews)
        if "FROM public.invoice_files" in sql:
            return FakeResult([self.file] if self.file else [])
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
    monkeypatch.setattr(
        auth_service, "resolve_session", lambda db, token: make_session(OWNER_ID, DEPARTMENT_A)
    )


def login_as(monkeypatch: pytest.MonkeyPatch, user_id: UUID, department_id: UUID) -> None:
    monkeypatch.setattr(
        auth_service, "resolve_session", lambda db, token: make_session(user_id, department_id)
    )


def get(url: str = URL) -> Any:
    return client.get(url, headers=AUTH)


def test_owner_reads_invoice_header_and_items(fake_db: FakeDb, as_owner: None) -> None:
    response = get()
    assert response.status_code == 200
    body = response.json()
    assert body["invoice_id"] == str(INVOICE_ID)
    assert body["status"] == "pending_department_approval"
    assert body["submission_round"] == 1
    assert body["tax_period"] == "202610"
    assert body["invoice_track"] == "CD"
    assert body["invoice_number"] == "75670992"
    assert body["invoice_date"] == "2026-10-15"
    assert body["seller_tax_id"] == "27601907"
    assert body["buyer_name"] == "範例科技股份有限公司"
    assert body["tax_type"] == "taxable"
    assert body["total_amount_zh"] == "陸仟參佰元整"
    # 時間轉成 UTC 並保留時區
    assert datetime.fromisoformat(body["submitted_at"]) == datetime(2026, 10, 30, 1, 30, tzinfo=UTC)
    assert body["submitted_at"].endswith(("Z", "+00:00"))
    assert [item["line_no"] for item in body["items"]] == [1, 2]
    assert body["items"][0]["item_name"] == "辦公用品"


def test_same_department_other_user_gets_404(
    fake_db: FakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    login_as(monkeypatch, OTHER_ID, DEPARTMENT_A)  # 與提交者同一個部門
    response = get()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_different_department_other_user_gets_404(
    fake_db: FakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    login_as(monkeypatch, OTHER_ID, DEPARTMENT_B)
    assert get().status_code == 404


def test_owner_after_department_switch_still_reads(
    fake_db: FakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 發票是在部門 A 提交的；本人 Session 現在選取部門 B
    login_as(monkeypatch, OWNER_ID, DEPARTMENT_B)
    response = get()
    assert response.status_code == 200
    assert response.json()["invoice_id"] == str(INVOICE_ID)
    # 查詢條件只用發票與本人，沒有部門參數
    for _, params in fake_db.statements:
        assert DEPARTMENT_A not in params.values()
        assert DEPARTMENT_B not in params.values()
        assert "department_id" not in params


def test_not_found_and_not_owner_have_identical_response(
    fake_db: FakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    login_as(monkeypatch, OTHER_ID, DEPARTMENT_A)
    not_owner = get()
    login_as(monkeypatch, OWNER_ID, DEPARTMENT_A)
    missing = get(f"/api/v1/invoices/{uuid4()}")
    assert missing.status_code == not_owner.status_code == 404
    assert missing.json() == not_owner.json()


def test_invalid_uuid_returns_422(fake_db: FakeDb, as_owner: None) -> None:
    response = get("/api/v1/invoices/not-a-uuid")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert fake_db.statements == []


def test_missing_authorization_is_rejected(fake_db: FakeDb) -> None:
    response = client.get(URL)
    assert response.status_code == 401
    assert fake_db.statements == []


def test_invalid_session_is_rejected(fake_db: FakeDb, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(db: Any, token: str) -> SessionRead:
        raise UnauthorizedError("登入已失效，請重新登入")

    monkeypatch.setattr(auth_service, "resolve_session", reject)
    response = get()
    assert response.status_code == 401
    assert fake_db.statements == []


def test_items_are_ordered_by_line_no_in_sql(fake_db: FakeDb, as_owner: None) -> None:
    get()
    item_sql = next(sql for sql, _ in fake_db.statements if "FROM public.invoice_items" in sql)
    assert item_sql.endswith("ORDER BY line_no")


def test_decimal_precision_and_null_preserved(fake_db: FakeDb, as_owner: None) -> None:
    fake_db.invoice = header_row(
        sales_amount=Decimal("12345678901234567.89"),
        tax_amount=None,
        total_amount=Decimal("0.00"),
        total_amount_zh=None,
        seller_name=None,
        tax_type=None,
        invoice_date=None,
        submitted_at=None,
    )
    body = get().json()
    assert body["sales_amount"] == "12345678901234567.89"
    assert body["tax_amount"] is None
    assert body["total_amount"] == "0.00"
    assert body["total_amount_zh"] is None
    assert body["seller_name"] is None
    assert body["tax_type"] is None
    assert body["invoice_date"] is None
    assert body["submitted_at"] is None
    first, second = body["items"]
    assert first["quantity"] == "2.0000"
    assert first["unit_price"] == "3000.0000"
    assert first["line_amount"] == "6000.00"
    assert second["item_name"] is None
    assert second["quantity"] is None
    assert second["unit_price"] == "0.0001"
    assert second["line_amount"] is None


def test_modified_fields_returned_as_recorded(fake_db: FakeDb, as_owner: None) -> None:
    fake_db.reviews = [
        {
            "field_scope": "header",
            "line_no": None,
            "field_name": "seller_name",
            "ai_original_value": "範例文具",
            "submitted_value": "範例文具行",
        },
        {
            "field_scope": "item",
            "line_no": 1,
            "field_name": "line_amount",
            "ai_original_value": "600",
            "submitted_value": "6000",
        },
        {
            "field_scope": "item",
            "line_no": 2,
            "field_name": "item_name",
            "ai_original_value": None,
            "submitted_value": "新增品名",
        },
    ]
    body = get().json()
    assert body["modified_fields"] == [
        {
            "field_scope": "header",
            "line_no": None,
            "field_name": "seller_name",
            "ai_original_value": "範例文具",
            "submitted_value": "範例文具行",
        },
        {
            "field_scope": "item",
            "line_no": 1,
            "field_name": "line_amount",
            "ai_original_value": "600",
            "submitted_value": "6000",
        },
        {
            "field_scope": "item",
            "line_no": 2,
            "field_name": "item_name",
            "ai_original_value": None,
            "submitted_value": "新增品名",
        },
    ]
    review_sql, params = next(
        (sql, p) for sql, p in fake_db.statements if "invoice_field_reviews" in sql
    )
    assert params["submission_round"] == 1
    assert "submission_round = :submission_round" in review_sql


def test_no_review_rows_returns_empty_list(fake_db: FakeDb, as_owner: None) -> None:
    body = get().json()
    assert body["modified_fields"] == []
    assert "original_values" not in body


def test_deleted_ai_item_uses_existing_modified_field_contract(
    fake_db: FakeDb, as_owner: None
) -> None:
    deleted = {
        "item_name": "舊品名",
        "quantity": "1",
        "unit_price": "100",
        "line_amount": "100",
    }
    fake_db.reviews = [
        {
            "field_scope": "header",
            "line_no": None,
            "field_name": "deleted_item_3",
            "ai_original_value": deleted,
            "submitted_value": None,
        }
    ]
    (field_record,) = get().json()["modified_fields"]
    assert field_record["field_scope"] == "header"
    assert field_record["line_no"] is None
    assert field_record["field_name"] == "deleted_item_3"
    assert field_record["ai_original_value"] == deleted
    assert field_record["submitted_value"] is None


def test_warnings_returned_and_empty(fake_db: FakeDb, as_owner: None) -> None:
    assert get().json()["warnings"] == []
    warning = {"field": "tax_amount", "code": "tax_amount_mismatch", "message": "稅額與銷售額不符"}
    fake_db.invoice = header_row(validation_results={"warnings": [warning]})
    assert get().json()["warnings"] == [warning]


def test_null_or_default_validation_results_means_no_warnings(
    fake_db: FakeDb, as_owner: None
) -> None:
    for stored in (None, {}, {"warnings": []}):
        fake_db.invoice = header_row(validation_results=stored)
        response = get()
        assert response.status_code == 200
        assert response.json()["warnings"] == []


def test_extra_keys_in_valid_warning_are_not_forwarded(fake_db: FakeDb, as_owner: None) -> None:
    good = {"field": "items", "code": "x", "message": "m", "severity": "error"}
    fake_db.invoice = header_row(validation_results={"warnings": [good]})
    assert get().json()["warnings"] == [{"field": "items", "code": "x", "message": "m"}]


@pytest.mark.parametrize(
    ("stored", "reason"),
    [
        ("not-an-object", "validation_results_not_object"),
        (["warnings"], "validation_results_not_object"),
        ({"warnings": None}, "warnings_not_list"),
        ({"warnings": {"field": "a"}}, "warnings_not_list"),
        ({"warnings": ["bad"]}, "warning_not_object"),
        ({"warnings": [{"field": "a", "code": "b"}]}, "warning_message_invalid"),
        ({"warnings": [{"field": 1, "code": "b", "message": "m"}]}, "warning_field_invalid"),
        ({"warnings": [{"field": "a", "code": None, "message": "m"}]}, "warning_code_invalid"),
    ],
)
def test_malformed_validation_results_fail_instead_of_dropping(
    fake_db: FakeDb,
    as_owner: None,
    caplog: pytest.LogCaptureFixture,
    stored: Any,
    reason: str,
) -> None:
    fake_db.invoice = header_row(validation_results=stored)
    with caplog.at_level(logging.ERROR):
        response = get()
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INVOICE_DATA_INVALID"
    assert error["details"] is None
    assert "warnings" not in response.json()
    assert reason in caplog.text
    assert str(INVOICE_ID) in caplog.text


def test_one_bad_warning_among_good_ones_fails_whole_response(
    fake_db: FakeDb, as_owner: None, caplog: pytest.LogCaptureFixture
) -> None:
    good = {"field": "tax_amount", "code": "c", "message": "SECRET-MESSAGE-TEXT"}
    fake_db.invoice = header_row(
        validation_results={"warnings": [good, {"field": "a", "code": "b", "message": 5}]},
        buyer_name="SECRET-BUYER",
    )
    with caplog.at_level(logging.DEBUG):
        response = get()
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INVOICE_DATA_INVALID"
    # 回應與 log 都不含發票內容或警示文字
    for text in (response.text, caplog.text):
        assert "SECRET-MESSAGE-TEXT" not in text
        assert "SECRET-BUYER" not in text
    assert "項目 1" in caplog.text
    # 資料庫交易已在建構回應前結束
    assert fake_db.in_txn is False


def test_transaction_already_open_fails_safely_without_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeDb(in_txn=True)

    def override() -> Iterator[FakeDb]:
        yield db

    app.dependency_overrides[deps.get_optional_db] = override
    try:
        monkeypatch.setattr(
            auth_service, "resolve_session", lambda d, token: make_session(OWNER_ID, DEPARTMENT_A)
        )
        failing_client = TestClient(app, raise_server_exceptions=False)
        response = failing_client.get(URL, headers=AUTH)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    # 沒有執行任何 SQL，也沒有 rollback／commit 別人的交易
    assert db.statements == []
    db.rollback.assert_not_called()
    db.commit.assert_not_called()
    assert db.in_txn is True


def test_transaction_is_opened_and_closed_by_get_only(fake_db: FakeDb, as_owner: None) -> None:
    assert fake_db.in_txn is False
    assert get().status_code == 200
    assert fake_db.in_txn is False
    fake_db.rollback.assert_called_once()
    fake_db.commit.assert_not_called()


def test_not_found_rolls_back_its_own_transaction(
    fake_db: FakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    login_as(monkeypatch, OTHER_ID, DEPARTMENT_A)
    assert get().status_code == 404
    assert fake_db.in_txn is False
    fake_db.rollback.assert_called_once()


def test_snapshot_setup_failure_rolls_back_its_own_transaction(
    fake_db: FakeDb, as_owner: None
) -> None:
    fake_db.error = RuntimeError("synthetic set failure")
    failing_client = TestClient(app, raise_server_exceptions=False)
    assert failing_client.get(URL, headers=AUTH).status_code == 500
    assert fake_db.in_txn is False
    fake_db.rollback.assert_called_once()


def test_current_file_metadata_present(fake_db: FakeDb, as_owner: None) -> None:
    assert get().json()["file"] == FILE_ROW
    file_sql = next(sql for sql, _ in fake_db.statements if "FROM public.invoice_files" in sql)
    assert "is_current = true" in file_sql


def test_no_current_file_returns_null(fake_db: FakeDb, as_owner: None) -> None:
    fake_db.file = None
    response = get()
    assert response.status_code == 200
    assert response.json()["file"] is None


def test_response_has_no_storage_key(fake_db: FakeDb, as_owner: None) -> None:
    fake_db.file = {
        **FILE_ROW,
        "storage_path": f"{OWNER_ID}/INVOICES_20261030093000_x.jpg",
        "bucket_name": "invoices",
    }
    response = get()
    assert response.status_code == 200
    assert set(response.json()["file"]) == {
        "mime_type",
        "original_filename",
        "size_bytes",
        "version_no",
    }
    text = response.text
    assert "storage_path" not in text
    assert "bucket" not in text
    assert "INVOICES_" not in text
    # 查詢本身也不讀取物件路徑
    file_sql = next(sql for sql, _ in fake_db.statements if "FROM public.invoice_files" in sql)
    assert "storage_path" not in file_sql
    assert "bucket_name" not in file_sql


def test_db_not_configured_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def override() -> Iterator[None]:
        yield None

    app.dependency_overrides[deps.get_optional_db] = override
    try:
        monkeypatch.setattr(
            auth_service, "resolve_session", lambda db, token: make_session(OWNER_ID, DEPARTMENT_A)
        )
        response = get()
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_query_error_rolls_back_and_returns_500(
    fake_db: FakeDb, as_owner: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_db.error = RuntimeError("synthetic db failure")
    # 讓例外交給全域處理器，而不是在測試用戶端重新拋出
    failing_client = TestClient(app, raise_server_exceptions=False)
    response = failing_client.get(URL, headers=AUTH)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "synthetic" not in response.text
    fake_db.rollback.assert_called()


def test_get_is_read_only(fake_db: FakeDb, as_owner: None) -> None:
    fake_db.reviews = [
        {
            "field_scope": "header",
            "line_no": None,
            "field_name": "buyer_name",
            "ai_original_value": "a",
            "submitted_value": "b",
        }
    ]
    assert get().status_code == 200
    fake_db.commit.assert_not_called()
    for sql, _ in fake_db.statements:
        assert sql.startswith(("SELECT", "SET TRANSACTION"))
        for keyword in ("INSERT", "UPDATE", "DELETE"):
            assert keyword not in sql.upper().split()
    # 快照設定必須是交易的第一個陳述式
    assert fake_db.statements[0][0].startswith("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")


def test_authorization_filter_is_in_header_query(fake_db: FakeDb, as_owner: None) -> None:
    get()
    sql, params = next((s, p) for s, p in fake_db.statements if "FROM public.invoices WHERE" in s)
    assert "submitted_by = :user_id" in sql
    assert params == {"invoice_id": INVOICE_ID, "user_id": OWNER_ID}
