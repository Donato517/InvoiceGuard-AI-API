"""模組名稱：tests.unit.test_module_contracts；功能說明：檔案與 CRUD 契約邊界及 JSON 相容性。"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.schemas.common import MAX_BIGINT, MAX_PAGE, Page, PageQuery, RecordId
from app.schemas.data import InvoiceCreate, InvoicePatch, InvoiceQuery, InvoiceUpdate
from app.schemas.files import (
    MAX_UPLOAD_BYTES,
    DeleteFileRequest,
    DownloadGrant,
    FileQuery,
    MoveFileRequest,
    UploadFileRequest,
)

REQUEST_ID = UUID("00000000-0000-4000-8000-000000000001")


def upload_values(**values: Any) -> dict[str, Any]:
    """建立不含任何公司資料的上傳描述。"""
    return {
        "filename": "發票.png",
        "content_type": "image/png",
        "size_bytes": 100,
        "idempotency_key": REQUEST_ID,
    } | values


def invoice_values(**values: Any) -> dict[str, Any]:
    """建立純合成的發票契約資料。"""
    return {
        "invoice_number": "AB12345678",
        "invoice_date": "2026-10-22",
        "invoice_term": "11510",
        "total_amount": "100.50",
    } | values


def test_upload_contract_json_round_trip() -> None:
    request = UploadFileRequest(**upload_values())
    assert UploadFileRequest.model_validate_json(request.model_dump_json()) == request


@pytest.mark.parametrize(
    "filename",
    [
        "../invoice.png",
        "folder/invoice.png",
        "C:\\invoice.png",
        "..",
        "invoice\x00.png",
        "invoice\n.png",
        " ",
        "inv‮gnp.exe",
        "a\u0085b.png",
        "a​b.png",
        "a b.png",
        "CON",
        "con.png",
        "LPT1.pdf",
        "invoice.png ",
        "invoice.png.",
        "發" * 84 + ".pdf",
    ],
)
def test_upload_rejects_path_and_control_characters(filename: str) -> None:
    with pytest.raises(ValidationError):
        UploadFileRequest(**upload_values(filename=filename))


@pytest.mark.parametrize(
    "filename", ["發票.png", "invoice 2026-10.pdf", "console.png", "發" * 83 + ".pdf"]
)
def test_upload_accepts_display_filenames_within_255_bytes(filename: str) -> None:
    assert UploadFileRequest(**upload_values(filename=filename)).filename == filename


@pytest.mark.parametrize("size", [0, -1, MAX_UPLOAD_BYTES + 1, True, "100"])
def test_upload_size_is_bounded_and_strict(size: Any) -> None:
    with pytest.raises(ValidationError):
        UploadFileRequest(**upload_values(size_bytes=size))


@pytest.mark.parametrize(
    "extra",
    [
        {"bucket": "other"},
        {"object_key": "other/file"},
        {"owner_user_id": 123},
        {"role": "admin"},
        {"SUPABASE_SECRET_KEY": "synthetic"},
    ],
)
def test_upload_rejects_client_supplied_authority(extra: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        UploadFileRequest(**upload_values(**extra))


@pytest.mark.parametrize(
    "destination",
    ["../other", "/root", "C:\\root", "a//b", "https://example.invalid", "a/%2e%2e/b"],
)
def test_move_only_accepts_logical_folder(destination: str) -> None:
    with pytest.raises(ValidationError):
        MoveFileRequest(
            destination_folder=destination, expected_version=1, idempotency_key=REQUEST_ID
        )


def test_move_requires_version_and_idempotency_key() -> None:
    request = MoveFileRequest(
        destination_folder="invoices/2026", expected_version=2, idempotency_key=REQUEST_ID
    )
    assert request.expected_version == 2
    with pytest.raises(ValidationError):
        MoveFileRequest(
            destination_folder="invoices/2026", expected_version=0, idempotency_key=REQUEST_ID
        )
    with pytest.raises(ValidationError):
        MoveFileRequest(destination_folder="invoices/2026", expected_version=1)


def test_download_url_is_https_and_hidden_from_repr() -> None:
    grant = DownloadGrant(
        url="https://storage.example.invalid/object?token=synthetic-user-grant",
        expires_at=datetime(2026, 10, 22, tzinfo=UTC),
    )
    assert "synthetic-user-grant" not in repr(grant)
    with pytest.raises(ValidationError):
        DownloadGrant(
            url="http://storage.example.invalid/object",
            expires_at=datetime(2026, 10, 22, tzinfo=UTC),
        )
    with pytest.raises(ValidationError):
        DownloadGrant(
            url="https://storage.example.invalid/object", expires_at="2026-10-22T00:00:00"
        )


def test_invoice_money_uses_decimal_and_json_round_trip() -> None:
    request = InvoiceCreate(**invoice_values())
    assert request.total_amount == Decimal("100.50")
    assert InvoiceCreate.model_validate_json(request.model_dump_json()) == request


@pytest.mark.parametrize("amount", [1.2, True, "-1", "1.001", "NaN", "10000000000.00"])
def test_invoice_money_rejects_float_and_invalid_precision(amount: Any) -> None:
    with pytest.raises(ValidationError):
        InvoiceCreate(**invoice_values(total_amount=amount))


@pytest.mark.parametrize(
    "extra",
    [
        {"user_id": 999},
        {"status": "passed"},
        {"risk_score": 0},
        {"ai_result": {}},
        {"table": "users"},
        {"sql": "DELETE FROM invoices"},
    ],
)
def test_invoice_create_rejects_mass_assignment(extra: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        InvoiceCreate(**invoice_values(**extra))


def test_patch_distinguishes_clear_from_not_provided() -> None:
    patch = InvoicePatch(seller_name=None)
    assert patch.model_fields_set == {"seller_name"}
    assert patch.model_dump(exclude_unset=True) == {"seller_name": None}
    with pytest.raises(ValidationError):
        InvoicePatch()
    with pytest.raises(ValidationError):
        InvoicePatch(total_amount=None)


def test_update_rejects_missing_version_and_role_changes() -> None:
    with pytest.raises(ValidationError):
        InvoiceUpdate(patch=InvoicePatch(seller_name="合成測試"))
    with pytest.raises(ValidationError):
        InvoicePatch(user_id=123)


def test_pagination_and_query_are_bounded() -> None:
    with pytest.raises(ValidationError):
        PageQuery(page_size=101)
    with pytest.raises(ValidationError):
        PageQuery(page=MAX_PAGE + 1)
    assert PageQuery(page=MAX_PAGE).page == MAX_PAGE
    with pytest.raises(ValidationError):
        InvoiceQuery(order_by="arbitrary sql")
    with pytest.raises(ValidationError):
        Page[int](items=(1, 2), total=2, page=1, page_size=1)
    assert Page[int](items=(), total=0, page=1, page_size=20).items == ()


@pytest.mark.parametrize("value", [True, 1.0, 0, MAX_BIGINT + 1])
def test_record_id_and_version_are_bounded_integers(value: Any) -> None:
    with pytest.raises(ValidationError):
        DeleteFileRequest(expected_version=value, idempotency_key=REQUEST_ID)
    with pytest.raises(ValidationError):
        FileQuery(invoice_id=value)
    with pytest.raises(ValidationError):
        PageQuery(page=value)


def test_bigint_upper_bound_is_accepted() -> None:
    request = DeleteFileRequest(expected_version=MAX_BIGINT, idempotency_key=REQUEST_ID)
    assert request.expected_version == MAX_BIGINT
    assert FileQuery(invoice_id=MAX_BIGINT).invoice_id == MAX_BIGINT


def test_contracts_work_as_http_query_and_path_parameters() -> None:
    app = FastAPI()

    @app.get("/invoices")
    def list_invoices(query: Annotated[InvoiceQuery, Query()]) -> dict[str, int]:
        return {"page": query.page, "page_size": query.page_size}

    @app.get("/invoices/{invoice_id}")
    def get_invoice(invoice_id: RecordId) -> dict[str, int]:
        return {"id": invoice_id}

    client = TestClient(app)
    assert client.get("/invoices?page=2&page_size=10").json() == {"page": 2, "page_size": 10}
    assert client.get("/invoices/5").json() == {"id": 5}
    for path in (
        "/invoices?page=1.5",
        "/invoices?page=true",
        f"/invoices?page={MAX_PAGE + 1}",
        "/invoices/0",
        f"/invoices/{MAX_BIGINT + 1}",
    ):
        assert client.get(path).status_code == 422


def test_duplicate_invoice_line_numbers_are_rejected() -> None:
    item = {
        "line_no": 1,
        "description": "合成品項",
        "quantity": "1",
        "unit_price": "10",
        "amount": "10",
    }
    with pytest.raises(ValidationError):
        InvoiceCreate(**invoice_values(items=[item, item]))
