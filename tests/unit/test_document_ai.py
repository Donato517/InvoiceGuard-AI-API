"""
模組名稱：tests.unit.test_document_ai
功能說明：Google Document AI 模組的離線測試；以 httpx.MockTransport 模擬 Google，金鑰為測試時產生的合成值。
"""

import base64
import json
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import Settings
from app.integrations import document_ai
from app.integrations.document_ai import DocumentAIClient, DocumentAIError

TOKEN_URI = "https://oauth2.example.invalid/token"
PROCESSOR_URL = (
    "https://us-documentai.googleapis.com/v1/projects/synthetic-project"
    "/locations/us/processors/0123456789abcdef"
)
TEXT = "統一發票\nCD75670992\n"
DOCUMENT = {
    "text": TEXT,
    "pages": [
        {
            "pageNumber": 1,
            "dimension": {"width": 1000, "height": 800, "unit": "pixels"},
            "layout": {"confidence": 0.95},
            "lines": [
                {
                    "layout": {
                        # startIndex 為 0 時 Google 省略；int64 以字串表示
                        "textAnchor": {"textSegments": [{"endIndex": "5"}]},
                        "confidence": 0.98,
                        "boundingPoly": {
                            "normalizedVertices": [
                                {"x": 0.1, "y": 0.1},
                                {"x": 0.5, "y": 0.1},
                                {"x": 0.5, "y": 0.2},
                                {"x": 0.1, "y": 0.2},
                            ]
                        },
                    }
                },
                {
                    "layout": {
                        "textAnchor": {"textSegments": [{"startIndex": "5", "endIndex": "16"}]},
                        "confidence": 0.9,
                    }
                },
            ],
        }
    ],
}

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(scope="module")
def service_account_json() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "synthetic-project",
            "private_key_id": "synthetic-key-id",
            "private_key": pem,
            "client_email": "synthetic@synthetic-project.iam.gserviceaccount.com",
            "token_uri": TOKEN_URI,
        }
    )


@pytest.fixture(autouse=True)
def fresh_token_cache() -> Iterator[None]:
    document_ai.clear_token_cache()
    yield
    document_ai.clear_token_cache()


class FakeGoogle:
    """記錄請求並回傳指定回應；預設權杖與辨識都成功。"""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_response = httpx.Response(
            200, json={"access_token": "synthetic-access-token", "expires_in": 3600}
        )
        self.api_response = httpx.Response(200, json={"document": DOCUMENT})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if str(request.url) == TOKEN_URI:
            return self.token_response
        return self.api_response

    def calls(self, prefix: str) -> list[httpx.Request]:
        return [request for request in self.requests if str(request.url).startswith(prefix)]


def make_client(default_json: str, handler: Handler, **changes: str) -> DocumentAIClient:
    values = {
        "project_id": "synthetic-project",
        "location": "us",
        "processor_id": "0123456789abcdef",
        "service_account_json": default_json,
    }
    return DocumentAIClient(
        **(values | changes), http=httpx.Client(transport=httpx.MockTransport(handler))
    )


def jwt_claims(assertion: str) -> dict[str, Any]:
    payload = assertion.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def test_process_sends_document_and_parses_lines(service_account_json: str) -> None:
    google = FakeGoogle()
    content = b"synthetic-jpeg-bytes"

    result = make_client(service_account_json, google).process(content, "image/jpeg")

    (token_request,) = google.calls(TOKEN_URI)
    form = dict(httpx.QueryParams(token_request.content.decode()))
    assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    claims = jwt_claims(form["assertion"])
    assert claims["iss"] == "synthetic@synthetic-project.iam.gserviceaccount.com"
    assert claims["aud"] == TOKEN_URI
    assert claims["scope"] == document_ai.TOKEN_SCOPE

    (process_request,) = google.calls(PROCESSOR_URL)
    assert str(process_request.url) == PROCESSOR_URL + ":process"
    assert process_request.headers["Authorization"] == "Bearer synthetic-access-token"
    body = json.loads(process_request.content)
    assert base64.b64decode(body["rawDocument"]["content"]) == content
    assert body["rawDocument"]["mimeType"] == "image/jpeg"
    assert body["skipHumanReview"] is True
    assert body["fieldMask"] == document_ai.PROCESS_FIELD_MASK

    assert result.text == TEXT
    (page,) = result.pages
    assert (page.page_number, page.width, page.height, page.confidence) == (1, 1000, 800, 0.95)
    assert [line.text for line in page.lines] == ["統一發票", "CD75670992"]
    assert page.lines[0].confidence == 0.98
    assert page.lines[0].bounding_box[2] == (0.5, 0.2)
    assert page.lines[1].bounding_box == ()
    assert result.confidence == 0.95
    assert result.raw_response == {"document": DOCUMENT}
    assert "raw_response" not in repr(result)
    assert document_ai.PROVIDER == "google_document_ai"


class FakeClock:
    """取代 document_ai 模組的 time：monotonic 可手動推進，time() 用真實時間（權杖到期計算）。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return time.time()


@pytest.mark.parametrize(("token_seconds", "ocr_called"), [(0.6, True), (1.5, False)])
def test_timeout_seconds_covers_token_exchange_and_ocr(
    service_account_json: str,
    monkeypatch: pytest.MonkeyPatch,
    token_seconds: float,
    ocr_called: bool,
) -> None:
    clock = FakeClock()
    monkeypatch.setattr(document_ai, "time", clock)
    google = FakeGoogle()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URI:
            clock.now += token_seconds  # 換發權杖耗時
        return google(request)

    client = make_client(service_account_json, handler)
    if ocr_called:
        client.process(b"data", "image/jpeg", timeout_seconds=1)
    else:
        with pytest.raises(DocumentAIError) as error:
            client.process(b"data", "image/jpeg", timeout_seconds=1)
        assert (error.value.code, error.value.detail) == ("document_ai_timeout", "NoTimeLeft")

    (token_request,) = google.calls(TOKEN_URI)
    assert max(token_request.extensions["timeout"].values()) <= 1
    ocr_requests = google.calls(PROCESSOR_URL)
    assert bool(ocr_requests) is ocr_called
    if ocr_called:
        assert max(ocr_requests[0].extensions["timeout"].values()) == pytest.approx(0.4)


def test_access_token_is_cached_between_calls(service_account_json: str) -> None:
    google = FakeGoogle()
    client = make_client(service_account_json, google)

    client.process(b"one", "image/png")
    client.process(b"two", "application/pdf")

    assert len(google.calls(TOKEN_URI)) == 1
    assert len(google.calls(PROCESSOR_URL)) == 2


@pytest.mark.parametrize(
    "content,mime_type", [(b"", "image/jpeg"), (b"data", "image/gif"), (b"data", "")]
)
def test_invalid_input_never_calls_google(
    service_account_json: str, content: bytes, mime_type: str
) -> None:
    google = FakeGoogle()
    with pytest.raises(DocumentAIError) as caught:
        make_client(service_account_json, google).process(content, mime_type)
    assert caught.value.code == "document_ai_invalid_input"
    assert google.requests == []


@pytest.mark.parametrize(
    "changes",
    [
        {"project_id": ""},
        {"location": "US WEST"},
        {"processor_id": "projects/x/processors/y"},
        {"service_account_json": "not json"},
        {"service_account_json": json.dumps({"type": "authorized_user"})},
    ],
)
def test_misconfiguration_is_not_configured(
    service_account_json: str, changes: dict[str, str]
) -> None:
    with pytest.raises(DocumentAIError) as caught:
        make_client(service_account_json, FakeGoogle(), **changes)
    assert caught.value.code == "document_ai_not_configured"
    assert "PRIVATE KEY" not in str(caught.value) + caught.value.detail


def test_insecure_token_uri_is_not_configured(service_account_json: str) -> None:
    info = json.loads(service_account_json) | {"token_uri": "http://oauth2.example.invalid/token"}
    with pytest.raises(DocumentAIError) as caught:
        make_client(service_account_json, FakeGoogle(), service_account_json=json.dumps(info))
    assert caught.value.code == "document_ai_not_configured"


def test_from_settings_reads_google_settings(service_account_json: str) -> None:
    configuration = Settings(
        _env_prefix="IG_UNIT_TEST_",
        GOOGLE_CLOUD_PROJECT_ID="synthetic-project",
        GOOGLE_CLOUD_LOCATION="us",
        DOCUMENT_AI_PROCESSOR_ID="0123456789abcdef",
        GOOGLE_SERVICE_ACCOUNT_JSON=service_account_json,
    )
    client = DocumentAIClient.from_settings(configuration)
    assert client._processor_url == PROCESSOR_URL
    with pytest.raises(DocumentAIError) as caught:
        DocumentAIClient.from_settings(Settings(_env_prefix="IG_UNIT_TEST_"))
    assert caught.value.code == "document_ai_not_configured"


@pytest.mark.parametrize(
    "status,error,code,detail",
    [
        (
            403,
            {
                "status": "PERMISSION_DENIED",
                "message": "synthetic message with project number 123",
                "details": [{"reason": "SERVICE_DISABLED"}],
            },
            "document_ai_denied",
            "PERMISSION_DENIED/SERVICE_DISABLED",
        ),
        (400, {"status": "INVALID_ARGUMENT"}, "document_ai_invalid_input", "INVALID_ARGUMENT"),
        (404, {"status": "NOT_FOUND"}, "document_ai_not_found", "NOT_FOUND"),
        (429, {"status": "RESOURCE_EXHAUSTED"}, "document_ai_quota_exceeded", "RESOURCE_EXHAUSTED"),
        (402, {"status": "RESOURCE_EXHAUSTED"}, "document_ai_quota_exceeded", "RESOURCE_EXHAUSTED"),
        (500, None, "document_ai_failed", "HTTP500"),
    ],
)
def test_google_errors_map_to_fixed_codes(
    service_account_json: str, status: int, error: Any, code: str, detail: str
) -> None:
    google = FakeGoogle()
    google.api_response = httpx.Response(status, json={"error": error} if error else {})
    with pytest.raises(DocumentAIError) as caught:
        make_client(service_account_json, google).process(b"data", "image/png")
    assert (caught.value.code, caught.value.detail) == (code, detail)
    assert "synthetic message" not in str(caught.value) + caught.value.detail


def test_token_failure_is_auth_failed(service_account_json: str) -> None:
    google = FakeGoogle()
    google.token_response = httpx.Response(
        400, json={"error": "invalid_grant", "error_description": "synthetic description"}
    )
    with pytest.raises(DocumentAIError) as caught:
        make_client(service_account_json, google).process(b"data", "image/png")
    assert (caught.value.code, caught.value.detail) == ("document_ai_auth_failed", "invalid_grant")
    assert google.calls(PROCESSOR_URL) == []


@pytest.mark.parametrize(
    "exception,code",
    [
        (httpx.ReadTimeout("synthetic"), "document_ai_timeout"),
        (httpx.ConnectError("synthetic"), "document_ai_unreachable"),
    ],
)
def test_timeouts_and_network_errors_have_fixed_codes(
    service_account_json: str, exception: Exception, code: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception

    with pytest.raises(DocumentAIError) as caught:
        make_client(service_account_json, handler).process(b"data", "image/png")
    assert caught.value.code == code


def test_describe_processor_reads_metadata(service_account_json: str) -> None:
    google = FakeGoogle()
    google.api_response = httpx.Response(
        200,
        json={
            "type": "OCR_PROCESSOR",
            "state": "ENABLED",
            "displayName": "InvoiceGuard-OCR",
            "defaultProcessorVersion": "projects/1/locations/us/processors/x/processorVersions/v2",
        },
    )
    info = make_client(service_account_json, google).describe_processor()
    assert info == document_ai.ProcessorInfo("OCR_PROCESSOR", "ENABLED", "InvoiceGuard-OCR", "v2")
    (request,) = google.calls(PROCESSOR_URL)
    assert request.method == "GET"
    assert str(request.url) == PROCESSOR_URL


@pytest.mark.parametrize(
    "error",
    [
        {
            "status": {"message": "synthetic nested message"},
            "details": [{"reason": ["synthetic"]}, {"reason": "synthetic reason with spaces"}],
        },
        {"status": "x" * 65},
        {"status": "PERMISSION_DENIED", "details": "SYNTHETIC_NOT_A_LIST"},
    ],
)
def test_unexpected_google_error_fields_never_reach_detail(
    service_account_json: str, error: dict[str, Any]
) -> None:
    google = FakeGoogle()
    google.api_response = httpx.Response(403, json={"error": error})
    with pytest.raises(DocumentAIError) as caught:
        make_client(service_account_json, google).process(b"data", "image/png")
    assert caught.value.code == "document_ai_denied"
    assert caught.value.detail in {"HTTP403", "PERMISSION_DENIED"}


@pytest.mark.parametrize(
    "error", [{"nested": "synthetic"}, "Invalid Grant for key ABC", "x" * 65, ["invalid_grant"]]
)
def test_unexpected_token_error_never_reaches_detail(service_account_json: str, error: Any) -> None:
    google = FakeGoogle()
    google.token_response = httpx.Response(400, json={"error": error})
    with pytest.raises(DocumentAIError) as caught:
        make_client(service_account_json, google).process(b"data", "image/png")
    assert (caught.value.code, caught.value.detail) == ("document_ai_auth_failed", "HTTP400")
