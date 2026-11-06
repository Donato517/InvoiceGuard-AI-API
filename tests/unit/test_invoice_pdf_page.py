"""
模組名稱：tests.unit.test_invoice_pdf_page
功能說明：測試多頁 PDF 找發票頁（POST /invoices/pdf-pages/classify）：總覽圖拼接、輸入限制、模型回覆解讀與錯誤對應。
注意事項：以 Gemini 替身執行，不連正式 DB、Storage 或模型服務；影像為程式產生的合成圖。
"""

import io
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core import deps
from app.core.exceptions import AppError, UnauthorizedError
from app.integrations.chat_models import ChatReply
from app.integrations.gemini import GeminiError
from app.main import app
from app.schemas.auth import DepartmentRead, SessionRead
from app.services import auth_service, invoice_pdf_page_service
from app.services.invoice_pdf_page_service import _InvalidReplyError

client = TestClient(app)
AUTH = {"Authorization": "Bearer synthetic-session-token"}
URL = "/api/v1/invoices/pdf-pages/classify"


def image_bytes(size: tuple[int, int] = (300, 200), fmt: str = "JPEG") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, (255, 255, 255)).save(output, format=fmt)
    return output.getvalue()


def reply(payload: Any) -> ChatReply:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return ChatReply(
        text=text,
        model="gemini-test",
        finish_reason="STOP",
        prompt_tokens=1,
        output_tokens=1,
        total_tokens=2,
        raw_response={},
    )


def session_read() -> SessionRead:
    department = DepartmentRead(
        department_id=UUID("22222222-2222-4222-8222-222222222222"),
        department_code="purchasing_d",
        department_name="採購部",
        is_primary=True,
    )
    return SessionRead(
        user_id=UUID("11111111-1111-4111-8111-111111111111"),
        email="user@example.com",
        display_name="測試使用者",
        department=department,
        departments=(department,),
        expires_at=datetime(2026, 11, 6, tzinfo=UTC) + timedelta(hours=1),
    )


@dataclass
class FakeGemini:
    """Gemini 替身：記錄呼叫並回傳固定回覆（或丟出例外）。"""

    result: ChatReply | Exception
    calls: list[dict[str, Any]] = field(default_factory=list)
    closed: int = 0

    def extract_invoice(self, content: bytes, mime_type: str, **kwargs: Any) -> ChatReply:
        self.calls.append({"content": content, "mime_type": mime_type, **kwargs})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def close(self) -> None:
        self.closed += 1


@pytest.fixture
def fake_db() -> Iterator[MagicMock]:
    db = MagicMock()
    app.dependency_overrides[deps.get_optional_db] = lambda: db
    yield db
    app.dependency_overrides.clear()


@pytest.fixture
def gemini(monkeypatch: pytest.MonkeyPatch, fake_db: MagicMock) -> FakeGemini:
    fake = FakeGemini(
        reply(
            {
                "pages": [
                    {"tile": 1, "is_triplicate_invoice": False, "copy": None},
                    {"tile": 2, "is_triplicate_invoice": True, "copy": 2},
                ]
            }
        )
    )
    monkeypatch.setattr(auth_service, "resolve_session", lambda db, token: session_read())
    monkeypatch.setattr(invoice_pdf_page_service.GeminiClient, "from_settings", lambda: fake)
    return fake


def post(images: list[bytes]) -> Any:
    files = [("files", (f"p{i}.jpg", content, "image/jpeg")) for i, content in enumerate(images)]
    return client.post(URL, files=files, headers=AUTH)


# ---- 總覽圖 ----


def test_sheet_keeps_single_page_at_recognition_size() -> None:
    sheet = Image.open(
        io.BytesIO(invoice_pdf_page_service.build_sheet([image_bytes((3000, 1800))]))
    )
    assert sheet.format == "JPEG"
    gap, label = invoice_pdf_page_service.GAP, invoice_pdf_page_service.LABEL_HEIGHT
    assert sheet.size == (2000 + 2 * gap, 1200 + label + 2 * gap)


def test_sheet_arranges_pages_in_a_numbered_grid() -> None:
    images = [image_bytes((1600, 1000))] * 5 + [image_bytes((800, 1200), "PNG")]
    sheet = Image.open(io.BytesIO(invoice_pdf_page_service.build_sheet(images)))
    gap, label = invoice_pdf_page_service.GAP, invoice_pdf_page_service.LABEL_HEIGHT
    # 6 張排 3 欄 2 列；每格取最寬與最高（800×800 以內）再加標籤列
    assert sheet.size == (3 * 800 + 4 * gap, 2 * (800 + label) + 3 * gap)
    # 第 1 格標籤是黑底
    assert sheet.getpixel((gap + 2, gap + 2)) == (0, 0, 0)


@pytest.mark.parametrize(
    ("images", "code"),
    [
        ([], "INVOICE_PAGE_COUNT_INVALID"),
        ([image_bytes()] * 10, "INVOICE_PAGE_COUNT_INVALID"),
        ([b"%PDF-1.7 synthetic"], "INVOICE_IMAGE_INVALID"),
        ([b"\xff\xd8\xff broken jpeg"], "INVOICE_IMAGE_INVALID"),
        ([b"\xff\xd8\xff" + b"0" * (1536 * 1024)], "INVOICE_IMAGE_TOO_LARGE"),
    ],
)
def test_sheet_rejects_invalid_input(images: list[bytes], code: str) -> None:
    with pytest.raises(AppError) as caught:
        invoice_pdf_page_service.build_sheet(images)
    assert caught.value.code == code


# ---- 模型回覆 ----


def test_reply_missing_tiles_and_bad_copies_are_safe() -> None:
    pages = invoice_pdf_page_service.parse_reply(
        reply(
            "```json\n"
            + json.dumps(
                {
                    "pages": [
                        {"tile": 1, "is_triplicate_invoice": True, "copy": 1},
                        {"tile": 2, "is_triplicate_invoice": True, "copy": 4},
                        {"tile": 3, "is_triplicate_invoice": False, "copy": 2},
                        {"tile": True, "is_triplicate_invoice": True, "copy": 3},
                        {"tile": 9, "is_triplicate_invoice": True, "copy": 3},
                        "noise",
                    ]
                }
            )
            + "\n```"
        ),
        4,
    )
    assert [(p.index, p.is_triplicate_invoice, p.copy_no) for p in pages] == [
        (1, True, 1),
        (2, True, None),  # 聯別只接受 1～3
        (3, False, None),  # 不是發票就沒有聯別
        (4, False, None),  # 缺少的編號視為不是發票
    ]


@pytest.mark.parametrize("text", ["not json", "[]", '{"pages": "x"}'])
def test_reply_without_pages_list_is_invalid(text: str) -> None:
    with pytest.raises(_InvalidReplyError):
        invoice_pdf_page_service.parse_reply(reply(text), 1)


# ---- 端點 ----


def test_endpoint_returns_classification_in_upload_order(gemini: FakeGemini) -> None:
    response = post([image_bytes(), image_bytes()])
    assert response.status_code == 200
    assert response.json() == {
        "pages": [
            {"index": 1, "is_triplicate_invoice": False, "copy_no": None},
            {"index": 2, "is_triplicate_invoice": True, "copy_no": 2},
        ],
        "model": "gemini-test",
    }
    call = gemini.calls[0]
    assert call["mime_type"] == "image/jpeg" and call["content"].startswith(b"\xff\xd8\xff")
    assert "#1 到 #2" in call["prompt"] and call["timeout_seconds"] > 0
    assert "few_shot_examples" not in call  # 挑頁不帶辨識用的範例
    assert gemini.closed == 1


def test_endpoint_rejects_too_many_pages_without_calling_model(gemini: FakeGemini) -> None:
    response = post([image_bytes()] * 10)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVOICE_PAGE_COUNT_INVALID"
    assert gemini.calls == []


def test_endpoint_requires_session(gemini: FakeGemini, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(db: Any, token: str) -> SessionRead:
        raise UnauthorizedError("請重新登入")

    monkeypatch.setattr(auth_service, "resolve_session", reject)
    assert post([image_bytes()]).status_code == 401
    assert gemini.calls == []


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (GeminiError("gemini_timeout"), 502, "AI_PAGE_PICK_FAILED"),
        (GeminiError("gemini_quota_exceeded"), 503, None),
    ],
)
def test_endpoint_maps_model_errors(
    gemini: FakeGemini, error: Exception, status: int, code: str | None
) -> None:
    gemini.result = error
    response = post([image_bytes()])
    assert response.status_code == status
    if code:
        assert response.json()["error"]["code"] == code
    assert gemini.closed == 1


def test_endpoint_reports_unreadable_reply(gemini: FakeGemini) -> None:
    gemini.result = reply("抱歉，我無法判斷")
    response = post([image_bytes()])
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AI_PAGE_PICK_FAILED"
