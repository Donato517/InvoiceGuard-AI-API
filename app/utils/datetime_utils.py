"""
模組名稱：app.utils.datetime_utils
功能說明：時間與台灣發票期別轉換工具。
注意事項：
    - 系統內部與資料庫一律使用 UTC（timezone-aware datetime），只有顯示與發票期別換算才轉台灣時間。
    - 台灣無日光節約時間，因此以固定 UTC+8 表示，不需依賴 tzdata。
"""

from datetime import UTC, date, datetime, timedelta, timezone

TAIPEI_TZ = timezone(timedelta(hours=8), name="Asia/Taipei")

# 西元年轉民國年的差值
ROC_YEAR_OFFSET = 1911


def now_utc() -> datetime:
    """取得目前 UTC 時間（timezone-aware）。"""
    return datetime.now(UTC)


def to_taipei(value: datetime) -> datetime:
    """將 timezone-aware datetime 轉為台灣時間。

    Raises:
        ValueError: 傳入 naive datetime（無時區資訊）。
    """
    if value.tzinfo is None:
        raise ValueError("必須傳入含時區資訊的 datetime")
    return value.astimezone(TAIPEI_TZ)


def to_invoice_term(value: date) -> str:
    """將日期換算為統一發票期別（民國年 3 碼＋雙月的後月 2 碼）。

    統一發票每兩個月一期，期別以該期的「偶數月」表示。

    Args:
        value: 發票開立日期。

    Returns:
        期別字串，例如 date(2024, 9, 15) → "11310"、date(2024, 1, 5) → "11302"。
    """
    roc_year = value.year - ROC_YEAR_OFFSET
    even_month = value.month + (value.month % 2)
    return f"{roc_year:03d}{even_month:02d}"
