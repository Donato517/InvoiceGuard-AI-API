"""
模組名稱：tests.unit.test_vertex_embedding
功能說明：Agent Platform 向量模組的離線測試；以 httpx.MockTransport 模擬 Google，憑證為合成值。
注意事項：
    - ADMIN 與 API 各有一份相同的本測試；不呼叫正式服務。
"""

import json
import math
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from app.core.config import Settings
from app.integrations.vertex_embedding import (
    API_BASE,
    MAX_CONCURRENCY,
    EmbeddingError,
    VertexEmbeddingClient,
)

TOKEN_URI = "https://oauth2.googleapis.com/token"
PROJECT = "synthetic-project"
MODEL = "gemini-embedding-2"
DIMENSIONS = 4
ACCESS_TOKEN = "synthetic-access-token"
EMBED_URL = (
    f"{API_BASE}/projects/{PROJECT}/locations/global/publishers/google/models/{MODEL}:embedContent"
)
VECTOR = [0.1, 0.2, 0.3, 0.4]

Embed = Callable[[httpx.Request], httpx.Response]


def embed_ok(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"embedding": {"values": VECTOR}})


class FakeGoogle:
    """記錄請求；權杖固定成功，embedContent 回應由 embed 決定。"""

    def __init__(self, embed: Embed = embed_ok) -> None:
        self.embed = embed
        self.requests: list[httpx.Request] = []
        self.lock = threading.Lock()
        self.token_response = httpx.Response(
            200, json={"access_token": ACCESS_TOKEN, "expires_in": 3600}
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            self.requests.append(request)
        if str(request.url) == TOKEN_URI:
            return self.token_response
        return self.embed(request)

    @property
    def embed_requests(self) -> list[httpx.Request]:
        return [request for request in self.requests if str(request.url) == EMBED_URL]


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
            "project_id": PROJECT,
            "private_key": pem,
            "client_email": f"synthetic@{PROJECT}.iam.gserviceaccount.com",
            "token_uri": TOKEN_URI,
        }
    )


def make_client(
    service_account: str, google: Any, *, dimensions: int = DIMENSIONS
) -> VertexEmbeddingClient:
    return VertexEmbeddingClient(
        project_id=PROJECT,
        model=MODEL,
        dimensions=dimensions,
        service_account_json=service_account,
        http=httpx.Client(transport=httpx.MockTransport(google)),
    )


def sent_body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


def sent_text(request: httpx.Request) -> str:
    return sent_body(request)["content"]["parts"][0]["text"]


def test_embed_sends_document_prefix_dimensions_and_bearer_token(
    service_account_json: str,
) -> None:
    google = FakeGoogle()

    batch = make_client(service_account_json, google).embed_texts(["營業稅規定"], title="稅務")

    (request,) = google.embed_requests
    assert request.headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert ACCESS_TOKEN not in str(request.url)
    assert sent_body(request) == {
        "content": {"role": "user", "parts": [{"text": "title: 稅務 | text: 營業稅規定"}]},
        "outputDimensionality": DIMENSIONS,
        "autoTruncate": False,
    }
    assert batch.vectors == (tuple(VECTOR),)
    assert (batch.model, batch.dimensions) == (MODEL, DIMENSIONS)


def test_document_without_title_uses_none(service_account_json: str) -> None:
    google = FakeGoogle()

    make_client(service_account_json, google).embed_texts(["內容"])

    assert sent_text(google.embed_requests[0]) == "title: none | text: 內容"


def test_query_uses_search_prefix(service_account_json: str) -> None:
    google = FakeGoogle()

    make_client(service_account_json, google).embed_texts(["可以扣抵嗎"], task="query")

    assert sent_text(google.embed_requests[0]) == "task: search result | query: 可以扣抵嗎"


def test_vectors_keep_input_order_under_concurrency(service_account_json: str) -> None:
    def embed(request: httpx.Request) -> httpx.Response:
        index = int(sent_text(request).rsplit(" ", 1)[-1])
        # 前面的文字較晚完成，順序若依完成時間就會錯
        time.sleep(0.02 if index < 4 else 0)
        return httpx.Response(200, json={"embedding": {"values": [index, 0, 0, 0]}})

    batch = make_client(service_account_json, FakeGoogle(embed)).embed_texts(
        [str(index) for index in range(12)]
    )

    assert [vector[0] for vector in batch.vectors] == [float(index) for index in range(12)]


def test_concurrency_is_used_and_capped(service_account_json: str) -> None:
    lock = threading.Lock()
    active = 0
    peak = 0

    def embed(_request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return embed_ok(_request)

    make_client(service_account_json, FakeGoogle(embed)).embed_texts(
        [f"段落{index}" for index in range(MAX_CONCURRENCY * 3)]
    )

    assert 1 < peak <= MAX_CONCURRENCY


def test_one_failure_fails_the_whole_batch(service_account_json: str) -> None:
    def embed(request: httpx.Request) -> httpx.Response:
        if "壞" in sent_text(request):
            return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}})
        return embed_ok(request)

    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, FakeGoogle(embed)).embed_texts(["好", "壞", "好"])

    assert caught.value.code == "embedding_quota_exceeded"


@pytest.mark.parametrize(
    "texts,kwargs",
    [
        ([], {}),
        ("單一字串", {}),
        (["  "], {}),
        (["有效", ""], {}),
        ([123], {}),
        (["文字"], {"task": "classification"}),
        (["文字"], {"task": "query", "title": "標題"}),
        (["文字"], {"title": "  "}),
    ],
)
def test_invalid_input_is_rejected_before_any_request(
    service_account_json: str, texts: Any, kwargs: dict[str, Any]
) -> None:
    google = FakeGoogle()

    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, google).embed_texts(texts, **kwargs)

    assert caught.value.code == "embedding_invalid_input"
    assert google.requests == []


@pytest.mark.parametrize(
    "status,error,code",
    [
        (400, {"status": "INVALID_ARGUMENT"}, "embedding_invalid_input"),
        (401, {"status": "UNAUTHENTICATED"}, "embedding_auth_failed"),
        (
            403,
            {"status": "PERMISSION_DENIED", "details": [{"reason": "IAM_PERMISSION_DENIED"}]},
            "embedding_denied",
        ),
        (403, {"status": "PERMISSION_DENIED"}, "embedding_denied"),
        (404, {"status": "NOT_FOUND"}, "embedding_not_found"),
        (429, {"status": "RESOURCE_EXHAUSTED"}, "embedding_quota_exceeded"),
        (402, {}, "embedding_quota_exceeded"),
        (504, {"status": "DEADLINE_EXCEEDED"}, "embedding_timeout"),
        (500, {"status": "INTERNAL"}, "embedding_failed"),
    ],
)
def test_google_errors_map_to_fixed_codes(
    service_account_json: str, status: int, error: dict[str, Any], code: str
) -> None:
    google = FakeGoogle(lambda _: httpx.Response(status, json={"error": error}))

    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, google).embed_texts(["文字"])

    assert caught.value.code == code


def test_error_detail_only_carries_google_codes(service_account_json: str) -> None:
    body = {
        "error": {
            "status": "INVALID_ARGUMENT",
            "message": "The input text 機密內容 exceeds the maximum",
            "details": [{"reason": "TOO_LONG"}, {"reason": "not a code"}, "x"],
        }
    }
    google = FakeGoogle(lambda _: httpx.Response(400, json=body))

    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, google).embed_texts(["機密內容"])

    assert caught.value.detail == "INVALID_ARGUMENT/TOO_LONG"
    assert "機密內容" not in repr(caught.value) and ACCESS_TOKEN not in repr(caught.value)


@pytest.mark.parametrize(
    "embed",
    [
        lambda _: httpx.Response(200, content=b"not json"),
        lambda _: httpx.Response(200, json=[]),
        lambda _: httpx.Response(200, json={"embedding": {}}),
        lambda _: httpx.Response(200, json={"embedding": {"values": [0.1]}}),
        lambda _: httpx.Response(200, json={"embedding": {"values": [0.1, 0.2, 0.3, None]}}),
        lambda _: httpx.Response(200, json={"embedding": {"values": [0.1, 0.2, 0.3, True]}}),
        lambda _: httpx.Response(200, content=b'{"embedding": {"values": [1, 2, 3, NaN]}}'),
    ],
)
def test_malformed_vector_fails_closed(service_account_json: str, embed: Embed) -> None:
    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, FakeGoogle(embed)).embed_texts(["文字"])

    assert caught.value.code == "embedding_failed"


def test_timeout_budget_limits_each_request(service_account_json: str) -> None:
    google = FakeGoogle()

    make_client(service_account_json, google).embed_texts(["文字"], timeout_seconds=3)

    for request in google.requests:
        assert all(0 < value <= 3 for value in request.extensions["timeout"].values())


@pytest.mark.parametrize("seconds", [0, -1, math.nan, math.inf, True])
def test_invalid_budget_is_timeout_before_any_request(
    service_account_json: str, seconds: float
) -> None:
    google = FakeGoogle()

    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, google).embed_texts(["文字"], timeout_seconds=seconds)

    assert caught.value.code == "embedding_timeout"
    assert google.requests == []


def test_expired_budget_stops_remaining_calls(service_account_json: str) -> None:
    google = FakeGoogle()

    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, google)._embed_one(
            "文字", ACCESS_TOKEN, time.monotonic() - 1
        )

    assert caught.value.code == "embedding_timeout"
    assert google.embed_requests == []


@pytest.mark.parametrize(
    "failure,code",
    [
        (httpx.ReadTimeout("slow"), "embedding_timeout"),
        (httpx.ConnectError("down"), "embedding_unreachable"),
    ],
)
def test_transport_errors_map_to_fixed_codes(
    service_account_json: str, failure: Exception, code: str
) -> None:
    def embed(_request: httpx.Request) -> httpx.Response:
        raise failure

    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, FakeGoogle(embed)).embed_texts(["文字"])

    assert caught.value.code == code


def test_access_token_is_cached_between_calls(service_account_json: str) -> None:
    google = FakeGoogle()
    client = make_client(service_account_json, google)

    client.embed_texts(["第一批"])
    client.embed_texts(["第二批"])

    assert sum(str(request.url) == TOKEN_URI for request in google.requests) == 1
    assert len(google.embed_requests) == 2


def test_expired_access_token_is_refreshed(service_account_json: str) -> None:
    google = FakeGoogle()
    google.token_response = httpx.Response(
        200, json={"access_token": ACCESS_TOKEN, "expires_in": 30}
    )
    client = make_client(service_account_json, google)

    client.embed_texts(["第一批"])
    client.embed_texts(["第二批"])

    assert sum(str(request.url) == TOKEN_URI for request in google.requests) == 2


@pytest.mark.parametrize(
    "response,code",
    [
        (httpx.Response(400, json={"error": "invalid_grant"}), "embedding_auth_failed"),
        (httpx.Response(503), "embedding_failed"),
        (httpx.Response(200, json={}), "embedding_auth_failed"),
        (
            httpx.Response(200, json={"access_token": ACCESS_TOKEN, "expires_in": "soon"}),
            "embedding_auth_failed",
        ),
    ],
)
def test_token_failures_stop_before_embedding(
    service_account_json: str, response: httpx.Response, code: str
) -> None:
    google = FakeGoogle()
    google.token_response = response

    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, google).embed_texts(["文字"])

    assert caught.value.code == code
    assert google.embed_requests == []


@pytest.mark.parametrize(
    "project,model,dimensions",
    [
        ("", MODEL, DIMENSIONS),
        ("Bad Project", MODEL, DIMENSIONS),
        (PROJECT, "", DIMENSIONS),
        (PROJECT, "../other", DIMENSIONS),
        (PROJECT, MODEL, 0),
        (PROJECT, MODEL, True),
    ],
)
def test_invalid_settings_are_not_configured(
    service_account_json: str, project: str, model: str, dimensions: int
) -> None:
    with pytest.raises(EmbeddingError) as caught:
        VertexEmbeddingClient(
            project_id=project,
            model=model,
            dimensions=dimensions,
            service_account_json=service_account_json,
        )
    assert caught.value.code == "embedding_not_configured"


@pytest.mark.parametrize(
    "change",
    [
        {"type": "authorized_user"},
        {"client_email": ""},
        {"private_key": ""},
        {"token_uri": "https://attacker.example/token"},
    ],
)
def test_invalid_service_account_is_not_configured(
    service_account_json: str, change: dict[str, str]
) -> None:
    info = {**json.loads(service_account_json), **change}

    with pytest.raises(EmbeddingError) as caught:
        make_client(json.dumps(info), FakeGoogle())

    assert caught.value.code == "embedding_not_configured"


@pytest.mark.parametrize("raw", ["", "not json", "[]"])
def test_unreadable_service_account_is_not_configured(raw: str) -> None:
    with pytest.raises(EmbeddingError) as caught:
        make_client(raw, FakeGoogle())

    assert caught.value.code == "embedding_not_configured"


def test_broken_signing_key_is_not_configured(service_account_json: str) -> None:
    info = {**json.loads(service_account_json), "private_key": "not a key"}

    with pytest.raises(EmbeddingError) as caught:
        make_client(json.dumps(info), FakeGoogle()).embed_texts(["文字"])

    assert caught.value.code == "embedding_not_configured"


def test_from_settings_uses_defaults_and_overrides(service_account_json: str) -> None:
    configured = {
        "GOOGLE_CLOUD_PROJECT_ID": PROJECT,
        "GOOGLE_SERVICE_ACCOUNT_JSON": service_account_json,
    }

    client = VertexEmbeddingClient.from_settings(
        Settings(_env_prefix="IG_UNIT_TEST_", **configured)
    )
    custom = VertexEmbeddingClient.from_settings(
        Settings(
            _env_prefix="IG_UNIT_TEST_",
            VERTEX_EMBEDDING_MODEL="gemini-embedding-x",
            VERTEX_EMBEDDING_DIMENSIONS=768,
            **configured,
        )
    )

    assert (client.model, client.dimensions) == ("gemini-embedding-2", 1536)
    assert (custom.model, custom.dimensions) == ("gemini-embedding-x", 768)
    client.close()
    custom.close()


def test_from_settings_without_google_settings_is_not_configured() -> None:
    with pytest.raises(EmbeddingError) as caught:
        VertexEmbeddingClient.from_settings(Settings(_env_prefix="IG_UNIT_TEST_"))

    assert caught.value.code == "embedding_not_configured"


@pytest.mark.parametrize("dimensions", [127, 2001])
def test_settings_reject_dimensions_outside_supported_range(dimensions: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_prefix="IG_UNIT_TEST_", VERTEX_EMBEDDING_DIMENSIONS=dimensions)


def test_context_manager_only_closes_its_own_http_client(service_account_json: str) -> None:
    shared = httpx.Client(transport=httpx.MockTransport(FakeGoogle()))

    with VertexEmbeddingClient(
        project_id=PROJECT,
        model=MODEL,
        dimensions=DIMENSIONS,
        service_account_json=service_account_json,
        http=shared,
    ):
        pass
    assert not shared.is_closed
    shared.close()

    with VertexEmbeddingClient(
        project_id=PROJECT,
        model=MODEL,
        dimensions=DIMENSIONS,
        service_account_json=service_account_json,
    ) as owned:
        http = owned._http
    assert http.is_closed


def test_failure_cancels_queued_requests_before_slow_first_result(
    service_account_json: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """第二筆先失敗時，不等第一筆慢回覆才取消後面尚未開始的請求。"""
    import app.integrations.vertex_embedding as module

    monkeypatch.setattr(module, "MAX_CONCURRENCY", 2)
    failed = threading.Event()
    started: list[int] = []
    lock = threading.Lock()

    def embed(request: httpx.Request) -> httpx.Response:
        index = int(sent_text(request).rsplit(" ", 1)[-1])
        with lock:
            started.append(index)
        if index == 0:
            assert failed.wait(2)
            time.sleep(0.08)
        elif index == 1:
            failed.set()
            return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}})
        return embed_ok(request)

    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, FakeGoogle(embed)).embed_texts(
            [str(index) for index in range(24)]
        )
    assert caught.value.code == "embedding_quota_exceeded"
    assert set(started) <= {0, 1}


@pytest.mark.parametrize("stage", ["http", "parse"])
def test_late_success_cannot_escape_total_budget(
    service_account_json: str, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """HTTP 回覆或解析完成已超過總預算，都不能以成功向量回傳。"""
    import app.integrations.vertex_embedding as module

    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    def embed(request: httpx.Request) -> httpx.Response:
        if stage == "http":
            clock[0] = 102.0
        return embed_ok(request)

    parse = module._parse_vector

    def slow_parse(response: httpx.Response, dimensions: int) -> tuple[float, ...]:
        value = parse(response, dimensions)
        if stage == "parse":
            clock[0] = 102.0
        return value

    monkeypatch.setattr(module, "_parse_vector", slow_parse)
    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, FakeGoogle(embed)).embed_texts(
            ["合成文字"], timeout_seconds=1
        )
    assert caught.value.code == "embedding_timeout"


def test_token_lock_wait_respects_budget(service_account_json: str) -> None:
    """同一 client 的權杖鎖競爭也受單次呼叫的時間預算限制。"""
    client = make_client(service_account_json, FakeGoogle())
    released = threading.Event()
    client._token_lock.acquire()

    def release() -> None:
        released.set()
        client._token_lock.release()

    timer = threading.Timer(0.25, release)
    timer.start()
    try:
        with pytest.raises(EmbeddingError) as caught:
            client.embed_texts(["合成文字"], timeout_seconds=0.01)
        assert caught.value.code == "embedding_timeout"
        assert not released.is_set()
    finally:
        timer.join()


@pytest.mark.parametrize("token", ["review-機密-token", "bad token", "bad\ttoken", "bad\x00token"])
def test_invalid_bearer_token_is_rejected_without_leaking(
    service_account_json: str, token: str
) -> None:
    """不合法的合成權杖在建立 Authorization 標頭之前拒絕。"""
    google = FakeGoogle()
    google.token_response = httpx.Response(200, json={"access_token": token, "expires_in": 3600})
    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, google).embed_texts(["合成文字"])
    assert caught.value.code == "embedding_auth_failed"
    assert token not in str(caught.value) + repr(caught.value) + caught.value.detail
    assert not google.embed_requests


def test_unknown_google_codes_cannot_echo_input_or_token(service_account_json: str) -> None:
    """status/reason 即使符合大寫格式，也不得把未核定字串當安全錯誤細節。"""
    marker = "REVIEW_SECRET_INPUT"
    token = "REVIEW_SECRET_TOKEN"
    google = FakeGoogle(
        lambda _: httpx.Response(
            400,
            json={"error": {"status": marker, "details": [{"reason": token}], "message": marker}},
        )
    )
    google.token_response = httpx.Response(200, json={"access_token": token})
    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, google).embed_texts([marker])
    exposed = str(caught.value) + repr(caught.value) + caught.value.detail
    assert marker not in exposed and token not in exposed
    assert caught.value.code == "embedding_invalid_input"


@pytest.mark.parametrize("token_uri", [[], {}, 123])
def test_malformed_token_uri_uses_fixed_configuration_error(
    service_account_json: str, token_uri: Any
) -> None:
    """JSON 欄位型別錯誤也應回固定設定錯誤，不洩漏底層例外。"""
    info = json.loads(service_account_json)
    info["token_uri"] = token_uri
    with pytest.raises(EmbeddingError) as caught:
        make_client(json.dumps(info), FakeGoogle())
    assert caught.value.code == "embedding_not_configured"


def test_huge_vector_component_fails_with_fixed_error(service_account_json: str) -> None:
    """超出浮點範圍的 JSON 整數不能變成未分類 OverflowError。"""
    google = FakeGoogle(
        lambda _: httpx.Response(200, json={"embedding": {"values": [10**400, 0, 0, 0]}})
    )
    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, google).embed_texts(["合成文字"])
    assert caught.value.code == "embedding_failed"


def test_huge_budget_is_rejected_before_any_request(service_account_json: str) -> None:
    """無法轉為有限秒數的整數預算在任何請求前拒絕。"""
    google = FakeGoogle()
    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, google).embed_texts(["合成文字"], timeout_seconds=10**400)
    assert caught.value.code == "embedding_timeout"
    assert not google.requests


@pytest.mark.parametrize("project,model", [(None, MODEL), (PROJECT, None), (123, MODEL)])
def test_nonstring_identifiers_are_not_configured(
    service_account_json: str, project: Any, model: Any
) -> None:
    """直接建構的識別值型別錯誤仍遵守固定錯誤介面。"""
    with pytest.raises(EmbeddingError) as caught:
        VertexEmbeddingClient(
            project_id=project,
            model=model,
            dimensions=DIMENSIONS,
            service_account_json=service_account_json,
        )
    assert caught.value.code == "embedding_not_configured"


@pytest.mark.parametrize("component", [math.inf, -math.inf])
def test_infinite_components_fail_closed(service_account_json: str, component: float) -> None:
    """Google 非標準 JSON 的正負無限值不能成為向量。"""
    body = json.dumps({"embedding": {"values": [0, 0, 0, component]}}).encode()
    google = FakeGoogle(lambda _: httpx.Response(200, content=body))
    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, google).embed_texts(["合成文字"])
    assert caught.value.code == "embedding_failed"


@pytest.mark.parametrize("stage", ["token", "embedding"])
def test_redirects_are_not_followed_even_by_injected_client(
    service_account_json: str, stage: str
) -> None:
    """外部 HTTP client 即使設定跟隨重新導向，模組仍不得跟隨。"""
    response = httpx.Response(302, headers={"Location": "https://synthetic.invalid/redirect"})
    google = FakeGoogle(lambda _: response if stage == "embedding" else embed_ok(_))
    if stage == "token":
        google.token_response = response
    client = make_client(service_account_json, google)
    client._http.follow_redirects = True
    with pytest.raises(EmbeddingError):
        client.embed_texts(["合成文字"])
    assert len(google.requests) == (1 if stage == "token" else 2)
    assert all(str(request.url) in {TOKEN_URI, EMBED_URL} for request in google.requests)


@pytest.mark.parametrize("task", [[], {}])
def test_nonstring_task_is_rejected_before_any_request(
    service_account_json: str, task: Any
) -> None:
    """未遵守 Literal 型別的呼叫也回固定輸入錯誤。"""
    google = FakeGoogle()
    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, google).embed_texts(["合成文字"], task=task)
    assert caught.value.code == "embedding_invalid_input"
    assert not google.requests


@pytest.mark.parametrize("field", ["text", "title"])
def test_invalid_unicode_does_not_escape_in_exception(
    service_account_json: str, field: str
) -> None:
    """不合法 Unicode 不得以含原文的 UnicodeEncodeError 逸出。"""
    marker = "REVIEW_SECRET\ud800"
    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, FakeGoogle()).embed_texts(
            [marker if field == "text" else "合成文字"], title=marker if field == "title" else None
        )
    assert caught.value.code == "embedding_invalid_input"
    assert marker not in repr(caught.value) + caught.value.detail


def test_unexpected_transport_exception_does_not_echo_input(service_account_json: str) -> None:
    """自訂 transport 的意外例外也不能把原文帶出公開錯誤介面。"""
    marker = "REVIEW_SECRET_INPUT"

    def embed(_: httpx.Request) -> httpx.Response:
        raise RuntimeError(marker)

    with pytest.raises(EmbeddingError) as caught:
        make_client(service_account_json, FakeGoogle(embed)).embed_texts([marker])
    assert caught.value.code == "embedding_failed"
    assert marker not in repr(caught.value) + caught.value.detail
