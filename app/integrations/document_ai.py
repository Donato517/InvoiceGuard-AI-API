"""模組名稱：app.integrations.document_ai
功能說明：Document AI REST 呼叫、原生解析及辨識來源中繼資料（ADMIN 與 API 共用同一份，各讀本站設定）。

Backward compatible entry point::
    DocumentAIClient.from_settings().process(content, "image/jpeg")

New evidence path::
    client.process(content, mime, options=ProcessOptions(
        profile="evidence", include_page_images=True))

Only calls/parses Document AI. No database writes, supplier lookup, Gemini call,
invoice approval, or automatic retries. raw_response is the actual MASKED reply,
not a full unfiltered Google document. Missing confidence remains None.
Uploaded original is not modified. Official references:
    https://cloud.google.com/document-ai/docs/reference/rest/v1/projects.locations.processors/process
    https://cloud.google.com/document-ai/docs/reference/rest/v1/Document
    https://developers.google.com/identity/protocols/oauth2/service-account
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

import httpx

PROVIDER = "google_document_ai"
PARSER_VERSION = "invoiceguard-docai/2.0.0"
SUPPORTED_MIME_TYPES = frozenset({"image/jpeg", "image/png", "application/pdf"})
TOKEN_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
PROCESS_FIELD_MASK = "text,pages.pageNumber,pages.dimension,pages.layout,pages.lines"
TOKEN_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
PROCESS_TIMEOUT = httpx.Timeout(45.0, connect=10.0)
# 呼叫端未傳 timeout_seconds 時的總預算；低於兩站函式上限（ADMIN 30 秒、API 60 秒），保留解析與回應時間。
DEFAULT_TIMEOUT_SECONDS = 25.0
TOKEN_REFRESH_MARGIN_SECONDS = 60
# Application guard, not a promise about every processor's Google service limit.
DEFAULT_MAX_INPUT_BYTES = 20 * 1024 * 1024
_ALLOWED_TOKEN_URLS = frozenset(
    {
        "https://oauth2.googleapis.com/token",
        "https://accounts.google.com/o/oauth2/token",
        "https://www.googleapis.com/oauth2/v4/token",
    }
)
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
    """Stable, sanitized error. Never carries invoice text, key, token or HTTP body."""

    def __init__(self, code: DocumentAICode, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


@dataclass(frozen=True)
class TextSegment:
    start: int
    end: int


@dataclass(frozen=True)
class OcrLine:
    # First three fields retain the uploaded module's constructor contract.
    text: str
    confidence: float | None
    bounding_box: tuple[tuple[float, float], ...]
    text_segments: tuple[TextSegment, ...] = ()
    pixel_vertices: tuple[tuple[float, float], ...] = ()
    orientation: str | None = None
    raw_text: str = field(default="", repr=False)


@dataclass(frozen=True)
class OcrToken(OcrLine):
    detected_break: str | None = None


@dataclass(frozen=True)
class VisualElement:
    type: str
    layout: OcrLine


@dataclass(frozen=True)
class QualityDefect:
    type: str
    confidence: float | None


@dataclass(frozen=True)
class ImageQuality:
    score: float | None
    defects: tuple[QualityDefect, ...] = ()


@dataclass(frozen=True)
class PageImage:
    content: bytes = field(repr=False)
    mime_type: str
    width: int | None
    height: int | None


@dataclass(frozen=True)
class OcrPage:
    # First five fields retain the uploaded module's constructor contract.
    page_number: int
    width: float | None
    height: float | None
    confidence: float | None
    lines: tuple[OcrLine, ...]
    page_index: int = 0  # Index in Document.pages; NOT original page number minus one.
    unit: str | None = None
    tokens: tuple[OcrToken, ...] = ()
    symbols: tuple[OcrLine, ...] = ()
    visual_elements: tuple[VisualElement, ...] = ()
    form_fields: tuple[dict[str, Any], ...] = field(default=(), repr=False)
    tables: tuple[dict[str, Any], ...] = field(default=(), repr=False)
    transforms: tuple[dict[str, Any], ...] = field(default=(), repr=False)
    image: PageImage | None = field(default=None, repr=False)
    image_quality: ImageQuality | None = None
    orientation: str | None = None
    document_sha256: str = ""


@dataclass(frozen=True)
class EntityPageRef:
    page_index: int
    page_number: int | None
    bounding_box: tuple[tuple[float, float], ...]
    pixel_vertices: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class OcrEntity:
    id: str
    type: str
    mention_text: str
    confidence: float | None
    text_segments: tuple[TextSegment, ...] = ()
    normalized_value: dict[str, Any] | None = field(default=None, repr=False)
    page_refs: tuple[EntityPageRef, ...] = ()
    properties: tuple[OcrEntity, ...] = ()


@dataclass(frozen=True)
class RecognitionMetadata:
    requested_resource: str = ""
    requested_version: str | None = None  # None = default path; do not guess actual version.
    profile: str = "legacy"
    options_sha256: str = ""
    source_sha256: str = ""
    document_sha256: str = ""
    elapsed_seconds: float | None = None
    parser_version: str = PARSER_VERSION
    file_id: str = ""
    file_version: str = ""
    recognition_id: str = ""
    document_group_id: str | None = None


@dataclass(frozen=True)
class OcrResult:
    text: str
    pages: tuple[OcrPage, ...]
    raw_response: dict[str, Any] = field(repr=False)
    entities: tuple[OcrEntity, ...] = ()
    metadata: RecognitionMetadata = field(default_factory=RecognitionMetadata)
    document_layout: dict[str, Any] | None = field(default=None, repr=False)
    chunked_document: dict[str, Any] | None = field(default=None, repr=False)

    @property
    def confidence(self) -> float | None:
        """Legacy average of native PAGE scores; not field correctness probability."""
        values = [p.confidence for p in self.pages if p.confidence is not None]
        return sum(values) / len(values) if values else None


@dataclass(frozen=True)
class ProcessorInfo:
    type: str
    state: str
    display_name: str
    default_version: str


@dataclass(frozen=True)
class ProcessOptions:
    """InvoiceGuard profiles, not Google API profile names.

    Extra processing is opt-in. Evidence images can increase reply size. Type
    validation uses supplied processor_type or a metadata GET before paid POST.
    Actual version-specific support remains Google's responsibility; errors are
    surfaced, never silently downgraded.
    """

    profile: Literal["legacy", "evidence", "quality", "selection", "extract", "layout"] = "legacy"
    include_page_images: bool = False
    enable_image_quality_scores: bool = False
    enable_selection_mark_detection: bool = False
    enable_native_pdf_parsing: bool = False
    enable_symbols: bool = False
    language_hints: tuple[str, ...] = ()
    pages: tuple[int, ...] = ()
    layout_chunk_size: int | None = None
    include_ancestor_headings: bool = True

    def as_request(self, processor_type: str | None = None) -> tuple[str, dict[str, Any]]:
        """驗證適用的 Processor 類型，產生官方 fieldMask 與 processOptions。"""
        if not isinstance(self.profile, str) or self.profile not in {
            "legacy",
            "evidence",
            "quality",
            "selection",
            "extract",
            "layout",
        }:
            raise DocumentAIError("document_ai_invalid_input", "UnknownProfile")
        for value in (
            self.include_page_images,
            self.enable_image_quality_scores,
            self.enable_selection_mark_detection,
            self.enable_native_pdf_parsing,
            self.enable_symbols,
            self.include_ancestor_headings,
        ):
            if type(value) is not bool:
                raise DocumentAIError("document_ai_invalid_input", "InvalidBooleanOption")
        if (
            not isinstance(self.pages, (tuple, list))
            or any(type(p) is not int or p < 1 for p in self.pages)
            or len(set(self.pages)) != len(self.pages)
        ):
            raise DocumentAIError("document_ai_invalid_input", "InvalidPageSelection")
        if not isinstance(self.language_hints, (tuple, list)) or any(
            not isinstance(h, str) or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", h)
            for h in self.language_hints
        ):
            raise DocumentAIError("document_ai_invalid_input", "InvalidLanguageHint")
        ocr: dict[str, Any] = {}
        if self.profile == "quality" or self.enable_image_quality_scores:
            ocr["enableImageQualityScores"] = True
        if self.profile == "selection" or self.enable_selection_mark_detection:
            ocr["premiumFeatures"] = {"enableSelectionMarkDetection": True}
        if self.enable_native_pdf_parsing:
            ocr["enableNativePdfParsing"] = True
        if self.enable_symbols:
            ocr["enableSymbol"] = True
        if self.language_hints:
            ocr["hints"] = {"languageHints": list(self.language_hints)}
        if ocr and processor_type not in {"OCR_PROCESSOR", "FORM_PARSER_PROCESSOR"}:
            raise DocumentAIError("document_ai_invalid_input", "OcrOptionsRequireOcrOrForm")
        if self.profile == "layout" and processor_type != "LAYOUT_PARSER_PROCESSOR":
            raise DocumentAIError("document_ai_invalid_input", "LayoutProcessorRequired")
        if self.profile == "layout" and ocr:
            raise DocumentAIError("document_ai_invalid_input", "IncompatibleOptions")
        if self.layout_chunk_size is not None and (
            self.profile != "layout"
            or type(self.layout_chunk_size) is not int
            or self.layout_chunk_size < 1
        ):
            raise DocumentAIError("document_ai_invalid_input", "InvalidChunkSize")
        options: dict[str, Any] = {}
        if ocr:
            options["ocrConfig"] = ocr
        if self.pages:
            options["individualPageSelector"] = {"pages": list(self.pages)}
        if self.profile == "layout":
            chunking: dict[str, Any] = {"includeAncestorHeadings": self.include_ancestor_headings}
            if self.layout_chunk_size is not None:
                chunking["chunkSize"] = self.layout_chunk_size
            options["layoutConfig"] = {"chunkingConfig": chunking}
        mask = PROCESS_FIELD_MASK.split(",")
        if self.profile != "legacy":
            mask += [
                "mimeType",
                "error",
                "shardInfo",
                "pages.tokens",
                "pages.transforms",
                "pages.visualElements",
                "pages.imageQualityScores",
            ]
        if self.profile == "extract":
            mask += ["entities", "entityRelations", "pages.formFields", "pages.tables"]
        if self.profile == "layout":
            mask += ["documentLayout", "chunkedDocument"]
        if self.enable_image_quality_scores:
            mask += ["pages.imageQualityScores"]
        if self.enable_selection_mark_detection:
            mask += ["pages.visualElements"]
        if self.enable_symbols:
            mask += ["pages.symbols"]
        if self.include_page_images:
            mask += ["pages.image", "pages.transforms"]
        return ",".join(dict.fromkeys(mask)), options

    @property
    def needs_processor_type(self) -> bool:
        return bool(
            self.profile in {"quality", "selection", "layout"}
            or self.enable_image_quality_scores
            or self.enable_selection_mark_detection
            or self.enable_native_pdf_parsing
            or self.enable_symbols
            or self.language_hints
        )


def _positive_seconds(value: float | None) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise DocumentAIError("document_ai_timeout", "NoTimeLeft")
    return float(value)


def _bounded_timeout(default: httpx.Timeout, seconds: float | None) -> httpx.Timeout:
    seconds = _positive_seconds(seconds)
    if seconds is None:
        return default
    return httpx.Timeout(
        **{
            name: min(seconds, getattr(default, name) or seconds)
            for name in ("connect", "read", "write", "pool")
        }
    )


def _deadline_timeout(default: httpx.Timeout, deadline: float | None) -> httpx.Timeout:
    return _bounded_timeout(default, None if deadline is None else deadline - time.monotonic())


_token_lock = threading.Lock()
_token_cache: dict[str, tuple[str, float]] = {}
_refresh_locks: dict[str, threading.Lock] = {}


def clear_token_cache() -> None:
    """Clear cached access tokens (e.g. after key rotation)."""
    with _token_lock:
        _token_cache.clear()


def _create_assertion(info: Mapping[str, Any], now: int) -> str:
    # Existing dependency, loaded only when service-account auth is actually used.
    try:
        from google.auth import crypt, jwt
    except ImportError:
        raise DocumentAIError("document_ai_not_configured", "MissingGoogleAuth") from None
    try:
        signer = crypt.RSASigner.from_service_account_info(info)
        value = jwt.encode(
            signer,
            {
                "iss": info["client_email"],
                "aud": info["token_uri"],
                "scope": TOKEN_SCOPE,
                "iat": now,
                "exp": now + 3600,
            },
        )
        return value.decode("ascii") if isinstance(value, bytes) else str(value)
    except (ValueError, KeyError, TypeError):
        raise DocumentAIError("document_ai_not_configured", "InvalidSigningKey") from None


class DocumentAIClient:
    """Sync REST client. Injected HTTP clients remain owned by their caller.

    timeout_seconds is a cooperative request budget, not a hard wall-clock kill
    switch. HTTPX applies stage timeouts. A service-level deadline should also
    govern optional downstream processing. No implicit paid-call retry occurs.
    """

    def __init__(
        self,
        *,
        project_id: str,
        location: str,
        processor_id: str,
        service_account_json: str = "",
        http: httpx.Client | None = None,
        processor_version: str | None = None,
        processor_type: str | None = None,
        access_token_provider: Callable[[], str] | None = None,
        max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    ) -> None:
        if not all(isinstance(v, str) for v in (project_id, location, processor_id)):
            raise DocumentAIError("document_ai_not_configured")
        project_id, location, processor_id = (
            v.strip() for v in (project_id, location, processor_id)
        )
        if not all(
            re.fullmatch(r"[a-z0-9][a-z0-9-]*", v) for v in (project_id, location)
        ) or not re.fullmatch(r"[A-Za-z0-9_-]+", processor_id):
            raise DocumentAIError("document_ai_not_configured")
        if processor_version is not None and (
            not isinstance(processor_version, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", processor_version)
        ):
            raise DocumentAIError("document_ai_not_configured", "InvalidProcessorVersion")
        if type(max_input_bytes) is not int or max_input_bytes < 1:
            raise DocumentAIError("document_ai_not_configured", "InvalidSizeLimit")
        self._info: dict[str, Any] = {}
        self._token_provider = access_token_provider
        self._credential_key = ""
        if access_token_provider is None:
            try:
                info = json.loads(service_account_json)
            except (ValueError, TypeError):
                raise DocumentAIError("document_ai_not_configured") from None
            if (
                not isinstance(info, dict)
                or info.get("type") != "service_account"
                or not all(
                    isinstance(info.get(k), str) and info[k].strip()
                    for k in ("client_email", "private_key")
                )
                or info.get("token_uri") not in _ALLOWED_TOKEN_URLS
            ):
                raise DocumentAIError("document_ai_not_configured", "InvalidServiceAccount")
            self._info = info
            # Credential identity includes key fingerprint; no token/key is logged.
            self._credential_key = hashlib.sha256(
                json.dumps(
                    [info["client_email"], info["private_key"], info["token_uri"], TOKEN_SCOPE]
                ).encode()
            ).hexdigest()
        elif not callable(access_token_provider):
            raise DocumentAIError("document_ai_not_configured", "InvalidTokenProvider")
        host = (
            "documentai.googleapis.com"
            if location == "global"
            else f"{location}-documentai.googleapis.com"
        )
        self._resource = f"projects/{project_id}/locations/{location}/processors/{processor_id}"
        self._processor_url = f"https://{host}/v1/{self._resource}"
        self._version = processor_version
        self._processor_type = processor_type
        self._owns_http = http is None
        self._http = http if http is not None else httpx.Client(follow_redirects=False)
        self._max_input_bytes = max_input_bytes
        self._closed = False

    @classmethod
    def from_settings(cls, configuration: Any = None, **overrides: Any) -> DocumentAIClient:
        """Existing app.core.config integration, imported lazily for standalone use."""
        if configuration is None:
            try:
                from app.core.config import settings
            except ImportError:
                raise DocumentAIError("document_ai_not_configured", "MissingAppSettings") from None
            configuration = settings
        try:
            secret = configuration.GOOGLE_SERVICE_ACCOUNT_JSON
            kwargs = dict(
                project_id=configuration.GOOGLE_CLOUD_PROJECT_ID,
                location=configuration.GOOGLE_CLOUD_LOCATION,
                processor_id=configuration.DOCUMENT_AI_PROCESSOR_ID,
                service_account_json=secret.get_secret_value()
                if hasattr(secret, "get_secret_value")
                else secret,
                processor_version=getattr(configuration, "DOCUMENT_AI_PROCESSOR_VERSION", None)
                or None,
                processor_type=getattr(configuration, "DOCUMENT_AI_PROCESSOR_TYPE", None) or None,
            )
        except AttributeError:
            raise DocumentAIError("document_ai_not_configured", "MissingSetting") from None
        kwargs.update(overrides)
        return cls(**kwargs)

    def close(self) -> None:
        if not self._closed and self._owns_http:
            self._http.close()
        self._closed = True

    def __enter__(self) -> DocumentAIClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def process(
        self,
        content: bytes,
        mime_type: str,
        *,
        timeout_seconds: float | None = None,
        options: ProcessOptions | None = None,
    ) -> OcrResult:
        if (
            not isinstance(content, bytes)
            or not content
            or len(content) > self._max_input_bytes
            or mime_type not in SUPPORTED_MIME_TYPES
        ):
            raise DocumentAIError("document_ai_invalid_input")
        budget = _positive_seconds(
            DEFAULT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        )
        started = time.monotonic()
        deadline = None if budget is None else started + budget
        chosen = options if options is not None else ProcessOptions()
        if not isinstance(chosen, ProcessOptions):
            raise DocumentAIError("document_ai_invalid_input", "InvalidOptions")
        processor_type = self._processor_type
        if chosen.needs_processor_type and processor_type is None:
            processor_type = self.describe_processor(
                timeout_seconds=None if deadline is None else deadline - time.monotonic()
            ).type
        mask, processing = chosen.as_request(processor_type)
        body: dict[str, Any] = {
            "rawDocument": {
                "content": base64.b64encode(content).decode("ascii"),
                "mimeType": mime_type,
            },
            "fieldMask": mask,
        }
        if processing:
            body["processOptions"] = processing
        # Deprecated skipHumanReview removed; unrelated to InvoiceGuard approvals.
        resource = self._resource + (f"/processorVersions/{self._version}" if self._version else "")
        url = (
            self._processor_url
            + (f"/processorVersions/{self._version}" if self._version else "")
            + ":process"
        )
        data = self._request("POST", url, body, PROCESS_TIMEOUT, deadline)
        meta = RecognitionMetadata(
            requested_resource=resource,
            requested_version=self._version,
            profile=chosen.profile,
            source_sha256=hashlib.sha256(content).hexdigest(),
            options_sha256=_json_hash({"fieldMask": mask, "processOptions": processing}),
            elapsed_seconds=time.monotonic() - started,
        )
        return parse_response(data, metadata=meta)

    def describe_processor(self, *, timeout_seconds: float | None = None) -> ProcessorInfo:
        budget = _positive_seconds(timeout_seconds)
        data = self._request(
            "GET",
            self._processor_url,
            None,
            TOKEN_TIMEOUT,
            None if budget is None else time.monotonic() + budget,
        )
        info = ProcessorInfo(
            type=str(data.get("type", "")),
            state=str(data.get("state", "")),
            display_name=str(data.get("displayName", "")),
            default_version=str(data.get("defaultProcessorVersion", "")).rsplit("/", 1)[-1],
        )
        self._processor_type = info.type
        return info

    def _request(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None,
        timeout: httpx.Timeout,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        if self._closed:
            raise DocumentAIError("document_ai_failed", "ClientClosed")
        headers = {"Authorization": f"Bearer {self._access_token(deadline)}"}
        response = _send(
            self._http,
            method,
            url,
            json=body,
            headers=headers,
            timeout=_deadline_timeout(timeout, deadline),
            follow_redirects=False,
        )
        if deadline is not None and time.monotonic() >= deadline:
            raise DocumentAIError("document_ai_timeout", "BudgetExceeded")
        if response.is_success:
            return _json_object(response)
        detail = _google_detail(response)
        raise DocumentAIError(_error_code(response.status_code, detail.split("/")[0]), detail)

    def _access_token(self, deadline: float | None = None) -> str:
        if self._token_provider is not None:
            _deadline_timeout(TOKEN_TIMEOUT, deadline)
            try:
                token = self._token_provider()
            except Exception:
                raise DocumentAIError("document_ai_auth_failed", "TokenProviderFailed") from None
            if not isinstance(token, str) or not token or "\n" in token or "\r" in token:
                raise DocumentAIError("document_ai_auth_failed", "InvalidAccessToken")
            return token
        key = self._credential_key
        with _token_lock:
            cached = _token_cache.get(key)
            if cached and cached[1] - TOKEN_REFRESH_MARGIN_SECONDS > time.time():
                return cached[0]
            refresh_lock = _refresh_locks.setdefault(key, threading.Lock())
        wait = 15.0 if deadline is None else _positive_seconds(deadline - time.monotonic())
        if not refresh_lock.acquire(timeout=wait):
            raise DocumentAIError("document_ai_timeout", "TokenRefreshBusy")
        try:
            with _token_lock:
                cached = _token_cache.get(key)
                if cached and cached[1] - TOKEN_REFRESH_MARGIN_SECONDS > time.time():
                    return cached[0]
            now = int(time.time())
            assertion = _create_assertion(self._info, now)
            response = _send(
                self._http,
                "POST",
                self._info["token_uri"],
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                timeout=_deadline_timeout(TOKEN_TIMEOUT, deadline),
                follow_redirects=False,
            )
            if not response.is_success:
                code = (
                    "document_ai_auth_failed"
                    if response.status_code < 500
                    else "document_ai_failed"
                )
                raise DocumentAIError(code, _token_detail(response))
            data = _json_object(response)
            token = data.get("access_token")
            expires = data.get("expires_in", 3600)
            if not isinstance(token, str) or not token or "\n" in token or "\r" in token:
                raise DocumentAIError("document_ai_auth_failed", "MissingAccessToken")
            if type(expires) is not int or expires <= 0:
                raise DocumentAIError("document_ai_auth_failed", "InvalidExpiry")
            with _token_lock:
                for expired_key in [
                    k for k, (_, until) in _token_cache.items() if until <= time.time()
                ]:
                    _token_cache.pop(expired_key, None)
                _token_cache[key] = (token, now + expires)
            return token
        finally:
            refresh_lock.release()


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
    except (ValueError, UnicodeError):
        raise DocumentAIError("document_ai_failed", "InvalidJson") from None
    if not isinstance(data, dict):
        raise DocumentAIError("document_ai_failed", "InvalidJson")
    return data


_STATUS_CODES: dict[str, DocumentAICode] = {
    "UNAUTHENTICATED": "document_ai_auth_failed",
    "PERMISSION_DENIED": "document_ai_denied",
    "NOT_FOUND": "document_ai_not_found",
    "RESOURCE_EXHAUSTED": "document_ai_quota_exceeded",
    "INVALID_ARGUMENT": "document_ai_invalid_input",
    "DEADLINE_EXCEEDED": "document_ai_timeout",
}
_HTTP_CODES: dict[int, DocumentAICode] = {
    400: "document_ai_invalid_input",
    401: "document_ai_auth_failed",
    402: "document_ai_quota_exceeded",
    403: "document_ai_denied",
    404: "document_ai_not_found",
    429: "document_ai_quota_exceeded",
}
_GOOGLE_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_OAUTH_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _safe_code(value: Any, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _error_code(http_status: int, google_status: str) -> DocumentAICode:
    return _STATUS_CODES.get(google_status) or _HTTP_CODES.get(http_status, "document_ai_failed")


def _google_detail(response: httpx.Response) -> str:
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        return f"HTTP{response.status_code}"
    if not isinstance(error, dict):
        return f"HTTP{response.status_code}"
    status = error.get("status")
    status = status if _safe_code(status, _GOOGLE_CODE) else f"HTTP{response.status_code}"
    details = error.get("details", [])
    reasons = (
        [
            x["reason"]
            for x in details
            if isinstance(x, dict) and _safe_code(x.get("reason"), _GOOGLE_CODE)
        ]
        if isinstance(details, list)
        else []
    )
    return "/".join([status, *reasons[:4]])


def _token_detail(response: httpx.Response) -> str:
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        error = None
    return error if _safe_code(error, _OAUTH_CODE) else f"HTTP{response.status_code}"


def _number(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except (OverflowError, ValueError):
        return None


def _score(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and 0 <= number <= 1 else None


def _int(value: Any, default: int | None = None) -> int | None:
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"\d+", value):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _objects(value: Any) -> list[dict[str, Any]]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, (list, tuple)) else []


def _segments(anchor: Mapping[str, Any], text: str) -> tuple[TextSegment, ...]:
    out = []
    for seg in _objects(anchor.get("textSegments", [])):
        start, end = _int(seg.get("startIndex", 0)), _int(seg.get("endIndex"))
        if start is None or end is None or start < 0 or end < start or end > len(text):
            raise DocumentAIError("document_ai_failed", "InvalidTextAnchor")
        out.append(TextSegment(start, end))
    return tuple(out)


def _segment_text(text: str, layout: dict[str, Any]) -> str:
    anchor = _obj(layout.get("textAnchor"))
    segments = _segments(anchor, text)
    return (
        "".join(text[s.start : s.end] for s in segments)
        if segments
        else str(anchor.get("content", ""))
    )


def _vertices(poly: Mapping[str, Any], name: str) -> tuple[tuple[float, float], ...]:
    points = []
    for vertex in _objects(poly.get(name, [])):
        x, y = _number(vertex.get("x", 0)), _number(vertex.get("y", 0))
        if x is None or y is None:
            return ()  # Native raw polygon retained in raw_response, not made usable.
        points.append((x, y))
    return tuple(points)


def _bounding_box(layout: dict[str, Any]) -> tuple[tuple[float, float], ...]:
    return _vertices(_obj(layout.get("boundingPoly")), "normalizedVertices")


def _layout(text: str, value: Any) -> OcrLine:
    layout = _obj(value)
    raw_text = _segment_text(text, layout)
    return OcrLine(
        raw_text.strip(),
        _score(layout.get("confidence")),
        _bounding_box(layout),
        _segments(_obj(layout.get("textAnchor")), text),
        _vertices(_obj(layout.get("boundingPoly")), "vertices"),
        layout.get("orientation") if isinstance(layout.get("orientation"), str) else None,
        raw_text,
    )


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _entity(
    value: dict[str, Any], text: str, pages: tuple[OcrPage, ...], depth: int = 0
) -> OcrEntity:
    if depth > 16:
        raise DocumentAIError("document_ai_failed", "EntityNestingTooDeep")
    refs = []
    for ref in _objects(_obj(value.get("pageAnchor")).get("pageRefs")):
        index = _int(ref.get("page", 0))
        if index is None or not 0 <= index < len(pages):
            raise DocumentAIError("document_ai_failed", "InvalidEntityPageRef")
        poly = _obj(ref.get("boundingPoly"))
        refs.append(
            EntityPageRef(
                index,
                pages[index].page_number,
                _vertices(poly, "normalizedVertices"),
                _vertices(poly, "vertices"),
            )
        )
    return OcrEntity(
        str(value.get("id", "")),
        str(value.get("type", "")),
        str(value.get("mentionText", "")),
        _score(value.get("confidence")),
        _segments(_obj(value.get("textAnchor")), text),
        copy.deepcopy(value.get("normalizedValue"))
        if isinstance(value.get("normalizedValue"), dict)
        else None,
        tuple(refs),
        tuple(_entity(p, text, pages, depth + 1) for p in _objects(value.get("properties"))),
    )


def parse_response(
    raw: Mapping[str, Any], *, metadata: RecognitionMetadata | None = None
) -> OcrResult:
    """Parse an existing REST process reply, without any network/storage side effect.

    Sharded batch replies are intentionally rejected: this client is online-only,
    and applying shard-offset anchors as local text would create false evidence.
    """
    if not isinstance(raw, Mapping) or not isinstance(raw.get("document"), dict):
        raise DocumentAIError("document_ai_failed", "MissingDocument")
    document = raw["document"]
    if _obj(document.get("error")).get("code", 0):
        raise DocumentAIError("document_ai_failed", "DocumentProcessingError")
    if (
        _int(_obj(document.get("shardInfo")).get("shardCount", 1), 1) != 1
        or _int(_obj(document.get("shardInfo")).get("textOffset", 0), 0) != 0
    ):
        raise DocumentAIError("document_ai_failed", "ShardedDocumentUnsupported")
    text = document.get("text", "")
    if not isinstance(text, str):
        raise DocumentAIError("document_ai_failed", "InvalidDocumentText")
    pages = []
    for index, page in enumerate(_objects(document.get("pages"))):
        number = _int(page.get("pageNumber", index + 1))
        if number is None or number < 1:
            raise DocumentAIError("document_ai_failed", "InvalidPageNumber")
        dim, layout = _obj(page.get("dimension")), _obj(page.get("layout"))
        tokens = []
        for token in _objects(page.get("tokens")):
            item = _layout(text, token.get("layout"))
            tokens.append(
                OcrToken(
                    item.text,
                    item.confidence,
                    item.bounding_box,
                    item.text_segments,
                    item.pixel_vertices,
                    item.orientation,
                    item.raw_text,
                    _obj(token.get("detectedBreak")).get("type"),
                )
            )
        quality = _obj(page.get("imageQualityScores"))
        image = None
        image_data = _obj(page.get("image"))
        if image_data.get("content"):
            encoded = image_data["content"]
            if not isinstance(encoded, str) or len(encoded) > 48 * 1024 * 1024:
                raise DocumentAIError("document_ai_failed", "InvalidPageImage")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                raise DocumentAIError("document_ai_failed", "InvalidPageImage") from None
            image = PageImage(
                content,
                str(image_data.get("mimeType", "")),
                _int(image_data.get("width")),
                _int(image_data.get("height")),
            )
        pages.append(
            OcrPage(
                number,
                _number(dim.get("width")),
                _number(dim.get("height")),
                _score(layout.get("confidence")),
                tuple(_layout(text, x.get("layout")) for x in _objects(page.get("lines"))),
                page_index=index,
                unit=dim.get("unit"),
                tokens=tuple(tokens),
                symbols=tuple(
                    _layout(text, x.get("layout")) for x in _objects(page.get("symbols"))
                ),
                visual_elements=tuple(
                    VisualElement(str(x.get("type", "")), _layout(text, x.get("layout")))
                    for x in _objects(page.get("visualElements"))
                ),
                form_fields=tuple(copy.deepcopy(_objects(page.get("formFields")))),
                tables=tuple(copy.deepcopy(_objects(page.get("tables")))),
                transforms=tuple(copy.deepcopy(_objects(page.get("transforms")))),
                image=image,
                image_quality=ImageQuality(
                    _score(quality.get("qualityScore")),
                    tuple(
                        QualityDefect(str(d.get("type", "")), _score(d.get("confidence")))
                        for d in _objects(quality.get("detectedDefects"))
                    ),
                )
                if quality
                else None,
                orientation=layout.get("orientation"),
            )
        )
    page_tuple = tuple(pages)
    if len({p.page_number for p in page_tuple}) != len(page_tuple):
        raise DocumentAIError("document_ai_failed", "DuplicatePageNumber")
    try:
        digest = _json_hash(document)
    except (ValueError, TypeError):
        raise DocumentAIError("document_ai_failed", "InvalidDocumentJson") from None
    page_tuple = tuple(replace(page, document_sha256=digest) for page in page_tuple)
    return OcrResult(
        text,
        page_tuple,
        copy.deepcopy(dict(raw)),
        entities=tuple(_entity(e, text, page_tuple) for e in _objects(document.get("entities"))),
        metadata=replace(metadata or RecognitionMetadata(), document_sha256=digest),
        document_layout=copy.deepcopy(document.get("documentLayout")),
        chunked_document=copy.deepcopy(document.get("chunkedDocument")),
    )


def _parse_document(document: dict[str, Any], raw: dict[str, Any]) -> OcrResult:
    # Retains the previous private helper for existing test/import compatibility.
    return parse_response({**raw, "document": document})
