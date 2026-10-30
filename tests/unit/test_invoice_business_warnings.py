"""
模組名稱：tests.unit.test_invoice_business_warnings
功能說明：測試業務警示——發票日期晚於台灣當天（invoice_date_future）、金額與稅額不一致——
    的預覽端點 POST /api/v1/invoices/check-warnings，以及正式送出 POST /api/v1/invoices 重新計算並保存的警示。
注意事項：以 Session、DB、repository、Storage 替身執行，不連正式 DB、Storage 或外部服務；
    「今天」一律注入或以替身固定，不依賴執行當天的日期。警示都只是提醒，不得產生額外的 422 或阻擋。
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core import deps
from app.db.repositories import invoice_repository, recognition_repository
from app.main import app
from app.services import auth_service, invoice_upload_service, invoice_warning_service
from app.services.invoice_upload_service import future_date_warnings, today_taipei
from app.services.invoice_warning_service import preview_warnings
from tests.unit import test_invoice_upload as upload_tests
from tests.unit.test_invoice_required_check import session_read, valid_body

client = TestClient(app)
# 借用辨識／送出的替身 fixture（pytest 以名稱在本模組找 fixture）
fake_db = upload_tests.fake_db
services = upload_tests.services
recognize = upload_tests.recognize
submit_payload = upload_tests.submit_payload
AUTH = {"Authorization": "Bearer synthetic-session-token"}
PREVIEW = "/api/v1/invoices/check-warnings"
TODAY = date(2026, 10, 30)
FUTURE_MESSAGE = "發票日期晚於今天，請核對原始發票。"


def codes(result: Any) -> list[str]:
    return [warning.code for warning in result.warnings]


# ---- 台灣當天日期（可注入時鐘）----


@pytest.mark.parametrize(
    ("utc_now", "expected"),
    [
        (datetime(2026, 10, 30, 15, 59, 59, tzinfo=UTC), date(2026, 10, 30)),  # 台灣 23:59:59
        (datetime(2026, 10, 30, 16, 0, 0, tzinfo=UTC), date(2026, 10, 31)),  # 台灣 00:00:00 跨日
        (datetime(2026, 10, 30, 0, 0, 0, tzinfo=UTC), date(2026, 10, 30)),
        (datetime(2026, 12, 31, 16, 0, 0, tzinfo=UTC), date(2027, 1, 1)),  # 跨年
    ],
)
def test_today_taipei_uses_taiwan_date(utc_now: datetime, expected: date) -> None:
    assert today_taipei(utc_now) == expected


def test_today_taipei_defaults_to_current_time() -> None:
    assert abs((today_taipei() - datetime.now(UTC).date()).days) <= 1


# ---- 未來日期規則 ----


@pytest.mark.parametrize(
    ("invoice_date", "future"),
    [
        (TODAY, False),
        (TODAY - timedelta(days=1), False),
        (date(2026, 1, 1), False),
        (TODAY + timedelta(days=1), True),
        (date(2027, 1, 1), True),  # 跨年
        (date(2099, 12, 31), True),
    ],
)
def test_future_date_rule(invoice_date: date, future: bool) -> None:
    result = future_date_warnings(invoice_date, TODAY)

    assert [(w.field, w.code, w.message) for w in result] == (
        [("invoice_date", "invoice_date_future", FUTURE_MESSAGE)] if future else []
    )


def test_future_date_rule_skips_missing_date() -> None:
    assert future_date_warnings(None, TODAY) == []


def test_taiwan_midnight_boundary_decides_future() -> None:
    before = today_taipei(datetime(2026, 10, 30, 15, 59, tzinfo=UTC))  # 台灣仍是 10/30
    after = today_taipei(datetime(2026, 10, 30, 16, 0, tzinfo=UTC))  # 台灣已是 10/31

    assert future_date_warnings(date(2026, 10, 31), before) != []
    assert future_date_warnings(date(2026, 10, 31), after) == []


# ---- 預覽服務 ----


def test_preview_clean_body_has_no_warnings() -> None:
    result = preview_warnings(valid_body(), TODAY)

    assert result.warnings == ()
    assert result.checked_on == TODAY


def test_preview_total_mismatch_matches_acceptance_case() -> None:
    result = preview_warnings(valid_body(total_amount="9999"), TODAY)

    assert [(w.field, w.code) for w in result.warnings] == [
        ("total_amount", "total_amount_mismatch")
    ]


def test_preview_fixing_total_clears_warning() -> None:
    assert preview_warnings(valid_body(total_amount="9999"), TODAY).warnings != ()
    assert preview_warnings(valid_body(total_amount="6300"), TODAY).warnings == ()


def test_preview_items_total_mismatch() -> None:
    body = valid_body()
    body["items"][0]["line_amount"] = "5000"

    assert codes(preview_warnings(body, TODAY)) == ["items_total_mismatch"]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"tax_amount": "400", "total_amount": "6400"}, ["tax_amount_mismatch"]),
        ({"tax_amount": "301", "total_amount": "6301"}, []),  # 容差 1 元內
        ({"tax_type": "zero_rated"}, ["tax_amount_mismatch"]),
        ({"tax_type": "tax_exempt"}, ["tax_amount_mismatch"]),
        ({"tax_type": "zero_rated", "tax_amount": "0", "total_amount": "6000"}, []),
        ({"tax_type": "tax_exempt", "tax_amount": "0", "total_amount": "6000"}, []),
        (
            {"tax_type": "tax_exempt", "tax_amount": "0", "total_amount": "9999"},
            ["total_amount_mismatch"],
        ),
    ],
)
def test_preview_keeps_existing_tax_type_rules(
    changes: dict[str, Any], expected: list[str]
) -> None:
    assert codes(preview_warnings(valid_body(**changes), TODAY)) == expected


@pytest.mark.parametrize("field", ["sales_amount", "tax_amount", "total_amount"])
@pytest.mark.parametrize("bad", [None, "", "  ", "abc", "12.345", "-1", 1.5, True, [], {}])
def test_preview_missing_or_bad_amount_makes_no_arithmetic_claim(field: str, bad: Any) -> None:
    # 三個金額欄位任一未知，「銷售額＋稅額＝總計」就不判斷；明細合計僅在銷售額已知時才比
    result = preview_warnings(valid_body(**{field: bad}), TODAY)

    assert "total_amount_mismatch" not in codes(result)
    if field != "sales_amount":
        assert result.warnings == ()


def test_preview_missing_tax_type_skips_tax_rule() -> None:
    body = valid_body(tax_type=None, tax_amount="999", total_amount="6999")

    assert codes(preview_warnings(body, TODAY)) == []


def test_preview_blank_line_amount_skips_items_total() -> None:
    body = valid_body()
    body["items"][0]["line_amount"] = ""

    assert codes(preview_warnings(body, TODAY)) == []


@pytest.mark.parametrize("items", [None, [], "x", 5, [None], ["a"], [{}]])
def test_preview_odd_items_never_crash_or_claim(items: Any) -> None:
    assert codes(preview_warnings(valid_body(items=items), TODAY)) == []


@pytest.mark.parametrize(
    "bad_date",
    [
        None,
        "",
        "2026-13-01",
        "2026-02-30",
        "20261031",
        "2026/10/31",
        20261031,
        [],
        "９９９９-12-31",
    ],
)
def test_preview_bad_date_gives_no_future_warning(bad_date: Any) -> None:
    assert codes(preview_warnings(valid_body(invoice_date=bad_date), TODAY)) == []


def test_preview_empty_body_is_harmless() -> None:
    assert preview_warnings({}, TODAY).warnings == ()


def test_preview_future_and_amount_warnings_coexist_in_submit_order() -> None:
    body = valid_body(invoice_date="2027-01-01", total_amount="9999")

    assert codes(preview_warnings(body, TODAY)) == ["invoice_date_future", "total_amount_mismatch"]


# ---- 預覽端點 ----


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    db = MagicMock()

    def override() -> Iterator[MagicMock]:
        yield db

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("業務警示預覽不應呼叫 repository")

    app.dependency_overrides[deps.get_optional_db] = override
    monkeypatch.setattr(auth_service, "resolve_session", lambda db, token: session_read())
    monkeypatch.setattr(invoice_warning_service, "today_taipei", lambda: TODAY)
    for module in (invoice_repository, recognition_repository):
        for name in dir(module):
            if name.startswith(("insert", "lock", "link", "exists", "mark", "complete")):
                monkeypatch.setattr(module, name, forbidden)
    yield db
    app.dependency_overrides.clear()
    assert db.mock_calls == []


def test_endpoint_returns_warnings_and_checked_on(isolated: MagicMock) -> None:
    response = client.post(
        PREVIEW, json=valid_body(invoice_date="2026-10-31", total_amount="9999"), headers=AUTH
    )

    assert response.status_code == 200
    assert response.json() == {
        "warnings": [
            {"field": "invoice_date", "code": "invoice_date_future", "message": FUTURE_MESSAGE},
            {
                "field": "total_amount",
                "code": "total_amount_mismatch",
                "message": "銷售額＋稅額與總計不符，請確認",
            },
        ],
        "checked_on": "2026-10-30",
    }


def test_endpoint_accepts_incomplete_and_malformed_body(isolated: MagicMock) -> None:
    for body in (
        {},
        {"items": "x", "invoice_date": 5},
        valid_body(invoice_track="", seller_tax_id=None),
    ):
        response = client.post(PREVIEW, json=body, headers=AUTH)
        assert response.status_code == 200, response.text
        assert response.json()["warnings"] == []


def test_endpoint_requires_login(isolated: MagicMock) -> None:
    response = client.post(PREVIEW, json=valid_body())

    assert response.status_code == 401


def test_endpoint_rejects_non_object_body(isolated: MagicMock) -> None:
    assert client.post(PREVIEW, json=[1], headers=AUTH).status_code == 422


def test_endpoint_session_failure_is_not_swallowed(
    isolated: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.exceptions import UnauthorizedError

    def expired(db: Any, token: str) -> Any:
        raise UnauthorizedError("登入已過期")

    monkeypatch.setattr(auth_service, "resolve_session", expired)

    assert client.post(PREVIEW, json=valid_body(), headers=AUTH).status_code == 401


# ---- 正式送出：重新計算、保存、不阻擋 ----


def submit_with(services: dict[str, Any], monkeypatch: pytest.MonkeyPatch, **changes: Any) -> Any:
    monkeypatch.setattr(invoice_upload_service, "today_taipei", lambda now=None: TODAY)
    recognition_id = recognize().json()["recognition_id"]
    return client.post(
        "/api/v1/invoices", json=submit_payload(recognition_id, **changes), headers=AUTH
    )


def test_submit_with_future_date_warns_stores_and_does_not_block(
    services: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    response = submit_with(services, monkeypatch, invoice_date="2026-10-31")

    assert response.status_code == 201
    expected = [{"field": "invoice_date", "code": "invoice_date_future", "message": FUTURE_MESSAGE}]
    assert response.json()["warnings"] == expected
    (invoice,) = services["records"].invoices
    assert invoice["validation_results"] == {"warnings": expected}
    assert invoice["status"] == "pending_department_approval"


@pytest.mark.parametrize("invoice_date", ["2026-10-30", "2026-10-29", "2025-12-31"])
def test_submit_today_or_past_has_no_future_warning(
    services: dict[str, Any], monkeypatch: pytest.MonkeyPatch, invoice_date: str
) -> None:
    response = submit_with(services, monkeypatch, invoice_date=invoice_date)

    assert response.status_code == 201
    assert response.json()["warnings"] == []


def test_submit_total_mismatch_is_saved_and_still_accepted(
    services: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    response = submit_with(services, monkeypatch, total_amount="9999")

    assert response.status_code == 201
    assert [w["code"] for w in response.json()["warnings"]] == ["total_amount_mismatch"]
    (invoice,) = services["records"].invoices
    assert [w["code"] for w in invoice["validation_results"]["warnings"]] == [
        "total_amount_mismatch"
    ]


def test_submit_and_preview_return_identical_warnings(
    services: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    changes = {"invoice_date": "2027-02-01", "total_amount": "9999", "tax_amount": "400"}
    monkeypatch.setattr(invoice_warning_service, "today_taipei", lambda: TODAY)
    recognition_id = recognize().json()["recognition_id"]
    payload = submit_payload(recognition_id, **changes)

    preview = client.post(PREVIEW, json=payload, headers=AUTH)
    monkeypatch.setattr(invoice_upload_service, "today_taipei", lambda now=None: TODAY)
    submitted = client.post("/api/v1/invoices", json=payload, headers=AUTH)

    assert preview.status_code == 200 and submitted.status_code == 201
    assert preview.json()["warnings"] == submitted.json()["warnings"]
    assert len(preview.json()["warnings"]) == 3


def test_submit_still_rejects_bad_date_and_missing_date_with_422(
    services: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(invoice_upload_service, "today_taipei", lambda now=None: TODAY)
    recognition_id = recognize().json()["recognition_id"]

    for bad in ("2026-13-45", "", None, "not-a-date"):
        payload = submit_payload(recognition_id, invoice_date=bad)
        assert client.post("/api/v1/invoices", json=payload, headers=AUTH).status_code == 422, bad
    assert services["records"].invoices == []
