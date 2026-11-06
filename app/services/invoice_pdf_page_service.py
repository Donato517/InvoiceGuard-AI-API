"""
模組名稱：app.services.invoice_pdf_page_service
功能說明：多頁 PDF 找發票頁——把前台送來的頁面縮圖拼成一張編號總覽圖，請 Gemini 逐張判斷是不是三聯式統一發票
    與聯別（第一聯存根聯不能報帳）。
相依模組：app.integrations.gemini（沿用 extract_invoice 單張影像呼叫，不修改共用模組）、Pillow
注意事項：
    - PDF 拆頁與轉圖在瀏覽器完成（pdf.js），整份 PDF 不上傳；本服務只收縮圖，不存檔、不寫 DB。
    - 每次最多 9 張（3×3 總覽圖）；45 頁的 PDF 由前台分批送。只送 1 張時以原解析度判斷，供確認候選頁的聯別。
    - 判斷結果只用來挑頁與擋第一聯；挑出的頁面仍走 POST /invoices/recognize 的正式辨識與檢核。
"""

import io
import json
import logging
import math
import re
import time
from typing import Any

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from app.core.exceptions import AppError, ExternalServiceError, ServiceUnavailableError
from app.integrations.chat_models import ChatReply
from app.integrations.gemini import GeminiClient, GeminiError
from app.schemas.invoice_pdf_page import PdfPageClassification, PdfPageClassifyRead

logger = logging.getLogger(__name__)

MAX_PAGES_PER_REQUEST = 9
MAX_IMAGE_BYTES = 1536 * 1024  # 單張縮圖上限（前台縮圖約 50～400 KB）
MAX_TOTAL_BYTES = 4 * 1024 * 1024  # Vercel 請求本文上限 4.5 MB
MAX_IMAGE_PIXELS = 25_000_000  # 拒絕過大的影像，避免解壓縮炸彈
DEADLINE_SECONDS = 25.0  # 與辨識相同；前台請求 30 秒逾時
TILE_SIDE = 800  # 多張時每格最長邊
SINGLE_SIDE = 2000  # 只有 1 張時保留的最長邊（與正式辨識相同）
LABEL_HEIGHT = 64
GAP = 16
SHEET_QUALITY = 85

_SIGNATURES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")

SYSTEM_PROMPT = (
    "你是台灣統一發票的分頁助手。使用者會給你一張總覽圖，裡面有數張以「#編號」標示的頁面。"
    "你只判斷每一頁是不是三聯式統一發票，以及票面印的聯別；不要抄錄任何欄位內容。"
)

USER_PROMPT_TEMPLATE = """總覽圖中共有 {count} 張頁面，每張上方的黑底白字標示 #1 到 #{count}。請逐張判斷：
- is_triplicate_invoice：是否為三聯式統一發票（手開或電腦開立的三聯式皆算；票頭通常印有「統一發票（三聯式）」、買受人統一編號欄）。
  二聯式發票、電子發票證明聯、收據、估價單、合約、明細表、空白頁都填 false。頁面中只有一部分是三聯式發票（例如掃描在 A4 上）也算 true。
- copy：票面印的聯別。「第一聯 存根聯」填 1、「第二聯 扣抵聯」填 2、「第三聯 收執聯」填 3；
  看不清楚、沒有印、或不是三聯式發票時填 null，不要猜。
只回傳 JSON，每張頁面一筆、依編號排序：
{{"pages": [{{"tile": 1, "is_triplicate_invoice": true, "copy": 2}}]}}"""


class _InvalidReplyError(ValueError):
    """模型回覆不是預期的 JSON。"""


def classify_pages(images: list[bytes]) -> PdfPageClassifyRead:
    """判斷一批 PDF 頁面縮圖是不是三聯式統一發票與聯別。

    Args:
        images: 頁面影像（JPG／PNG），依頁序排列，1～9 張。

    Returns:
        PdfPageClassifyRead: 每張的判斷結果（index 依上傳順序，從 1 起算）與模型名稱。

    Raises:
        AppError: 張數不符（INVOICE_PAGE_COUNT_INVALID）、檔案不是影像（INVOICE_IMAGE_INVALID）、
            檔案過大（INVOICE_IMAGE_TOO_LARGE）。
        ExternalServiceError: 模型呼叫失敗或回覆無法解讀（AI_PAGE_PICK_FAILED）。
        ServiceUnavailableError: 模型服務未設定或用量已滿。
    """
    started = time.monotonic()
    sheet = build_sheet(images)
    try:
        client = GeminiClient.from_settings()
    except GeminiError as exc:
        raise _gemini_error(exc) from None
    try:
        reply = client.extract_invoice(
            sheet,
            "image/jpeg",
            system_instruction=SYSTEM_PROMPT,
            prompt=USER_PROMPT_TEMPLATE.format(count=len(images)),
            timeout_seconds=DEADLINE_SECONDS - (time.monotonic() - started),
        )
        pages = parse_reply(reply, len(images))
    except GeminiError as exc:
        logger.warning("PDF 挑頁呼叫 Gemini 失敗：%s", exc.code)
        raise _gemini_error(exc) from None
    except _InvalidReplyError:
        logger.warning("PDF 挑頁的模型回覆無法解讀")
        raise ExternalServiceError(
            "AI 無法判斷 PDF 的頁面，請稍後再試", code="AI_PAGE_PICK_FAILED"
        ) from None
    finally:
        try:
            client.close()
        except Exception as exc:
            logger.warning("關閉 Gemini client 失敗：%s", type(exc).__name__)
    return PdfPageClassifyRead(pages=pages, model=reply.model)


def build_sheet(images: list[bytes]) -> bytes:
    """把頁面影像拼成編號總覽圖（JPEG）；每格上方標示 #編號，不遮住頁面內容。

    Args:
        images: 頁面影像（JPG／PNG），1～9 張。

    Returns:
        bytes: 總覽圖 JPEG。

    Raises:
        AppError: 張數、格式或大小不符。
    """
    if not 1 <= len(images) <= MAX_PAGES_PER_REQUEST:
        raise AppError(
            f"每次需送 1～{MAX_PAGES_PER_REQUEST} 張頁面影像", code="INVOICE_PAGE_COUNT_INVALID"
        )
    if sum(len(content) for content in images) > MAX_TOTAL_BYTES:
        raise AppError("頁面影像總和超過 4 MB", code="INVOICE_IMAGE_TOO_LARGE")
    side = SINGLE_SIDE if len(images) == 1 else TILE_SIDE
    pages = [_open_page(content, side) for content in images]

    columns = 1 if len(pages) == 1 else 2 if len(pages) <= 4 else 3
    rows = math.ceil(len(pages) / columns)
    cell_w = max(page.width for page in pages)
    cell_h = max(page.height for page in pages) + LABEL_HEIGHT
    sheet = Image.new(
        "RGB",
        (columns * cell_w + (columns + 1) * GAP, rows * cell_h + (rows + 1) * GAP),
        (200, 200, 200),
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=LABEL_HEIGHT - 16)
    for number, page in enumerate(pages, start=1):
        col, row = (number - 1) % columns, (number - 1) // columns
        x = GAP + col * (cell_w + GAP)
        y = GAP + row * (cell_h + GAP)
        draw.rectangle((x, y, x + cell_w - 1, y + LABEL_HEIGHT - 1), fill=(0, 0, 0))
        draw.text((x + 16, y + 6), f"#{number}", fill=(255, 255, 255), font=font)
        sheet.paste(page, (x, y + LABEL_HEIGHT))
    output = io.BytesIO()
    sheet.save(output, format="JPEG", quality=SHEET_QUALITY)
    return output.getvalue()


def parse_reply(reply: ChatReply, count: int) -> tuple[PdfPageClassification, ...]:
    """解讀模型回覆；缺少的編號視為不是發票，聯別只接受 1、2、3。

    Args:
        reply: 模型回覆。
        count: 本批頁面張數。

    Returns:
        tuple[PdfPageClassification, ...]: 依編號排序、每張一筆。

    Raises:
        _InvalidReplyError: 回覆不是 JSON 物件或沒有 pages 清單。
    """
    text = reply.text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except ValueError:
        raise _InvalidReplyError from None
    if not isinstance(data, dict) or not isinstance(data.get("pages"), list):
        raise _InvalidReplyError
    found: dict[int, tuple[bool, Any]] = {}
    for entry in data["pages"]:
        if not isinstance(entry, dict):
            continue
        tile = entry.get("tile")
        if isinstance(tile, bool) or not isinstance(tile, int) or not 1 <= tile <= count:
            continue
        found.setdefault(tile, (entry.get("is_triplicate_invoice") is True, entry.get("copy")))
    pages = []
    for index in range(1, count + 1):
        is_invoice, copy_no = found.get(index, (False, None))
        valid_copy = copy_no if copy_no in (1, 2, 3) and not isinstance(copy_no, bool) else None
        pages.append(
            PdfPageClassification(
                index=index,
                is_triplicate_invoice=is_invoice,
                copy_no=valid_copy if is_invoice else None,
            )
        )
    return tuple(pages)


def _open_page(content: bytes, side: int) -> Image.Image:
    """驗證並開啟一張頁面影像，縮到最長邊 side 以內（RGB）。"""
    if len(content) > MAX_IMAGE_BYTES:
        raise AppError("單張頁面影像超過 1.5 MB", code="INVOICE_IMAGE_TOO_LARGE")
    if not content.startswith(_SIGNATURES):
        raise AppError("頁面影像需為 JPG 或 PNG", code="INVOICE_IMAGE_INVALID")
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise AppError("頁面影像尺寸過大", code="INVOICE_IMAGE_TOO_LARGE")
            page = image.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise AppError("無法讀取頁面影像", code="INVOICE_IMAGE_INVALID") from None
    page.thumbnail((side, side))
    return page


def _gemini_error(exc: GeminiError) -> AppError:
    if exc.code == "gemini_not_configured":
        return ServiceUnavailableError("發票辨識服務尚未設定，請聯絡系統管理員")
    if exc.code == "gemini_quota_exceeded":
        return ServiceUnavailableError("發票辨識服務用量已達上限，請稍後再試")
    return ExternalServiceError("AI 無法判斷 PDF 的頁面，請稍後再試", code="AI_PAGE_PICK_FAILED")
