"""
模組名稱：app.integrations.supabase_storage
功能說明：Vercel 模組（檔案存取）——Supabase Storage S3 相容端點的用戶端（AWS SigV4，標準函式庫）：
    上傳、下載、列表、移動、刪除。
使用方式：
    from app.integrations.supabase_storage import S3StorageClient

    storage = S3StorageClient.from_settings()
    storage.put("folder/a.png", data, content_type="image/png")
注意事項：
    - 示範（/dev/files）與正式功能都使用此模組；ADMIN 與 API 的本檔內容相同，修改時兩站同步。
    - 設定來自 S3_ENDPOINT_URL、S3_REGION、S3_ACCESS_KEY_ID、S3_SECRET_ACCESS_KEY、SUPABASE_STORAGE_BUCKET。
    - 物件鍵由上層服務產生；HTTP／連線錯誤轉成固定代碼，只附 S3 錯誤代碼（如 NoSuchKey），不含金鑰、簽章或網址。
"""

import hashlib
import hmac
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.core.config import Settings, settings

TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
S3_NAMESPACE = "{http://s3.amazonaws.com/doc/2006-03-01/}"

StorageCode = Literal[
    "storage_not_configured",
    "storage_unreachable",
    "storage_denied",
    "storage_not_found",
    "storage_type_rejected",
    "storage_failed",
]


class StorageError(RuntimeError):
    """Storage 操作失敗；code 為固定代碼，detail 只放 S3 錯誤代碼。"""

    def __init__(self, code: StorageCode, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


@dataclass(frozen=True)
class StoredObject:
    """列表結果的一筆物件。"""

    key: str
    size_bytes: int
    last_modified: datetime


def _encode(value: str, safe: str = "-_.~") -> str:
    return urllib.parse.quote(value, safe=safe)


def _query_string(query: dict[str, str]) -> str:
    return "&".join(f"{_encode(name)}={_encode(value)}" for name, value in sorted(query.items()))


def sign_v4(
    method: str,
    host: str,
    path: str,
    query: dict[str, str],
    headers: dict[str, str],
    payload_hash: str,
    *,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
    now: datetime,
) -> dict[str, str]:
    """以 AWS Signature Version 4 簽署請求；path 必須已是編碼後的路徑。

    Returns:
        要送出的標頭（含 x-amz-date 與 Authorization，不含 host）。
    """
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    signed = {name.lower(): " ".join(value.split()) for name, value in headers.items()}
    signed.update(host=host, **{"x-amz-date": amz_date})
    names = sorted(signed)
    canonical = "\n".join(
        [
            method,
            path,
            _query_string(query),
            "".join(f"{name}:{signed[name]}\n" for name in names),
            ";".join(names),
            payload_hash,
        ]
    )
    scope = f"{amz_date[:8]}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    key = f"AWS4{secret_key}".encode()
    for part in (amz_date[:8], region, service, "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    signed.pop("host")
    signed["Authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={';'.join(names)}, Signature={signature}"
    )
    return signed


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """3xx 不跟隨，避免把簽章送到其他位置。"""

    def redirect_request(self, *_: Any, **__: Any) -> None:
        return None


class S3StorageClient:
    """Supabase Storage 的 S3 相容端點（path-style）。"""

    def __init__(
        self,
        *,
        endpoint_url: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        parts = urllib.parse.urlsplit(endpoint_url.strip().rstrip("/"))
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or not all(value.strip() for value in (region, access_key_id, secret_access_key))
            or not bucket.strip()
        ):
            raise StorageError("storage_not_configured")
        self._host = parts.netloc
        self._base_path = parts.path
        self._region = region.strip()
        self._access_key = access_key_id.strip()
        self._secret_key = secret_access_key.strip()
        self._bucket = bucket.strip()
        self._opener = opener or urllib.request.build_opener(_NoRedirect)

    @classmethod
    def from_settings(cls, configuration: Settings | None = None) -> "S3StorageClient":
        """以 S3_* 與 SUPABASE_STORAGE_BUCKET 建立用戶端。

        Raises:
            StorageError: storage_not_configured——端點 scheme 不是 https、缺少 hostname、含非空的
                username／password／query，或 region／access key／secret key／bucket 去除空白後為空。
            ValueError: urlsplit 無法解析端點，例如 IPv6 括號格式錯誤。
        """
        configuration = configuration if configuration is not None else settings
        return cls(
            endpoint_url=configuration.S3_ENDPOINT_URL,
            region=configuration.S3_REGION,
            access_key_id=configuration.S3_ACCESS_KEY_ID.get_secret_value(),
            secret_access_key=configuration.S3_SECRET_ACCESS_KEY.get_secret_value(),
            bucket=configuration.SUPABASE_STORAGE_BUCKET,
        )

    def put(self, key: str, data: bytes, *, content_type: str) -> None:
        """上傳（同鍵覆寫）；物件鍵由 service 產生。"""
        self._request("PUT", key, body=data, headers={"content-type": content_type})

    def get(self, key: str) -> tuple[bytes, str]:
        """下載物件內容與 Content-Type。"""
        _, headers, body = self._request("GET", key)
        return body, headers.get("content-type", "application/octet-stream")

    def list_objects(self, prefix: str) -> list[StoredObject]:
        """列出前綴底下所有物件（含子資料夾），依鍵排序。"""
        objects: list[StoredObject] = []
        query = {"list-type": "2", "prefix": prefix}
        while True:
            _, _, body = self._request("GET", "", query=query)
            try:
                root = ElementTree.fromstring(body)
                for item in root.iter(S3_NAMESPACE + "Contents"):
                    objects.append(
                        StoredObject(
                            key=item.findtext(S3_NAMESPACE + "Key", ""),
                            size_bytes=int(item.findtext(S3_NAMESPACE + "Size", "0")),
                            last_modified=datetime.fromisoformat(
                                item.findtext(S3_NAMESPACE + "LastModified", "")
                            ),
                        )
                    )
                token = root.findtext(S3_NAMESPACE + "NextContinuationToken")
                truncated = root.findtext(S3_NAMESPACE + "IsTruncated") == "true"
            except (ElementTree.ParseError, ValueError):
                raise StorageError("storage_failed", "InvalidListResponse") from None
            if not truncated or not token:
                return sorted(objects, key=lambda stored: stored.key)
            query = {**query, "continuation-token": token}

    def move(self, source_key: str, destination_key: str) -> None:
        """S3 沒有原生移動：先複製到新鍵，成功後刪除原鍵。"""
        source = _encode(f"{self._bucket}/{source_key}", safe="/-_.~")
        _, _, body = self._request("PUT", destination_key, headers={"x-amz-copy-source": source})
        if b"<Error>" in body:
            raise StorageError("storage_failed", _error_code(body))
        self.delete(source_key)

    def delete(self, key: str) -> None:
        """刪除物件；不存在時 S3 仍回成功。"""
        self._request("DELETE", key)

    def _request(
        self,
        method: str,
        key: str,
        *,
        query: dict[str, str] | None = None,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        query = query or {}
        path = f"{self._base_path}/{_encode(self._bucket)}"
        if key:
            path += "/" + _encode(key, safe="/-_.~")
        payload_hash = hashlib.sha256(body).hexdigest()
        signed = sign_v4(
            method,
            self._host,
            path,
            query,
            {**(headers or {}), "x-amz-content-sha256": payload_hash},
            payload_hash,
            access_key=self._access_key,
            secret_key=self._secret_key,
            region=self._region,
            service="s3",
            now=datetime.now(UTC),
        )
        url = f"https://{self._host}{path}" + (f"?{_query_string(query)}" if query else "")
        request = urllib.request.Request(
            url, data=body if method in {"PUT", "POST"} else None, headers=signed, method=method
        )
        try:
            with self._opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                content = response.read(MAX_RESPONSE_BYTES)
                return response.status, {k.lower(): v for k, v in response.headers.items()}, content
        except urllib.error.HTTPError as error:
            with error:
                detail = _error_code(error.read(65536))
            if error.code in {401, 403}:
                raise StorageError("storage_denied", detail) from None
            if error.code == 404:
                raise StorageError("storage_not_found", detail) from None
            if error.code == 415:
                # Bucket 設定了 Allowed MIME types，且不含此 Content-Type
                raise StorageError("storage_type_rejected", detail or "HTTP415") from None
            raise StorageError("storage_failed", detail or f"HTTP{error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise StorageError("storage_unreachable") from None


def _error_code(body: bytes) -> str:
    """只取 S3 錯誤 XML 的 <Code>（英數字），不回傳訊息原文。"""
    try:
        code = ElementTree.fromstring(body).findtext("Code") or ""
    except ElementTree.ParseError:
        return ""
    return code if code.isalnum() and len(code) <= 64 else ""
