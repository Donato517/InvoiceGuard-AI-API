"""
模組名稱：tests.unit.test_groq
功能說明：Groq 模組的離線測試；以 httpx.MockTransport 模擬 Groq，Key 為合成值。
"""

import json
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.integrations.chat_models import ChatMessage
from app.integrations.groq import API_URL, GroqClient, GroqError

API_KEY = "gsk_synthetic-groq-key"
DEFAULT_MODEL = "openai/gpt-oss-20b"
ADVANCED_MODEL = "openai/gpt-oss-120b"
REPLY = {
    "model": DEFAULT_MODEL,
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": '{"invoice_number": "75670992"}',
                "reasoning": "synthetic reasoning",
            },
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52},
}


class FakeGroq:
    def __init__(self, response: httpx.Response | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.response = response or httpx.Response(200, json=REPLY)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response

    def body(self, index: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[index].content)


def make_client(handler: Any) -> GroqClient:
    return GroqClient(
        api_key=API_KEY,
        default_model=DEFAULT_MODEL,
        advanced_model=ADVANCED_MODEL,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


QUESTION = [ChatMessage("user", "請回傳 JSON")]


def test_chat_sends_openai_compatible_request_with_bearer_key() -> None:
    groq = FakeGroq()

    reply = make_client(groq).chat(
        [
            ChatMessage("user", "q1"),
            ChatMessage("model", "a1"),
            ChatMessage("user", "請回傳 JSON"),
        ],
        system_instruction="你是發票助手",
        purpose="recognition",
        json_output=True,
        max_tokens=500,
    )

    (request,) = groq.requests
    assert str(request.url) == API_URL
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    assert API_KEY not in str(request.url)
    body = groq.body()
    assert body["model"] == DEFAULT_MODEL
    assert body["messages"] == [
        {"role": "system", "content": "你是發票助手"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "請回傳 JSON"},
    ]
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_completion_tokens"] == 500

    assert reply.text == '{"invoice_number": "75670992"}'
    assert "synthetic reasoning" not in reply.text
    assert (reply.model, reply.finish_reason) == (DEFAULT_MODEL, "stop")
    assert (reply.prompt_tokens, reply.output_tokens, reply.total_tokens) == (40, 12, 52)
    assert "raw_response" not in repr(reply)


@pytest.mark.parametrize(
    "purpose,advanced,model",
    [
        ("default", False, DEFAULT_MODEL),
        ("recognition", False, DEFAULT_MODEL),
        ("default", True, ADVANCED_MODEL),
        ("recognition", True, ADVANCED_MODEL),
        ("rag", False, ADVANCED_MODEL),
        ("discussion", False, ADVANCED_MODEL),
    ],
)
def test_purpose_selects_20b_or_120b(purpose: Any, advanced: bool, model: str) -> None:
    groq = FakeGroq()
    client = make_client(groq)
    assert client.model_for(purpose, advanced=advanced) == model
    client.chat(QUESTION, purpose=purpose, advanced=advanced)
    assert groq.body()["model"] == model


def test_optional_fields_are_omitted_by_default() -> None:
    groq = FakeGroq()
    make_client(groq).chat(QUESTION)
    body = groq.body()
    assert body["messages"] == [{"role": "user", "content": "請回傳 JSON"}]
    assert "response_format" not in body
    assert "max_completion_tokens" not in body


@pytest.mark.parametrize(
    "kwargs",
    [
        {"messages": []},
        {"messages": [ChatMessage("user", "q"), ChatMessage("assistant", "a")]},
        {"messages": [ChatMessage("system", "q")]},
        {"messages": [ChatMessage("user", "  ")]},
        {"messages": QUESTION, "purpose": "translation"},
        {"messages": QUESTION, "max_tokens": 0},
    ],
)
def test_invalid_input_never_calls_groq(kwargs: dict[str, Any]) -> None:
    groq = FakeGroq()
    messages = kwargs.pop("messages")
    with pytest.raises(GroqError) as caught:
        make_client(groq).chat(messages, **kwargs)
    assert caught.value.code == "groq_invalid_input"
    assert groq.requests == []


@pytest.mark.parametrize(
    "changes", [{"api_key": ""}, {"default_model": "bad model"}, {"advanced_model": ""}]
)
def test_misconfiguration_is_not_configured(changes: dict[str, str]) -> None:
    values = {"api_key": API_KEY, "default_model": DEFAULT_MODEL, "advanced_model": ADVANCED_MODEL}
    with pytest.raises(GroqError) as caught:
        GroqClient(**(values | changes))
    assert caught.value.code == "groq_not_configured"


def test_from_settings_uses_20b_and_120b_defaults() -> None:
    client = GroqClient.from_settings(Settings(_env_prefix="IG_UNIT_TEST_", GROQ_API_KEY=API_KEY))
    assert client.model_for("default") == "openai/gpt-oss-20b"
    assert client.model_for("rag") == "openai/gpt-oss-120b"
    with pytest.raises(GroqError):
        GroqClient.from_settings(Settings(_env_prefix="IG_UNIT_TEST_"))


@pytest.mark.parametrize(
    "status,error,code,detail",
    [
        (
            401,
            {"type": "invalid_request_error", "code": "invalid_api_key"},
            "groq_auth_failed",
            "invalid_api_key",
        ),
        (
            400,
            {"type": "invalid_request_error", "code": "json_validate_failed"},
            "groq_invalid_input",
            "json_validate_failed",
        ),
        (
            404,
            {"type": "invalid_request_error", "code": "model_not_found"},
            "groq_not_found",
            "model_not_found",
        ),
        (
            403,
            {"type": "invalid_request_error", "code": "permission_denied"},
            "groq_denied",
            "permission_denied",
        ),
        (413, {"type": "invalid_request_error"}, "groq_invalid_input", "invalid_request_error"),
        (
            422,
            {"type": "invalid_request_error", "code": "unprocessable_entity"},
            "groq_invalid_input",
            "unprocessable_entity",
        ),
        (
            429,
            {"type": "tokens", "code": "rate_limit_exceeded"},
            "groq_quota_exceeded",
            "rate_limit_exceeded",
        ),
        (498, {"type": "capacity_exceeded"}, "groq_quota_exceeded", "capacity_exceeded"),
        (503, None, "groq_failed", "HTTP503"),
    ],
)
def test_groq_errors_map_to_fixed_codes(
    status: int, error: dict[str, Any] | None, code: str, detail: str
) -> None:
    body = {"error": error | {"message": f"synthetic message {API_KEY}"}} if error else {}
    with pytest.raises(GroqError) as caught:
        make_client(FakeGroq(httpx.Response(status, json=body))).chat(QUESTION)
    assert (caught.value.code, caught.value.detail) == (code, detail)
    assert API_KEY not in str(caught.value) + caught.value.detail


@pytest.mark.parametrize(
    "error",
    [
        # 巢狀物件／陣列：不能用 str() 把內含的 message 帶進 detail
        {"code": {"message": "synthetic nested message"}, "type": ["synthetic", "list"]},
        # 上游把 Key 回顯在 code：不得出現在 detail
        {"code": "gsk_synthetic_groq_key_echo"},
        {"code": API_KEY},
        # 長字串或含空白、大寫：不是 Groq 短代碼
        {"code": "x" * 65},
        {"code": "Rate Limit Exceeded for org 123"},
        "synthetic plain error string",
    ],
)
def test_unexpected_error_fields_never_reach_detail(error: Any) -> None:
    client = GroqClient(
        api_key="gsk_synthetic_groq_key_echo",
        default_model=DEFAULT_MODEL,
        advanced_model=ADVANCED_MODEL,
        http=httpx.Client(
            transport=httpx.MockTransport(FakeGroq(httpx.Response(429, json={"error": error})))
        ),
    )
    with pytest.raises(GroqError) as caught:
        client.chat(QUESTION)
    assert caught.value.code == "groq_quota_exceeded"
    assert caught.value.detail == "HTTP429"


@pytest.mark.parametrize(
    "body,detail",
    [
        ({"choices": []}, "NoChoice"),
        ({"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}, "length"),
        ({"choices": [{"message": {"content": None}}]}, "EmptyReply"),
    ],
)
def test_empty_replies_raise(body: dict[str, Any], detail: str) -> None:
    with pytest.raises(GroqError) as caught:
        make_client(FakeGroq(httpx.Response(200, json=body))).chat(QUESTION)
    assert (caught.value.code, caught.value.detail) == ("groq_failed", detail)


@pytest.mark.parametrize(
    "exception,code",
    [
        (httpx.ReadTimeout("synthetic"), "groq_timeout"),
        (httpx.ConnectError("synthetic"), "groq_unreachable"),
    ],
)
def test_timeouts_and_network_errors_have_fixed_codes(exception: Exception, code: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception

    with pytest.raises(GroqError) as caught:
        make_client(handler).chat(QUESTION)
    assert caught.value.code == code
