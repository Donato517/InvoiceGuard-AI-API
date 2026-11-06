"""
模組名稱：tests.unit.test_invoice_upload
功能說明：測試手機上傳發票流程 API（POST /invoices/recognize、/invoices/check-duplicate、/invoices）
    與發票欄位換算工具。
注意事項：以 repository、Storage、Document AI、Groq 替身執行，不連正式 DB、Storage 或模型服務。
"""

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import deps
from app.core.exceptions import UnauthorizedError
from app.db.repositories import invoice_repository, recognition_repository
from app.db.repositories.recognition_repository import RecognitionForSubmit
from app.integrations import document_ai, gemini, groq
from app.integrations.chat_models import ChatReply
from app.integrations.document_ai import DocumentAIError
from app.integrations.gemini import GeminiError
from app.integrations.supabase_storage import StorageError
from app.main import app
from app.schemas.auth import DepartmentRead, SessionRead
from app.services import auth_service, invoice_upload_service
from app.utils import invoice_format

client = TestClient(app)

USER_ID = UUID("11111111-1111-4111-8111-111111111111")
DEPARTMENT_ID = UUID("22222222-2222-4222-8222-222222222222")
CREATED_AT = datetime(2026, 10, 29, 1, 2, 3, tzinfo=UTC)
JPEG = b"\xff\xd8\xff\xe0" + b"synthetic-jpeg"
PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-png"
PDF = b"%PDF-1.7\n" + b"synthetic-pdf"
AUTH = {"Authorization": "Bearer synthetic-session-token"}
OCR_TEXT = "統一發票（三聯式）\nCD75670992\n中華民國115年8月15日\n"
MODEL_JSON = {
    "is_triplicate": True,
    "invoice_number": "CD-75670992",
    "invoice_date": "115年8月15日",
    "tax_period": "一一五年七、八月份",
    "buyer_name": "範例科技股份有限公司",
    "buyer_tax_id": "04595257",
    "seller_name": "範例文具行",
    "seller_tax_id": "27601907",
    "items": [
        {"item_name": "辦公用品", "quantity": "2", "unit_price": "3,000", "line_amount": "6,000"}
    ],
    "sales_amount": "6,000",
    "tax_type": "taxable",
    "tax_amount": "300",
    "total_amount": "6,300元",
    "total_amount_zh": "陸仟參佰元整",
}


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
        expires_at=CREATED_AT + timedelta(hours=1),
    )


def reply(payload: Any, model: str = "gemini-3.8-flash") -> ChatReply:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return ChatReply(
        text=text,
        model=model,
        finish_reason="STOP",
        prompt_tokens=100,
        output_tokens=50,
        total_tokens=150,
        raw_response={},
    )


@dataclass
class FakeStorage:
    """Storage 替身：記錄上傳與刪除。"""

    objects: dict[str, bytes] = field(default_factory=dict)
    puts: list[tuple[str, str]] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    put_error: StorageError | None = None
    delete_error: StorageError | None = None

    def put(self, key: str, data: bytes, *, content_type: str) -> None:
        if self.put_error:
            raise self.put_error
        self.objects[key] = data
        self.puts.append((key, content_type))

    def delete(self, key: str) -> None:
        if self.delete_error:
            raise self.delete_error
        self.deletes.append(key)
        self.objects.pop(key, None)


@dataclass
class FakeGemini:
    """Gemini 替身：依序回傳 replies（ChatReply 或例外）。"""

    replies: list[ChatReply | Exception] = field(default_factory=lambda: [reply(MODEL_JSON)])
    call_details: list[dict[str, Any]] = field(default_factory=list)
    page_count: int = 1
    closed: int = 0
    close_error: Exception | None = None
    error: Exception | None = None
    confidence: float = 1.0

    @property
    def calls(self) -> list[Any]:
        return [c["mime_type"] for c in self.call_details]

    @property
    def timeouts(self) -> list[float | None]:
        return [c["timeout_seconds"] for c in self.call_details]

    def close(self) -> None:
        self.closed += 1
        if self.close_error:
            raise self.close_error

    def extract_invoice(
        self,
        content: bytes,
        mime_type: str,
        *,
        system_instruction: str | None = None,
        prompt: str,
        timeout_seconds: float | None = None,
        few_shot_examples: Any = None,
    ) -> ChatReply:
        self.call_details.append(
            {
                "content": content,
                "mime_type": mime_type,
                "system_instruction": system_instruction,
                "prompt": prompt,
                "timeout_seconds": timeout_seconds,
                "few_shot_examples": few_shot_examples,
            }
        )
        if self.error:
            raise self.error
        result = self.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@dataclass
class FakeRecords:
    """辨識紀錄與發票 repository 替身。"""

    logs: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    duplicate: bool = False
    invoices: list[dict[str, Any]] = field(default_factory=list)
    items: list[Any] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    differences: list[Any] = field(default_factory=list)
    changes: list[Any] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    links: list[tuple[UUID, UUID, UUID]] = field(default_factory=list)
    locks: list[dict[str, str]] = field(default_factory=list)
    expired: list[tuple[UUID, str]] = field(default_factory=list)
    deleted_marks: list[UUID] = field(default_factory=list)


@pytest.fixture
def fake_db() -> Iterator[MagicMock]:
    db = MagicMock()

    def override() -> Iterator[MagicMock]:
        yield db

    app.dependency_overrides[deps.get_optional_db] = override
    yield db
    app.dependency_overrides.clear()


@pytest.fixture
def services(monkeypatch: pytest.MonkeyPatch, fake_db: MagicMock) -> dict[str, Any]:
    storage, gemini_mock, records = FakeStorage(), FakeGemini(), FakeRecords()
    monkeypatch.setattr(auth_service, "resolve_session", lambda db, token: session_read())
    monkeypatch.setattr(
        invoice_upload_service.S3StorageClient, "from_settings", lambda *a, **k: storage
    )
    monkeypatch.setattr(invoice_upload_service.GeminiClient, "from_settings", lambda: gemini_mock)

    def insert(db: Any, **values: Any) -> datetime:
        records.logs[values["recognition_id"]] = {**values, "result_status": "pending"}
        return CREATED_AT

    def complete(db: Any, recognition_id: UUID, **values: Any) -> None:
        records.logs[recognition_id].update(values)

    def lock_for_submit(db: Any, recognition_id: UUID, user_id: UUID) -> Any:
        log = records.logs.get(recognition_id)
        if log is None or log["requested_by"] != user_id:
            return None
        return RecognitionForSubmit(
            recognition_id=recognition_id,
            source_storage_path=log["source_storage_path"],
            extracted_fields=log.get("extracted_fields"),
            raw_response=log.get("raw_response"),
            result_status=log["result_status"],
            invoice_id=log.get("invoice_id"),
            source_deleted_at=log.get("source_deleted_at"),
            expired=log.get("expired", False),
        )

    def link_invoice(db: Any, recognition_id: UUID, invoice_id: UUID, file_id: UUID) -> None:
        records.links.append((recognition_id, invoice_id, file_id))
        records.logs[recognition_id]["invoice_id"] = invoice_id

    def lock_expired_sources(db: Any, limit: int, *, file_prefix: str) -> list[tuple[UUID, str]]:
        assert file_prefix == "INVOICES_"
        return records.expired[:limit]

    monkeypatch.setattr(recognition_repository, "insert", insert)
    monkeypatch.setattr(recognition_repository, "complete", complete)
    monkeypatch.setattr(recognition_repository, "lock_for_submit", lock_for_submit)
    monkeypatch.setattr(recognition_repository, "link_invoice", link_invoice)
    monkeypatch.setattr(recognition_repository, "lock_expired_sources", lock_expired_sources)
    monkeypatch.setattr(
        recognition_repository,
        "mark_source_deleted",
        lambda db, recognition_id: records.deleted_marks.append(recognition_id),
    )

    def insert_invoice(db: Any, header: Any, **values: Any) -> tuple[UUID, datetime]:
        records.invoices.append({"header": header, **values})
        return uuid4(), CREATED_AT

    def insert_items(db: Any, invoice_id: UUID, items: Any) -> dict[int, UUID]:
        records.items.extend(items)
        return {item.line_no: uuid4() for item in items}

    def insert_file(db: Any, invoice_id: UUID, **values: Any) -> UUID:
        records.files.append(values)
        return uuid4()

    monkeypatch.setattr(
        invoice_repository,
        "lock_invoice_key",
        lambda db, **identity: records.locks.append(identity),
    )
    monkeypatch.setattr(
        invoice_repository, "exists_duplicate", lambda db, **identity: records.duplicate
    )
    monkeypatch.setattr(invoice_repository, "insert_invoice", insert_invoice)
    monkeypatch.setattr(invoice_repository, "insert_items", insert_items)
    monkeypatch.setattr(invoice_repository, "insert_file", insert_file)
    monkeypatch.setattr(
        invoice_repository,
        "insert_field_reviews",
        lambda db, invoice_id, differences, **values: records.differences.extend(differences),
    )
    monkeypatch.setattr(
        invoice_repository,
        "insert_changes",
        lambda db, invoice_id, changes, **values: records.changes.extend(changes),
    )
    monkeypatch.setattr(
        invoice_repository,
        "insert_status_history",
        lambda db, invoice_id, **values: records.history.append(values),
    )
    return {
        "storage": storage,
        "ocr": gemini_mock,
        "model": gemini_mock,
        "gemini": gemini_mock,
        "records": records,
        "db": fake_db,
    }


def recognize(
    content: bytes = JPEG, content_type: str = "image/jpeg", filename: str = "相機拍攝.jpg"
) -> Any:
    files = {"file": (filename, content, content_type)}
    return client.post("/api/v1/invoices/recognize", files=files, headers=AUTH)


def submit_payload(recognition_id: str, **changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "recognition_id": recognition_id,
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
    return payload | changes


def change(field_name: str, old: Any, new: Any, line_no: int | None = None) -> dict[str, Any]:
    scope = "header" if line_no is None else "item"
    return {
        "field_scope": scope,
        "line_no": line_no,
        "field_name": field_name,
        "old_value": old,
        "new_value": new,
    }


def summary(rows: list[Any], *names: str) -> list[tuple[Any, ...]]:
    return [tuple(getattr(row, name) for name in names) for row in rows]


# ==================== 辨識 ====================


def test_recognize_stores_image_and_returns_normalized_fields(services: dict[str, Any]) -> None:
    response = recognize()

    assert response.status_code == 200
    body = response.json()
    recognition_id = UUID(body["recognition_id"])
    assert body["result_status"] == "success"
    assert body["is_triplicate"] is True
    assert body["warnings"] == []
    invoice = body["invoice"]
    assert invoice["invoice_track"] == "CD"
    assert invoice["invoice_number"] == "75670992"
    assert invoice["invoice_date"] == "2026-08-15"
    assert invoice["tax_period"] == "202608"
    assert invoice["tax_type"] == "taxable"
    assert (invoice["sales_amount"], invoice["tax_amount"], invoice["total_amount"]) == (
        "6000",
        "300",
        "6300",
    )
    assert invoice["items"] == [
        {
            "line_no": 1,
            "item_name": "辦公用品",
            "quantity": "2",
            "unit_price": "3000",
            "line_amount": "6000",
        }
    ]
    assert body["printed"] == {"invoice_date": "115年8月15日", "tax_period": "一一五年七、八月份"}
    assert body["recognition"] == {
        "ocr_provider": "google_gemini",
        "ocr_confidence": 1.0,
        "ai_provider": "google_gemini",
        "model": "gemini-3.8-flash",
        "fallback_used": False,
    }
    assert body["expires_at"] == "2026-10-29T02:02:03Z"

    key, content_type = services["storage"].puts[0]
    assert content_type == "image/jpeg"
    assert re.fullmatch(rf"{USER_ID}/INVOICES_\d{{14}}_{recognition_id}\.jpg", key)
    log = services["records"].logs[recognition_id]
    assert log["source_storage_path"] == key
    assert log["ai_provider"] == "google_gemini"
    assert log["requested_by"] == USER_ID
    assert log["result_status"] == "success"
    assert log["model_name"] == "gemini-3.8-flash"
    assert log["confidence_score"] == 1.0
    assert log["extracted_fields"]["invoice"] == invoice
    assert log["raw_response"]["source"] == {
        "filename": "相機拍攝.jpg",
        "mime_type": "image/jpeg",
        "size_bytes": len(JPEG),
    }
    assert log["raw_response"]["gemini"]["model"] == "gemini-3.8-flash"
    assert len(services["gemini"].call_details) == 1
    call = services["gemini"].call_details[0]
    assert call["mime_type"] == "image/jpeg"
    assert call["content"] == JPEG
    assert call["few_shot_examples"] is not None
    assert len(call["few_shot_examples"]) == 2


def test_recognize_accepts_png(services: dict[str, Any]) -> None:
    response = recognize(PNG, "image/png")

    assert response.status_code == 200
    assert services["storage"].puts[0][0].endswith(".png")
    assert services["ocr"].calls == ["image/png"]


@pytest.mark.parametrize(
    ("content", "content_type", "code"),
    [
        (b"not-an-image", "image/jpeg", "INVOICE_IMAGE_INVALID"),
        (PNG, "image/jpeg", "INVOICE_IMAGE_INVALID"),
        (PDF, "image/png", "INVOICE_IMAGE_INVALID"),
        (b"GIF89a-synthetic", "image/gif", "INVOICE_IMAGE_INVALID"),
        (JPEG + b"0" * (4 * 1024 * 1024), "image/jpeg", "INVOICE_IMAGE_TOO_LARGE"),
        (PDF + b"0" * (4 * 1024 * 1024), "application/pdf", "INVOICE_IMAGE_TOO_LARGE"),
    ],
    ids=["not-image", "type-mismatch", "pdf-declared-png", "gif", "too-large", "pdf-too-large"],
)
def test_recognize_rejects_invalid_image_before_any_write(
    services: dict[str, Any], content: bytes, content_type: str, code: str
) -> None:
    response = recognize(content, content_type)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == code
    assert services["storage"].puts == []
    assert services["records"].logs == {}


def test_recognize_accepts_single_page_pdf(services: dict[str, Any]) -> None:
    response = recognize(PDF, "application/pdf", "掃描發票.pdf")

    assert response.status_code == 200
    key, content_type = services["storage"].puts[0]
    assert key.endswith(".pdf")
    assert invoice_format.is_invoice_storage_key(key)
    assert content_type == "application/pdf"
    assert services["ocr"].calls == ["application/pdf"]
    log = services["records"].logs[UUID(response.json()["recognition_id"])]
    assert log["raw_response"]["source"]["mime_type"] == "application/pdf"
    assert log["raw_response"]["source"]["filename"] == "掃描發票.pdf"


@pytest.mark.parametrize("text", [OCR_TEXT, "", "  \n "], ids=["with-text", "empty", "blank"])
def test_recognize_rejects_multi_page_pdf(services: dict[str, Any], text: str) -> None:
    services["ocr"].page_count = 2
    services["ocr"].text = text

    response = recognize(PDF, "application/pdf", "兩頁.pdf")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVOICE_PDF_MULTIPAGE"
    (log,) = services["records"].logs.values()
    assert (log["result_status"], log["error_message"]) == ("failed", "invoice_pdf_multipage")
    assert services["model"].calls == []


def test_multi_page_image_result_is_not_rejected(services: dict[str, Any]) -> None:
    services["ocr"].page_count = 2

    assert recognize().status_code == 200


def test_submit_pdf_records_pdf_file(services: dict[str, Any]) -> None:
    recognition_id = recognize(PDF, "application/pdf", "掃描發票.pdf").json()["recognition_id"]

    response = client.post("/api/v1/invoices", json=submit_payload(recognition_id), headers=AUTH)

    assert response.status_code == 201
    (file_values,) = services["records"].files
    assert file_values["mime_type"] == "application/pdf"
    assert file_values["storage_path"].endswith(".pdf")
    assert file_values["original_filename"] == "掃描發票.pdf"
    assert file_values["size_bytes"] == len(PDF)


def test_recognize_requires_bearer_token(services: dict[str, Any]) -> None:
    response = client.post("/api/v1/invoices/recognize", files={"file": ("a.jpg", JPEG)})

    assert response.status_code == 401
    assert services["storage"].puts == []


def test_recognize_rejects_invalid_session(
    services: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(db: Any, token: str) -> SessionRead:
        raise UnauthorizedError("登入已失效，請重新登入")

    monkeypatch.setattr(auth_service, "resolve_session", reject)

    assert recognize().status_code == 401
    assert services["records"].logs == {}


def test_recognize_handles_json_within_markdown_code_fence(services: dict[str, Any]) -> None:
    fenced = f"```json\n{json.dumps(MODEL_JSON)}\n```"
    services["gemini"].replies = [reply(fenced)]

    body = recognize().json()

    assert body["result_status"] == "success"
    assert body["invoice"]["invoice_number"] == "75670992"


def test_recognize_does_not_retry_when_key_is_rejected(services: dict[str, Any]) -> None:
    services["gemini"].replies = [GeminiError("gemini_auth_failed", "API_KEY_INVALID")]

    response = recognize()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AI_RECOGNITION_FAILED"
    assert len(services["gemini"].calls) == 1
    (log,) = services["records"].logs.values()
    assert log["result_status"] == "failed"
    assert log["error_message"] == "gemini_auth_failed:API_KEY_INVALID"


def test_recognize_records_gemini_failure(services: dict[str, Any]) -> None:
    services["gemini"].error = GeminiError("gemini_timeout")

    response = recognize()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AI_RECOGNITION_FAILED"
    (log,) = services["records"].logs.values()
    assert (log["result_status"], log["error_message"]) == ("failed", "gemini_timeout")


def test_recognize_records_storage_failure(services: dict[str, Any]) -> None:
    services["storage"].put_error = StorageError("storage_denied", "AccessDenied")

    response = recognize()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "STORAGE_FAILED"
    (log,) = services["records"].logs.values()
    assert log["error_message"] == "storage_denied:AccessDenied"
    assert services["gemini"].calls == []


def test_recognize_rejects_image_without_text(services: dict[str, Any]) -> None:
    services["gemini"].replies = [reply({"error": "no_text"})]

    response = recognize()

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVOICE_TEXT_NOT_FOUND"
    (log,) = services["records"].logs.values()
    assert log["error_message"] == "invoice_text_not_found"


def test_recognize_stops_before_writing_when_gemini_is_not_configured(
    services: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def not_configured() -> Any:
        raise GeminiError("gemini_not_configured")

    monkeypatch.setattr(invoice_upload_service.GeminiClient, "from_settings", not_configured)

    response = recognize()

    assert response.status_code == 503
    assert services["storage"].puts == []
    assert services["records"].logs == {}


def test_recognize_warns_about_inconsistent_values(services: dict[str, Any]) -> None:
    services["model"].replies = [
        reply(
            MODEL_JSON
            | {
                "is_triplicate": False,
                "invoice_number": "C7567099",
                "tax_period": "一一五年九、十月份",
                "seller_tax_id": "12345678",
                "buyer_tax_id": None,
                "tax_type": None,
                "tax_amount": "350",
                "total_amount": "6300",
                "items": [{"item_name": "辦公用品", "line_amount": "5000"}],
            }
        )
    ]

    body = recognize().json()

    assert body["result_status"] == "partial"
    assert body["invoice"]["tax_type"] == "taxable"
    assert body["invoice"]["invoice_track"] is None
    assert [(warning["field"], warning["code"]) for warning in body["warnings"]] == [
        ("is_triplicate", "not_triplicate"),
        ("invoice_number", "invoice_number_invalid"),
        ("tax_period", "tax_period_mismatch"),
        ("buyer_tax_id", "tax_id_invalid"),
        ("tax_type", "tax_type_inferred"),
        ("seller_tax_id", "tax_id_checksum"),
        ("tax_amount", "tax_amount_mismatch"),
        ("total_amount", "total_amount_mismatch"),
        ("items", "items_total_mismatch"),
    ]


def test_recognize_infers_a_missing_year_from_the_printed_period(
    services: dict[str, Any],
) -> None:
    # 實測票面：年份與月日相隔很遠，模型只抄到「10月3」
    services["model"].replies = [
        reply(MODEL_JSON | {"invoice_date": "10月3", "tax_period": "一一四年九、十月份"})
    ]

    body = recognize().json()

    assert body["invoice"]["invoice_date"] == "2025-10-03"
    assert body["invoice"]["tax_period"] == "202510"
    assert body["printed"]["invoice_date"] == "10月3"
    inferred = [w for w in body["warnings"] if w["code"] == "invoice_date_year_inferred"]
    assert len(inferred) == 1 and "2025-10-03" in inferred[0]["message"]
    assert all(w["code"] != "invoice_date_invalid" for w in body["warnings"])


def test_recognize_does_not_guess_when_the_month_is_outside_the_period(
    services: dict[str, Any],
) -> None:
    services["model"].replies = [
        reply(MODEL_JSON | {"invoice_date": "8月3", "tax_period": "一一四年九、十月份"})
    ]

    body = recognize().json()

    assert body["invoice"]["invoice_date"] is None
    assert any(w["code"] == "invoice_date_invalid" for w in body["warnings"])


def test_recognize_warns_when_chinese_amount_differs_from_total(services: dict[str, Any]) -> None:
    # 讀成 114,858，與總計 6,300 不符
    services["model"].replies = [
        reply(MODEL_JSON | {"total_amount_zh": "壹拾壹萬肆仟捌佰伍拾捌元"})
    ]

    warnings = recognize().json()["warnings"]

    zh = [w for w in warnings if w["code"] == "total_amount_zh_mismatch"]
    assert len(zh) == 1 and zh[0]["field"] == "total_amount_zh" and "114,858" in zh[0]["message"]


def test_recognize_flags_a_real_chinese_amount_misread(services: dict[str, Any]) -> None:
    # 正式實測樣本 0068：總計 53,223，模型漏抄末位「參」，國字大寫只讀到 53,220
    services["model"].replies = [
        reply(
            MODEL_JSON
            | {
                "sales_amount": "50689",
                "tax_amount": "2534",
                "total_amount": "53223",
                "total_amount_zh": "伍萬參仟貳佰贰拾元",
            }
        )
    ]

    warnings = recognize().json()["warnings"]

    zh = [w for w in warnings if w["code"] == "total_amount_zh_mismatch"]
    assert len(zh) == 1 and "53,220" in zh[0]["message"]


def test_recognize_accepts_chinese_amount_with_struck_through_places(
    services: dict[str, Any],
) -> None:
    services["model"].replies = [
        reply(
            MODEL_JSON
            | {
                "total_amount": "14858",
                "sales_amount": "14150",
                "tax_amount": "708",
                "total_amount_zh": "總計新臺幣(中文大寫)億仟佰拾壹萬肆仟捌佰伍拾捌元",
            }
        )
    ]

    warnings = recognize().json()["warnings"]

    assert not [w for w in warnings if w["code"].startswith("total_amount_zh")]


def test_recognize_flags_unreadable_chinese_amount(services: dict[str, Any]) -> None:
    services["model"].replies = [reply(MODEL_JSON | {"total_amount_zh": "約六千三"})]

    warnings = recognize().json()["warnings"]

    assert any(w["code"] == "total_amount_zh_unreadable" for w in warnings)


def test_recognize_warns_about_a_line_whose_amount_differs_from_quantity_times_price(
    services: dict[str, Any],
) -> None:
    # 抽樣 0057：四行中有一行 數量×單價 ≠ 金額（模型讀錯其中一個數字）
    services["model"].replies = [
        reply(
            MODEL_JSON
            | {
                "items": [
                    {
                        "item_name": "杯",
                        "quantity": "28",
                        "unit_price": "135",
                        "line_amount": "3780",
                    },
                    {
                        "item_name": "貼紙",
                        "quantity": "67",
                        "unit_price": "141",
                        "line_amount": "9547",
                    },
                ],
                "sales_amount": "13327",
                "tax_amount": "666",
                "total_amount": "13993",
                "total_amount_zh": None,
            }
        )
    ]

    warnings = recognize().json()["warnings"]

    lines = [w for w in warnings if w["code"] == "item_line_amount_mismatch"]
    assert [w["field"] for w in lines] == ["items.1.line_amount"]
    assert "9,447" not in lines[0]["message"] and "9447" in lines[0]["message"]


def test_recognize_cleans_up_expired_unsubmitted_images(services: dict[str, Any]) -> None:
    storage, records = services["storage"], services["records"]
    expired_key = f"{uuid4()}/INVOICES_20261028235959_{uuid4()}.jpg"
    records.expired = [(uuid4(), expired_key), (uuid4(), "rag/other-domain/file.pdf")]

    assert recognize().status_code == 200

    assert storage.deletes == [expired_key]
    assert records.deleted_marks == [records.expired[0][0]]


def test_cleanup_keeps_record_when_storage_delete_fails(services: dict[str, Any]) -> None:
    storage, records = services["storage"], services["records"]
    records.expired = [(uuid4(), f"{uuid4()}/INVOICES_20261028235959_{uuid4()}.jpg")]
    storage.delete_error = StorageError("storage_unreachable")

    assert invoice_upload_service.cleanup_expired_sources(services["db"], storage) == 0
    assert records.deleted_marks == []


# ==================== 查重 ====================


@pytest.mark.parametrize("duplicate", [True, False])
def test_check_duplicate(services: dict[str, Any], duplicate: bool) -> None:
    services["records"].duplicate = duplicate
    payload = {"invoice_track": "CD", "invoice_number": "75670992", "seller_tax_id": "27601907"}

    response = client.post("/api/v1/invoices/check-duplicate", json=payload, headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"is_duplicate": duplicate}


def test_check_duplicate_validates_format(services: dict[str, Any]) -> None:
    payload = {"invoice_track": "cd", "invoice_number": "7567", "seller_tax_id": "2760"}

    response = client.post("/api/v1/invoices/check-duplicate", json=payload, headers=AUTH)

    assert response.status_code == 422


# ==================== 送出 ====================


def test_submit_creates_invoice_linked_to_recognized_image(services: dict[str, Any]) -> None:
    recognition_id = recognize().json()["recognition_id"]
    records = services["records"]

    response = client.post(
        "/api/v1/invoices",
        json=submit_payload(recognition_id, seller_name="範例文具有限公司"),
        headers=AUTH,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending_accounting_review"
    assert body["tax_period"] == "202608"
    assert body["warnings"] == []
    (invoice,) = records.invoices
    header = invoice["header"]
    assert (header.invoice_track, header.invoice_number) == ("CD", "75670992")
    assert header.invoice_date == date(2026, 8, 15)
    assert header.tax_period == "202608"
    assert header.tax_type == "taxable"
    assert header.sales_amount == Decimal("6000")
    assert invoice["status"] == "pending_accounting_review"
    assert invoice["submission_round"] == 1
    assert invoice["submitted_by"] == USER_ID
    assert invoice["department_id"] == DEPARTMENT_ID
    assert invoice["validation_results"] == {"warnings": []}
    (file_values,) = records.files
    log = records.logs[UUID(recognition_id)]
    assert file_values == {
        "bucket_name": "invoices",
        "storage_path": log["source_storage_path"],
        "original_filename": "相機拍攝.jpg",
        "mime_type": "image/jpeg",
        "size_bytes": len(JPEG),
        "uploaded_by": USER_ID,
    }
    assert [
        (d.field_scope, d.field_name, d.ai_original_value, d.submitted_value)
        for d in records.differences
    ] == [("header", "seller_name", "範例文具行", "範例文具有限公司")]
    assert summary(records.changes, "field_scope", "field_name", "old_value", "new_value") == [
        ("header", "seller_name", "範例文具行", "範例文具有限公司")
    ]
    assert body["modified_fields"] == [
        {
            "field_scope": "header",
            "line_no": None,
            "field_name": "seller_name",
            "ai_original_value": "範例文具行",
            "submitted_value": "範例文具有限公司",
        }
    ]
    assert records.history == [
        {
            "old_status": None,
            "new_status": "pending_accounting_review",
            "reason": "手機拍照上傳送出",
            "changed_by": USER_ID,
        }
    ]
    assert records.links[0][0] == UUID(recognition_id)
    assert records.locks == [
        {"invoice_track": "CD", "invoice_number": "75670992", "seller_tax_id": "27601907"}
    ]


def test_submit_marks_item_changes_by_source_line(services: dict[str, Any]) -> None:
    recognition_id = recognize().json()["recognition_id"]
    payload = submit_payload(
        recognition_id,
        tax_amount="250",
        items=[
            {"source_line_no": None, "item_name": "運費", "line_amount": "100"},
            {
                "source_line_no": 1,
                "item_name": "辦公用品",
                "quantity": "2.50",
                "unit_price": "3000.0",
                "line_amount": "6000.00",
            },
        ],
    )

    body = client.post("/api/v1/invoices", json=payload, headers=AUTH).json()

    assert [(w["field"], w["code"]) for w in body["warnings"]] == [
        ("tax_amount", "tax_amount_mismatch"),
        ("total_amount", "total_amount_mismatch"),
        ("items.1.line_amount", "item_line_amount_mismatch"),  # 2.5 × 3000 ≠ 6000
        ("items", "items_total_mismatch"),
    ]
    # AI 明細 1 移到第 2 列：只比對它自己的值（數量 2→2.5）；第 1 列為新增明細
    assert summary(
        services["records"].differences, "field_scope", "line_no", "field_name", "ai_original_value"
    ) == [
        ("header", None, "tax_amount", "300"),
        ("item", 1, "item_name", None),
        ("item", 1, "line_amount", None),
        ("item", 2, "quantity", "2"),
    ]
    assert services["records"].invoices[0]["validation_results"]["warnings"][0]["code"] == (
        "tax_amount_mismatch"
    )


def test_submit_marks_deleted_ai_item(services: dict[str, Any]) -> None:
    recognition_id = recognize().json()["recognition_id"]
    payload = submit_payload(
        recognition_id,
        items=[{"source_line_no": None, "item_name": "辦公用品", "line_amount": "6000"}],
    )

    body = client.post("/api/v1/invoices", json=payload, headers=AUTH).json()

    deleted = {
        "item_name": "辦公用品",
        "quantity": "2",
        "unit_price": "3000",
        "line_amount": "6000",
    }
    assert summary(services["records"].differences, "field_scope", "line_no", "field_name") == [
        ("item", 1, "item_name"),
        ("item", 1, "line_amount"),
        ("header", None, "deleted_item_1"),
    ]
    assert body["modified_fields"][-1]["ai_original_value"] == deleted
    assert body["modified_fields"][-1]["submitted_value"] is None
    assert summary(services["records"].changes, "field_name", "old_value", "new_value")[-1] == (
        "deleted_item_1",
        deleted,
        None,
    )


def test_submit_stores_interim_changes_in_order(services: dict[str, Any]) -> None:
    recognition_id = recognize().json()["recognition_id"]
    payload = submit_payload(
        recognition_id,
        tax_amount="250",
        changes=[
            change("seller_name", "範例文具行", "範例文具"),
            change("tax_amount", "300", "2,80"),
            change("seller_name", "範例文具", "範例文具行"),
            change("quantity", "2", "3", line_no=1),
            change("tax_amount", "280", "250.00"),
            change("quantity", "3", "2", line_no=1),
        ],
    )

    response = client.post("/api/v1/invoices", json=payload, headers=AUTH)

    assert response.status_code == 201
    records = services["records"]
    # 改了又改回（A→B→A）不標記為修改欄位，但修改紀錄保留每一次
    assert summary(records.differences, "field_name", "ai_original_value", "submitted_value") == [
        ("tax_amount", "300", "250")
    ]
    assert summary(
        records.changes, "field_scope", "line_no", "field_name", "old_value", "new_value"
    ) == [
        ("header", None, "seller_name", "範例文具行", "範例文具"),
        ("header", None, "tax_amount", "300", "280"),
        ("header", None, "seller_name", "範例文具", "範例文具行"),
        ("item", 1, "quantity", "2", "3"),
        ("header", None, "tax_amount", "280", "250"),
        ("item", 1, "quantity", "3", "2"),
    ]


@pytest.mark.parametrize(
    "changes",
    [
        [change("seller_name", "其他商行", "範例文具有限公司")],
        [change("seller_name", "範例文具行", "範例文具")],
        [change("seller_name", "範例文具行", "範例文具行")],
        [change("unknown_field", None, "x")],
        [change("quantity", "2", "3", line_no=2)],
        [change("item_name", None, "x", line_no=None) | {"field_scope": "item"}],
        [change("invoice_number", "75670992", "75670993")],
    ],
    ids=[
        "not-from-ai-value",
        "not-ending-at-submitted",
        "no-op",
        "unknown-field",
        "line-out-of-range",
        "item-without-line",
        "number-not-submitted",
    ],
)
def test_submit_rejects_inconsistent_changes(
    services: dict[str, Any], changes: list[dict[str, Any]]
) -> None:
    recognition_id = recognize().json()["recognition_id"]
    payload = submit_payload(recognition_id, seller_name="範例文具有限公司", changes=changes)

    response = client.post("/api/v1/invoices", json=payload, headers=AUTH)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVOICE_CHANGES_INVALID"
    assert services["records"].invoices == []


@pytest.mark.parametrize("sources", [[1, 1], [2]], ids=["duplicate", "not-recognized"])
def test_submit_rejects_invalid_item_sources(services: dict[str, Any], sources: list[int]) -> None:
    recognition_id = recognize().json()["recognition_id"]
    items = [
        {"source_line_no": source, "item_name": "辦公用品", "line_amount": "3000"}
        for source in sources
    ]

    response = client.post(
        "/api/v1/invoices", json=submit_payload(recognition_id, items=items), headers=AUTH
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVOICE_ITEMS_INVALID"
    assert services["records"].invoices == []


@pytest.mark.parametrize("value", [None, "", "   "])
def test_submit_accepts_blank_optional_fields(services: dict[str, Any], value: Any) -> None:
    recognition_id = recognize().json()["recognition_id"]
    optional = dict.fromkeys(
        ("seller_name", "buyer_name", "buyer_tax_id", "total_amount_zh"), value
    )

    response = client.post(
        "/api/v1/invoices", json=submit_payload(recognition_id, **optional), headers=AUTH
    )

    assert response.status_code == 201
    header = services["records"].invoices[0]["header"]
    assert (header.seller_name, header.buyer_name, header.buyer_tax_id, header.total_amount_zh) == (
        None,
        None,
        None,
        None,
    )


def test_submit_rejects_duplicate_invoice(services: dict[str, Any]) -> None:
    recognition_id = recognize().json()["recognition_id"]
    services["records"].duplicate = True

    response = client.post("/api/v1/invoices", json=submit_payload(recognition_id), headers=AUTH)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVOICE_DUPLICATED"
    assert services["records"].invoices == []
    services["db"].rollback.assert_called()


@pytest.mark.parametrize(
    ("change", "status_code", "code"),
    [
        ({"expired": True}, 409, "RECOGNITION_EXPIRED"),
        ({"source_deleted_at": CREATED_AT}, 409, "RECOGNITION_EXPIRED"),
        ({"invoice_id": UUID(int=1)}, 409, "RECOGNITION_ALREADY_SUBMITTED"),
        ({"result_status": "failed"}, 409, "RECOGNITION_NOT_USABLE"),
        ({"requested_by": uuid4()}, 404, "RECOGNITION_NOT_FOUND"),
    ],
)
def test_submit_rejects_unusable_recognition(
    services: dict[str, Any], change: dict[str, Any], status_code: int, code: str
) -> None:
    recognition_id = recognize().json()["recognition_id"]
    services["records"].logs[UUID(recognition_id)].update(change)

    response = client.post("/api/v1/invoices", json=submit_payload(recognition_id), headers=AUTH)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert services["records"].invoices == []


@pytest.mark.parametrize(
    "change",
    [
        {"sales_amount": 6000.5},
        {"invoice_track": "cd"},
        {"tax_type": "unknown"},
        {"seller_tax_id": ""},
        {"items": []},
        {"buyer_tax_id": "123"},
        {"seller_tax_id": None},
        {"seller_name": "x" * 201},
        {"items": [{"source_line_no": 0, "item_name": "x", "line_amount": "1"}]},
        {"changes": [{"field_scope": "header", "field_name": "seller_name", "old_value": 1}]},
        {"tax_amount": "1.234"},
        {"unexpected": "x"},
    ],
)
def test_submit_validates_request(services: dict[str, Any], change: dict[str, Any]) -> None:
    payload = submit_payload(str(uuid4()), **change)

    response = client.post("/api/v1/invoices", json=payload, headers=AUTH)

    assert response.status_code == 422
    assert services["records"].invoices == []


# ==================== 欄位換算工具 ====================


def test_invoice_storage_key_uses_taipei_time_and_prefix() -> None:
    recognition_id = uuid4()
    key = invoice_format.invoice_storage_key(
        USER_ID, recognition_id, "image/jpeg", datetime(2026, 10, 28, 16, 5, 9, tzinfo=UTC)
    )

    assert key == f"{USER_ID}/INVOICES_20261029000509_{recognition_id}.jpg"
    assert invoice_format.is_invoice_storage_key(key)
    assert not invoice_format.is_invoice_storage_key("x/" + key)
    pdf_key = invoice_format.invoice_storage_key(
        USER_ID, recognition_id, "application/pdf", CREATED_AT
    )
    assert pdf_key.endswith(f"{recognition_id}.pdf")
    assert invoice_format.is_invoice_storage_key(pdf_key)
    with pytest.raises(ValueError):
        invoice_format.invoice_storage_key(USER_ID, recognition_id, "image/gif", CREATED_AT)
    with pytest.raises(ValueError):
        invoice_format.invoice_storage_key(
            USER_ID, recognition_id, "image/png", datetime(2026, 1, 1)
        )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("115/08/15", date(2026, 8, 15)),
        ("115.8.15", date(2026, 8, 15)),
        ("中華民國115年8月15日", date(2026, 8, 15)),
        ("1150815", date(2026, 8, 15)),
        ("2026/08/15", date(2026, 8, 15)),
        ("１１５／０８／１５", date(2026, 8, 15)),
        ("115/02/30", None),
        ("", None),
    ],
)
def test_parse_printed_date(text: str, expected: date | None) -> None:
    assert invoice_format.parse_printed_date(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("壹萬肆仟捌佰伍拾捌元整", 14858),
        ("拾壹萬肆仟捌佰伍拾捌元", 14858),  # 開頭沒有數字的「拾」是被劃掉的位名
        ("壹拾壹萬肆仟捌佰伍拾捌元", 114858),
        # 以下為正式 Document AI 實測（2026-11-03 第二聯扣抵聯樣本）的模型輸出
        ("拾壹萬捌仟貳佰伍拾零元", 18250),
        ("億 仟佰 拾貳萬柒仟伍佰貳拾陸元", 27526),
        ("拾捌萬捌仟玖佰零拾陸元", 88906),
        ("仟貳佰零拾參萬玖仟陸佰贰拾伍元", 2_039_625),
        ("億 仟 佰 拾參萬壹仟零佰貳拾貳元", 31022),
        ("拾壹萬玖仟零佰柒拾陸元", 19076),
        ("總計新臺幣(中文大寫)億仟佰拾壹萬肆仟捌佰伍拾捌元", 14858),  # 沒有數字的位名視為空位
        ("陸仟參佰元整", 6300),
        ("伍仟零伍拾元整", 5050),
        ("壹仟萬元整", 10_000_000),
        ("壹億貳仟萬", 120_000_000),
        ("拾元", None),  # 無數字的位名視為空位，自由書寫的「拾元」無法判讀
        ("零元", 0),
        ("壹壹元", None),  # 連續兩個數字
        ("約六千三", None),
        ("", None),
        (None, None),
    ],
)
def test_chinese_amount_to_int(text: str | None, expected: int | None) -> None:
    assert invoice_format.chinese_amount_to_int(text) == expected


@pytest.mark.parametrize(
    ("date_text", "period_text", "expected"),
    [
        ("10月3", "一一四年九、十月份", date(2025, 10, 3)),
        ("10月3日", "114年9、10月", date(2025, 10, 3)),
        ("９月１５日", "一一四年九、十月份", date(2025, 9, 15)),
        ("8月3日", "一一四年九、十月份", None),  # 月份不在期別內：不猜測
        ("10月32日", "一一四年九、十月份", None),  # 日期不存在
        ("114年10月", "一一四年九、十月份", None),  # 沒有日
        ("10月3日", None, None),
        (None, "一一四年九、十月份", None),
    ],
)
def test_infer_date_from_period(
    date_text: str | None, period_text: str | None, expected: date | None
) -> None:
    assert invoice_format.infer_date_from_period(date_text, period_text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("一〇八年九、十月份", "201910"),
        ("一一五年七、八月份", "202608"),
        ("115年07-08月", "202608"),
        ("115年1、2月", "202602"),
        ("八月份", None),
    ],
)
def test_parse_printed_period(text: str, expected: str | None) -> None:
    assert invoice_format.parse_printed_period(text) == expected


def test_amount_invoice_number_and_tax_id_helpers() -> None:
    assert invoice_format.normalize_amount("NT$1,000元整") == "1000"
    assert invoice_format.normalize_amount("1000.50") == "1000.5"
    assert invoice_format.normalize_amount("1.23456", 4) == "1.2346"
    assert invoice_format.normalize_amount("-1") is None
    assert invoice_format.normalize_amount(True) is None
    assert invoice_format.normalize_amount("1e20") is None
    assert invoice_format.split_invoice_number(None, "cd-75670992") == ("CD", "75670992")
    assert invoice_format.split_invoice_number("CD", "7567") == ("CD", None)
    assert invoice_format.normalize_tax_id("2760 1907") == "27601907"
    assert invoice_format.valid_tax_id("27601907")
    assert invoice_format.valid_tax_id("10458575")  # 第 7 碼為 7 的規則
    assert not invoice_format.valid_tax_id("12345678")
    assert invoice_format.tax_period_for(date(2026, 7, 1)) == "202608"


# ==================== Codex 反例回歸 ====================


def test_recognize_treats_out_of_range_values_as_missing(services: dict[str, Any]) -> None:
    services["model"].replies = [
        reply(MODEL_JSON | {"sales_amount": "1e30", "tax_period": "99999年9、10月份"})
    ]

    response = recognize()

    assert response.status_code == 200
    body = response.json()
    assert body["invoice"]["sales_amount"] is None
    assert ("sales_amount", "amount_missing") in [
        (warning["field"], warning["code"]) for warning in body["warnings"]
    ]


def test_recognize_records_failure_when_post_processing_breaks(
    services: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(data: Any) -> Any:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(invoice_upload_service, "_build_recognition", broken)

    response = recognize()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AI_RECOGNITION_FAILED"
    (log,) = services["records"].logs.values()
    assert (log["result_status"], log["error_message"]) == (
        "failed",
        "postprocess_failed:RuntimeError",
    )


def test_recognize_passes_remaining_time_to_gemini(services: dict[str, Any]) -> None:
    recognize()

    gemini_timeout = services["gemini"].call_details[0]["timeout_seconds"]
    assert 0 < gemini_timeout <= invoice_upload_service.RECOGNITION_DEADLINE_SECONDS


@pytest.mark.parametrize("google_status,http_status", [(200, 200), (429, 503)])
def test_recognize_with_synced_gemini_adapter(
    services: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    google_status: int,
    http_status: int,
) -> None:
    """以真實同步 adapter 接既有端點；DB／Storage 維持合成替身。"""
    requests: list[httpx.Request] = []

    def google(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if google_status == 200:
            payload = {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": json.dumps(MODEL_JSON)}],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "modelVersion": "gemini-3.8-flash",
            }
        else:
            payload = {"error": {"status": "RESOURCE_EXHAUSTED"}}
        return httpx.Response(google_status, json=payload)

    with httpx.Client(transport=httpx.MockTransport(google)) as http:
        adapter = gemini.GeminiClient(api_key="synthetic", model="gemini-3.8-flash", http=http)
        monkeypatch.setattr(invoice_upload_service.GeminiClient, "from_settings", lambda: adapter)
        response = recognize()
        assert http.is_closed
    assert response.status_code == http_status
    assert len(requests) == 1
    (log,) = services["records"].logs.values()
    if google_status == 200:
        body = response.json()
        assert body["recognition"]["ocr_provider"] == "google_gemini"
        assert body["recognition"]["ai_provider"] == "google_gemini"
        assert body["recognition"]["model"] == "gemini-3.8-flash"
        assert not services["records"].invoices
    else:
        assert log["result_status"] == "failed"
        assert log["error_message"] == "gemini_quota_exceeded:RESOURCE_EXHAUSTED"


def _fail_insert(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("synthetic insert failure")


@pytest.mark.parametrize(
    "case",
    [
        "success",
        "gemini_error",
        "storage_error",
        "gemini_not_configured",
        "multi_page_pdf",
        "no_text",
        "insert_failure",
    ],
)
def test_recognize_closes_gemini_client_on_every_outcome(
    services: dict[str, Any], monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Gemini client 每次辨識都恰好關閉一次，包含辨識之前與之後的各種失敗。"""
    content, content_type, filename = JPEG, "image/jpeg", "a.jpg"
    if case == "gemini_error":
        services["gemini"].error = GeminiError("gemini_timeout")
    elif case == "storage_error":
        services["storage"].put_error = StorageError("storage_denied", "AccessDenied")
    elif case == "gemini_not_configured":

        def not_configured() -> Any:
            raise GeminiError("gemini_not_configured")

        monkeypatch.setattr(invoice_upload_service.GeminiClient, "from_settings", not_configured)
    elif case == "multi_page_pdf":
        services["gemini"].page_count = 2
        content, content_type, filename = PDF, "application/pdf", "a.pdf"
    elif case == "no_text":
        services["gemini"].replies = [reply({"error": "no_text"})]
    elif case == "insert_failure":
        monkeypatch.setattr(recognition_repository, "insert", _fail_insert)

    if case == "insert_failure":
        with pytest.raises(RuntimeError):
            recognize(content, content_type, filename)
    else:
        response = recognize(content, content_type, filename)
        assert (response.status_code == 200) is (case == "success")
    if case != "gemini_not_configured":
        assert services["gemini"].closed == 1


@pytest.mark.parametrize(
    "case,status,code",
    [
        ("success", 200, None),
        ("gemini_error", 502, "AI_RECOGNITION_FAILED"),
    ],
)
def test_recognize_close_failure_keeps_original_result(
    services: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    case: str,
    status: int,
    code: str | None,
) -> None:
    """close() 本身失敗只記例外型別，不蓋過辨識結果或原本的錯誤，辨識紀錄照常完成。"""
    services["gemini"].close_error = OSError("synthetic-close-detail")
    if case == "gemini_error":
        services["gemini"].error = GeminiError("gemini_timeout")

    with caplog.at_level(logging.WARNING, logger=invoice_upload_service.__name__):
        response = recognize()

    assert response.status_code == status
    if code:
        assert response.json()["error"]["code"] == code
    assert services["gemini"].closed == 1
    if case == "success":
        (log,) = services["records"].logs.values()
        assert log["result_status"] == "success"
    elif case == "gemini_error":
        (log,) = services["records"].logs.values()
        assert (log["result_status"], log["error_message"]) == ("failed", "gemini_timeout")
    warnings = [r.getMessage() for r in caplog.records if r.name == invoice_upload_service.__name__]
    assert "關閉 Gemini client 失敗：OSError" in warnings
    assert all("synthetic-close-detail" not in message for message in warnings)


def test_recognize_does_not_close_when_gemini_is_not_configured(
    services: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """設定不足時根本沒有建立 Gemini client，也不寫任何資料。"""

    def not_configured() -> Any:
        raise GeminiError("gemini_not_configured")

    monkeypatch.setattr(invoice_upload_service.GeminiClient, "from_settings", not_configured)
    response = recognize()
    assert response.status_code == 503
    assert services["gemini"].closed == 0
    assert not services["records"].logs


def test_client_timeouts_never_exceed_defaults_or_remaining_time() -> None:
    assert groq._bounded_timeout(None) == groq.CHAT_TIMEOUT
    assert groq._bounded_timeout(5).read == 5
    assert groq._bounded_timeout(100).read == groq.CHAT_TIMEOUT.read
    assert document_ai._bounded_timeout(document_ai.PROCESS_TIMEOUT, 3).read == 3
    with pytest.raises(DocumentAIError):
        document_ai._bounded_timeout(document_ai.PROCESS_TIMEOUT, 0)


def test_normalize_amount_rounds_half_up_within_numeric_limits() -> None:
    assert invoice_format.normalize_amount("2.345") == "2.35"
    assert invoice_format.normalize_amount("2.34565", 4) == "2.3457"
    assert invoice_format.normalize_amount("1e30") is None
    assert invoice_format.normalize_amount("9999999999999999.995") is None
    assert invoice_format.normalize_amount("9999999999999999.99") == "9999999999999999.99"
    assert invoice_format.parse_printed_period("99999年9、10月份") is None


# 前台 mobile-camera.js 的 canonicalValue 在瀏覽器實際算出的結果（2026-10-29）；兩邊規則須一致，
# 否則修改紀錄會被判定不一致而無法送出
FRONTEND_CANONICAL_CASES = [
    ("sales_amount", "6,000", "6000"),
    ("sales_amount", "006000.50", "6000.5"),
    ("sales_amount", "0.000", "0"),
    ("sales_amount", "1e5", "1e5"),
    ("sales_amount", "-5", "-5"),
    ("sales_amount", "６０００", "６０００"),
    ("sales_amount", " 1 000 ", "1000"),
    ("quantity", "2.5000", "2.5"),
    ("quantity", "10", "10"),
    ("invoice_track", " cd ", "CD"),
    ("seller_tax_id", "2760-1907", "27601907"),
    ("seller_name", "  範例　", "範例"),
    ("seller_name", "   ", None),
    ("invoice_date", "2026-08-15", "2026-08-15"),
    ("tax_type", "taxable", "taxable"),
    ("line_amount", "100.", "100."),
    ("line_amount", ".5", ".5"),
    # Codex 2026-10-29 反例：高精度數字（不可經 Decimal context 捨入）與 Python／JS 空白定義差異
    ("quantity", "2.00000000000000000000000000001", "2.00000000000000000000000000001"),
    (
        "sales_amount",
        "12345678901234567890123456789012345.000100",
        "12345678901234567890123456789012345.0001",
    ),
    ("sales_amount", "1 000", "1000"),
    ("seller_name", "﻿範例﻿", "範例"),
    ("seller_name", "範例\x85", "範例\x85"),
    ("seller_name", "\x1c範例", "\x1c範例"),
    ("invoice_track", "c　d", "CD"),
]


def test_submit_keeps_high_precision_interim_change(services: dict[str, Any]) -> None:
    """數量 2 → 2.00000000000000000000000000001 → 2：兩次修改都要保留，不能被捨入成「無變化」。"""
    recognition_id = recognize().json()["recognition_id"]
    tiny = "2.00000000000000000000000000001"
    payload = submit_payload(
        recognition_id,
        changes=[
            change("quantity", "2", tiny, line_no=1),
            change("quantity", tiny, "2", line_no=1),
        ],
    )

    response = client.post("/api/v1/invoices", json=payload, headers=AUTH)

    assert response.status_code == 201
    assert summary(services["records"].changes, "field_name", "old_value", "new_value") == [
        ("quantity", "2", tiny),
        ("quantity", tiny, "2"),
    ]
    assert services["records"].differences == []


def test_change_log_limit_is_enforced_by_api(services: dict[str, Any]) -> None:
    recognition_id = recognize().json()["recognition_id"]
    flips = [
        change("seller_name", *(("範例文具行", "範例") if i % 2 == 0 else ("範例", "範例文具行")))
        for i in range(501)
    ]

    response = client.post(
        "/api/v1/invoices", json=submit_payload(recognition_id, changes=flips), headers=AUTH
    )

    assert response.status_code == 422
    assert services["records"].invoices == []


@pytest.mark.parametrize(("field_name", "value", "expected"), FRONTEND_CANONICAL_CASES)
def test_canonical_value_matches_frontend(
    field_name: str, value: str, expected: str | None
) -> None:
    assert invoice_upload_service._canonical_value(field_name, value) == expected


def test_submit_accepts_change_log_built_by_frontend(services: dict[str, Any]) -> None:
    """與瀏覽器實跑核對頁時送出的修改紀錄同形（含新增明細從空白開始的紀錄）。"""
    recognition_id = recognize().json()["recognition_id"]
    payload = submit_payload(
        recognition_id,
        tax_amount="250",
        items=[
            {
                "source_line_no": 1,
                "item_name": "辦公用品",
                "quantity": "3",
                "unit_price": "3000",
                "line_amount": "6000",
            },
            {
                "source_line_no": None,
                "item_name": "運費",
                "quantity": None,
                "unit_price": None,
                "line_amount": "100",
            },
        ],
        changes=[
            change("seller_name", "範例文具行", "範例文具有限公司"),
            change("seller_name", "範例文具有限公司", "範例文具行"),
            change("tax_amount", "300", "280"),
            change("tax_amount", "280", "250"),
            change("quantity", "2", "3", line_no=1),
            change("item_name", None, "運費", line_no=2),
            change("line_amount", None, "100", line_no=2),
        ],
    )

    response = client.post("/api/v1/invoices", json=payload, headers=AUTH)

    assert response.status_code == 201
    records = services["records"]
    assert summary(records.differences, "field_scope", "line_no", "field_name") == [
        ("header", None, "tax_amount"),
        ("item", 1, "quantity"),
        ("item", 2, "item_name"),
        ("item", 2, "line_amount"),
    ]
    assert len(records.changes) == 7
    assert [field["field_name"] for field in response.json()["modified_fields"]] == [
        "tax_amount",
        "quantity",
        "item_name",
        "line_amount",
    ]
