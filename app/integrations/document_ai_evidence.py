"""模組名稱：app.integrations.document_ai_evidence
功能說明：綁定辨識來源、準備原生頁面與產生可追溯裁圖。

No OCR, network, file writes, DB queries or image enhancement. Uses the returned
Document AI page image first because its annotations are in that image space.
Raw originals and independently rendered PDF pages have DIFFERENT spaces. Cross-
space crops require an explicit, externally validated homography; never guessed.

Pillow is required. pypdfium2 is optional and used ONLY by render_pdf_page().
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import threading
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

if __package__:
    from .document_ai import OcrPage, OcrResult, TextSegment
else:
    from document_ai import OcrPage, OcrResult, TextSegment

CROP_RECIPE_VERSION = "invoiceguard-crop/1.0.0"
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_BYTES = 32 * 1024 * 1024
COORDINATE_SPACES = frozenset({"docai_page", "original_oriented", "rendered_pdf"})
_PDF_LOCK = threading.Lock()
Point = tuple[float, float]
Polygon = tuple[Point, ...]


class EvidenceError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _nonempty(value: str) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) <= 256


@dataclass(frozen=True)
class SourceRef:
    """Opaque identity supplied by authenticated service, not by model output."""

    file_id: str
    version: str
    sha256: str
    recognition_id: str
    document_group_id: str | None = None  # invoice_id / retake family, supplied by service.

    def __post_init__(self) -> None:
        if not all(_nonempty(v) for v in (self.file_id, self.version, self.recognition_id)):
            raise EvidenceError("invalid_source", "MissingIdentity")
        if self.document_group_id is not None and not _nonempty(self.document_group_id):
            raise EvidenceError("invalid_source", "InvalidDocumentGroup")
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise EvidenceError("invalid_source", "InvalidContentHash")

    @classmethod
    def from_bytes(
        cls,
        *,
        file_id: str,
        version: str,
        recognition_id: str,
        content: bytes,
        document_group_id: str | None = None,
    ) -> SourceRef:
        if not isinstance(content, bytes) or not content:
            raise EvidenceError("invalid_source", "EmptyContent")
        return cls(file_id, version, sha256(content), recognition_id, document_group_id)


@dataclass(frozen=True)
class PreparedPage:
    source: SourceRef
    page_number: int
    page_index: int
    coordinate_space: str
    image_bytes: bytes = field(repr=False)
    width: int
    height: int
    image_sha256: str
    mime_type: str = "image/png"
    document_sha256: str = ""
    mapping_note: str = ""


@dataclass(frozen=True)
class EvidenceRegion:
    evidence_id: str
    source: SourceRef
    page_number: int
    page_index: int
    coordinate_space: str
    polygon: Polygon
    text_segments: tuple[TextSegment, ...] = ()
    origin: str = "application_region"
    mapping_note: str = ""
    document_sha256: str = ""

    def __post_init__(self) -> None:
        if not _nonempty(self.evidence_id):
            raise EvidenceError("invalid_region", "MissingEvidenceId")
        _page_identity(self.page_number, self.page_index, self.coordinate_space)
        validate_polygon(self.polygon)


@dataclass(frozen=True)
class CropArtifact:
    artifact_id: str
    source: SourceRef
    page_number: int
    page_index: int
    coordinate_space: str
    image_bytes: bytes = field(repr=False)
    mime_type: str
    width: int
    height: int
    sha256: str
    source_image_sha256: str
    pixel_box: tuple[int, int, int, int]
    regions: tuple[EvidenceRegion, ...]
    recipe_version: str = CROP_RECIPE_VERSION

    def provenance(self) -> dict[str, Any]:
        """Safe metadata container; image bytes excluded. Contents still need ACLs."""
        return {
            "artifact_id": self.artifact_id,
            "source": {
                "file_id": self.source.file_id,
                "version": self.source.version,
                "sha256": self.source.sha256,
                "recognition_id": self.source.recognition_id,
                "document_group_id": self.source.document_group_id,
            },
            "page_number": self.page_number,
            "page_index": self.page_index,
            "coordinate_space": self.coordinate_space,
            "image_sha256": self.sha256,
            "source_image_sha256": self.source_image_sha256,
            "document_sha256": self.regions[0].document_sha256 if self.regions else "",
            "pixel_box": list(self.pixel_box),
            "output_size": [self.width, self.height],
            "mime_type": self.mime_type,
            "recipe_version": self.recipe_version,
            "regions": [
                {
                    "evidence_id": r.evidence_id,
                    "polygon": [list(p) for p in r.polygon],
                    "text_segments": [{"start": s.start, "end": s.end} for s in r.text_segments],
                    "origin": r.origin,
                    "mapping_note": r.mapping_note,
                }
                for r in self.regions
            ],
        }


def _page_identity(page_number: int, page_index: int, space: str) -> None:
    if (
        type(page_number) is not int
        or page_number < 1
        or type(page_index) is not int
        or page_index < 0
    ):
        raise EvidenceError("invalid_page", "InvalidPageIndex")
    if space not in COORDINATE_SPACES:
        raise EvidenceError("invalid_page", "UnknownCoordinateSpace")


def validate_polygon(polygon: Sequence[Point]) -> Polygon:
    if not isinstance(polygon, (tuple, list)) or not 3 <= len(polygon) <= 64:
        raise EvidenceError("invalid_polygon", "VertexCount")
    points = []
    for point in polygon:
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            raise EvidenceError("invalid_polygon", "InvalidVertex")
        if any(
            type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in point
        ):
            raise EvidenceError("invalid_polygon", "OutOfBounds")
        points.append((float(point[0]), float(point[1])))
    area = (
        abs(
            sum(
                points[i][0] * points[(i + 1) % len(points)][1]
                - points[(i + 1) % len(points)][0] * points[i][1]
                for i in range(len(points))
            )
        )
        / 2
    )
    if area < 1e-12:
        raise EvidenceError("invalid_polygon", "ZeroArea")

    # Reject self-intersecting polygons rather than crop a misleading region.
    def crosses(a: Point, b: Point, c: Point, d: Point) -> bool:
        def side(p: Point, q: Point, r: Point) -> float:
            return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

        return side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0

    n = len(points)
    for i in range(n):
        for j in range(i + 1, n):
            if j in {i, (i + 1) % n} or (j + 1) % n == i:
                continue
            if crosses(points[i], points[(i + 1) % n], points[j], points[(j + 1) % n]):
                raise EvidenceError("invalid_polygon", "SelfIntersection")
    return tuple(points)


def _decode_image(content: bytes, *, apply_exif: bool = False) -> Image.Image:
    if not isinstance(content, bytes) or not content or len(content) > MAX_IMAGE_BYTES:
        raise EvidenceError("invalid_image", "InvalidByteSize")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in {"PNG", "JPEG"}:
                    raise EvidenceError("invalid_image", "UnsupportedImageFormat")
                if (
                    image.width * image.height > MAX_IMAGE_PIXELS
                    or image.width < 1
                    or image.height < 1
                ):
                    raise EvidenceError("invalid_image", "ImageTooLarge")
                if getattr(image, "n_frames", 1) != 1:
                    raise EvidenceError("invalid_image", "AnimatedImageUnsupported")
                image.load()
                oriented = ImageOps.exif_transpose(image) if apply_exif else image
                if oriented.mode in {"RGBA", "LA"} or (
                    oriented.mode == "P" and "transparency" in oriented.info
                ):
                    rgba = oriented.convert("RGBA")
                    result = Image.new("RGB", rgba.size, "white")
                    result.paste(rgba, mask=rgba.getchannel("A"))
                    return result
                return oriented.convert("RGB")
    except EvidenceError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise EvidenceError("invalid_image", "DecodeFailed") from None


def _png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    # Strip EXIF/text/ICC metadata. Never mutate or enhance source pixels.
    clean = Image.new("RGB", image.size)
    clean.paste(image)
    clean.save(output, format="PNG")
    data = output.getvalue()
    if len(data) > MAX_IMAGE_BYTES:
        raise EvidenceError("invalid_image", "EncodedImageTooLarge")
    return data


def _verify_source(content: bytes, source: SourceRef) -> None:
    if not isinstance(content, bytes) or sha256(content) != source.sha256:
        raise EvidenceError("source_mismatch", "ContentHashMismatch")


def bind_recognition(result: OcrResult, *, source: SourceRef, original_content: bytes) -> OcrResult:
    """由受信任 service 綁定目前檔案版本；已綁定結果不可改標。

    source 必須來自已驗權的辨識紀錄。資料庫版本及授權仍由 service 重驗。
    """
    _verify_source(original_content, source)
    meta = result.metadata
    if meta.source_sha256 != source.sha256 or not meta.document_sha256:
        raise EvidenceError("source_mismatch", "UnboundRecognition")
    current = (meta.file_id, meta.file_version, meta.recognition_id, meta.document_group_id)
    expected = (source.file_id, source.version, source.recognition_id, source.document_group_id)
    if any(current) and current != expected:
        raise EvidenceError("source_mismatch", "RecognitionIdentityMismatch")
    return replace(
        result,
        metadata=replace(
            meta,
            file_id=source.file_id,
            file_version=source.version,
            recognition_id=source.recognition_id,
            document_group_id=source.document_group_id,
        ),
    )


def prepare_document_page(
    result: OcrResult, *, source: SourceRef, original_content: bytes, page_number: int
) -> PreparedPage:
    """Use returned Page.image, with content/recognition binding validated.

    Parse stored responses with RecognitionMetadata(source_sha256=...) first.
    No fallback to raw image if corrected page image is absent.
    """
    _verify_source(original_content, source)
    if result.metadata.source_sha256 != source.sha256:
        raise EvidenceError("source_mismatch", "UnboundRecognition")
    meta = result.metadata
    if (meta.file_id, meta.file_version, meta.recognition_id, meta.document_group_id) != (
        source.file_id,
        source.version,
        source.recognition_id,
        source.document_group_id,
    ):
        raise EvidenceError("source_mismatch", "RecognitionIdentityMismatch")
    matches = [p for p in result.pages if p.page_number == page_number]
    if len(matches) != 1:
        raise EvidenceError("source_not_locatable", "PageNotFound")
    page = matches[0]
    if page.image is None or not page.image.content:
        raise EvidenceError("source_not_locatable", "PageImageMissing")
    image = _decode_image(page.image.content)
    if (page.image.width is not None and page.image.width != image.width) or (
        page.image.height is not None and page.image.height != image.height
    ):
        raise EvidenceError("source_not_locatable", "PageImageSizeMismatch")
    data = _png(image)
    return PreparedPage(
        source,
        page.page_number,
        page.page_index,
        "docai_page",
        data,
        image.width,
        image.height,
        sha256(data),
        document_sha256=result.metadata.document_sha256,
        mapping_note="NativeDocumentAIPageImage",
    )


def prepare_original_image(content: bytes, *, source: SourceRef) -> PreparedPage:
    """Oriented whole original for fallback viewing. NOT DocAI coordinate space."""
    _verify_source(content, source)
    image = _decode_image(content, apply_exif=True)
    data = _png(image)
    return PreparedPage(
        source,
        1,
        0,
        "original_oriented",
        data,
        image.width,
        image.height,
        sha256(data),
        mapping_note="EXIFOrientationApplied",
    )


def render_pdf_page(
    content: bytes, *, source: SourceRef, page_number: int, dpi: int = 144
) -> PreparedPage:
    """Render full PDF page for viewing. No equivalence to DocAI space is inferred.

    Install pypdfium2 to use. Encrypted, oversized and invalid PDFs are rejected.
    PDFium is guarded by a process-local lock because it is not thread-safe.
    """
    _verify_source(content, source)
    if not content.startswith(b"%PDF-") or len(content) > MAX_IMAGE_BYTES:
        raise EvidenceError("invalid_pdf", "InvalidByteSizeOrSignature")
    if (
        type(page_number) is not int
        or page_number < 1
        or type(dpi) is not int
        or not 36 <= dpi <= 300
    ):
        raise EvidenceError("invalid_pdf", "InvalidRenderOptions")
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise EvidenceError("renderer_unavailable", "InstallPypdfium2") from None
    try:
        with _PDF_LOCK, pdfium.PdfDocument(content) as document:
            if page_number > len(document):
                raise EvidenceError("invalid_pdf", "PageOutOfRange")
            page = document[page_number - 1]
            try:
                scale = dpi / 72
                if (
                    math.ceil(page.get_width() * scale) * math.ceil(page.get_height() * scale)
                    > MAX_IMAGE_PIXELS
                ):
                    raise EvidenceError("invalid_pdf", "PageTooLarge")
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil().convert("RGB")
                    data = _png(image)
                    width, height = image.size
                finally:
                    bitmap.close()
            finally:
                page.close()
    except EvidenceError:
        raise
    except Exception:
        raise EvidenceError("invalid_pdf", "RenderFailed") from None
    return PreparedPage(
        source,
        page_number,
        page_number - 1,
        "rendered_pdf",
        data,
        width,
        height,
        sha256(data),
        mapping_note=f"PDFiumDpi{dpi}",
    )


def region_from_line(
    page: OcrPage,
    line_index: int,
    *,
    source: SourceRef,
    evidence_id: str | None = None,
    token: bool = False,
) -> EvidenceRegion:
    items = page.tokens if token else page.lines
    if type(line_index) is not int or not 0 <= line_index < len(items):
        raise EvidenceError("source_not_locatable", "LineOrTokenNotFound")
    item = items[line_index]
    polygon = item.bounding_box
    if not polygon and item.pixel_vertices:
        # Absolute vertices are pixels, not page.dimension (which can be points).
        image = page.image
        if image is None or not image.width or not image.height:
            raise EvidenceError("source_not_locatable", "PixelDimensionsMissing")
        polygon = tuple((x / image.width, y / image.height) for x, y in item.pixel_vertices)
    if not polygon:
        raise EvidenceError("source_not_locatable", "PolygonMissing")
    kind = "token" if token else "line"
    return EvidenceRegion(
        evidence_id or f"{source.recognition_id}:p{page.page_index}:{kind}{line_index}",
        source,
        page.page_number,
        page.page_index,
        "docai_page",
        polygon,
        item.text_segments,
        f"native_{kind}",
        document_sha256=page.document_sha256,
    )


def whole_page_region(page: PreparedPage, *, evidence_id: str) -> EvidenceRegion:
    return EvidenceRegion(
        evidence_id,
        page.source,
        page.page_number,
        page.page_index,
        page.coordinate_space,
        ((0, 0), (1, 0), (1, 1), (0, 1)),
        origin="whole_page",
        document_sha256=page.document_sha256,
    )


def transform_region(
    region: EvidenceRegion,
    *,
    destination: PreparedPage,
    normalized_homography: Sequence[Sequence[float]],
    mapping_note: str,
) -> EvidenceRegion:
    """Explicit normalized source->destination 3x3 mapping, not guessed from sizes.

    Caller must validate matrix against original/DocAI/PDF images. Google raw
    OpenCV transforms must first be converted to the proper normalized direction;
    this function intentionally does NOT assume they already are that mapping.
    """
    if destination.source != region.source or destination.page_number != region.page_number:
        raise EvidenceError("source_mismatch", "TransformAcrossSource")
    if not _nonempty(mapping_note):
        raise EvidenceError("invalid_transform", "MappingNoteRequired")
    try:
        matrix = tuple(tuple(row) for row in normalized_homography)
    except TypeError:
        raise EvidenceError("invalid_transform", "InvalidMatrix") from None
    if (
        len(matrix) != 3
        or any(len(row) != 3 for row in matrix)
        or any(type(v) not in (int, float) or not math.isfinite(v) for row in matrix for v in row)
    ):
        raise EvidenceError("invalid_transform", "InvalidMatrix")
    a, b, c = matrix
    determinant = (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )
    if abs(determinant) < 1e-12:
        raise EvidenceError("invalid_transform", "SingularMatrix")
    points = []
    for x, y in region.polygon:
        w = c[0] * x + c[1] * y + c[2]
        if abs(w) < 1e-12:
            raise EvidenceError("invalid_transform", "PointAtInfinity")
        points.append(((a[0] * x + a[1] * y + a[2]) / w, (b[0] * x + b[1] * y + b[2]) / w))
    return replace(
        region,
        coordinate_space=destination.coordinate_space,
        page_index=destination.page_index,
        polygon=validate_polygon(points),
        origin="explicit_transform",
        mapping_note=mapping_note,
        document_sha256=destination.document_sha256,
    )


def crop_evidence(
    page: PreparedPage,
    regions: Iterable[EvidenceRegion],
    *,
    padding_ratio: float = 0.08,
    min_padding_pixels: int = 4,
    max_output_edge: int | None = None,
) -> CropArtifact:
    """Bounding-rectangle crop of one or multiple verified regions on one page.

    Padding is relative to selected extent and clipped only at image boundaries.
    No upscaling, rotation, generative fill or guess of missing source coordinates.
    """
    _page_identity(page.page_number, page.page_index, page.coordinate_space)
    selected = tuple(regions)
    if (
        not selected
        or not all(isinstance(r, EvidenceRegion) for r in selected)
        or len(selected) > 256
        or len({r.evidence_id for r in selected}) != len(selected)
    ):
        raise EvidenceError("invalid_region", "EmptyOrDuplicateRegions")
    if (
        type(padding_ratio) not in (int, float)
        or not math.isfinite(padding_ratio)
        or not 0 <= padding_ratio <= 1
    ):
        raise EvidenceError("invalid_crop", "InvalidPadding")
    if type(min_padding_pixels) is not int or not 0 <= min_padding_pixels <= 1024:
        raise EvidenceError("invalid_crop", "InvalidPadding")
    if max_output_edge is not None and (type(max_output_edge) is not int or max_output_edge < 32):
        raise EvidenceError("invalid_crop", "InvalidOutputSize")
    if sha256(page.image_bytes) != page.image_sha256:
        raise EvidenceError("source_mismatch", "PreparedImageChanged")
    for region in selected:
        if (
            region.source != page.source
            or region.page_number != page.page_number
            or region.page_index != page.page_index
            or region.coordinate_space != page.coordinate_space
        ):
            raise EvidenceError("source_mismatch", "RegionAndImageSpaceDiffer")
        if page.document_sha256 != region.document_sha256:
            raise EvidenceError("source_mismatch", "RegionAndDocumentDiffer")
        validate_polygon(region.polygon)
    image = _decode_image(page.image_bytes)
    if image.size != (page.width, page.height):
        raise EvidenceError("source_mismatch", "PreparedImageSizeMismatch")
    xs = [p[0] * image.width for r in selected for p in r.polygon]
    ys = [p[1] * image.height for r in selected for p in r.polygon]
    px = max(min_padding_pixels, (max(xs) - min(xs)) * padding_ratio)
    py = max(min_padding_pixels, (max(ys) - min(ys)) * padding_ratio)
    box = (
        max(0, math.floor(min(xs) - px)),
        max(0, math.floor(min(ys) - py)),
        min(image.width, math.ceil(max(xs) + px)),
        min(image.height, math.ceil(max(ys) + py)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        raise EvidenceError("invalid_crop", "EmptyCrop")
    crop = image.crop(box)
    if max_output_edge is not None:
        crop.thumbnail((max_output_edge, max_output_edge), Image.Resampling.LANCZOS)
    data = _png(crop)
    identity = json.dumps(
        {
            "source": page.source.__dict__,
            "image": page.image_sha256,
            "page": page.page_number,
            "space": page.coordinate_space,
            "box": box,
            "regions": [r.evidence_id for r in selected],
            "output": sha256(data),
            "recipe": CROP_RECIPE_VERSION,
        },
        sort_keys=True,
    ).encode()
    return CropArtifact(
        "crop:" + sha256(identity)[:24],
        page.source,
        page.page_number,
        page.page_index,
        page.coordinate_space,
        data,
        "image/png",
        crop.width,
        crop.height,
        sha256(data),
        page.image_sha256,
        box,
        selected,
    )


def full_page_evidence(
    page: PreparedPage, *, evidence_id: str, max_output_edge: int | None = None
) -> CropArtifact:
    return crop_evidence(
        page,
        [whole_page_region(page, evidence_id=evidence_id)],
        padding_ratio=0,
        min_padding_pixels=0,
        max_output_edge=max_output_edge,
    )
