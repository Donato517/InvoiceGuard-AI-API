"""
模組名稱：app.integrations.document_ai
功能說明：Google Document AI 模組（OCR）——以服務帳號取得存取權杖，呼叫 OCR Processor 辨識圖片／PDF。
使用方式：
    from app.integrations.document_ai import DocumentAIClient
    result = DocumentAIClient.from_settings().process(content, "image/jpeg")
    result.text、result.pages[0].lines、result.confidence、result.raw_response
注意事項：
    - 設定來自 GOOGLE_CLOUD_PROJECT_ID、GOOGLE_CLOUD_LOCATION、DOCUMENT_AI_PROCESSOR_ID、
      GOOGLE_SERVICE_ACCOUNT_JSON；本機由 START 注入，雲端由 Vercel 提供。
    - 只負責呼叫與解析，不寫 DB；辨識紀錄（ai_recognition_logs）由上層 service 決定是否寫入，
      PROVIDER、confidence、raw_response 對應該表的 ai_provider、confidence_score、raw_response。
    - HTTP／連線錯誤轉成固定代碼，detail 只放 Google 的 status／reason，不含權杖、私鑰或文件內容。
    - 存取權杖在同一程序內暫存到到期前 60 秒，避免每次辨識都重新換發。
"""

import base64
import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from google.auth import crypt, jwt

from app.core.config import Settings, settings

PROVIDER = "google_document_ai"
# 與 invoice_files.mime_type 的 CHECK 一致
SUPPORTED_MIME_TYPES = frozenset({"image/jpeg", "image/png", "application/pdf"})
TOKEN_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
# 只取文字、頁碼、尺寸、版面與行；不回傳頁面影像，縮小回應
PROCESS_FIELD_MASK = "text,pages.pageNumber,pages.dimension,pages.layout,pages.lines"
TOKEN_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
# Vercel 函式上限 60 秒，保留回應處理時間
PROCESS_TIMEOUT = httpx.Timeout(45.0, connect=10.0)
TOKEN_REFRESH_MARGIN_SECONDS = 60

DocumentAICode = Literal[
    "document_ai_not_configured",
    "document_ai_invalid_input",
    "document_ai_auth_failed",
    "document_ai_denied",
    "document_ai_not_found",
    "document_ai_quota_exceeded",
    "document_ai_timeout",
    "document_ai_unreachable",
    "document_ai_failed",
]


class DocumentAIError(RuntimeError):
    """Document AI 操作失敗；code 為固定代碼，detail 只放 Google 的 status／reason。"""

    def __init__(self, code: DocumentAICode, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


@dataclass(frozen=True)
class OcrLine:
    """一行辨識文字；bounding_box 為 0～1 的正規化頂點座標。"""

    text: str
    confidence: float | None
    bounding_box: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class OcrPage:
    """一頁的尺寸、整頁信心值與各行文字。"""

    page_number: int
    width: float | None
    height: float | None
    confidence: float | None
    lines: tuple[OcrLine, ...]


@dataclass(frozen=True)
class OcrResult:
    """辨識結果；raw_response 為 Google 原始回應，供上層寫入 ai_recognition_logs.raw_response。"""

    text: str
    pages: tuple[OcrPage, ...]
    raw_response: dict[str, Any] = field(repr=False)

    @property
    def confidence(self) -> float | None:
        """各頁信心值平均；沒有頁面信心值時為 None。"""
        values = [page.confidence for page in self.pages if page.confidence is not None]
        return sum(values) / len(values) if values else None


@dataclass(frozen=True)
class ProcessorInfo:
    """Processor 中繼資料（唯讀查詢）。"""

    type: str
    state: str
    display_name: str
    default_version: str


def _bounded_timeout(default: httpx.Timeout, seconds: float | None) -> httpx.Timeout:
    """呼叫端剩餘秒數與預設逾時取較小者；已無剩餘時間時直接視為逾時。"""
    if seconds is None:
        return default
    if not seconds > 0:
        raise DocumentAIError("document_ai_timeout", "NoTimeLeft")
    read = min(seconds, default.read or seconds)
    return httpx.Timeout(read, connect=min(read, default.connect or read))


def _deadline_timeout(default: httpx.Timeout, deadline: float | None) -> httpx.Timeout:
    """依截止時間（time.monotonic）重新計算這次請求可用的逾時；None 使用預設。"""
    if deadline is None:
        return default
    return _bounded_timeout(default, deadline - time.monotonic())


_token_lock = threading.Lock()
# client_email → (access_token, 到期 epoch 秒)
_token_cache: dict[str, tuple[str, float]] = {}


def clear_token_cache() -> None:
    """清除程序內暫存的存取權杖（測試或憑證更換時使用）。"""
    with _token_lock:
        _token_cache.clear()


class DocumentAIClient:
    """Google Document AI OCR Processor 用戶端（REST）。"""

    def __init__(
        self,
        *,
        project_id: str,
        location: str,
        processor_id: str,
        service_account_json: str,
        http: httpx.Client | None = None,
    ) -> None:
        project_id, location, processor_id = (
            value.strip() for value in (project_id, location, processor_id)
        )
        if not all(
            re.fullmatch(r"[a-z0-9][a-z0-9-]*", value) for value in (project_id, location)
        ) or not re.fullmatch(r"[A-Za-z0-9_-]+", processor_id):
            raise DocumentAIError("document_ai_not_configured")
        try:
            info = json.loads(service_account_json)
        except ValueError:
            raise DocumentAIError("document_ai_not_configured") from None
        if (
            not isinstance(info, dict)
            or info.get("type") != "service_account"
            or not all(isinstance(info.get(key), str) for key in ("client_email", "private_key"))
            or not str(info.get("token_uri", "")).startswith("https://")
        ):
            raise DocumentAIError("document_ai_not_configured")
        self._info = info
        self._processor_url = (
            f"https://{location}-documentai.googleapis.com/v1/projects/{project_id}"
            f"/locations/{location}/processors/{processor_id}"
        )
        self._http = http or httpx.Client(follow_redirects=False)

    @classmethod
    def from_settings(cls, configuration: Settings | None = None) -> "DocumentAIClient":
        """以 GOOGLE_CLOUD_* 、DOCUMENT_AI_PROCESSOR_ID 與服務帳號 JSON 建立用戶端。

        Raises:
            DocumentAIError: document_ai_not_configured——任一設定空白、格式不符或服務帳號 JSON 無效。
        """
        configuration = configuration if configuration is not None else settings
        return cls(
            project_id=configuration.GOOGLE_CLOUD_PROJECT_ID,
            location=configuration.GOOGLE_CLOUD_LOCATION,
            processor_id=configuration.DOCUMENT_AI_PROCESSOR_ID,
            service_account_json=configuration.GOOGLE_SERVICE_ACCOUNT_JSON.get_secret_value(),
        )

    def process(
        self, content: bytes, mime_type: str, *, timeout_seconds: float | None = None
    ) -> OcrResult:
        """辨識單一圖片或 PDF（線上處理）。

        Args:
            content: 檔案內容。
            mime_type: image/jpeg、image/png 或 application/pdf。
            timeout_seconds: 呼叫端剩餘的秒數，涵蓋換發存取權杖與 OCR 兩次請求；None 使用各自預設
                （權杖 15 秒、OCR 45 秒），不會超過預設。

        Returns:
            OcrResult: 全文、各頁各行文字與信心值、Google 原始回應。

        Raises:
            DocumentAIError: 輸入無效、認證或權限失敗、配額不足、逾時、無法連線或服務錯誤。
        """
        if not content or mime_type not in SUPPORTED_MIME_TYPES:
            raise DocumentAIError("document_ai_invalid_input")
        if timeout_seconds is not None and not timeout_seconds > 0:
            raise DocumentAIError("document_ai_timeout", "NoTimeLeft")
        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        body = {
            "rawDocument": {
                "content": base64.b64encode(content).decode("ascii"),
                "mimeType": mime_type,
            },
            "skipHumanReview": True,
            "fieldMask": PROCESS_FIELD_MASK,
        }
        data = self._request(
            "POST", self._processor_url + ":process", body, PROCESS_TIMEOUT, deadline
        )
        document = data.get("document")
        if not isinstance(document, dict):
            raise DocumentAIError("document_ai_failed", "MissingDocument")
        return _parse_document(document, data)

    def describe_processor(self) -> ProcessorInfo:
        """唯讀查詢 Processor 類型、狀態與預設版本（不計費）。"""
        data = self._request("GET", self._processor_url, None, TOKEN_TIMEOUT)
        return ProcessorInfo(
            type=str(data.get("type", "")),
            state=str(data.get("state", "")),
            display_name=str(data.get("displayName", "")),
            default_version=str(data.get("defaultProcessorVersion", "")).rsplit("/", 1)[-1],
        )

    def _request(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None,
        timeout: httpx.Timeout,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._access_token(deadline)}"}
        # 換發權杖耗用的時間要從剩餘時間扣除
        timeout = _deadline_timeout(timeout, deadline)
        response = _send(self._http, method, url, json=body, headers=headers, timeout=timeout)
        if response.is_success:
            return _json_object(response)
        detail = _google_detail(response)
        raise DocumentAIError(_error_code(response.status_code, detail.split("/")[0]), detail)

    def _access_token(self, deadline: float | None = None) -> str:
        email = self._info["client_email"]
        with _token_lock:
            cached = _token_cache.get(email)
            if cached and cached[1] - TOKEN_REFRESH_MARGIN_SECONDS > time.time():
                return cached[0]
        try:
            signer = crypt.RSASigner.from_service_account_info(self._info)
        except (ValueError, KeyError):
            raise DocumentAIError("document_ai_not_configured") from None
        now = int(time.time())
        assertion = jwt.encode(
            signer,
            {
                "iss": email,
                "aud": self._info["token_uri"],
                "scope": TOKEN_SCOPE,
                "iat": now,
                "exp": now + 3600,
            },
        )
        response = _send(
            self._http,
            "POST",
            self._info["token_uri"],
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion.decode("ascii"),
            },
            timeout=_deadline_timeout(TOKEN_TIMEOUT, deadline),
        )
        if not response.is_success:
            # 400 invalid_grant／401 為服務帳號金鑰被停用或刪除
            code = "document_ai_auth_failed" if response.status_code < 500 else "document_ai_failed"
            raise DocumentAIError(code, _token_detail(response))
        data = _json_object(response)
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise DocumentAIError("document_ai_auth_failed", "MissingAccessToken")
        expires_in = data.get("expires_in", 3600)
        expires_at = now + (expires_in if isinstance(expires_in, int) else 3600)
        with _token_lock:
            _token_cache[email] = (token, expires_at)
        return token


def _send(http: httpx.Client, method: str, url: str, **kwargs: Any) -> httpx.Response:
    try:
        return http.request(method, url, **kwargs)
    except httpx.TimeoutException:
        raise DocumentAIError("document_ai_timeout") from None
    except httpx.HTTPError:
        raise DocumentAIError("document_ai_unreachable") from None


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        raise DocumentAIError("document_ai_failed", "InvalidJson") from None
    if not isinstance(data, dict):
        raise DocumentAIError("document_ai_failed", "InvalidJson")
    return data


# Google 錯誤 status 優先於 HTTP 狀態碼（例如額度用完可能回 402＋RESOURCE_EXHAUSTED）
_STATUS_CODES: dict[str, DocumentAICode] = {
    "UNAUTHENTICATED": "document_ai_auth_failed",
    "PERMISSION_DENIED": "document_ai_denied",
    "NOT_FOUND": "document_ai_not_found",
    "RESOURCE_EXHAUSTED": "document_ai_quota_exceeded",
    "INVALID_ARGUMENT": "document_ai_invalid_input",
}
_HTTP_CODES: dict[int, DocumentAICode] = {
    400: "document_ai_invalid_input",
    401: "document_ai_auth_failed",
    402: "document_ai_quota_exceeded",
    403: "document_ai_denied",
    404: "document_ai_not_found",
    429: "document_ai_quota_exceeded",
}


def _error_code(http_status: int, google_status: str) -> DocumentAICode:
    return _STATUS_CODES.get(google_status) or _HTTP_CODES.get(http_status, "document_ai_failed")


def _google_detail(response: httpx.Response) -> str:
    """只取 Google 錯誤的 status 與 reason（例如 PERMISSION_DENIED/SERVICE_DISABLED）。

    不是大寫短代碼的內容（巢狀物件、長字串）一律不帶出，status 不合格時改用 HTTP 狀態碼。
    """
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        return f"HTTP{response.status_code}"
    if not isinstance(error, dict):
        return f"HTTP{response.status_code}"
    details = error.get("details")
    reasons = (
        [
            item["reason"]
            for item in details
            if isinstance(item, dict) and _safe_code(item.get("reason"), _GOOGLE_CODE)
        ]
        if isinstance(details, list)
        else []
    )
    status = error.get("status")
    status = status if _safe_code(status, _GOOGLE_CODE) else f"HTTP{response.status_code}"
    return "/".join([status, *reasons])


def _token_detail(response: httpx.Response) -> str:
    """OAuth 錯誤只取小寫短代碼（例如 invalid_grant），其他內容改用 HTTP 狀態碼。"""
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        error = None
    return error if _safe_code(error, _OAUTH_CODE) else f"HTTP{response.status_code}"


# Google API 的 status／reason 為大寫英數底線；OAuth 錯誤為小寫英數底線
_GOOGLE_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_OAUTH_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _safe_code(value: Any, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _segment_text(text: str, layout: dict[str, Any]) -> str:
    # int64 欄位在 JSON 為字串；startIndex 為 0 時省略
    segments = layout.get("textAnchor", {}).get("textSegments", [])
    return "".join(
        text[int(segment.get("startIndex", 0)) : int(segment.get("endIndex", 0))]
        for segment in segments
        if isinstance(segment, dict)
    )


def _bounding_box(layout: dict[str, Any]) -> tuple[tuple[float, float], ...]:
    vertices = layout.get("boundingPoly", {}).get("normalizedVertices", [])
    return tuple(
        (float(vertex.get("x", 0.0)), float(vertex.get("y", 0.0)))
        for vertex in vertices
        if isinstance(vertex, dict)
    )


def _parse_document(document: dict[str, Any], raw: dict[str, Any]) -> OcrResult:
    text = str(document.get("text", ""))
    pages = []
    for index, page in enumerate(document.get("pages", []), start=1):
        if not isinstance(page, dict):
            continue
        dimension = page.get("dimension", {})
        lines = tuple(
            OcrLine(
                text=_segment_text(text, line.get("layout", {})).strip(),
                confidence=_number(line.get("layout", {}).get("confidence")),
                bounding_box=_bounding_box(line.get("layout", {})),
            )
            for line in page.get("lines", [])
            if isinstance(line, dict)
        )
        pages.append(
            OcrPage(
                page_number=int(page.get("pageNumber", index)),
                width=_number(dimension.get("width")),
                height=_number(dimension.get("height")),
                confidence=_number(page.get("layout", {}).get("confidence")),
                lines=lines,
            )
        )
    return OcrResult(text=text, pages=tuple(pages), raw_response=raw)
