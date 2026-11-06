"""
模組名稱：app.services.invoice_upload_service
功能說明：手機上傳發票流程——辨識（存影像 → Google Gemini 多模態結構化整理欄位 → 程式換算與檢核 → 記錄）、
    查重、送出（建立發票、明細、影像檔、欄位複核、修改歷程與狀態歷程），以及清理逾時未送出的影像。
相依模組：app.db.repositories.recognition_repository、app.db.repositories.invoice_repository、
    app.integrations.supabase_storage、app.integrations.gemini、app.utils.invoice_format
注意事項：
    - 接受 JPG、PNG（手機拍照、電腦選檔）與單頁 PDF（電腦選檔），4 MB 以內，以檔頭判斷類型；
      一份 PDF 一張發票（invoice_files 每張發票一個目前檔案），多頁 PDF 拒絕。
    - 檔案存 invoices bucket：{user_id}/INVOICES_{台灣時間 YYYYMMDDHHMMSS}_{recognition_id}.{副檔名}；
      送出時 invoice_files 直接指向同一物件，不搬移。
    - 辨識後 1 小時內未送出即不可送出；逾時影像在之後的辨識請求順帶刪除並記 source_deleted_at（不另設排程）。
    - 模型只抄錄票面原文；日期、期別、金額、字軌號碼與統編由程式換算與檢核。檢核結果是提醒，不阻擋送出，
      送出值的檢核寫入 invoices.validation_results。
    - 送出時狀態為 pending_accounting_review（待會計覆核，目前不啟用單位核准層），部門取本次 Session 的選取部門；
      已有相同字軌＋號碼＋賣方統編且未作廢的發票時拒絕送出。
    - 使用者修改過的欄位（AI 原值≠送出值，含刪除的 AI 明細）每輪寫一筆 invoice_field_reviews 供審核勾選；
      核對頁的逐次修改（含改了又改回的中間修改）依序寫入 invoice_changes。修改紀錄須從 AI 原值接續到送出值，
      不一致時拒絕送出；有差異卻沒有紀錄的欄位由 API 補一筆。
    - 送出時在同一交易寫入 Round 1 提交快照（invoice_submission_snapshots，kind=first；表頭與明細的標準值、影像
      file_id、提交者、送出時間、檢核提醒）。快照資料表不存在、欄位不符或執行角色沒有權限（含 RLS）時不會略過：
      回 503 INVOICE_SNAPSHOT_UNAVAILABLE 並整筆回滾（不留下發票，辨識紀錄維持未送出，可重試）。
    - 辨識總時限 25 秒（前台請求 30 秒逾時）。
    - 部門功能權限（功能碼）尚未接線：目前 Session 有效即可使用。
"""

import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import PurePath
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.exceptions import (
    AppError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.db.repositories import invoice_repository, recognition_repository, resubmit_repository
from app.db.repositories.invoice_repository import (
    FieldChange,
    FieldDifference,
    InvoiceHeader,
    InvoiceItem,
)
from app.integrations import gemini
from app.integrations.chat_models import ChatReply
from app.integrations.gemini import GeminiClient, GeminiError
from app.integrations.invoice_recognition_contract import SYSTEM_PROMPT, USER_PROMPT
from app.integrations.supabase_storage import S3StorageClient, StorageError
from app.schemas.auth import SessionRead
from app.schemas.invoice_upload import (
    DuplicateCheckRead,
    DuplicateCheckRequest,
    FieldWarning,
    InvoiceRecognitionRead,
    InvoiceSubmitRead,
    InvoiceSubmitRequest,
    ModifiedField,
    PrintedText,
    RecognitionInfo,
    RecognizedInvoice,
    RecognizedItem,
)
from app.utils.datetime_utils import now_utc, to_taipei
from app.utils.invoice_format import (
    INVOICE_BUCKET,
    INVOICE_FILE_EXTENSIONS,
    INVOICE_FILE_PREFIX,
    TAX_TYPES,
    WHITESPACE,
    canonical_digits,
    canonical_number,
    chinese_amount_to_int,
    infer_date_from_period,
    invoice_storage_key,
    is_invoice_storage_key,
    normalize_amount,
    normalize_tax_id,
    parse_printed_date,
    parse_printed_period,
    split_invoice_number,
    strip_spaces,
    tax_period_for,
    valid_tax_id,
)

logger = logging.getLogger(__name__)

# Vercel 請求本文上限 4.5 MB；前台先把影像縮圖再上傳，PDF 原檔上傳
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_ITEMS = 50
MAX_TEXT_LENGTH = 200
# 辨識總時限：前台請求 30 秒逾時，保留存圖與寫 DB 的時間
RECOGNITION_DEADLINE_SECONDS = 25.0
CLEANUP_BATCH = 10
SUBMITTED_STATUS = "pending_accounting_review"
SUBMIT_REASON = "手機拍照上傳送出"
TAX_RATE = Decimal("0.05")
TAX_TOLERANCE = Decimal("1")
ITEM_LINE_TOLERANCE = Decimal("1")  # 數量×單價與明細金額的容差（金額四捨五入到元）

_FILE_SIGNATURES = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "application/pdf": b"%PDF-",
}
_EXTENSION_TYPES = {extension: mime for mime, extension in INVOICE_FILE_EXTENSIONS.items()}
_HEADER_FIELDS = (
    "invoice_track",
    "invoice_number",
    "invoice_date",
    "seller_tax_id",
    "seller_name",
    "buyer_tax_id",
    "buyer_name",
    "tax_type",
    "sales_amount",
    "tax_amount",
    "total_amount",
    "total_amount_zh",
)
_ITEM_FIELDS = ("item_name", "quantity", "unit_price", "line_amount")
# 比對與修改紀錄的標準值：數字去逗號與尾端 0，代碼去空白與連字號並轉大寫
_NUMBER_FIELDS = frozenset(
    {"sales_amount", "tax_amount", "total_amount", "quantity", "unit_price", "line_amount"}
)
_CODE_FIELDS = frozenset({"invoice_track", "invoice_number", "seller_tax_id", "buyer_tax_id"})
# 數字欄位去除的字元（空白、半形與全形逗號）；代碼欄位去除空白與連字號——與前台 canonicalValue 相同
_NUMBER_NOISE = re.compile(f"[{re.escape(WHITESPACE)},，]")
_CODE_NOISE = re.compile(f"[{re.escape(WHITESPACE)}-]")
_TAX_ID_LABELS = {"seller_tax_id": "賣方統一編號", "buyer_tax_id": "買受人統一編號"}

_SYSTEM_PROMPT = SYSTEM_PROMPT

_USER_PROMPT = USER_PROMPT

_DB_UNAVAILABLE = "發票服務暫時無法使用，請稍後再試"


class _InvalidReplyError(ValueError):
    """模型回覆不是 JSON 物件。"""


def recognize(
    db: Session | None,
    current: SessionRead,
    *,
    content: bytes,
    content_type: str | None,
    filename: str | None,
) -> InvoiceRecognitionRead:
    """辨識一張發票（影像或單頁 PDF）：存入 Storage、Gemini 多模態視覺擷取、程式換算與檢核，並寫入辨識紀錄。

    Args:
        db: 資料庫 Session；未設定資料庫時為 None。
        current: 已核對的登入者與選取部門。
        content: 檔案內容（JPG／PNG／單頁 PDF，4 MB 以內）。
        content_type: 上傳時宣告的類型；需與實際內容一致。
        filename: 原始檔名（只保留檔名部分，寫入辨識紀錄供送出時使用）。

    Returns:
        InvoiceRecognitionRead: recognition_id、欄位、票面原文、檢核提醒、模型資訊與影像保留期限。

    Raises:
        AppError: 檔案格式或大小不符（INVOICE_IMAGE_INVALID／INVOICE_IMAGE_TOO_LARGE）、
            沒有文字（INVOICE_TEXT_NOT_FOUND）、PDF 超過一頁（INVOICE_PDF_MULTIPAGE）。
        ExternalServiceError: Storage 或模型呼叫失敗。
        ServiceUnavailableError: 資料庫、Storage 或模型服務未設定或用量已滿。
    """
    db = _require_db(db)
    mime_type = _file_type(content, content_type)
    started = time.monotonic()
    storage = _storage()
    try:
        gemini_client = GeminiClient.from_settings()
    except GeminiError as exc:
        raise _gemini_error(exc) from None

    recognition_id = uuid4()
    key = invoice_storage_key(current.user_id, recognition_id, mime_type, now_utc())
    try:
        try:
            created_at = recognition_repository.insert(
                db,
                recognition_id=recognition_id,
                source_storage_path=key,
                ai_provider=gemini.PROVIDER,
                requested_by=current.user_id,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

        try:
            if mime_type == "application/pdf" and (
                _pdf_page_count(content) > 1 or getattr(gemini_client, "page_count", 1) > 1
            ):
                raise AppError(
                    "PDF 只能有一頁：一份 PDF 一張發票，請分開上傳", code="INVOICE_PDF_MULTIPAGE"
                )
            storage.put(key, content, content_type=mime_type)
            reply = gemini_client.extract_invoice(
                content,
                mime_type,
                system_instruction=_SYSTEM_PROMPT,
                prompt=_USER_PROMPT,
                timeout_seconds=_remaining(started),
            )
            data = _parse_reply(reply)
            if data.get("error") == "multipage":
                raise AppError(
                    "PDF 只能有一頁：一份 PDF 一張發票，請分開上傳", code="INVOICE_PDF_MULTIPAGE"
                )
            if data.get("error") == "no_text" or (
                not data.get("invoice_number")
                and not data.get("seller_tax_id")
                and not data.get("total_amount")
                and not data.get("items")
                and data.get("is_triplicate") is None
            ):
                raise AppError("影像中沒有辨識到文字，請重新拍攝", code="INVOICE_TEXT_NOT_FOUND")
        except StorageError as exc:
            _record_failure(db, recognition_id, _log_code(exc.code, exc.detail))
            raise _storage_error(exc) from None
        except GeminiError as exc:
            _record_failure(db, recognition_id, _log_code(exc.code, exc.detail))
            raise _gemini_error(exc) from None
        except _InvalidReplyError:
            _record_failure(db, recognition_id, "gemini_invalid_reply")
            raise ExternalServiceError(
                "AI 無法整理這張發票的欄位，請重新拍攝或稍後再試", code="AI_RECOGNITION_FAILED"
            ) from None
        except AppError as exc:
            _record_failure(db, recognition_id, exc.code.lower())
            raise
    finally:
        _close_gemini_client(gemini_client)

    try:
        is_triplicate, invoice, printed, warnings = _build_recognition(data)
        result = InvoiceRecognitionRead(
            recognition_id=recognition_id,
            result_status="partial" if warnings else "success",
            is_triplicate=is_triplicate,
            invoice=invoice,
            printed=printed,
            warnings=tuple(warnings),
            recognition=RecognitionInfo(
                ocr_provider=gemini.PROVIDER,
                ocr_confidence=1.0,
                ai_provider=gemini.PROVIDER,
                model=reply.model,
                fallback_used=False,
            ),
            expires_at=created_at + timedelta(hours=recognition_repository.SOURCE_RETENTION_HOURS),
        )
    except Exception as exc:
        logger.warning("整理辨識結果失敗：%s", type(exc).__name__)
        _record_failure(db, recognition_id, f"postprocess_failed:{type(exc).__name__}")
        raise ExternalServiceError(
            "AI 無法整理這張發票的欄位，請重新拍攝或稍後再試", code="AI_RECOGNITION_FAILED"
        ) from None
    stored = result.model_dump(mode="json")
    try:
        recognition_repository.complete(
            db,
            recognition_id,
            model_name=reply.model,
            is_triplicate=is_triplicate,
            confidence_score=1.0,
            extracted_fields={
                name: stored[name] for name in ("is_triplicate", "invoice", "printed", "warnings")
            },
            raw_response={
                "source": {
                    "filename": _safe_filename(filename),
                    "mime_type": mime_type,
                    "size_bytes": len(content),
                },
                "gemini": {
                    "provider": gemini.PROVIDER,
                    "model": reply.model,
                    "finish_reason": reply.finish_reason,
                    "content": reply.text,
                    "prompt_tokens": reply.prompt_tokens,
                    "output_tokens": reply.output_tokens,
                },
            },
            result_status=result.result_status,
            error_message=None,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    cleanup_expired_sources(db, storage)
    return result


def check_duplicate(db: Session | None, request: DuplicateCheckRequest) -> DuplicateCheckRead:
    """查詢系統內是否已有相同字軌、號碼與賣方統編且未作廢的發票。

    Raises:
        ServiceUnavailableError: 資料庫未設定。
    """
    db = _require_db(db)
    try:
        duplicate = invoice_repository.exists_duplicate(
            db,
            invoice_track=request.invoice_track,
            invoice_number=request.invoice_number,
            seller_tax_id=request.seller_tax_id,
        )
    finally:
        db.rollback()
    return DuplicateCheckRead(is_duplicate=duplicate)


def submit(
    db: Session | None,
    current: SessionRead,
    request: InvoiceSubmitRequest,
    *,
    today: date | None = None,
) -> InvoiceSubmitRead:
    """送出使用者核對後的發票：建立發票（待會計覆核）、明細、影像檔、欄位複核、修改歷程與狀態歷程。

    Args:
        db: 資料庫 Session；未設定資料庫時為 None。
        current: 已核對的登入者與選取部門。
        request: 使用者確認的欄位與本次辨識的 recognition_id。
        today: 判斷「發票日期晚於今天」的台灣當天日期；預設取目前台灣日期，測試可注入。

    Returns:
        InvoiceSubmitRead: invoice_id、狀態、期別、送出時間、送出值的檢核提醒與使用者修改過的欄位。

    Raises:
        NotFoundError: 辨識紀錄不存在或不是本人的（RECOGNITION_NOT_FOUND）。
        ConflictError: 已送出、超過 1 小時、辨識未完成或發票重複（INVOICE_DUPLICATED）。
        AppError: 明細來源（INVOICE_ITEMS_INVALID）或修改紀錄（INVOICE_CHANGES_INVALID）與送出內容不一致。
        ServiceUnavailableError: 資料庫未設定，或第 1 輪快照的資料表／權限不可用（INVOICE_SNAPSHOT_UNAVAILABLE）。
    """
    db = _require_db(db)
    header = InvoiceHeader(
        invoice_track=request.invoice_track,
        invoice_number=request.invoice_number,
        invoice_date=request.invoice_date,
        tax_period=tax_period_for(request.invoice_date),
        seller_tax_id=request.seller_tax_id,
        seller_name=request.seller_name,
        buyer_tax_id=request.buyer_tax_id,
        buyer_name=request.buyer_name,
        sales_amount=request.sales_amount,
        tax_amount=request.tax_amount,
        total_amount=request.total_amount,
        total_amount_zh=request.total_amount_zh,
        tax_type=request.tax_type,
    )
    items = tuple(
        InvoiceItem(
            line_no=line_no,
            item_name=item.item_name,
            quantity=item.quantity,
            unit_price=item.unit_price,
            line_amount=item.line_amount,
        )
        for line_no, item in enumerate(request.items, start=1)
    )
    warnings = [
        *future_date_warnings(header.invoice_date, today),
        *_consistency_warnings(
            seller_tax_id=header.seller_tax_id,
            buyer_tax_id=header.buyer_tax_id,
            tax_type=header.tax_type,
            sales=header.sales_amount,
            tax=header.tax_amount,
            total=header.total_amount,
            line_amounts=[item.line_amount for item in items],
            total_zh=header.total_amount_zh,
            item_details=[(item.quantity, item.unit_price, item.line_amount) for item in items],
        ),
    ]
    try:
        log = recognition_repository.lock_for_submit(db, request.recognition_id, current.user_id)
        if log is None:
            raise NotFoundError("找不到這次辨識紀錄，請重新拍攝", code="RECOGNITION_NOT_FOUND")
        if log.invoice_id is not None:
            raise ConflictError("這張發票已送出", code="RECOGNITION_ALREADY_SUBMITTED")
        if log.expired or log.source_deleted_at is not None or not log.source_storage_path:
            raise ConflictError("辨識結果已超過 1 小時，請重新拍攝辨識", code="RECOGNITION_EXPIRED")
        if log.result_status not in ("success", "partial"):
            raise ConflictError("這次辨識未完成，請重新辨識", code="RECOGNITION_NOT_USABLE")
        ai_invoice = (log.extracted_fields or {}).get("invoice") or {}
        sources = tuple(item.source_line_no for item in request.items)
        differences, changes = _user_modifications(ai_invoice, header, items, sources, request)
        identity = {
            "invoice_track": header.invoice_track,
            "invoice_number": header.invoice_number,
            "seller_tax_id": header.seller_tax_id,
        }
        invoice_repository.lock_invoice_key(db, **identity)
        if invoice_repository.exists_duplicate(db, **identity):
            raise ConflictError("此發票已存在於系統中，禁止重複上傳", code="INVOICE_DUPLICATED")

        invoice_id, submitted_at = invoice_repository.insert_invoice(
            db,
            header,
            submission_round=1,
            status=SUBMITTED_STATUS,
            validation_results={"warnings": [warning.model_dump() for warning in warnings]},
            submitted_by=current.user_id,
            department_id=current.department.department_id,
        )
        item_ids = invoice_repository.insert_items(db, invoice_id, items)
        source = (log.raw_response or {}).get("source") or {}
        file_id = invoice_repository.insert_file(
            db,
            invoice_id,
            bucket_name=INVOICE_BUCKET,
            storage_path=log.source_storage_path,
            original_filename=source.get("filename"),
            mime_type=_EXTENSION_TYPES[PurePath(log.source_storage_path).suffix.lstrip(".")],
            size_bytes=source.get("size_bytes"),
            uploaded_by=current.user_id,
        )
        _save_first_snapshot(
            db,
            invoice_id,
            header,
            items,
            item_ids,
            warnings,
            file_id=file_id,
            submitted_by=current.user_id,
            submitted_at=submitted_at,
        )
        invoice_repository.insert_field_reviews(
            db,
            invoice_id,
            differences,
            item_ids=item_ids,
            submission_round=1,
            recognition_id=request.recognition_id,
        )
        invoice_repository.insert_changes(
            db,
            invoice_id,
            changes,
            item_ids=item_ids,
            submission_round=1,
            changed_by=current.user_id,
        )
        invoice_repository.insert_status_history(
            db,
            invoice_id,
            old_status=None,
            new_status=SUBMITTED_STATUS,
            reason=SUBMIT_REASON,
            changed_by=current.user_id,
        )
        recognition_repository.link_invoice(db, request.recognition_id, invoice_id, file_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return InvoiceSubmitRead(
        invoice_id=invoice_id,
        status=SUBMITTED_STATUS,
        tax_period=header.tax_period,
        submitted_at=submitted_at,
        warnings=tuple(warnings),
        modified_fields=tuple(
            ModifiedField(
                field_scope=difference.field_scope,
                line_no=difference.line_no,
                field_name=difference.field_name,
                ai_original_value=difference.ai_original_value,
                submitted_value=difference.submitted_value,
            )
            for difference in differences
        ),
    )


def cleanup_expired_sources(db: Session, storage: S3StorageClient) -> int:
    """刪除超過 1 小時仍未送出的辨識影像並記錄 source_deleted_at；失敗只記日誌，不影響本次請求。

    Returns:
        本次標記為已刪除的筆數。
    """
    deleted = 0
    try:
        rows = recognition_repository.lock_expired_sources(
            db, CLEANUP_BATCH, file_prefix=INVOICE_FILE_PREFIX
        )
        for recognition_id, path in rows:
            if not is_invoice_storage_key(path):
                continue
            try:
                storage.delete(path)
            except StorageError as exc:
                if exc.code != "storage_not_found":
                    logger.warning("刪除逾時發票影像失敗：%s", exc.code)
                    continue
            recognition_repository.mark_source_deleted(db, recognition_id)
            deleted += 1
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("清理逾時發票影像失敗：%s", type(exc).__name__)
        return 0
    return deleted


def _require_db(db: Session | None) -> Session:
    if db is None:
        raise ServiceUnavailableError(_DB_UNAVAILABLE)
    return db


def _file_type(content: bytes, content_type: str | None) -> str:
    """以檔案內容判斷 JPG／PNG／PDF；宣告類型須一致，大小須在 4 MB 以內。"""
    if len(content) > MAX_FILE_BYTES:
        raise AppError("檔案超過 4 MB，請重新拍攝或縮小後再上傳", code="INVOICE_IMAGE_TOO_LARGE")
    detected = next(
        (mime for mime, signature in _FILE_SIGNATURES.items() if content.startswith(signature)),
        None,
    )
    declared = (content_type or "").split(";")[0].strip().lower()
    if detected is None or (declared and declared != detected):
        raise AppError("請上傳 JPG、PNG 或 PDF 發票檔案", code="INVOICE_IMAGE_INVALID")
    return detected


def _storage() -> S3StorageClient:
    try:
        return S3StorageClient.from_settings(bucket=INVOICE_BUCKET)
    except (StorageError, ValueError):
        raise ServiceUnavailableError("影像儲存服務尚未設定，請聯絡系統管理員") from None


def _remaining(started: float) -> float:
    """辨識總時限的剩餘秒數（可能為 0 或負數）。"""
    return RECOGNITION_DEADLINE_SECONDS - (time.monotonic() - started)


def _parse_reply(reply: ChatReply) -> dict[str, Any]:
    text = reply.text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except ValueError:
        raise _InvalidReplyError from None
    if not isinstance(data, dict):
        raise _InvalidReplyError
    return data


def _text(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip()
    return text[:MAX_TEXT_LENGTH] if text else None


def _decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def _build_recognition(
    data: dict[str, Any],
) -> tuple[bool | None, RecognizedInvoice, PrintedText, list[FieldWarning]]:
    """模型抄錄的原文 → 欄位值（程式換算）＋檢核提醒。"""
    warnings: list[FieldWarning] = []
    is_triplicate = data.get("is_triplicate")
    is_triplicate = is_triplicate if isinstance(is_triplicate, bool) else None
    if is_triplicate is False:
        warnings.append(
            FieldWarning(
                field="is_triplicate",
                code="not_triplicate",
                message="影像看起來不是三聯式統一發票，請確認",
            )
        )

    track, number = split_invoice_number(None, _text(data.get("invoice_number")))
    if track is None or number is None:
        warnings.append(
            FieldWarning(
                field="invoice_number",
                code="invoice_number_invalid",
                message="無法辨識字軌號碼（2 碼英文＋8 碼數字），請輸入",
            )
        )
    printed_date = _text(data.get("invoice_date"))
    printed_period = _text(data.get("tax_period"))
    invoice_date = parse_printed_date(printed_date)
    printed_tax_period = parse_printed_period(printed_period)
    inferred_date = None
    if invoice_date is None:
        inferred_date = invoice_date = infer_date_from_period(printed_date, printed_period)
    if inferred_date is not None:
        warnings.append(
            FieldWarning(
                field="invoice_date",
                code="invoice_date_year_inferred",
                message=(
                    f"票面日期缺少年份，已依票面期別推算為 {inferred_date.isoformat()}，"
                    "請對照原始發票確認"
                ),
            )
        )
    elif invoice_date is None:
        warnings.append(
            FieldWarning(
                field="invoice_date",
                code="invoice_date_invalid",
                message="無法辨識發票日期，請輸入",
            )
        )
    elif printed_tax_period is not None and printed_tax_period != tax_period_for(invoice_date):
        warnings.append(
            FieldWarning(
                field="tax_period",
                code="tax_period_mismatch",
                message="票面期別與發票日期不一致，請確認日期",
            )
        )

    tax_ids = {name: normalize_tax_id(_text(data.get(name))) for name in _TAX_ID_LABELS}
    for name, value in tax_ids.items():
        if value is None:
            warnings.append(
                FieldWarning(
                    field=name,
                    code="tax_id_invalid",
                    message=f"無法辨識{_TAX_ID_LABELS[name]}（8 碼數字），請輸入",
                )
            )

    amounts = {
        name: normalize_amount(data.get(name))
        for name in ("sales_amount", "tax_amount", "total_amount")
    }
    for name, value in amounts.items():
        if value is None:
            warnings.append(
                FieldWarning(field=name, code="amount_missing", message="無法辨識金額，請輸入")
            )

    tax_type = data.get("tax_type") if data.get("tax_type") in TAX_TYPES else None
    if tax_type is None:
        tax = _decimal(amounts["tax_amount"])
        if tax is not None and tax > 0:
            tax_type = "taxable"
            warnings.append(
                FieldWarning(
                    field="tax_type",
                    code="tax_type_inferred",
                    message="未辨識到課稅別勾選，依稅額推定為應稅，請確認",
                )
            )
        else:
            warnings.append(
                FieldWarning(
                    field="tax_type", code="tax_type_missing", message="無法辨識課稅別，請選擇"
                )
            )

    items = _recognized_items(data.get("items"))
    if not items:
        warnings.append(
            FieldWarning(field="items", code="items_missing", message="未辨識到品名明細，請輸入")
        )

    warnings.extend(
        _consistency_warnings(
            seller_tax_id=tax_ids["seller_tax_id"],
            buyer_tax_id=tax_ids["buyer_tax_id"],
            tax_type=tax_type,
            sales=_decimal(amounts["sales_amount"]),
            tax=_decimal(amounts["tax_amount"]),
            total=_decimal(amounts["total_amount"]),
            line_amounts=[_decimal(item.line_amount) for item in items],
            total_zh=_text(data.get("total_amount_zh")),
            item_details=[
                (_decimal(item.quantity), _decimal(item.unit_price), _decimal(item.line_amount))
                for item in items
            ],
        )
    )
    invoice = RecognizedInvoice(
        invoice_track=track,
        invoice_number=number,
        invoice_date=invoice_date,
        tax_period=tax_period_for(invoice_date) if invoice_date else printed_tax_period,
        seller_tax_id=tax_ids["seller_tax_id"],
        seller_name=_text(data.get("seller_name")),
        buyer_tax_id=tax_ids["buyer_tax_id"],
        buyer_name=_text(data.get("buyer_name")),
        tax_type=tax_type,
        sales_amount=amounts["sales_amount"],
        tax_amount=amounts["tax_amount"],
        total_amount=amounts["total_amount"],
        total_amount_zh=_text(data.get("total_amount_zh")),
        items=tuple(items),
    )
    return (
        is_triplicate,
        invoice,
        PrintedText(invoice_date=printed_date, tax_period=printed_period),
        warnings,
    )


def _recognized_items(value: object) -> list[RecognizedItem]:
    if not isinstance(value, list):
        return []
    items: list[RecognizedItem] = []
    for raw in value:
        if not isinstance(raw, dict) or len(items) >= MAX_ITEMS:
            continue
        fields = {
            "item_name": _text(raw.get("item_name")),
            "quantity": normalize_amount(raw.get("quantity"), 4),
            "unit_price": normalize_amount(raw.get("unit_price"), 4),
            "line_amount": normalize_amount(raw.get("line_amount")),
        }
        if any(fields.values()):
            items.append(RecognizedItem(line_no=len(items) + 1, **fields))
    return items


def today_taipei(now: datetime | None = None) -> date:
    """台灣（Asia/Taipei）的當天日期；now 必須含時區，預設取目前時間，測試可注入。"""
    return to_taipei(now or now_utc()).date()


def future_date_warnings(
    invoice_date: date | None, today: date | None = None
) -> list[FieldWarning]:
    """發票日期晚於台灣當天日期時的提醒（只提醒，不阻擋送出）；日期未填或今天以前為空清單。"""
    if invoice_date is None or invoice_date <= (today or today_taipei()):
        return []
    return [
        FieldWarning(
            field="invoice_date",
            code="invoice_date_future",
            message="發票日期晚於今天，請核對原始發票。",
        )
    ]


def _consistency_warnings(
    *,
    seller_tax_id: str | None,
    buyer_tax_id: str | None,
    tax_type: str | None,
    sales: Decimal | None,
    tax: Decimal | None,
    total: Decimal | None,
    line_amounts: list[Decimal | None],
    total_zh: str | None = None,
    item_details: list[tuple[Decimal | None, Decimal | None, Decimal | None]] | None = None,
) -> list[FieldWarning]:
    """統編檢查碼、課稅別與稅額、銷售額＋稅額＝總計、國字大寫＝總計、數量×單價≈明細金額、明細合計＝銷售額。

    item_details 為各明細的（數量，單價，金額），與 line_amounts 同順序；三者齊全的明細才檢核逐行乘積。
    """
    warnings: list[FieldWarning] = []
    for name, value in (("seller_tax_id", seller_tax_id), ("buyer_tax_id", buyer_tax_id)):
        if value is not None and not valid_tax_id(value):
            warnings.append(
                FieldWarning(
                    field=name,
                    code="tax_id_checksum",
                    message=f"{_TAX_ID_LABELS[name]}檢查碼不符，請確認",
                )
            )
    if tax_type is not None and sales is not None and tax is not None:
        if tax_type == "taxable":
            expected = (sales * TAX_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            if abs(tax - expected) > TAX_TOLERANCE:
                warnings.append(
                    FieldWarning(
                        field="tax_amount",
                        code="tax_amount_mismatch",
                        message=f"應稅稅額應約為銷售額的 5%（{canonical_number(expected)}），請確認",
                    )
                )
        elif tax != 0:
            warnings.append(
                FieldWarning(
                    field="tax_amount",
                    code="tax_amount_mismatch",
                    message="零稅率或免稅發票的稅額應為 0，請確認",
                )
            )
    if sales is not None and tax is not None and total is not None and sales + tax != total:
        warnings.append(
            FieldWarning(
                field="total_amount",
                code="total_amount_mismatch",
                message="銷售額＋稅額與總計不符，請確認",
            )
        )
    if total is not None and total_zh:
        zh_value = chinese_amount_to_int(total_zh)
        if zh_value is None:
            warnings.append(
                FieldWarning(
                    field="total_amount_zh",
                    code="total_amount_zh_unreadable",
                    message="無法判讀國字大寫金額，請對照票面確認",
                )
            )
        elif Decimal(zh_value) != total:
            warnings.append(
                FieldWarning(
                    field="total_amount_zh",
                    code="total_amount_zh_mismatch",
                    message=f"國字大寫金額（{zh_value:,}）與總計不符，請確認",
                )
            )
    for index, (quantity, unit_price, amount) in enumerate(item_details or []):
        if quantity is None or unit_price is None or amount is None:
            continue
        expected = quantity * unit_price
        if abs(expected - amount) > ITEM_LINE_TOLERANCE:
            warnings.append(
                FieldWarning(
                    field=f"items.{index}.line_amount",
                    code="item_line_amount_mismatch",
                    message=(
                        f"第 {index + 1} 筆明細：數量×單價（{canonical_number(expected)}）"
                        f"與金額（{canonical_number(amount)}）不符，請確認"
                    ),
                )
            )
    if (
        sales is not None
        and line_amounts
        and all(amount is not None for amount in line_amounts)
        and sum(line_amounts, Decimal(0)) != sales
    ):
        warnings.append(
            FieldWarning(
                field="items",
                code="items_total_mismatch",
                message="明細金額合計與銷售額不符，請確認",
            )
        )
    return warnings


def _save_first_snapshot(
    db: Session,
    invoice_id: UUID,
    header: InvoiceHeader,
    items: tuple[InvoiceItem, ...],
    item_ids_by_line: dict[int, UUID],
    warnings: list[FieldWarning],
    *,
    file_id: UUID,
    submitted_by: UUID,
    submitted_at: datetime,
) -> None:
    """在首次送出的同一交易寫入第 1 輪完整提交快照（kind=first）；不 commit。

    格式與重送時補建的第 1 輪快照相同（同一組欄位與標準值），所以重送的 `snapshot_exists` 檢查會略過補建。
    快照是「送出當下」的值，與 AI 原值（invoice_field_reviews）和逐次修改（invoice_changes）分開保存。
    不會默默略過：快照資料表不存在、欄位不符或執行角色沒有權限（含 RLS）時，轉成 503
    INVOICE_SNAPSHOT_UNAVAILABLE 並由 submit 回滾整筆交易（不留下沒有快照的正式案件，辨識紀錄維持未送出）；
    其他資料庫錯誤原樣拋出，同樣回滾。

    Raises:
        ServiceUnavailableError: 快照資料結構或權限不可用（INVOICE_SNAPSHOT_UNAVAILABLE）。
    """
    snapshot_header: dict[str, Any] = {
        name: _canonical_value(name, getattr(header, name)) for name in _HEADER_FIELDS
    }
    snapshot_header["tax_period"] = header.tax_period
    try:
        resubmit_repository.insert_snapshot(
            db,
            invoice_id,
            submission_round=1,
            kind="first",
            header=snapshot_header,
            items=[
                {
                    "item_id": str(item_ids_by_line[item.line_no]),
                    "line_no": item.line_no,
                    **{name: _canonical_value(name, getattr(item, name)) for name in _ITEM_FIELDS},
                }
                for item in items
            ],
            validation_results={"warnings": [warning.model_dump() for warning in warnings]},
            file_id=file_id,
            submitted_by=submitted_by,
            submitted_at=submitted_at,
        )
    except Exception as error:
        state = resubmit_repository.snapshot_structure_sqlstate(error)
        if state is None:
            raise  # 不是快照結構／權限問題：原樣拋出，由 submit 回滾
        # 只記錄錯誤類別與 SQLSTATE，不記錄 SQL 參數或發票內容
        logger.error("首次送出無法寫入第 1 輪快照：sqlstate=%s", state)
        raise ServiceUnavailableError(
            "發票服務暫時無法保存提交紀錄，請稍後再試或聯絡系統管理員",
            code="INVOICE_SNAPSHOT_UNAVAILABLE",
        ) from None


def _canonical_value(field_name: str, value: object) -> str | None:
    """比對與修改紀錄用的標準值；前台 mobile-camera.js 的 canonicalValue 須採相同規則。

    空白（WHITESPACE 集合）為 None；數字去逗號與空白後，若只有 ASCII 數字與小數點，以字串去前導 0 與尾端 0
    （不經 Decimal 運算，任何位數都精確）；日期轉 ISO；字軌、號碼、統編去空白與連字號並轉大寫。
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        text = format(value, "f")  # 不經 context 捨入
        return canonical_digits(text) or text
    if isinstance(value, date):
        return value.isoformat()
    text = strip_spaces(str(value))
    if not text:
        return None
    if field_name in _NUMBER_FIELDS:
        cleaned = _NUMBER_NOISE.sub("", text)
        return canonical_digits(cleaned) or cleaned
    if field_name in _CODE_FIELDS:
        return _CODE_NOISE.sub("", text).upper()
    return text


def _invalid_items() -> AppError:
    return AppError("明細與辨識結果對不上，請重新核對後送出", code="INVOICE_ITEMS_INVALID")


def _invalid_changes() -> AppError:
    return AppError("修改紀錄與送出內容不一致，請重新核對後送出", code="INVOICE_CHANGES_INVALID")


def _user_modifications(
    ai_invoice: dict[str, Any],
    header: InvoiceHeader,
    items: tuple[InvoiceItem, ...],
    sources: tuple[int | None, ...],
    request: InvoiceSubmitRequest,
) -> tuple[tuple[FieldDifference, ...], tuple[FieldChange, ...]]:
    """依 AI 原值、送出值與核對頁的修改紀錄，產生欄位複核（淨差異）與逐次修改紀錄。

    Returns:
        (使用者修改過的欄位, 依序的修改紀錄)

    Raises:
        AppError: 明細來源重複或不存在、修改紀錄的欄位不存在或無法從 AI 原值接續到送出值。
    """
    ai_items = {
        raw["line_no"]: raw
        for raw in ai_invoice.get("items") or []
        if isinstance(raw, dict) and isinstance(raw.get("line_no"), int)
    }
    used = [source for source in sources if source is not None]
    if len(set(used)) != len(used) or any(source not in ai_items for source in used):
        raise _invalid_items()

    # (範圍, 明細序號, 欄位) → AI 原值與送出值
    baseline: dict[tuple[str, int | None, str], str | None] = {}
    final: dict[tuple[str, int | None, str], str | None] = {}
    for name in _HEADER_FIELDS:
        key = ("header", None, name)
        baseline[key] = _canonical_value(name, ai_invoice.get(name))
        final[key] = _canonical_value(name, getattr(header, name))
    for item, source in zip(items, sources, strict=True):
        ai_item = ai_items.get(source) or {}
        for name in _ITEM_FIELDS:
            key = ("item", item.line_no, name)
            baseline[key] = _canonical_value(name, ai_item.get(name))
            final[key] = _canonical_value(name, getattr(item, name))

    differences = [
        FieldDifference(*key, baseline[key], final[key])
        for key in final
        if baseline[key] != final[key]
    ]
    deleted = [
        FieldDifference(
            "header",
            None,
            f"deleted_item_{line_no}",
            {name: _canonical_value(name, ai_item.get(name)) for name in _ITEM_FIELDS},
            None,
        )
        for line_no, ai_item in sorted(ai_items.items())
        if line_no not in used
    ]

    changes: list[FieldChange] = []
    last_value: dict[tuple[str, int | None, str], str | None] = {}
    for change in request.changes:
        key = (change.field_scope, change.line_no, change.field_name)
        if key not in final:
            raise _invalid_changes()
        old = _canonical_value(change.field_name, change.old_value)
        new = _canonical_value(change.field_name, change.new_value)
        if old == new or old != last_value.get(key, baseline[key]):
            raise _invalid_changes()
        last_value[key] = new
        changes.append(FieldChange(*key, old, new))
    if any(value != final[key] for key, value in last_value.items()):
        raise _invalid_changes()
    # 有差異卻沒有紀錄的欄位（例如前台未送紀錄）補一筆；刪除的 AI 明細也記一筆
    changes.extend(
        FieldChange(d.field_scope, d.line_no, d.field_name, d.ai_original_value, d.submitted_value)
        for d in [*differences, *deleted]
        if (d.field_scope, d.line_no, d.field_name) not in last_value
    )
    return tuple(differences + deleted), tuple(changes)


def _pdf_page_count(content: bytes) -> int:
    """計算 PDF 頁數（依 /Type /Page 物件標記）。"""
    pages = re.findall(rb"/Type\s*/Page(?![a-zA-Z])", content)
    return len(pages)


def _close_gemini_client(client: GeminiClient) -> None:
    """關閉本次辨識的 Gemini client；關閉失敗只記例外型別，不蓋過辨識結果或原本的錯誤。"""
    try:
        client.close()
    except Exception as exc:
        logger.warning("關閉 Gemini client 失敗：%s", type(exc).__name__)


def _safe_filename(filename: str | None) -> str | None:
    name = PurePath((filename or "").replace("\\", "/")).name.strip()
    return name[:MAX_TEXT_LENGTH] or None


def _log_code(code: str, detail: str) -> str:
    return f"{code}:{detail}" if detail else code


def _record_failure(db: Session, recognition_id: UUID, error_message: str) -> None:
    """辨識失敗時記錄狀態與固定代碼；記錄失敗只寫日誌，不蓋過原本的錯誤。"""
    try:
        recognition_repository.complete(
            db,
            recognition_id,
            model_name=None,
            is_triplicate=None,
            confidence_score=None,
            extracted_fields=None,
            raw_response=None,
            result_status="failed",
            error_message=error_message,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("記錄辨識失敗狀態時發生錯誤：%s", type(exc).__name__)


def _storage_error(exc: StorageError) -> AppError:
    if exc.code == "storage_not_configured":
        return ServiceUnavailableError("影像儲存服務尚未設定，請聯絡系統管理員")
    return ExternalServiceError("影像儲存失敗，請稍後再試", code="STORAGE_FAILED")


def _gemini_error(exc: GeminiError) -> AppError:
    if exc.code == "gemini_not_configured":
        return ServiceUnavailableError("發票辨識服務尚未設定，請聯絡系統管理員")
    if exc.code == "gemini_invalid_input":
        return AppError(
            "無法辨識這個檔案，請重新拍攝或改用清楚的檔案", code="INVOICE_IMAGE_INVALID"
        )
    if exc.code == "gemini_quota_exceeded":
        return ServiceUnavailableError("發票辨識服務用量已達上限，請稍後再試")
    return ExternalServiceError(
        "AI 無法整理這張發票的欄位，請重新拍攝或稍後再試", code="AI_RECOGNITION_FAILED"
    )
