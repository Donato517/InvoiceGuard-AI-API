"""模組名稱：tests.unit.test_document_ai_bundle
功能說明：Document AI 三模組的獨立離線反例、簽章、像素及多模態契約測試。
"""

import base64
import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import jwt
from PIL import Image, ImageDraw

from app.core.config import Settings
from app.integrations import document_ai as ocr
from app.integrations import document_ai_evidence as evidence
from app.integrations import document_ai_fewshot as fewshot


def picture(color: str = "red") -> bytes:
    """建立可做精確像素斷言的合成頁面。"""
    image = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(image).rectangle((20, 20, 59, 39), fill=color)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def source_for(content: bytes, identity: str = "target") -> evidence.SourceRef:
    """建立合成且彼此隔離的來源識別。"""
    return evidence.SourceRef.from_bytes(
        file_id=identity,
        version="v1",
        recognition_id=f"recognition-{identity}",
        document_group_id=f"group-{identity}",
        content=content,
    )


def native_result(content: bytes) -> ocr.OcrResult:
    """建立含原生頁圖、選頁頁碼及 Unicode 多段 anchor 的回應。"""
    vertices = [{"x": x, "y": y} for x, y in ((0.2, 0.2), (0.6, 0.2), (0.6, 0.4), (0.2, 0.4))]
    return ocr.parse_response(
        {
            "document": {
                "text": "甲😀乙\n",
                "pages": [
                    {
                        "pageNumber": 3,
                        "dimension": {"width": 72, "height": 72, "unit": "points"},
                        "image": {
                            "content": base64.b64encode(content).decode(),
                            "mimeType": "image/png",
                            "width": 100,
                            "height": 100,
                        },
                        "transforms": [{"rows": 3, "cols": 3, "type": 6, "data": "fixture"}],
                        "lines": [
                            {
                                "layout": {
                                    "textAnchor": {
                                        "textSegments": [
                                            {"startIndex": "1", "endIndex": "2"},
                                            {"startIndex": "2", "endIndex": "3"},
                                        ]
                                    },
                                    "confidence": 0,
                                    "boundingPoly": {"normalizedVertices": vertices},
                                }
                            }
                        ],
                    }
                ],
                "entities": [{"type": "amount", "pageAnchor": {"pageRefs": [{}]}}],
            }
        },
        metadata=ocr.RecognitionMetadata(source_sha256=evidence.sha256(content)),
    )


def artifact(identity: str, color: str) -> evidence.CropArtifact:
    """建立真正可解碼、去 metadata 的圖片證據。"""
    content = picture(color)
    source = source_for(content, identity)
    page = evidence.prepare_original_image(content, source=source)
    return evidence.full_page_evidence(page, evidence_id=identity)


def example_for(image: evidence.CropArtifact, **changes: Any) -> fewshot.VerifiedExample:
    """建立只驗證 amount 欄位的歷史範例，另含不應送出的欄位。"""
    values = dict(
        example_id="ex1",
        example_version="v1",
        scope_key="department-A",
        seller_tax_id="12345678",
        images=(image,),
        answers={"amount": "100", "private_unused": "not-forwarded"},
        answer_evidence={"amount": (image.artifact_id,)},
        verified_by="reviewer",
        verified_at=datetime.now(UTC) - timedelta(days=1),
    )
    return fewshot.VerifiedExample(**(values | changes))


def response_field(**changes: Any) -> dict[str, Any]:
    """建立一個語法正確但仍需人工核對的候選。"""
    return {
        "field": "amount",
        "status": "observed",
        "value": "200",
        "evidence_ids": ["T1"],
        "note": "",
    } | changes


@pytest.fixture(scope="module")
def signing_keys() -> tuple[dict[str, str], bytes]:
    """只在記憶體生成 RSA 測試私鑰，不讀檔案或真實帳號。"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return (
        {
            "type": "service_account",
            "client_email": "synthetic@example.invalid",
            "private_key": private,
            "private_key_id": "unit-key",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
        public,
    )


def test_actual_google_auth_signature_and_claims(
    signing_keys: tuple[dict[str, str], bytes],
) -> None:
    """實際簽章並以公鑰驗證；不替換 _create_assertion。"""
    info, public = signing_keys
    now = int(time.time())
    assertion = ocr._create_assertion(info, now)
    claims = jwt.decode(assertion, certs={"unit-key": public}, audience=info["token_uri"])
    assert claims == {
        "iss": info["client_email"],
        "aud": info["token_uri"],
        "scope": ocr.TOKEN_SCOPE,
        "iat": now,
        "exp": now + 3600,
    }
    assert jwt.decode_header(assertion)["alg"] == "RS256"


def test_token_refresh_is_serialized_and_key_rotation_isolated(
    signing_keys: tuple[dict[str, str], bytes],
) -> None:
    """並行呼叫只換發一次，換金鑰身分後重新換發。"""
    ocr.clear_token_cache()
    requests = []
    barrier = Barrier(6)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "unit-token", "expires_in": 3600})
        return httpx.Response(200, json={"document": {"text": "", "pages": []}})

    info, _ = signing_keys
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = ocr.DocumentAIClient(
            project_id="test",
            location="us",
            processor_id="123",
            service_account_json=json.dumps(info),
            http=http,
        )

        def process(_: int) -> ocr.OcrResult:
            barrier.wait(timeout=10)
            return client.process(b"synthetic", "image/png", timeout_seconds=5)

        with ThreadPoolExecutor(max_workers=6) as pool:
            assert len(list(pool.map(process, range(6)))) == 6
        assert sum(r.url.host == "oauth2.googleapis.com" for r in requests) == 1
        rotated = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other = dict(
            info,
            private_key=rotated.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
        )
        ocr.DocumentAIClient(
            project_id="test",
            location="us",
            processor_id="123",
            service_account_json=json.dumps(other),
            http=http,
        ).process(b"x", "image/png")
        assert sum(r.url.host == "oauth2.googleapis.com" for r in requests) == 2
    ocr.clear_token_cache()


def test_native_unicode_scores_page_refs_and_raw_immutability() -> None:
    result = native_result(picture())
    assert result.pages[0].lines[0].text == "😀乙"
    assert result.pages[0].lines[0].confidence == 0
    assert result.confidence is None
    assert result.entities[0].page_refs[0].page_index == 0
    assert result.entities[0].page_refs[0].page_number == 3
    assert result.pages[0].transforms[0]["rows"] == 3
    assert "candidates" not in result.raw_response
    assert ocr.OcrLine("x", None, ()).text_segments == ()
    assert asdict(ocr.OcrResult("x", (), {}))["raw_response"] == {}
    json.dumps(result.raw_response, allow_nan=False)


def test_version_url_options_deadline_and_external_client_ownership() -> None:
    """選頁用原始頁碼，版本與選項可追溯，不關閉外部 HTTP client。"""
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"document": {"text": "synthetic", "pages": []}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with ocr.DocumentAIClient(
            project_id="test",
            location="eu",
            processor_id="123",
            processor_version="ocr-test-v2",
            processor_type="OCR_PROCESSOR",
            access_token_provider=lambda: "synthetic",
            http=http,
        ) as client:
            result = client.process(
                b"synthetic",
                "image/png",
                options=ocr.ProcessOptions(
                    profile="evidence", include_page_images=True, pages=(3, 5), enable_symbols=True
                ),
            )
        assert not http.is_closed
    assert str(sent[0].url).endswith(
        "/locations/eu/processors/123/processorVersions/ocr-test-v2:process"
    )
    body = json.loads(sent[0].content)
    assert body["processOptions"] == {
        "ocrConfig": {"enableSymbol": True},
        "individualPageSelector": {"pages": [3, 5]},
    }
    assert "pages.image" in body["fieldMask"] and "pages.symbols" in body["fieldMask"]
    assert result.metadata.requested_version == "ocr-test-v2"
    assert result.metadata.source_sha256 == evidence.sha256(b"synthetic")
    assert max(sent[0].extensions["timeout"].values()) <= 25


@pytest.mark.parametrize(
    "options",
    [
        ocr.ProcessOptions(pages=(True,)),
        ocr.ProcessOptions(pages=(1, 1)),
        ocr.ProcessOptions(pages=None),
        ocr.ProcessOptions(language_hints=None),
        ocr.ProcessOptions(profile="quality"),
        ocr.ProcessOptions(profile="layout"),
        ocr.ProcessOptions(layout_chunk_size=0),
    ],
)
def test_invalid_options_never_send_paid_request(options: ocr.ProcessOptions) -> None:
    sent = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: sent.append(request))) as http:
        client = ocr.DocumentAIClient(
            project_id="test",
            location="us",
            processor_id="123",
            processor_type="INVOICE_PROCESSOR",
            access_token_provider=lambda: "synthetic",
            http=http,
        )
        with pytest.raises(ocr.DocumentAIError):
            client.process(b"synthetic", "image/png", options=options)
    assert not sent


def test_request_size_limit_skips_backend_and_multiple_targets_require_field_binding() -> None:
    target, historical = artifact("t", "red"), artifact("h", "blue")
    client = fewshot.FewShotClient(
        fewshot.CallableBackend(lambda *a, **kw: pytest.fail("must not call")),
        model="synthetic",
        policy=fewshot.FewShotPolicy(max_request_bytes=1),
    )
    values = dict(
        targets=(target,),
        fields=(fewshot.FieldRequest("amount", "amount"),),
        examples=(example_for(historical),),
        scope_key="department-A",
        seller_tax_id="12345678",
        supplier_verified=True,
        authorization_check=lambda _: True,
    )
    result = client.review(**values)
    assert result.status == "skipped" and result.reason == "RequestBudgetExceeded"
    second = replace(target, artifact_id="different-crop")
    with pytest.raises(fewshot.FewShotError) as error:
        client.review(**(values | {"targets": (target, second)}))
    assert error.value.detail == "InvalidFieldTargetEvidence"


@pytest.mark.parametrize(
    "value,valid", [("2026-10-30", True), ("2026-02-30", False), ("2026/10/30", False)]
)
def test_date_candidates_use_real_iso_dates(value: str, valid: bool) -> None:
    values = dict(
        fields=(fewshot.FieldRequest("amount", "date", "date"),), target_aliases={"T1": "image"}
    )
    payload = {"fields": [response_field(value=value)]}
    if valid:
        assert fewshot.validate_candidates(payload, **values)[0].value == value
    else:
        with pytest.raises(fewshot.FewShotError):
            fewshot.validate_candidates(payload, **values)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (0, 0.0),
        (1, 1.0),
        (True, None),
        (-0.1, None),
        (1.1, None),
        (".9", None),
        (float("nan"), None),
    ],
)
def test_confidence_never_invents_or_coerces_scores(value: Any, expected: float | None) -> None:
    assert ocr._score(value) == expected


def test_binding_pixel_crop_and_provenance() -> None:
    content = picture()
    source = source_for(content)
    result = evidence.bind_recognition(
        native_result(content), source=source, original_content=content
    )
    page = evidence.prepare_document_page(
        result, source=source, original_content=content, page_number=3
    )
    region = evidence.region_from_line(result.pages[0], 0, source=source)
    crop = evidence.crop_evidence(page, (region,), padding_ratio=0, min_padding_pixels=0)
    assert crop.pixel_box == (20, 20, 60, 40)
    with Image.open(io.BytesIO(crop.image_bytes)) as image:
        assert image.size == (40, 20)
        assert set(image.get_flattened_data()) == {(255, 0, 0)}
        assert not image.info
    assert crop.source == source and crop.page_number == 3 and crop.page_index == 0
    assert crop.provenance()["source"]["recognition_id"] == source.recognition_id
    assert crop.provenance()["document_sha256"] == result.metadata.document_sha256
    assert content == picture()


@pytest.mark.parametrize(
    "change",
    [
        {"version": "v2"},
        {"file_id": "other"},
        {"recognition_id": "another-run"},
        {"document_group_id": "other-group"},
    ],
)
def test_bound_recognition_cannot_be_relabelled(change: dict[str, str]) -> None:
    content = picture()
    source = source_for(content)
    result = evidence.bind_recognition(
        native_result(content), source=source, original_content=content
    )
    with pytest.raises(evidence.EvidenceError, match="source_mismatch"):
        evidence.prepare_document_page(
            result, source=replace(source, **change), original_content=content, page_number=3
        )
    with pytest.raises(evidence.EvidenceError, match="source_mismatch"):
        evidence.bind_recognition(
            result, source=replace(source, **change), original_content=content
        )


def test_unbound_recognition_and_same_size_wrong_image_are_rejected() -> None:
    content = picture()
    source = source_for(content)
    result = native_result(content)
    with pytest.raises(evidence.EvidenceError, match="source_mismatch"):
        evidence.prepare_document_page(
            result, source=source, original_content=content, page_number=3
        )
    with pytest.raises(evidence.EvidenceError, match="source_mismatch"):
        evidence.bind_recognition(result, source=source, original_content=picture("blue"))
    result = evidence.bind_recognition(result, source=source, original_content=content)
    page = evidence.prepare_document_page(
        result, source=source, original_content=content, page_number=3
    )
    region = evidence.region_from_line(result.pages[0], 0, source=source)
    with pytest.raises(evidence.EvidenceError, match="source_mismatch"):
        evidence.crop_evidence(replace(page, image_bytes=picture("blue")), (region,))
    other = replace(region, document_sha256="a" * 64)
    with pytest.raises(evidence.EvidenceError, match="source_mismatch"):
        evidence.crop_evidence(page, (other,))


def test_missing_native_image_requires_explicit_whole_page_fallback() -> None:
    content = picture()
    source = source_for(content)
    result = native_result(content)
    result = replace(result, pages=(replace(result.pages[0], image=None),))
    result = evidence.bind_recognition(result, source=source, original_content=content)
    with pytest.raises(evidence.EvidenceError, match="source_not_locatable"):
        evidence.prepare_document_page(
            result, source=source, original_content=content, page_number=3
        )
    fallback = evidence.prepare_original_image(content, source=source)
    assert (
        evidence.full_page_evidence(fallback, evidence_id="fallback").coordinate_space
        == "original_oriented"
    )


@pytest.mark.parametrize(
    "polygon",
    [
        ((0, 0), (1, 1), (0, 1), (1, 0)),
        ((0, 0), (0, 0), (0, 0)),
        ((-0.1, 0), (1, 0), (1, 1)),
        ((0, 0), (float("nan"), 0), (1, 1)),
    ],
)
def test_invalid_polygon_is_rejected(polygon: tuple[tuple[float, float], ...]) -> None:
    with pytest.raises(evidence.EvidenceError, match="invalid_polygon"):
        evidence.validate_polygon(polygon)


def test_pdf_optional_dependency_does_not_break_images(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    content = b"%PDF-synthetic"
    with pytest.raises(evidence.EvidenceError, match="renderer_unavailable"):
        evidence.render_pdf_page(content, source=source_for(content), page_number=1)
    assert artifact("image", "red").width == 100


def test_exif_orientation_and_explicit_homography() -> None:
    image = Image.new("RGB", (40, 20), "red")
    exif = Image.Exif()
    exif[274] = 6
    stream = io.BytesIO()
    image.save(stream, format="JPEG", exif=exif)
    content = stream.getvalue()
    source = source_for(content)
    page = evidence.prepare_original_image(content, source=source)
    assert (page.width, page.height) == (20, 40)
    region = evidence.EvidenceRegion(
        "r", source, 1, 0, "docai_page", ((0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4))
    )
    with pytest.raises(evidence.EvidenceError, match="source_mismatch"):
        evidence.crop_evidence(page, (region,))
    transformed = evidence.transform_region(
        region,
        destination=page,
        normalized_homography=((1, 0, 0.1), (0, 1, 0), (0, 0, 1)),
        mapping_note="synthetic translation",
    )
    assert transformed.polygon[0] == pytest.approx((0.3, 0.2))
    assert evidence.crop_evidence(page, (transformed,)).coordinate_space == "original_oriented"


def test_fewshot_sends_real_images_and_only_verified_requested_labels() -> None:
    target, historical = artifact("t", "red"), artifact("h", "blue")
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [{"text": json.dumps({"fields": [response_field()]})}]
                        },
                    }
                ]
            },
        )

    configuration = Settings(
        _env_prefix="IG_UNIT_TEST_",
        GEMINI_API_KEY="synthetic-key",
        GEMINI_MODEL="synthetic-image-model",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with fewshot.FewShotClient.from_settings(configuration, http=http) as client:
            result = client.review(
                targets=(target,),
                fields=(fewshot.FieldRequest("amount", "amount", "decimal"),),
                examples=(example_for(historical),),
                scope_key="department-A",
                seller_tax_id="12345678",
                supplier_verified=True,
                authorization_check=lambda _: True,
                timeout_seconds=2,
            )
        assert not http.is_closed
    assert result.status == "completed" and result.candidate_values() == {"amount": "200"}
    assert result.candidates[0].requires_human_review
    assert result.usage == {}  # 缺值不是零用量。
    body = json.loads(sent[0].content)
    parts = body["contents"][0]["parts"]
    images = [base64.b64decode(p["inlineData"]["data"]) for p in parts if "inlineData" in p]
    assert images == [historical.image_bytes, target.image_bytes]
    assert b"not-forwarded" not in sent[0].content
    assert b"private_unused" not in sent[0].content
    assert "responseJsonSchema" in body["generationConfig"]
    assert sent[0].headers["x-goog-api-key"] == "synthetic-key"
    assert "key=" not in str(sent[0].url)
    assert result.target_recognition_id == target.source.recognition_id


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "revoked"},
        {"status": "retired"},
        {"status": "candidate"},
        {"scope_key": "department-B"},
        {"seller_tax_id": "87654321"},
        {"template_key": "other"},
        {"expires_at": datetime(2000, 1, 1, tzinfo=UTC)},
        {"verified_at": datetime(2099, 1, 1, tzinfo=UTC)},
    ],
)
def test_wrong_or_withdrawn_examples_never_reach_backend(changes: dict[str, Any]) -> None:
    target, historical = artifact("t", "red"), artifact("h", "blue")
    selected = fewshot.select_verified_examples(
        (example_for(historical, **changes),),
        scope_key="department-A",
        seller_tax_id="12345678",
        invoice_kind="triplicate_handwritten",
        template_key=None,
        field_keys=("amount",),
        targets=(target,),
        authorization_check=lambda _: True,
        policy=fewshot.FewShotPolicy(),
    )
    assert selected == ()


@pytest.mark.parametrize("authorization", [False, None, 1, "true", "exception"])
def test_authorization_fails_closed(authorization: Any) -> None:
    target, historical = artifact("t", "red"), artifact("h", "blue")

    def check(_: fewshot.VerifiedExample) -> bool:
        if authorization == "exception":
            raise RuntimeError("private detail must not escape")
        return authorization

    assert (
        fewshot.select_verified_examples(
            (example_for(historical),),
            scope_key="department-A",
            seller_tax_id="12345678",
            invoice_kind="triplicate_handwritten",
            template_key=None,
            field_keys=("amount",),
            targets=(target,),
            authorization_check=check,
            policy=fewshot.FewShotPolicy(),
        )
        == ()
    )


@pytest.mark.parametrize("identity", ["file_id", "sha256", "document_group_id"])
def test_same_file_hash_or_retake_group_is_excluded(identity: str) -> None:
    target, historical = artifact("t", "red"), artifact("h", "blue")
    historical = replace(
        historical,
        source=replace(historical.source, **{identity: getattr(target.source, identity)}),
    )
    assert (
        fewshot.select_verified_examples(
            (example_for(historical),),
            scope_key="department-A",
            seller_tax_id="12345678",
            invoice_kind="triplicate_handwritten",
            template_key=None,
            field_keys=("amount",),
            targets=(target,),
            authorization_check=lambda _: True,
            policy=fewshot.FewShotPolicy(),
        )
        == ()
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"field": "unknown"},
        {"evidence_ids": ["E1_1"]},
        {"evidence_ids": ["T999"]},
        {"evidence_ids": []},
        {"value": True},
        {"value": "NaN"},
        {"value": "Infinity"},
        {"value": "1,000"},
        {"status": "unreadable", "value": "12"},
        {"status": "observed", "value": None},
        {"evidence_ids": ["T1", "T1"]},
    ],
)
def test_invalid_candidates_are_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(fewshot.FewShotError, match="fewshot_invalid_response"):
        fewshot.validate_candidates(
            {"fields": [response_field(**changes)]},
            fields=(fewshot.FieldRequest("amount", "amount", "decimal"),),
            target_aliases={"T1": "amount-image"},
        )


def test_field_cannot_cite_another_fields_target_image() -> None:
    fields = (
        fewshot.FieldRequest("amount", "amount", "decimal", target_artifact_ids=("amount-image",)),
    )
    with pytest.raises(fewshot.FewShotError) as error:
        fewshot.validate_candidates(
            {"fields": [response_field(evidence_ids=["T2"])]},
            fields=fields,
            target_aliases={"T1": "amount-image", "T2": "date-image"},
        )
    assert error.value.detail == "EvidenceBelongsToAnotherField"
    valid = fewshot.validate_candidates(
        {"fields": [response_field()]},
        fields=fields,
        target_aliases={"T1": "amount-image", "T2": "date-image"},
    )
    assert valid[0].evidence_ids == ("amount-image",)


@pytest.mark.parametrize(
    "payload",
    [
        {"fields": []},
        {"fields": [response_field(), response_field()]},
        '{"fields":[],"fields":[]}',
        '{"fields":NaN}',
    ],
)
def test_missing_duplicate_and_malformed_fields_fail(payload: Any) -> None:
    with pytest.raises(fewshot.FewShotError):
        fewshot.validate_candidates(
            payload,
            fields=(fewshot.FieldRequest("amount", "amount"),),
            target_aliases={"T1": "image"},
        )


@pytest.mark.parametrize("status", ["missing", "ambiguous", "unreadable"])
def test_nonobserved_status_preserves_null(status: str) -> None:
    result = fewshot.validate_candidates(
        {"fields": [response_field(status=status, value=None, evidence_ids=[])]},
        fields=(fewshot.FieldRequest("amount", "amount"),),
        target_aliases={"T1": "image"},
    )
    assert result[0].value is None


@pytest.mark.parametrize(
    "payload",
    [
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {"candidates": [{"finishReason": "MAX_TOKENS"}]},
        {"candidates": [{"finishReason": "SAFETY"}]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": []}}]},
        {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"parts": [{"thought": True, "text": "secret"}]},
                }
            ]
        },
        [],
        {"candidates": [1]},
    ],
)
def test_blocked_truncated_empty_or_malformed_gemini_reply_fails(payload: Any) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        backend = fewshot.GeminiRestBackend(api_key="synthetic", http=http)
        request = fewshot.ModelRequest("synthetic", "system", (), {})
        with pytest.raises(fewshot.FewShotError):
            backend.generate(request, timeout_seconds=1)


@pytest.mark.parametrize(
    "status,code",
    [(401, "fewshot_auth_failed"), (429, "fewshot_quota_exceeded"), (500, "fewshot_failed")],
)
def test_gemini_http_errors_have_no_retries_or_private_details(status: int, code: str) -> None:
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(status, json={"message": "private response"})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        pytest.raises(fewshot.FewShotError) as error,
    ):
        fewshot.GeminiRestBackend(api_key="synthetic", http=http).generate(
            fewshot.ModelRequest("synthetic", "system", (), {}), timeout_seconds=1
        )
    assert error.value.code == code and error.value.detail == f"HTTP{status}"
    assert len(sent) == 1


def test_supplier_unverified_or_backend_failure_never_creates_candidates() -> None:
    called = []

    def backend(request: fewshot.ModelRequest, *, timeout_seconds: float) -> fewshot.ModelReply:
        called.append(request)
        raise TimeoutError("synthetic")

    client = fewshot.FewShotClient(fewshot.CallableBackend(backend), model="synthetic")
    values = dict(
        targets=(artifact("t", "red"),),
        fields=(fewshot.FieldRequest("amount", "amount"),),
        examples=(example_for(artifact("h", "blue")),),
        scope_key="department-A",
        seller_tax_id="12345678",
        authorization_check=lambda _: True,
    )
    skipped = client.review(**values, supplier_verified=False)
    assert skipped.status == "skipped" and not called
    failed = client.review(**values, supplier_verified=True)
    assert (
        failed.status == "failed" and failed.reason == "fewshot_timeout" and not failed.candidates
    )
    assert len(called) == 1
