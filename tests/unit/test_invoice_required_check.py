"""
模組名稱：tests.unit.test_invoice_required_check
功能說明：測試 POST /api/v1/invoices/check-required（必填缺漏檢核），以及正式提交 POST /api/v1/invoices
    的 Pydantic 422 行為沒有被改變。
注意事項：以 Session、DB、repository 替身執行，不連正式 DB、Storage 或外部服務；
    任何 DB 或 repository 呼叫都會讓測試失敗。
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core import deps
from app.core.exceptions import UnauthorizedError
from app.db.repositories import invoice_repository, recognition_repository
from app.main import app
from app.schemas.auth import DepartmentRead, SessionRead
from app.services import auth_service

client = TestClient(app)

USER_ID = UUID("11111111-1111-4111-8111-111111111111")
DEPARTMENT_ID = UUID("22222222-2222-4222-8222-222222222222")
RECOGNITION_ID = "33333333-3333-4333-8333-333333333333"
AUTH = {"Authorization": "Bearer synthetic-session-token"}
CHECK = "/api/v1/invoices/check-required"
SUBMIT = "/api/v1/invoices"
# 表頭必填欄位（InvoiceSubmitRequest 目前的宣告；規則改變時此處與模型須一起更新）
REQUIRED_HEADER = (
    "invoice_track",
    "invoice_number",
    "invoice_date",
    "seller_tax_id",
    "tax_type",
    "sales_amount",
    "tax_amount",
    "total_amount",
)
OPTIONAL_HEADER = ("seller_name", "buyer_tax_id", "buyer_name", "total_amount_zh")


def session_read() -> SessionRead:
    department = DepartmentRead(
        department_id=DEPARTMENT_ID,
        department_code="purchasing_d",
        department_name="採購部",
        is_primary=True,
    )
    return SessionRead(
        user_id=USER_ID,
        email="user@example.com",
        display_name="測試使用者",
        department=department,
        departments=(department,),
        expires_at=datetime(2026, 10, 29, 2, 0, tzinfo=UTC) + timedelta(hours=1),
    )


def valid_body(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "recognition_id": RECOGNITION_ID,
        "invoice_track": "CD",
        "invoice_number": "75670992",
        "invoice_date": "2026-08-15",
        "seller_tax_id": "27601907",
        "seller_name": "範例文具行",
        "buyer_tax_id": "04595257",
        "buyer_name": "範例科技股份有限公司",
        "tax_type": "taxable",
        "sales_amount": "6000",
        "tax_amount": "300",
        "total_amount": "6300",
        "total_amount_zh": "陸仟參佰元整",
        "items": [
            {
                "source_line_no": 1,
                "item_name": "辦公用品",
                "quantity": "2",
                "unit_price": "3000",
                "line_amount": "6000",
            }
        ],
    }
    return body | changes


def check(body: Any, headers: dict[str, str] | None = AUTH) -> Any:
    return client.post(CHECK, json=body, headers=headers or {})


def missing_pairs(response: Any) -> list[tuple[str, int | None]]:
    assert response.status_code == 200, response.text
    return [(item["field"], item["line_no"]) for item in response.json()["missing"]]


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """Session 與 DB 替身；任何 repository 或 DB 呼叫都視為錯誤。"""
    db = MagicMock()

    def override() -> Iterator[MagicMock]:
        yield db

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("必填檢核與缺漏的提交不應呼叫 repository")

    app.dependency_overrides[deps.get_optional_db] = override
    monkeypatch.setattr(auth_service, "resolve_session", lambda db, token: session_read())
    for module in (invoice_repository, recognition_repository):
        for name in dir(module):
            if name.startswith(("insert", "lock", "link", "exists", "mark", "complete")):
                monkeypatch.setattr(module, name, forbidden)
    yield db
    app.dependency_overrides.clear()
    assert db.mock_calls == []


def test_complete_body_has_no_missing(isolated: MagicMock) -> None:
    response = check(valid_body())

    assert response.status_code == 200
    assert response.json() == {"required_complete": True, "missing": []}


def test_response_shape(isolated: MagicMock) -> None:
    body = valid_body()
    del body["invoice_number"]

    assert check(body).json() == {
        "required_complete": False,
        "missing": [
            {
                "field": "invoice_number",
                "code": "required_missing",
                "message": "請填寫發票號碼",
                "line_no": None,
            }
        ],
    }


@pytest.mark.parametrize("field", REQUIRED_HEADER)
def test_each_required_header_field_missing_alone(isolated: MagicMock, field: str) -> None:
    body = valid_body()
    del body[field]

    assert missing_pairs(check(body)) == [(field, None)]


@pytest.mark.parametrize("blank", [None, "", "   ", "　", "　 \t", " ", "﻿", "\n"], ids=repr)
def test_blank_values_count_as_missing(isolated: MagicMock, blank: Any) -> None:
    for field in REQUIRED_HEADER:
        assert missing_pairs(check(valid_body(**{field: blank}))) == [(field, None)], field


def test_multiple_missing_reported_together_in_field_order(isolated: MagicMock) -> None:
    body = valid_body(invoice_track="", invoice_date=None, tax_type=" ", total_amount="　")
    del body["seller_tax_id"]

    response = check(body)

    assert missing_pairs(response) == [
        ("invoice_track", None),
        ("invoice_date", None),
        ("seller_tax_id", None),
        ("tax_type", None),
        ("total_amount", None),
    ]
    assert response.json()["required_complete"] is False


def test_empty_body_lists_every_required_field_and_no_internal_ones(isolated: MagicMock) -> None:
    pairs = missing_pairs(check({}))

    assert [field for field, _ in pairs] == [*REQUIRED_HEADER, "items"]
    assert all(line_no is None for _, line_no in pairs)
    assert not {"recognition_id", "changes"} & {field for field, _ in pairs}


@pytest.mark.parametrize("field", OPTIONAL_HEADER)
@pytest.mark.parametrize("blank", [None, "", "  ", "　"])
def test_optional_header_fields_never_missing(isolated: MagicMock, field: str, blank: Any) -> None:
    assert check(valid_body(**{field: blank})).json() == {"required_complete": True, "missing": []}


def test_optional_header_fields_may_be_absent(isolated: MagicMock) -> None:
    body = valid_body()
    for field in OPTIONAL_HEADER:
        del body[field]

    assert check(body).json()["required_complete"] is True


@pytest.mark.parametrize("blank", [None, "", "  ", "　"])
def test_optional_item_fields_never_missing(isolated: MagicMock, blank: Any) -> None:
    item = {"item_name": "辦公用品", "quantity": blank, "unit_price": blank, "line_amount": "6000"}

    assert check(valid_body(items=[item])).json()["required_complete"] is True


def test_missing_items_and_empty_items(isolated: MagicMock) -> None:
    absent = valid_body()
    del absent["items"]

    assert missing_pairs(check(absent)) == [("items", None)]
    assert missing_pairs(check(valid_body(items=[]))) == [("items", None)]
    assert missing_pairs(check(valid_body(items=None))) == [("items", None)]


def test_item_missing_reports_the_right_line_numbers(isolated: MagicMock) -> None:
    items = [
        {"item_name": "甲", "line_amount": "100"},
        {"item_name": "", "line_amount": "200"},
        {"item_name": "丙", "line_amount": ""},
        {"line_amount": None},
    ]

    response = check(valid_body(items=items))

    assert missing_pairs(response) == [
        ("item_name", 2),
        ("line_amount", 3),
        ("item_name", 4),
        ("line_amount", 4),
    ]
    assert response.json()["missing"][0]["message"] == "請填寫品名"
    assert response.json()["missing"][1]["message"] == "請填寫明細金額"


def test_missing_and_format_errors_together_report_only_real_missing(isolated: MagicMock) -> None:
    """同時有缺漏與格式錯誤：missing 只含真正缺漏；格式錯誤的欄位（有值）一個都不列入。"""
    body = valid_body(
        invoice_track="cd",  # 格式錯誤（有值）
        invoice_number="",  # 缺漏
        invoice_date="2026/08/15",  # 格式錯誤
        seller_tax_id="1234567",  # 格式錯誤
        tax_type="",  # 缺漏
        sales_amount="6,000",  # 格式錯誤
        tax_amount=None,  # 缺漏
        total_amount="-5",  # 格式錯誤
        items=[
            {"item_name": "甲", "line_amount": "abc"},  # 金額格式錯誤，不是缺漏
            {"item_name": "", "line_amount": "100"},  # 缺品名
            {"item_name": "丙", "line_amount": " "},  # 缺金額
        ],
    )

    response = check(body)

    assert response.json()["required_complete"] is False
    assert missing_pairs(response) == [
        ("invoice_number", None),
        ("tax_type", None),
        ("tax_amount", None),
        ("item_name", 2),
        ("line_amount", 3),
    ]
    fields = {item["field"] for item in response.json()["missing"]}
    assert not fields & {
        "invoice_track",
        "invoice_date",
        "seller_tax_id",
        "sales_amount",
        "total_amount",
    }


def test_all_required_present_but_formats_wrong_is_complete_not_valid(isolated: MagicMock) -> None:
    """全部必填都有值但格式都錯：required_complete 仍為 true（只代表沒有缺漏），正式提交仍 422。"""
    body = valid_body(
        invoice_track="cd",
        invoice_number="123",
        seller_tax_id="x",
        sales_amount="6,000",
        tax_type="?",
    )

    assert check(body).json() == {"required_complete": True, "missing": []}
    response = client.post(SUBMIT, json=body, headers=AUTH)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_header_and_item_missing_together(isolated: MagicMock) -> None:
    items = [{"item_name": "甲", "line_amount": "100"}, {"item_name": "乙"}]

    pairs = missing_pairs(check(valid_body(invoice_number="", items=items)))

    assert pairs == [("invoice_number", None), ("line_amount", 2)]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("invoice_track", "cd"),
        ("invoice_track", "ＣＤ"),
        ("invoice_number", "7567099"),
        ("invoice_number", "７５６７０９９２"),
        ("seller_tax_id", "1234567"),
        ("seller_tax_id", "２７６０１９０７"),
        ("invoice_date", "2026/08/15"),
        ("sales_amount", "6,000"),
        ("sales_amount", "-1"),
        ("sales_amount", "abc"),
        ("sales_amount", 6000.5),
        ("tax_type", "unknown"),
    ],
)
def test_format_errors_are_not_missing_and_submit_keeps_422(
    isolated: MagicMock, field: str, value: Any
) -> None:
    body = valid_body(**{field: value})

    check_response = check(body)
    submit_response = client.post(SUBMIT, json=body, headers=AUTH)

    # 檢核只回報「必填缺漏」：有值但格式不符不算缺漏，required_complete 也就不代表資料有效
    assert check_response.json() == {"required_complete": True, "missing": []}
    # 正式提交的 Pydantic 驗證照舊，在進入 service（以及任何 DB 寫入）前攔下
    assert submit_response.status_code == 422
    error = submit_response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert [item["loc"] for item in error["details"]] == [["body", field]]


def test_submit_with_missing_required_field_keeps_pydantic_422(isolated: MagicMock) -> None:
    body = valid_body()
    del body["invoice_number"]
    body["seller_tax_id"] = ""

    response = client.post(SUBMIT, json=body, headers=AUTH)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["message"] == "請求參數格式錯誤"
    assert {tuple(item["loc"]) for item in error["details"]} == {
        ("body", "invoice_number"),
        ("body", "seller_tax_id"),
    }
    assert all(set(item) == {"loc", "type", "msg"} for item in error["details"])


def test_non_object_items_and_item_types_are_not_missing(isolated: MagicMock) -> None:
    assert check(valid_body(items="abc")).json()["required_complete"] is True
    assert check(valid_body(items=["x"])).json()["required_complete"] is True
    assert check(valid_body(items=[{"item_name": 1.5, "line_amount": "1"}])).json() == {
        "required_complete": True,
        "missing": [],
    }
    assert check(valid_body(items=[{"item_name": "甲", "line_amount": "abc"}])).json() == {
        "required_complete": True,
        "missing": [],
    }


def test_response_does_not_echo_submitted_values(isolated: MagicMock) -> None:
    secret = "SYNTHETIC-SECRET-VALUE-123"
    body = valid_body(seller_name=secret, invoice_number="", buyer_name=secret)

    assert secret not in check(body).text


def test_requires_bearer_token(isolated: MagicMock) -> None:
    response = client.post(CHECK, json=valid_body())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_requires_bearer_token_even_when_body_is_incomplete(isolated: MagicMock) -> None:
    response = client.post(CHECK, json={})

    assert response.status_code == 401


def test_invalid_session_is_rejected(isolated: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(db: Any, token: str) -> SessionRead:
        raise UnauthorizedError("登入已失效，請重新登入")

    monkeypatch.setattr(auth_service, "resolve_session", reject)

    response = check(valid_body())

    assert response.status_code == 401
    assert "missing" not in response.json()


def test_body_must_be_a_json_object(isolated: MagicMock) -> None:
    response = client.post(CHECK, json=[], headers=AUTH)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_route_does_not_shadow_existing_invoice_routes() -> None:
    paths = app.openapi()["paths"]

    for path in (
        "/api/v1/invoices/check-required",
        "/api/v1/invoices/check-duplicate",
        "/api/v1/invoices/recognize",
        "/api/v1/invoices",
    ):
        assert "post" in paths[path]
