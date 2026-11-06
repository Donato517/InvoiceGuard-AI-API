"""
測試目標：首次提交第 1 輪快照的格式與錯誤轉換（不連資料庫，以替身驗證）。
涵蓋：寫入的 header／items 與重送補建的第 1 輪使用同一組欄位與標準值；表不存在、欄位不符、權限（含 RLS）
不足的 SQLSTATE 轉成 503 INVOICE_SNAPSHOT_UNAVAILABLE；其他資料庫錯誤原樣拋出（不吞掉、不改類型）。
真實 PostgreSQL 的行為見 tests/integration/test_first_submit_snapshot_isolated_db.py。
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.exceptions import ServiceUnavailableError
from app.db.repositories import resubmit_repository
from app.db.repositories.invoice_repository import InvoiceHeader, InvoiceItem
from app.services import invoice_resubmit_service as resubmit
from app.services import invoice_upload_service as upload


class _DriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("driver error")
        self.sqlstate = sqlstate


def _header() -> InvoiceHeader:
    return InvoiceHeader(
        invoice_track="ab",
        invoice_number="12345678",
        invoice_date=date(2026, 10, 15),
        tax_period="202610",
        seller_tax_id="12345675",
        seller_name="甲公司",
        buyer_tax_id=None,
        buyer_name=None,
        sales_amount=Decimal("1000.00"),
        tax_amount=Decimal("50"),
        total_amount=Decimal("1050"),
        total_amount_zh=None,
        tax_type="taxable",
    )


def _items() -> tuple[InvoiceItem, ...]:
    return (
        InvoiceItem(
            line_no=1,
            item_name="品項",
            quantity=Decimal("2"),
            unit_price=Decimal("500.0"),
            line_amount=Decimal("1000"),
        ),
    )


def _call(**overrides: Any) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_insert(db: object, invoice_id: object, **kwargs: Any) -> None:
        captured.update(kwargs, invoice_id=invoice_id)

    item_id = uuid4()
    original = resubmit_repository.insert_snapshot
    resubmit_repository.insert_snapshot = fake_insert  # type: ignore[assignment]
    try:
        upload._save_first_snapshot(
            object(),  # type: ignore[arg-type]
            uuid4(),
            _header(),
            _items(),
            {1: item_id},
            [],
            file_id=uuid4(),
            submitted_by=uuid4(),
            submitted_at=datetime(2026, 11, 6, tzinfo=UTC),
            **overrides,
        )
    finally:
        resubmit_repository.insert_snapshot = original
    captured["item_id"] = item_id
    return captured


def test_snapshot_uses_round_one_first_kind_and_the_same_format_as_the_resubmit_backfill() -> None:
    captured = _call()
    header, items = _header(), _items()
    values = resubmit._value_map(
        {name: getattr(header, name) for name in upload._HEADER_FIELDS},
        {i.line_no: {name: getattr(i, name) for name in upload._ITEM_FIELDS} for i in items},
    )
    item_rows = [{"item_id": captured["item_id"], "line_no": 1}]

    assert (captured["submission_round"], captured["kind"]) == (1, "first")
    assert captured["header"] == resubmit._header_snapshot(header.tax_period, values)
    assert captured["items"] == resubmit._items_snapshot(item_rows, values)
    assert captured["header"]["invoice_track"] == "AB"  # 標準值：大寫
    assert captured["header"]["sales_amount"] == "1000"  # 標準值：去尾端 0
    assert captured["validation_results"] == {"warnings": []}


@pytest.mark.parametrize("sqlstate", ["42P01", "42703", "42501"])
def test_structure_or_privilege_errors_become_an_explicit_503(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise DBAPIError("INSERT ...", {"secret": "x"}, _DriverError(sqlstate))

    monkeypatch.setattr(resubmit_repository, "insert_snapshot", boom)
    with pytest.raises(ServiceUnavailableError) as error:
        upload._save_first_snapshot(
            object(),  # type: ignore[arg-type]
            uuid4(),
            _header(),
            _items(),
            {1: uuid4()},
            [],
            file_id=uuid4(),
            submitted_by=uuid4(),
            submitted_at=datetime(2026, 11, 6, tzinfo=UTC),
        )
    assert error.value.status_code == 503
    assert error.value.code == "INVOICE_SNAPSHOT_UNAVAILABLE"
    assert "secret" not in error.value.message and error.value.__cause__ is None


def test_other_database_errors_are_not_swallowed_or_retyped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise DBAPIError("INSERT ...", {}, _DriverError("23505"))

    monkeypatch.setattr(resubmit_repository, "insert_snapshot", boom)
    with pytest.raises(DBAPIError):
        upload._save_first_snapshot(
            object(),  # type: ignore[arg-type]
            uuid4(),
            _header(),
            _items(),
            {1: uuid4()},
            [],
            file_id=uuid4(),
            submitted_by=uuid4(),
            submitted_at=datetime(2026, 11, 6, tzinfo=UTC),
        )
