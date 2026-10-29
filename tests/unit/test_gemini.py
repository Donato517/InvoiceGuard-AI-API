"""
模組名稱：tests.unit.test_gemini
功能說明：Google Gemini 模組的離線測試；以 httpx.MockTransport 模擬 Google，Key 為合成值。
"""

import json
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.integrations.gemini import API_BASE, ChatMessage, GeminiClient, GeminiError

API_KEY = "synthetic-gemini-key"
REPLY = {
    "candidates": [
        {
            "content": {
                "role": "model",
                "parts": [
                    {"text": "synthetic thinking", "thought": True},
                    {"text": "三聯式發票"},
                    {"text": "每兩個月申報一次。"},
                ],
            },
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 8, "totalTokenCount": 30},
    "modelVersion": "gemini-3.8-flash",
}


class FakeGemini:
    def __init__(self, response: httpx.Response | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.response = response or httpx.Response(200, json=REPLY)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response


def make_client(handler: Any, *, model: str = "gemini-3.8-flash") -> GeminiClient:
    return GeminiClient(
        api_key=API_KEY, model=model, http=httpx.Client(transport=httpx.MockTransport(handler))
    )


def ask(handler: Any) -> Any:
    return make_client(handler).chat(
        [
            ChatMessage("user", "申報期限？"),
            ChatMessage("assistant", "請問是哪一種發票？"),
            ChatMessage("user", "三聯式"),
        ],
        system_instruction="你是發票稅務助手",
    )


def test_chat_sends_history_with_key_in_header_only() -> None:
    gemini = FakeGemini()

    reply = ask(gemini)

    (request,) = gemini.requests
    assert str(request.url) == f"{API_BASE}/gemini-3.8-flash:generateContent"
    assert API_KEY not in str(request.url)
    assert request.headers["x-goog-api-key"] == API_KEY
    body = json.loads(request.content)
    assert body["contents"] == [
        {"role": "user", "parts": [{"text": "申報期限？"}]},
        {"role": "model", "parts": [{"text": "請問是哪一種發票？"}]},
        {"role": "user", "parts": [{"text": "三聯式"}]},
    ]
    assert body["systemInstruction"] == {"parts": [{"text": "你是發票稅務助手"}]}

    assert reply.text == "三聯式發票每兩個月申報一次。"
    assert reply.model == "gemini-3.8-flash"
    assert reply.finish_reason == "STOP"
    assert (reply.prompt_tokens, reply.output_tokens, reply.total_tokens) == (12, 8, 30)
    assert reply.raw_response == REPLY
    assert "raw_response" not in repr(reply)


def test_system_instruction_is_optional() -> None:
    gemini = FakeGemini()
    make_client(gemini).chat([ChatMessage("user", "hi")])
    assert "systemInstruction" not in json.loads(gemini.requests[0].content)


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [ChatMessage("user", "q"), ChatMessage("model", "a")],
        [ChatMessage("system", "q")],
        [ChatMessage("user", "   ")],
    ],
)
def test_invalid_messages_never_call_google(messages: list[ChatMessage]) -> None:
    gemini = FakeGemini()
    with pytest.raises(GeminiError) as caught:
        make_client(gemini).chat(messages)
    assert caught.value.code == "gemini_invalid_input"
    assert gemini.requests == []


@pytest.mark.parametrize("api_key,model", [("", "gemini-3.8-flash"), (API_KEY, "Gemini 2.5!")])
def test_misconfiguration_is_not_configured(api_key: str, model: str) -> None:
    with pytest.raises(GeminiError) as caught:
        GeminiClient(api_key=api_key, model=model)
    assert caught.value.code == "gemini_not_configured"


def test_from_settings_uses_key_and_default_model() -> None:
    client = GeminiClient.from_settings(
        Settings(_env_prefix="IG_UNIT_TEST_", GEMINI_API_KEY=API_KEY)
    )
    assert client.model == "gemini-3.8-flash"
    custom = GeminiClient.from_settings(
        Settings(_env_prefix="IG_UNIT_TEST_", GEMINI_API_KEY=API_KEY, GEMINI_MODEL="gemini-x")
    )
    assert custom.model == "gemini-x"
    with pytest.raises(GeminiError):
        GeminiClient.from_settings(Settings(_env_prefix="IG_UNIT_TEST_"))


@pytest.mark.parametrize(
    "status,error,code",
    [
        (
            400,
            {"status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]},
            "gemini_auth_failed",
        ),
        (400, {"status": "INVALID_ARGUMENT"}, "gemini_invalid_input"),
        (403, {"status": "PERMISSION_DENIED"}, "gemini_denied"),
        (404, {"status": "NOT_FOUND"}, "gemini_not_found"),
        (429, {"status": "RESOURCE_EXHAUSTED"}, "gemini_quota_exceeded"),
        # 2026-10-28 實測：預付額度用完時 Google 回 402＋RESOURCE_EXHAUSTED
        (402, {"status": "RESOURCE_EXHAUSTED"}, "gemini_quota_exceeded"),
        (500, {"status": "PERMISSION_DENIED"}, "gemini_denied"),
        (503, {"status": "UNAVAILABLE"}, "gemini_failed"),
    ],
)
def test_google_errors_map_to_fixed_codes(status: int, error: dict[str, Any], code: str) -> None:
    error = error | {"message": f"synthetic message {API_KEY}"}
    with pytest.raises(GeminiError) as caught:
        ask(FakeGemini(httpx.Response(status, json={"error": error})))
    assert caught.value.code == code
    assert caught.value.detail.startswith(error["status"])
    assert API_KEY not in str(caught.value) + caught.value.detail


@pytest.mark.parametrize(
    "body,code,detail",
    [
        ({"promptFeedback": {"blockReason": "SAFETY"}}, "gemini_blocked", "SAFETY"),
        (
            {"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]},
            "gemini_blocked",
            "SAFETY",
        ),
        (
            {"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]},
            "gemini_failed",
            "STOP",
        ),
        ({"candidates": []}, "gemini_failed", "NoCandidate"),
    ],
)
def test_blocked_or_empty_replies_raise(body: dict[str, Any], code: str, detail: str) -> None:
    with pytest.raises(GeminiError) as caught:
        ask(FakeGemini(httpx.Response(200, json=body)))
    assert (caught.value.code, caught.value.detail) == (code, detail)


@pytest.mark.parametrize(
    "exception,code",
    [
        (httpx.ReadTimeout("synthetic"), "gemini_timeout"),
        (httpx.ConnectError("synthetic"), "gemini_unreachable"),
    ],
)
def test_timeouts_and_network_errors_have_fixed_codes(exception: Exception, code: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception

    with pytest.raises(GeminiError) as caught:
        ask(handler)
    assert caught.value.code == code


@pytest.mark.parametrize(
    "error",
    [
        # 巢狀物件／陣列與非代碼字串：不能用 str() 帶進 detail
        {
            "status": {"message": "synthetic nested message"},
            "details": [{"reason": ["synthetic"]}, {"reason": "API key synthetic leak"}],
        },
        {"status": "x" * 65},
        {"status": "Quota exceeded for project 123"},
        {"status": "RESOURCE_EXHAUSTED", "details": "SYNTHETIC_NOT_A_LIST"},
    ],
)
def test_unexpected_google_error_fields_never_reach_detail(error: dict[str, Any]) -> None:
    with pytest.raises(GeminiError) as caught:
        ask(FakeGemini(httpx.Response(429, json={"error": error})))
    assert caught.value.code == "gemini_quota_exceeded"
    assert caught.value.detail in {"HTTP429", "RESOURCE_EXHAUSTED"}
