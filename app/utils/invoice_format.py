"""
模組名稱：app.utils.invoice_format
功能說明：三聯式發票欄位的換算與檢核工具——民國日期、發票期別、金額、字軌號碼、統一編號檢查碼、
    發票檔案（JPG／PNG／PDF）的 Storage 檔名。
注意事項：
    - 模型只抄錄票面原文；日期、期別與金額一律由這裡的程式換算，不採用模型自行換算的結果。
    - 發票期別 tax_period 以 YYYYMM（西元）表示，月份取該期的偶數月，與 datetime_utils.to_invoice_term
      「期別以偶數月表示」的慣例一致（例：民國 108 年 9、10 月 → 201910）。
"""

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID

from app.utils.datetime_utils import ROC_YEAR_OFFSET, TAIPEI_TZ

# 2026-10-29 使用者核定：invoices bucket 內 {user UUID}/，檔名含 INVOICES_ 前綴與台灣時間 YYYYMMDDHHMMSS
INVOICE_BUCKET = "invoices"  # 與 invoice_files.bucket_name 的 CHECK 一致
INVOICE_FILE_PREFIX = "INVOICES_"
# 與 invoice_files.mime_type 的 CHECK 一致
INVOICE_FILE_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}
_STORAGE_KEY = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/"
    + INVOICE_FILE_PREFIX
    + r"\d{14}_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(?:jpg|png|pdf)"
)
TAX_TYPES = ("taxable", "zero_rated", "tax_exempt")
# 統一編號檢查碼加權（財政部規則：各位數乘積的十位與個位相加，總和可被 5 整除）
_TAX_ID_WEIGHTS = (1, 2, 1, 2, 1, 2, 4, 1)
_CHINESE_DIGITS = {
    "〇": 0, "零": 0, "○": 0, "Ｏ": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}  # fmt: skip
_FULL_WIDTH = str.maketrans("０１２３４５６７８９，．／－：", "0123456789,./-:")
# 空白字元：與 JavaScript 的 trim()／\s 相同的集合（前台 mobile-camera.js 的 SPACE_CHARS 須一致）。
# 不用 Python 的 str.strip()／\s：兩者的範圍與 JavaScript 不同（例如 \x1c、\x85、\ufeff）。
WHITESPACE = (
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_PLAIN_NUMBER = re.compile(r"([0-9]+)(?:\.([0-9]+))?")


def invoice_storage_key(
    user_id: UUID, recognition_id: UUID, content_type: str, now: datetime
) -> str:
    """產生發票檔案的 Storage 物件鍵：{user_id}/INVOICES_{YYYYMMDDHHMMSS 台灣時間}_{recognition_id}.{副檔名}。

    Raises:
        ValueError: 不支援的檔案類型（JPG／PNG／PDF 以外）或 now 不含時區。
    """
    if content_type not in INVOICE_FILE_EXTENSIONS:
        raise ValueError("unsupported file type")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    stamp = now.astimezone(TAIPEI_TZ).strftime("%Y%m%d%H%M%S")
    return f"{user_id}/{INVOICE_FILE_PREFIX}{stamp}_{recognition_id}.{INVOICE_FILE_EXTENSIONS[content_type]}"


def is_invoice_storage_key(key: str) -> bool:
    """是否為 invoice_storage_key 產生的物件鍵（清理暫存影像前核對，避免刪到其他物件）。"""
    return _STORAGE_KEY.fullmatch(key) is not None


def _number_text(value: str) -> str:
    return value.translate(_FULL_WIDTH).replace(" ", "")


def _chinese_number(text: str) -> int | None:
    """「一〇八」「一一五」逐位數字，或「九」「十」「十一」「十二」等月份寫法。"""
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if "十" in text:
        tens, _, ones = text.partition("十")
        tens_value = _CHINESE_DIGITS.get(tens, 1) if tens else 1
        ones_value = _CHINESE_DIGITS.get(ones, 0) if ones else 0
        return tens_value * 10 + ones_value
    if all(char in _CHINESE_DIGITS for char in text):
        return int("".join(str(_CHINESE_DIGITS[char]) for char in text))
    return None


def _to_gregorian_year(year: int) -> int:
    return year + ROC_YEAR_OFFSET if year < 1000 else year


def parse_printed_date(text: str | None) -> date | None:
    """票面日期轉為 date：接受民國 115/08/15、115.8.15、115年8月15日、1150815 與西元 2026/08/15。"""
    if not text:
        return None
    value = _number_text(text)
    match = re.search(r"(\d{2,4})\D+(\d{1,2})\D+(\d{1,2})", value) or re.fullmatch(
        r"(\d{3})(\d{2})(\d{2})", value
    )
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(_to_gregorian_year(year), month, day)
    except ValueError:
        return None


def tax_period_for(value: date) -> str:
    """發票日期所屬期別（YYYYMM，月份為該期偶數月）。"""
    month = value.month if value.month % 2 == 0 else value.month + 1
    return f"{value.year}{month:02d}"


def parse_printed_period(text: str | None) -> str | None:
    """票面期別轉 YYYYMM：例「一〇八年九、十月份」→ 201910、「115年07-08月」→ 202608。"""
    if not text:
        return None
    value = _number_text(text)
    year_part, separator, month_part = value.partition("年")
    if not separator:
        return None
    year = _chinese_number(re.sub(r"[^0-9〇零○Ｏ一二三四五六七八九十]", "", year_part))
    months = [
        number
        for token in re.split(r"[、,\-~～至及和]", month_part.replace("月份", "").replace("月", ""))
        if (number := _chinese_number(re.sub(r"[^0-9〇零○Ｏ一二三四五六七八九十]", "", token)))
    ]
    if year is None or not months or not all(1 <= month <= 12 for month in months):
        return None
    try:
        return tax_period_for(date(_to_gregorian_year(year), max(months), 1))
    except ValueError:  # 年份超出範圍（例：99999 年）
        return None


def normalize_amount(value: object, places: int = 2) -> str | None:
    """金額或數量轉成字串（去逗號、單位與空白）：最多 places 位小數、去除尾端 0，整數不帶小數。

    小數以四捨五入（ROUND_HALF_UP）取到 places 位；無法解析、負數或超出 numeric(18, places) 範圍
    （含四捨五入後進位超出）時回傳 None。
    """
    if value is None or isinstance(value, bool):
        return None
    text = _number_text(str(value)).replace(",", "").replace("NT$", "").replace("$", "")
    text = text.replace("元", "").replace("整", "").strip()
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    # 先排除過大的值，quantize 才不會超出 Decimal 精度而拋出例外
    if not amount.is_finite() or amount < 0 or amount.adjusted() >= 18 - places:
        return None
    amount = amount.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    if amount.adjusted() >= 18 - places:
        return None
    return canonical_number(amount)


def strip_spaces(text: str) -> str:
    """去除前後空白（WHITESPACE 集合，與前台相同）。"""
    return text.strip(WHITESPACE)


def canonical_digits(text: str) -> str | None:
    """只含 ASCII 數字與一個小數點的字串：去前導 0 與小數尾端 0（純字串處理，任何位數都精確）。

    例：「006000.50」→「6000.5」、「0.000」→「0」；格式不符回傳 None。
    """
    match = _PLAIN_NUMBER.fullmatch(text)
    if not match:
        return None
    integer = match.group(1).lstrip("0") or "0"
    fraction = (match.group(2) or "").rstrip("0")
    return f"{integer}.{fraction}" if fraction else integer


def canonical_number(value: Decimal) -> str:
    """Decimal 的標準字串：去除尾端 0、不用科學記號（例：1000.00 → 1000、1.50 → 1.5）。"""
    text = format(value.normalize(), "f")
    return "0" if text in {"-0", "0"} else text


def split_invoice_number(track: str | None, number: str | None) -> tuple[str | None, str | None]:
    """字軌與號碼正規化：可接受合在一起的「CD75670992」「CD-75670992」。不合格回傳 None。"""
    combined = _number_text(f"{track or ''}{number or ''}").upper().replace("-", "")
    match = re.fullmatch(r"([A-Z]{2})(\d{8})", combined)
    if match:
        return match.group(1), match.group(2)
    clean_track = _number_text(track or "").upper()
    clean_number = re.sub(r"\D", "", _number_text(number or ""))
    return (
        clean_track if re.fullmatch(r"[A-Z]{2}", clean_track) else None,
        clean_number if re.fullmatch(r"\d{8}", clean_number) else None,
    )


def normalize_tax_id(value: str | None) -> str | None:
    """統一編號只保留數字；不是 8 碼回傳 None（不在此判斷檢查碼）。"""
    digits = re.sub(r"\D", "", _number_text(value or ""))
    return digits if len(digits) == 8 else None


def valid_tax_id(value: str) -> bool:
    """統一編號檢查碼（各位數乘權重後，十位加個位的總和可被 5 整除；第 7 碼為 7 時另可 +1）。"""
    if not re.fullmatch(r"\d{8}", value):
        return False
    total = sum(
        sum(divmod(int(digit) * weight, 10))
        for digit, weight in zip(value, _TAX_ID_WEIGHTS, strict=True)
    )
    return total % 5 == 0 or (value[6] == "7" and (total + 1) % 5 == 0)
