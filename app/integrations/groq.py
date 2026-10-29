"""
模組名稱：app.integrations.groq
功能說明：Groq 模組（對話）——以 OpenAI 相容的 chat.completions 呼叫 gpt-oss 模型，依情境選擇 20B 或 120B。
使用方式：
    from app.integrations.chat_models import ChatMessage
    from app.integrations.groq import GroqClient
    client = GroqClient.from_settings()
    reply = client.chat([ChatMessage("user", "...")], purpose="recognition", json_output=True)
    reply = client.chat([ChatMessage("user", "...")], purpose="rag")          # 120B
    reply = client.chat([ChatMessage("user", "...")], advanced=True)          # 預設情境改用 120B
注意事項：
    - 情境（2026-10-28 使用者核定）：default、recognition（識別）用 GROQ_DEFAULT_MODEL（20B），
      需要時以 advanced=True 改用 GROQ_ADVANCED_MODEL（120B，進階備用）；rag、discussion（討論）用 120B。
    - 設定來自 GROQ_API_KEY、GROQ_DEFAULT_MODEL、GROQ_ADVANCED_MODEL；Key 只放 Authorization 標頭。
    - json_output=True 會要求模型只回 JSON 物件；訊息中須明確要求 JSON 格式。
    - 只負責呼叫與解析；提示詞、欄位整理與紀錄由上層 service 決定。錯誤 detail 只放 Groq 的錯誤 code／type。
"""

import re
from collections.abc import Sequence
from typing import Any, Literal

import httpx

from app.core.config import Settings, settings
from app.integrations.chat_models import ChatMessage, ChatReply

PROVIDER = "groq"
API_URL = "https://api.groq.com/openai/v1/chat/completions"
# Vercel 函式上限 60 秒，保留回應處理時間
CHAT_TIMEOUT = httpx.Timeout(45.0, connect=10.0)

ChatPurpose = Literal["default", "recognition", "rag", "discussion"]
# 使用進階模型（120B）的情境；其他情境預設 20B
ADVANCED_PURPOSES = frozenset({"rag", "discussion"})
_PURPOSES = frozenset({"default", "recognition", "rag", "discussion"})
_ROLES = {"user": "user", "assistant": "assistant", "model": "assistant"}
# 錯誤 detail 只放 Groq 的短代碼（如 rate_limit_exceeded），避免上游異常內容或 Key 回顯
_SAFE_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")

GroqCode = Literal[
    "groq_not_configured",
    "groq_invalid_input",
    "groq_auth_failed",
    "groq_denied",
    "groq_not_found",
    "groq_quota_exceeded",
    "groq_timeout",
    "groq_unreachable",
    "groq_failed",
]


class GroqError(RuntimeError):
    """Groq 呼叫失敗；code 為固定代碼，detail 只放 Groq 錯誤的 code 或 type。"""

    def __init__(self, code: GroqCode, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


class GroqClient:
    """Groq chat.completions 用戶端（OpenAI 相容 REST）。"""

    def __init__(
        self,
        *,
        api_key: str,
        default_model: str,
        advanced_model: str,
        http: httpx.Client | None = None,
    ) -> None:
        api_key, default_model, advanced_model = (
            value.strip() for value in (api_key, default_model, advanced_model)
        )
        if not api_key or not all(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", model)
            for model in (default_model, advanced_model)
        ):
            raise GroqError("groq_not_configured")
        self._api_key = api_key
        self._default_model = default_model
        self._advanced_model = advanced_model
        self._http = http or httpx.Client(follow_redirects=False)

    @classmethod
    def from_settings(cls, configuration: Settings | None = None) -> "GroqClient":
        """以 GROQ_API_KEY、GROQ_DEFAULT_MODEL、GROQ_ADVANCED_MODEL 建立用戶端。

        Raises:
            GroqError: groq_not_configured——Key 空白或模型名稱格式不符。
        """
        configuration = configuration if configuration is not None else settings
        return cls(
            api_key=configuration.GROQ_API_KEY.get_secret_value(),
            default_model=configuration.GROQ_DEFAULT_MODEL,
            advanced_model=configuration.GROQ_ADVANCED_MODEL,
        )

    def model_for(self, purpose: ChatPurpose = "default", *, advanced: bool = False) -> str:
        """依情境回傳模型：rag／discussion 或 advanced=True 用進階模型，其他用預設模型。

        Raises:
            GroqError: groq_invalid_input——不支援的情境。
        """
        if purpose not in _PURPOSES:
            raise GroqError("groq_invalid_input")
        return (
            self._advanced_model
            if advanced or purpose in ADVANCED_PURPOSES
            else self._default_model
        )

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        system_instruction: str | None = None,
        purpose: ChatPurpose = "default",
        advanced: bool = False,
        json_output: bool = False,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> ChatReply:
        """送出多輪對話，取得模型回答。

        Args:
            messages: 依時間排序的訊息；最後一則必須是 user。
            system_instruction: 系統指示，不需要時為 None。
            purpose: 情境；default、recognition 用預設模型，rag、discussion 用進階模型。
            advanced: True 時不論情境都改用進階模型（120B）。
            json_output: True 時要求模型只回 JSON 物件（訊息中須要求 JSON）。
            max_tokens: 回答 token 上限；None 由模型決定。
            timeout_seconds: 呼叫端剩餘的秒數；None 使用預設（45 秒），不會超過預設。

        Returns:
            ChatReply: 回答文字（不含推理過程）、實際模型、結束原因與 token 用量。

        Raises:
            GroqError: 輸入無效、Key 無效、權限或用量限制、逾時、無法連線或服務錯誤。
        """
        model = self.model_for(purpose, advanced=advanced)
        if timeout_seconds is not None and not timeout_seconds > 0:
            raise GroqError("groq_timeout", "NoTimeLeft")
        if (
            not messages
            or any(message.role not in _ROLES or not message.text.strip() for message in messages)
            or _ROLES[messages[-1].role] != "user"
            or (max_tokens is not None and max_tokens < 1)
        ):
            raise GroqError("groq_invalid_input")
        payload_messages = [
            {"role": _ROLES[message.role], "content": message.text} for message in messages
        ]
        if system_instruction and system_instruction.strip():
            payload_messages.insert(0, {"role": "system", "content": system_instruction})
        body: dict[str, Any] = {"model": model, "messages": payload_messages}
        if json_output:
            body["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            body["max_completion_tokens"] = max_tokens
        try:
            response = self._http.post(
                API_URL,
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=_bounded_timeout(timeout_seconds),
            )
        except httpx.TimeoutException:
            raise GroqError("groq_timeout") from None
        except httpx.HTTPError:
            raise GroqError("groq_unreachable") from None
        if not response.is_success:
            raise GroqError(
                _error_code(response.status_code), _error_detail(response, self._api_key)
            )
        try:
            data = response.json()
        except ValueError:
            raise GroqError("groq_failed", "InvalidJson") from None
        if not isinstance(data, dict):
            raise GroqError("groq_failed", "InvalidJson")
        return _parse_reply(data, model)


def _bounded_timeout(seconds: float | None) -> httpx.Timeout:
    """呼叫端剩餘秒數與預設逾時（CHAT_TIMEOUT）取較小者。"""
    if seconds is None:
        return CHAT_TIMEOUT
    read = min(seconds, CHAT_TIMEOUT.read or seconds)
    return httpx.Timeout(read, connect=min(read, CHAT_TIMEOUT.connect or read))


_HTTP_CODES: dict[int, GroqCode] = {
    400: "groq_invalid_input",
    401: "groq_auth_failed",
    403: "groq_denied",
    404: "groq_not_found",
    413: "groq_invalid_input",
    422: "groq_invalid_input",
    429: "groq_quota_exceeded",
    # Groq：498 為 Flex 方案容量不足
    498: "groq_quota_exceeded",
}


def _error_code(status: int) -> GroqCode:
    return _HTTP_CODES.get(status, "groq_failed")


def _error_detail(response: httpx.Response, api_key: str) -> str:
    """只取 Groq 錯誤的 code（例如 invalid_api_key、json_validate_failed）或 type。

    只接受小寫英數底線的短代碼，且不得含 Key；巢狀物件、陣列、長字串或其他內容一律改回 HTTP 狀態碼。
    """
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        error = None
    if isinstance(error, dict):
        for name in ("code", "type"):
            value = error.get(name)
            if isinstance(value, str) and _SAFE_CODE.fullmatch(value) and api_key not in value:
                return value
    return f"HTTP{response.status_code}"


def _token_count(usage: dict[str, Any], name: str) -> int | None:
    value = usage.get(name)
    return value if isinstance(value, int) else None


def _parse_reply(data: dict[str, Any], model: str) -> ChatReply:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise GroqError("groq_failed", "NoChoice")
    choice = choices[0]
    finish_reason = str(choice.get("finish_reason") or "")
    message = choice.get("message")
    # gpt-oss 的推理過程在 message.reasoning，不屬於回答內容
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise GroqError("groq_failed", finish_reason or "EmptyReply")
    usage = data.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    return ChatReply(
        text=text,
        model=str(data.get("model") or model),
        finish_reason=finish_reason,
        prompt_tokens=_token_count(usage, "prompt_tokens"),
        output_tokens=_token_count(usage, "completion_tokens"),
        total_tokens=_token_count(usage, "total_tokens"),
        raw_response=data,
    )
