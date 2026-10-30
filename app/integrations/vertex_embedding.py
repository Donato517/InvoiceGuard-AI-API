"""
模組名稱：app.integrations.vertex_embedding
功能說明：Google 向量模組——以服務帳號呼叫 Agent Platform（原 Vertex AI）的 embedContent，把文字轉成向量。
使用方式：
    from app.integrations.vertex_embedding import VertexEmbeddingClient
    with VertexEmbeddingClient.from_settings() as client:
        batch = client.embed_texts(chunks, task="document", title="營業稅規定", timeout_seconds=20)
        query = client.embed_texts(["進項稅額可以扣抵嗎"], task="query", timeout_seconds=5)
    batch.vectors、batch.model、batch.dimensions
注意事項：
    - 設定來自 GOOGLE_CLOUD_PROJECT_ID、GOOGLE_SERVICE_ACCOUNT_JSON、VERTEX_EMBEDDING_MODEL、
      VERTEX_EMBEDDING_DIMENSIONS；服務帳號需有 Agent Platform User（roles/aiplatform.user）。
      不使用 GEMINI_API_KEY。
    - Claude 於 2026-10-30 回報本專案不能用 batchEmbedContents 與 predict（本輪僅離線檢驗）；
      多筆文字以併發 embedContent 處理。
    - autoTruncate 固定 false：超過模型上限回 embedding_invalid_input，不默默截斷。
    - 文件與查詢的前綴由 task 決定，呼叫端傳原文即可。換模型或維度須全部重算，不可與舊向量混用。
    - 一筆失敗即整批失敗，不回傳部分結果，也不自動重試；只負責呼叫與解析，不寫 DB。
"""

import json
import math
import re
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.core.config import Settings, settings

PROVIDER = "google_vertex_ai"
API_BASE = "https://aiplatform.googleapis.com/v1"
LOCATION = "global"
TOKEN_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
# Claude 於 2026-10-30 回報 8 條併發成功；本輪不驗證雲端配額
MAX_CONCURRENCY = 8
# 呼叫端未傳 timeout_seconds 時的總預算；低於兩站函式上限（ADMIN 30 秒、API 60 秒）
DEFAULT_TIMEOUT_SECONDS = 25.0
EMBED_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
TOKEN_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
TOKEN_REFRESH_MARGIN_SECONDS = 60
_ALLOWED_TOKEN_URLS = frozenset(
    {
        "https://oauth2.googleapis.com/token",
        "https://accounts.google.com/o/oauth2/token",
        "https://www.googleapis.com/oauth2/v4/token",
    }
)

EmbeddingTask = Literal["document", "query"]
_TASKS = frozenset({"document", "query"})

EmbeddingCode = Literal[
    "embedding_not_configured",
    "embedding_invalid_input",
    "embedding_auth_failed",
    "embedding_denied",
    "embedding_not_found",
    "embedding_quota_exceeded",
    "embedding_timeout",
    "embedding_unreachable",
    "embedding_failed",
]


class EmbeddingError(RuntimeError):
    """向量呼叫失敗；code 為固定代碼，detail 只放 Google 的 status／reason，不含文字或權杖。"""

    def __init__(self, code: EmbeddingCode, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


@dataclass(frozen=True)
class EmbeddingBatch:
    """向量結果；vectors 與輸入文字順序相同。"""

    vectors: tuple[tuple[float, ...], ...]
    model: str
    dimensions: int


class VertexEmbeddingClient:
    """Agent Platform embedContent 用戶端（REST）。自行建立的 HTTP 用戶端由本物件關閉。"""

    def __init__(
        self,
        *,
        project_id: str,
        model: str,
        dimensions: int,
        service_account_json: str,
        http: httpx.Client | None = None,
    ) -> None:
        if not isinstance(project_id, str) or not isinstance(model, str):
            raise EmbeddingError("embedding_not_configured")
        project_id, model = project_id.strip(), model.strip()
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9-]*", project_id)
            or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", model)
            or type(dimensions) is not int
            or dimensions < 1
        ):
            raise EmbeddingError("embedding_not_configured")
        self._info = _service_account_info(service_account_json)
        self._url = (
            f"{API_BASE}/projects/{project_id}/locations/{LOCATION}"
            f"/publishers/google/models/{model}:embedContent"
        )
        self._model = model
        self._dimensions = dimensions
        self._owns_http = http is None
        self._http = http if http is not None else httpx.Client(follow_redirects=False)
        self._token: tuple[str, float] | None = None
        self._token_lock = threading.Lock()

    @classmethod
    def from_settings(cls, configuration: Settings | None = None) -> "VertexEmbeddingClient":
        """以專案、服務帳號與向量模型設定建立用戶端。

        Raises:
            EmbeddingError: embedding_not_configured——專案、模型或服務帳號不合法。
        """
        configuration = configuration if configuration is not None else settings
        return cls(
            project_id=configuration.GOOGLE_CLOUD_PROJECT_ID,
            model=configuration.VERTEX_EMBEDDING_MODEL,
            dimensions=configuration.VERTEX_EMBEDDING_DIMENSIONS,
            service_account_json=configuration.GOOGLE_SERVICE_ACCOUNT_JSON.get_secret_value(),
        )

    @property
    def model(self) -> str:
        """目前使用的模型名稱。"""
        return self._model

    @property
    def dimensions(self) -> int:
        """回傳向量的維度。"""
        return self._dimensions

    def close(self) -> None:
        """關閉自行建立的 HTTP 用戶端；外部傳入的由呼叫端管理。"""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> "VertexEmbeddingClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        task: EmbeddingTask = "document",
        title: str | None = None,
        timeout_seconds: float | None = None,
    ) -> EmbeddingBatch:
        """把多筆文字轉成向量，順序與輸入相同。

        Args:
            texts: 原文；不可為空，每筆不可空白。
            task: document（文件段落）或 query（使用者問題）。
            title: 文件標題，只用於 document；None 時依 Google 規定使用 none。
            timeout_seconds: 含取得權杖的總秒數；None 使用預設（25 秒）。

        Returns:
            EmbeddingBatch: 向量、模型名稱與維度。

        Raises:
            EmbeddingError: 輸入無效、超過模型上限、權限或配額不足、逾時、無法連線或服務錯誤。
        """
        prompts = _prompts(texts, task, title)
        deadline = time.monotonic() + _budget(timeout_seconds)
        token = self._access_token(deadline)
        stopped = threading.Event()
        failure_lock = threading.Lock()
        failures: list[BaseException] = []

        def embed(text: str) -> tuple[float, ...]:
            """失敗在 worker 內發出停止訊號，佇列後續工作不再送出 HTTP。"""
            if stopped.is_set():
                return ()
            try:
                return self._embed_one(text, token, deadline)
            except BaseException as exc:
                with failure_lock:
                    if not failures:
                        failures.append(exc)
                    stopped.set()
                raise

        vectors: list[tuple[float, ...]] = [()] * len(prompts)
        with ThreadPoolExecutor(max_workers=min(MAX_CONCURRENCY, len(prompts))) as pool:
            futures = {}
            for index, text in enumerate(prompts):
                if stopped.is_set():
                    break
                futures[pool.submit(embed, text)] = index
            try:
                for future in as_completed(futures):
                    if failures:
                        raise failures[0]
                    vectors[futures[future]] = future.result()
                if failures:
                    raise failures[0]
                _remaining_seconds(deadline)
            except BaseException:
                stopped.set()
                for future in futures:
                    future.cancel()
                raise
        return EmbeddingBatch(
            vectors=tuple(vectors), model=self._model, dimensions=self._dimensions
        )

    def _embed_one(self, text: str, token: str, deadline: float) -> tuple[float, ...]:
        response = _send(
            self._http,
            self._url,
            json={
                "content": {"role": "user", "parts": [{"text": text}]},
                "outputDimensionality": self._dimensions,
                "autoTruncate": False,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=_remaining_timeout(EMBED_TIMEOUT, deadline),
            deadline=deadline,
        )
        if not response.is_success:
            status, reasons = _google_error(response)
            raise EmbeddingError(
                _error_code(response.status_code, status), "/".join([status, *reasons])
            )
        return _parse_vector(response, self._dimensions)

    def _access_token(self, deadline: float) -> str:
        if not self._token_lock.acquire(
            timeout=min(_remaining_seconds(deadline), threading.TIMEOUT_MAX)
        ):
            raise EmbeddingError("embedding_timeout", "NoTimeLeft")
        try:
            _remaining_seconds(deadline)
            if self._token and self._token[1] - TOKEN_REFRESH_MARGIN_SECONDS > time.time():
                return self._token[0]
            now = int(time.time())
            response = _send(
                self._http,
                self._info["token_uri"],
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": _create_assertion(self._info, now),
                },
                timeout=_remaining_timeout(TOKEN_TIMEOUT, deadline),
                deadline=deadline,
            )
            if not response.is_success:
                code: EmbeddingCode = (
                    "embedding_auth_failed" if response.status_code < 500 else "embedding_failed"
                )
                raise EmbeddingError(code, f"HTTP{response.status_code}")
            data = _json_object(response)
            token, expires = data.get("access_token"), data.get("expires_in", 3600)
            if not isinstance(token, str) or not token or "\n" in token or "\r" in token:
                raise EmbeddingError("embedding_auth_failed", "MissingAccessToken")
            if re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token) is None:
                raise EmbeddingError("embedding_auth_failed", "InvalidAccessToken")
            if type(expires) is not int or expires <= 0:
                raise EmbeddingError("embedding_auth_failed", "InvalidExpiry")
            self._token = (token, now + expires)
            return token
        finally:
            self._token_lock.release()


def _service_account_info(raw: str) -> dict[str, Any]:
    try:
        info = json.loads(raw)
    except (ValueError, TypeError):
        raise EmbeddingError("embedding_not_configured") from None
    if (
        not isinstance(info, dict)
        or info.get("type") != "service_account"
        or not all(
            isinstance(info.get(name), str) and info[name].strip()
            for name in ("client_email", "private_key")
        )
        or not isinstance(info.get("token_uri"), str)
        or info["token_uri"] not in _ALLOWED_TOKEN_URLS
    ):
        raise EmbeddingError("embedding_not_configured", "InvalidServiceAccount")
    return info


def _create_assertion(info: dict[str, Any], now: int) -> str:
    # google-auth 只在實際取得權杖時載入，與 document_ai 相同
    try:
        from google.auth import crypt, jwt
    except ImportError:
        raise EmbeddingError("embedding_not_configured", "MissingGoogleAuth") from None
    try:
        value = jwt.encode(
            crypt.RSASigner.from_service_account_info(info),
            {
                "iss": info["client_email"],
                "aud": info["token_uri"],
                "scope": TOKEN_SCOPE,
                "iat": now,
                "exp": now + 3600,
            },
        )
    except (ValueError, KeyError, TypeError):
        raise EmbeddingError("embedding_not_configured", "InvalidSigningKey") from None
    return value.decode("ascii") if isinstance(value, bytes) else str(value)


def _prompts(texts: Sequence[str], task: str, title: str | None) -> list[str]:
    """驗證輸入並套用 gemini-embedding-2 規定的前綴（此模型不支援 task_type 參數）。"""
    if (
        isinstance(texts, str)
        or not isinstance(texts, Sequence)
        or not texts
        or any(not isinstance(text, str) or not text.strip() for text in texts)
        or not isinstance(task, str)
        or task not in _TASKS
        or (
            title is not None
            and (task != "document" or not isinstance(title, str) or not title.strip())
        )
    ):
        raise EmbeddingError("embedding_invalid_input")
    if task == "query":
        return [f"task: search result | query: {text}" for text in texts]
    heading = title.strip() if title else "none"
    return [f"title: {heading} | text: {text}" for text in texts]


def _budget(timeout_seconds: float | None) -> float:
    if timeout_seconds is None:
        return DEFAULT_TIMEOUT_SECONDS
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise EmbeddingError("embedding_timeout", "NoTimeLeft")
    try:
        seconds = float(timeout_seconds)
    except OverflowError:
        raise EmbeddingError("embedding_timeout", "NoTimeLeft") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise EmbeddingError("embedding_timeout", "NoTimeLeft")
    return seconds


def _remaining_seconds(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise EmbeddingError("embedding_timeout", "NoTimeLeft")
    return seconds


def _remaining_timeout(default: httpx.Timeout, deadline: float) -> httpx.Timeout:
    """預設逾時與總預算剩餘秒數取較小者。"""
    seconds = _remaining_seconds(deadline)
    return httpx.Timeout(
        **{
            name: min(seconds, getattr(default, name) or seconds)
            for name in ("connect", "read", "write", "pool")
        }
    )


def _send(http: httpx.Client, url: str, *, deadline: float, **kwargs: Any) -> httpx.Response:
    _remaining_seconds(deadline)
    try:
        response = http.post(url, follow_redirects=False, **kwargs)
    except httpx.TimeoutException:
        raise EmbeddingError("embedding_timeout") from None
    except httpx.HTTPError:
        raise EmbeddingError("embedding_unreachable") from None
    except UnicodeError:
        raise EmbeddingError("embedding_invalid_input", "InvalidTextEncoding") from None
    except Exception:
        raise EmbeddingError("embedding_failed", "TransportFailure") from None
    _remaining_seconds(deadline)
    return response


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except (ValueError, UnicodeError):
        raise EmbeddingError("embedding_failed", "InvalidJson") from None
    if not isinstance(data, dict):
        raise EmbeddingError("embedding_failed", "InvalidJson")
    return data


def _parse_vector(response: httpx.Response, dimensions: int) -> tuple[float, ...]:
    embedding = _json_object(response).get("embedding")
    values = embedding.get("values") if isinstance(embedding, dict) else None
    try:
        if (
            not isinstance(values, list)
            or len(values) != dimensions
            or not all(type(value) in (int, float) and math.isfinite(value) for value in values)
        ):
            raise EmbeddingError("embedding_failed", "InvalidVector")
    except OverflowError:
        raise EmbeddingError("embedding_failed", "InvalidVector") from None
    return tuple(float(value) for value in values)


# Google 錯誤 status 優先於 HTTP 狀態碼
_STATUS_CODES: dict[str, EmbeddingCode] = {
    "UNAUTHENTICATED": "embedding_auth_failed",
    "PERMISSION_DENIED": "embedding_denied",
    "NOT_FOUND": "embedding_not_found",
    "RESOURCE_EXHAUSTED": "embedding_quota_exceeded",
    "INVALID_ARGUMENT": "embedding_invalid_input",
    "DEADLINE_EXCEEDED": "embedding_timeout",
}
_HTTP_CODES: dict[int, EmbeddingCode] = {
    400: "embedding_invalid_input",
    401: "embedding_auth_failed",
    402: "embedding_quota_exceeded",
    403: "embedding_denied",
    404: "embedding_not_found",
    429: "embedding_quota_exceeded",
}
# 僅輸出核定的固定識別碼，不把任意大寫字串當安全內容。
_SAFE_GOOGLE_STATUSES = frozenset(_STATUS_CODES) | {
    "INTERNAL",
    "UNKNOWN",
    "CANCELLED",
    "ALREADY_EXISTS",
    "FAILED_PRECONDITION",
    "ABORTED",
    "OUT_OF_RANGE",
    "UNIMPLEMENTED",
    "UNAVAILABLE",
    "DATA_LOSS",
}
_SAFE_GOOGLE_REASONS = frozenset(
    {
        "IAM_PERMISSION_DENIED",
        "ACCESS_TOKEN_EXPIRED",
        "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
        "SERVICE_DISABLED",
        "BILLING_DISABLED",
        "RATE_LIMIT_EXCEEDED",
        "QUOTA_EXCEEDED",
        "CONSUMER_INVALID",
        "TOO_LONG",
    }
)


def _error_code(http_status: int, google_status: str) -> EmbeddingCode:
    return _STATUS_CODES.get(google_status) or _HTTP_CODES.get(http_status, "embedding_failed")


def _is_google_code(value: Any, allowed: frozenset[str]) -> bool:
    return isinstance(value, str) and value in allowed


def _google_error(response: httpx.Response) -> tuple[str, list[str]]:
    """只取 Google 錯誤的 status 與 reason；Google 的 message 可能含輸入資訊，一律不帶出。"""
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
            if isinstance(item, dict) and _is_google_code(item.get("reason"), _SAFE_GOOGLE_REASONS)
        ]
        if isinstance(details, list)
        else []
    )
    status = error.get("status")
    return (
        status if _is_google_code(status, _SAFE_GOOGLE_STATUSES) else f"HTTP{response.status_code}"
    ), reasons[:4]
