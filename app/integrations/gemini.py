"""
模組名稱：app.integrations.gemini
功能說明：Google Gemini 模組（對話）——以 API Key 呼叫 generateContent，傳入多輪訊息、取得回答。
使用方式：
    from app.integrations.gemini import ChatMessage, GeminiClient
    reply = GeminiClient.from_settings().chat(
        [ChatMessage("user", "三聯式發票申報期限？")], system_instruction="你是發票稅務助手"
    )
    reply.text、reply.finish_reason、reply.total_tokens
注意事項：
    - 設定來自 GEMINI_API_KEY 與 GEMINI_MODEL（預設 gemini-3.8-flash）；本機由 START 注入 Key。
    - API Key 只放在 x-goog-api-key 標頭，不放網址；錯誤 detail 只放 Google 的 status／reason。
    - 訊息角色接受 user／model，assistant 視同 model（對應知識庫問答契約的 history）。
    - 只負責呼叫與解析；送出內容的遮罩、知識庫檢索與問答紀錄由上層 service 決定。
"""

import re
from collections.abc import Sequence
from typing import Any, Literal

import httpx

from app.core.config import Settings, settings
from app.integrations.chat_models import ChatMessage, ChatReply

PROVIDER = "google_gemini"
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
# Vercel 函式上限 60 秒，保留回應處理時間
CHAT_TIMEOUT = httpx.Timeout(45.0, connect=10.0)
# 這些結束原因代表內容被安全機制擋下
BLOCKED_FINISH_REASONS = frozenset(
    {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY"}
)
_ROLES = {"user": "user", "model": "model", "assistant": "model"}

GeminiCode = Literal[
    "gemini_not_configured",
    "gemini_invalid_input",
    "gemini_auth_failed",
    "gemini_denied",
    "gemini_not_found",
    "gemini_quota_exceeded",
    "gemini_blocked",
    "gemini_timeout",
    "gemini_unreachable",
    "gemini_failed",
]


class GeminiError(RuntimeError):
    """Gemini 呼叫失敗；code 為固定代碼，detail 只放 Google 的 status／reason 或擋下原因。"""

    def __init__(self, code: GeminiCode, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


class GeminiClient:
    """Gemini generateContent 用戶端（REST）。"""

    def __init__(self, *, api_key: str, model: str, http: httpx.Client | None = None) -> None:
        api_key, model = api_key.strip(), model.strip()
        if not api_key or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", model):
            raise GeminiError("gemini_not_configured")
        self._api_key = api_key
        self._model = model
        self._http = http or httpx.Client(follow_redirects=False)

    @classmethod
    def from_settings(cls, configuration: Settings | None = None) -> "GeminiClient":
        """以 GEMINI_API_KEY 與 GEMINI_MODEL 建立用戶端。

        Raises:
            GeminiError: gemini_not_configured——Key 空白或模型名稱格式不符。
        """
        configuration = configuration if configuration is not None else settings
        return cls(
            api_key=configuration.GEMINI_API_KEY.get_secret_value(),
            model=configuration.GEMINI_MODEL,
        )

    @property
    def model(self) -> str:
        """目前使用的模型名稱。"""
        return self._model

    def chat(
        self, messages: Sequence[ChatMessage], *, system_instruction: str | None = None
    ) -> ChatReply:
        """送出多輪對話，取得模型回答。

        Args:
            messages: 依時間排序的訊息；最後一則必須是 user。
            system_instruction: 系統指示（角色、語氣、回答範圍），不需要時為 None。

        Returns:
            ChatReply: 回答文字、模型、結束原因與 token 用量。

        Raises:
            GeminiError: 輸入無效、Key 無效、權限或配額不足、內容被擋下、逾時、無法連線或服務錯誤。
        """
        if (
            not messages
            or any(message.role not in _ROLES or not message.text.strip() for message in messages)
            or _ROLES[messages[-1].role] != "user"
        ):
            raise GeminiError("gemini_invalid_input")
        body: dict[str, Any] = {
            "contents": [
                {"role": _ROLES[message.role], "parts": [{"text": message.text}]}
                for message in messages
            ]
        }
        if system_instruction and system_instruction.strip():
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        try:
            response = self._http.post(
                f"{API_BASE}/{self._model}:generateContent",
                json=body,
                headers={"x-goog-api-key": self._api_key},
                timeout=CHAT_TIMEOUT,
            )
        except httpx.TimeoutException:
            raise GeminiError("gemini_timeout") from None
        except httpx.HTTPError:
            raise GeminiError("gemini_unreachable") from None
        if not response.is_success:
            status, reasons = _google_error(response)
            raise GeminiError(
                _error_code(response.status_code, status, reasons), "/".join([status, *reasons])
            )
        try:
            data = response.json()
        except ValueError:
            raise GeminiError("gemini_failed", "InvalidJson") from None
        if not isinstance(data, dict):
            raise GeminiError("gemini_failed", "InvalidJson")
        return _parse_reply(data, self._model)


# Google 錯誤 status 優先於 HTTP 狀態碼：預付額度用完時回 402＋RESOURCE_EXHAUSTED
_STATUS_CODES: dict[str, GeminiCode] = {
    "UNAUTHENTICATED": "gemini_auth_failed",
    "PERMISSION_DENIED": "gemini_denied",
    "NOT_FOUND": "gemini_not_found",
    "RESOURCE_EXHAUSTED": "gemini_quota_exceeded",
    "INVALID_ARGUMENT": "gemini_invalid_input",
}
_HTTP_CODES: dict[int, GeminiCode] = {
    400: "gemini_invalid_input",
    401: "gemini_auth_failed",
    402: "gemini_quota_exceeded",
    403: "gemini_denied",
    404: "gemini_not_found",
    429: "gemini_quota_exceeded",
}


def _error_code(http_status: int, google_status: str, reasons: list[str]) -> GeminiCode:
    # Key 無效時 Google 回 400 INVALID_ARGUMENT，reason 為 API_KEY_INVALID
    if "API_KEY_INVALID" in reasons:
        return "gemini_auth_failed"
    return _STATUS_CODES.get(google_status) or _HTTP_CODES.get(http_status, "gemini_failed")


def _google_error(response: httpx.Response) -> tuple[str, list[str]]:
    """只取 Google 錯誤的 status 與 reason；不是大寫短代碼的內容（巢狀物件、長字串）一律不帶出。"""
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        error = None
    if not isinstance(error, dict):
        return f"HTTP{response.status_code}", []
    details = error.get("details")
    reasons = (
        [
            item["reason"]
            for item in details
            if isinstance(item, dict) and _is_google_code(item.get("reason"))
        ]
        if isinstance(details, list)
        else []
    )
    status = error.get("status")
    return (status if _is_google_code(status) else f"HTTP{response.status_code}"), reasons


# Google 的 status／reason 為大寫英數底線（如 RESOURCE_EXHAUSTED、API_KEY_INVALID）
_GOOGLE_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


def _is_google_code(value: Any) -> bool:
    return isinstance(value, str) and _GOOGLE_CODE.fullmatch(value) is not None


def _token_count(usage: dict[str, Any], name: str) -> int | None:
    value = usage.get(name)
    return value if isinstance(value, int) else None


def _parse_reply(data: dict[str, Any], model: str) -> ChatReply:
    block_reason = data.get("promptFeedback", {}).get("blockReason")
    if block_reason:
        raise GeminiError("gemini_blocked", str(block_reason))
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        raise GeminiError("gemini_failed", "NoCandidate")
    candidate = candidates[0]
    finish_reason = str(candidate.get("finishReason", ""))
    parts = candidate.get("content", {}).get("parts", [])
    # 思考過程（thought）不屬於回答內容
    text = "".join(
        str(part.get("text", ""))
        for part in parts
        if isinstance(part, dict) and not part.get("thought")
    )
    if not text.strip():
        if finish_reason in BLOCKED_FINISH_REASONS:
            raise GeminiError("gemini_blocked", finish_reason)
        raise GeminiError("gemini_failed", finish_reason or "EmptyReply")
    usage = data.get("usageMetadata", {})
    usage = usage if isinstance(usage, dict) else {}
    return ChatReply(
        text=text,
        model=str(data.get("modelVersion") or model),
        finish_reason=finish_reason,
        prompt_tokens=_token_count(usage, "promptTokenCount"),
        output_tokens=_token_count(usage, "candidatesTokenCount"),
        total_tokens=_token_count(usage, "totalTokenCount"),
        raw_response=data,
    )
