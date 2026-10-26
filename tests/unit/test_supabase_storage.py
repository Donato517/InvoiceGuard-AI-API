"""模組名稱：tests.unit.test_supabase_storage；功能說明：Supabase Storage S3 用戶端（與 ADMIN 相同）測試；全部使用合成資料與替身，不連網路。"""

import hashlib
import io
import urllib.error
import urllib.parse
from datetime import UTC, datetime
from email.message import Message
from typing import Any

import pytest

from app.core.config import Settings
from app.integrations import supabase_storage

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
SECRET = "SYNTHETIC-SECRET-ACCESS-KEY"


def make_settings(**values: Any) -> Settings:
    """以隔離前綴與合成值建構，不讀取公司環境變數。"""
    return Settings(_env_file=None, _env_prefix="IG_UNIT_TEST_", **values)


# ---- SigV4 ----


def test_sign_v4_matches_aws_reference_vector() -> None:
    """AWS SigV4 測試套件 get-vanilla。"""
    headers = supabase_storage.sign_v4(
        "GET",
        "example.amazonaws.com",
        "/",
        {},
        {},
        hashlib.sha256(b"").hexdigest(),
        access_key="AKIDEXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        region="us-east-1",
        service="service",
        now=datetime(2015, 8, 30, 12, 36, tzinfo=UTC),
    )
    assert headers["x-amz-date"] == "20150830T123600Z"
    assert headers["Authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
        "SignedHeaders=host;x-amz-date, "
        "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
    )


# ---- S3 用戶端 ----


class FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.status, self.body = status, body
        self.headers = Message()
        for name, value in headers.items():
            self.headers[name] = value

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def read(self, _: int) -> bytes:
        return self.body


class FakeOpener:
    """記錄請求並依序回傳預設回應；回應為 (status, body) 或 (status, body, headers)。"""

    def __init__(self, *responses: tuple[Any, ...]) -> None:
        self.responses = list(responses)
        self.requests: list[Any] = []

    def open(self, request: Any, timeout: float) -> FakeResponse:
        self.requests.append(request)
        status, body, *rest = self.responses.pop(0)
        headers = rest[0] if rest else {}
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "x", Message(), io.BytesIO(body))
        return FakeResponse(status, body, headers)


def client(opener: FakeOpener) -> supabase_storage.S3StorageClient:
    return supabase_storage.S3StorageClient(
        endpoint_url="https://ref.storage.example.com/storage/v1/s3",
        region="synthetic-1",
        access_key_id="SYNTHETICACCESS",
        secret_access_key=SECRET,
        bucket="bucket",
        opener=opener,  # type: ignore[arg-type]
    )


def test_put_signs_path_style_request_with_payload_hash() -> None:
    opener = FakeOpener((200, b""))
    client(opener).put("dev/images/a.png", PNG, content_type="image/png")
    request = opener.requests[0]
    assert request.get_method() == "PUT"
    assert (
        request.full_url == "https://ref.storage.example.com/storage/v1/s3/bucket/dev/images/a.png"
    )
    headers = {name.lower(): value for name, value in request.header_items()}
    assert headers["x-amz-content-sha256"] == hashlib.sha256(PNG).hexdigest()
    assert headers["content-type"] == "image/png"
    assert headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=SYNTHETICACCESS/")
    assert "/synthetic-1/s3/aws4_request" in headers["authorization"]
    assert "content-type;host;x-amz-content-sha256;x-amz-date" in headers["authorization"]
    assert SECRET not in str(request.header_items())
    assert request.data == PNG


def test_list_objects_follows_continuation_and_parses_xml() -> None:
    namespace = "http://s3.amazonaws.com/doc/2006-03-01/"

    def page(keys: list[str], token: str | None) -> bytes:
        items = "".join(
            f"<Contents><Key>{key}</Key><Size>3</Size>"
            "<LastModified>2026-10-25T07:00:00.000Z</LastModified></Contents>"
            for key in keys
        )
        more = (
            f"<IsTruncated>true</IsTruncated><NextContinuationToken>{token}</NextContinuationToken>"
            if token
            else "<IsTruncated>false</IsTruncated>"
        )
        return f'<ListBucketResult xmlns="{namespace}">{items}{more}</ListBucketResult>'.encode()

    opener = FakeOpener((200, page(["dev/rag/b.txt"], "T1")), (200, page(["dev/rag/a.txt"], None)))
    objects = client(opener).list_objects("dev/rag/")
    assert [stored.key for stored in objects] == ["dev/rag/a.txt", "dev/rag/b.txt"]
    assert objects[0].size_bytes == 3 and objects[0].last_modified.tzinfo is not None
    first, second = (urllib.parse.urlsplit(r.full_url) for r in opener.requests)
    assert first.path == "/storage/v1/s3/bucket"
    assert urllib.parse.parse_qs(first.query) == {"list-type": ["2"], "prefix": ["dev/rag/"]}
    assert urllib.parse.parse_qs(second.query)["continuation-token"] == ["T1"]


def test_get_move_and_delete() -> None:
    opener = FakeOpener(
        (200, b"hello", {"Content-Type": "text/plain; charset=utf-8"}),
        (200, b"<CopyObjectResult></CopyObjectResult>"),
        (204, b""),
    )
    storage = client(opener)
    assert storage.get("dev/rag/a.txt") == (b"hello", "text/plain; charset=utf-8")
    storage.move("dev/rag/a.txt", "dev/rag/archive/a.txt")
    get, copy, delete = opener.requests
    assert copy.get_method() == "PUT"
    assert copy.full_url.endswith("/bucket/dev/rag/archive/a.txt")
    assert dict(copy.header_items())["X-amz-copy-source"] == "bucket/dev/rag/a.txt"
    assert (delete.get_method(), delete.full_url.endswith("/bucket/dev/rag/a.txt")) == (
        "DELETE",
        True,
    )


@pytest.mark.parametrize(
    "status,code",
    [
        (403, "storage_denied"),
        (404, "storage_not_found"),
        (415, "storage_type_rejected"),
        (500, "storage_failed"),
    ],
)
def test_http_errors_become_fixed_codes_with_s3_code_only(status: int, code: str) -> None:
    body = b"<Error><Code>NoSuchKey</Code><Message>secret detail</Message></Error>"
    with pytest.raises(supabase_storage.StorageError) as caught:
        client(FakeOpener((status, body))).get("dev/rag/a.txt")
    assert (caught.value.code, caught.value.detail) == (code, "NoSuchKey")


def test_failed_copy_does_not_delete_source() -> None:
    opener = FakeOpener((200, b"<Error><Code>InternalError</Code></Error>"))
    with pytest.raises(supabase_storage.StorageError):
        client(opener).move("dev/rag/a.txt", "dev/rag/b/a.txt")
    assert len(opener.requests) == 1


def test_network_error_is_unreachable() -> None:
    class Broken:
        def open(self, request: Any, timeout: float) -> Any:
            raise urllib.error.URLError("synthetic")

    storage = client(Broken())  # type: ignore[arg-type]
    with pytest.raises(supabase_storage.StorageError) as caught:
        storage.delete("dev/rag/a.txt")
    assert caught.value.code == "storage_unreachable"


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"S3_ENDPOINT_URL": "http://ref.example.com/s3"},
        {"S3_ENDPOINT_URL": "https://ref.example.com/s3", "S3_REGION": "r"},
    ],
)
def test_missing_settings_are_not_configured(values: dict[str, str]) -> None:
    with pytest.raises(supabase_storage.StorageError) as caught:
        supabase_storage.S3StorageClient.from_settings(make_settings(**values))
    assert caught.value.code == "storage_not_configured"


def test_from_settings_uses_s3_variables_and_bucket() -> None:
    configured = make_settings(
        S3_ENDPOINT_URL="https://ref.example.com/storage/v1/s3",
        S3_REGION="synthetic-1",
        S3_ACCESS_KEY_ID="A",
        S3_SECRET_ACCESS_KEY="B",
        SUPABASE_STORAGE_BUCKET="bucket",
    )
    assert isinstance(
        supabase_storage.S3StorageClient.from_settings(configured),
        supabase_storage.S3StorageClient,
    )
