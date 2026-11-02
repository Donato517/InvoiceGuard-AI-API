"""測試目標：統一編號檢查碼（財政部 2023 年新制 `S % 5 == 0`；第 7 碼為 7 時另可 `(S + 1) % 5 == 0`）。

範圍：只驗證既有 `invoice_format.valid_tax_id` 與其在警示預覽／正式送出的使用方式，不改規則。
    - 檢查碼不通過只是警示（tax_id_checksum），不阻擋提交——與現行行為一致，此檔鎖定該行為。
    - 檢查碼通過不代表公司存在、營業中或發票有效；`00000000` 只代表算式通過。
    - 同一份向量也放在 ADMIN 的 tests/unit/test_tax_id_parity.py，驗證 F09 的 `is_valid_ban` 在共同輸入上結果一致。
S 是各位數乘權數 [1,2,1,2,1,2,4,1] 後「十位＋個位」的總和；括號內為手算並用程式複核過的 S。
"""

import pytest

from app.schemas.invoice_upload import InvoiceSubmitRequest
from app.services import invoice_warning_service
from app.utils import invoice_format

# (統編, 預期, 說明)；與 ADMIN test_tax_id_parity.py 的向量相同
VECTORS = [
    ("04595257", True, "S=40，新舊制皆通過"),
    ("04595252", True, "S=35，只有新制（% 5）通過；舊制 % 10 會不通過"),
    ("10458570", True, "S=25，第 7 碼為 7，但由主規則通過"),
    ("10458574", True, "S=29，第 7 碼為 7，由 (S+1)%5 例外通過"),
    ("10000073", True, "S=14，第 7 碼為 7，由 (S+1)%5 例外通過"),
    ("10000074", True, "S=15，第 7 碼為 7，主規則通過"),
    ("27601907", True, "S=30"),
    ("12345678", False, "S=42"),
    ("10000003", False, "S=4，第 7 碼不是 7，例外不適用"),
    ("10000070", False, "S=11，第 7 碼為 7 但 (S+1)%5 != 0"),
    ("00000000", True, "S=0，只代表算式通過，不代表有這家公司"),
    ("0459525", False, "7 碼"),
    ("045952577", False, "9 碼"),
    ("0459525A", False, "含英文字母"),
    ("0459-525", False, "含符號"),
    ("", False, "空字串"),
    (" 04595257", False, "前後空白不在此函式處理"),
    ("04595257\n", False, "結尾換行不通過"),
]


@pytest.mark.parametrize(("tax_id", "expected", "reason"), VECTORS)
def test_valid_tax_id_vectors(tax_id: str, expected: bool, reason: str) -> None:
    assert invoice_format.valid_tax_id(tax_id) is expected, reason


def test_leading_zero_is_preserved_as_text() -> None:
    assert invoice_format.valid_tax_id("04595257")
    assert not invoice_format.valid_tax_id("4595257")  # 少了前導 0 就是 7 碼


def test_seventh_digit_exception_uses_mod_5_not_mod_10() -> None:
    # S=14：新制例外 (14+1) % 5 == 0 通過；若誤用舊制 % 10，(14+1) % 10 != 0 會不通過
    assert invoice_format.valid_tax_id("10000073")


def test_normalize_does_not_judge_checksum() -> None:
    assert invoice_format.normalize_tax_id("0459 5257") == "04595257"
    assert invoice_format.normalize_tax_id("12345678") == "12345678"  # 檢查碼錯誤仍會被保留
    assert invoice_format.normalize_tax_id("0459525") is None


# ---- 在警示預覽與正式送出的使用方式 ----


def _warning_fields(body: dict[str, object]) -> list[tuple[str, str]]:
    result = invoice_warning_service.preview_warnings(body)
    return [(w.field, w.code) for w in result.warnings if w.code == "tax_id_checksum"]


def test_preview_warns_for_seller_and_buyer_independently() -> None:
    assert _warning_fields({"seller_tax_id": "04595257", "buyer_tax_id": "04595252"}) == []
    assert _warning_fields({"seller_tax_id": "12345678", "buyer_tax_id": "04595257"}) == [
        ("seller_tax_id", "tax_id_checksum")
    ]
    assert _warning_fields({"seller_tax_id": "04595257", "buyer_tax_id": "12345678"}) == [
        ("buyer_tax_id", "tax_id_checksum")
    ]
    assert _warning_fields({"seller_tax_id": "12345678", "buyer_tax_id": "10000003"}) == [
        ("seller_tax_id", "tax_id_checksum"),
        ("buyer_tax_id", "tax_id_checksum"),
    ]


def test_preview_does_not_judge_missing_or_malformed_tax_ids() -> None:
    # 買受人可空；格式錯誤的視為「未知」，由必填檢核與正式送出（422）處理，不誤報檢查碼
    assert _warning_fields({"seller_tax_id": "04595257"}) == []
    assert _warning_fields({"seller_tax_id": "0459525", "buyer_tax_id": ""}) == []
    assert _warning_fields({"seller_tax_id": "０４５９５２５７"}) == []
    assert _warning_fields({"seller_tax_id": "٠٤٥٩٥٢٥٧", "buyer_tax_id": "０４５９５２５２"}) == []


def _submit_payload(**overrides: object) -> dict[str, object]:
    return {
        "recognition_id": "00000000-0000-4000-8000-000000000001",
        "invoice_track": "AB",
        "invoice_number": "12345678",
        "invoice_date": "2026-10-15",
        "seller_tax_id": "04595257",
        "tax_type": "taxable",
        "sales_amount": "1000",
        "tax_amount": "50",
        "total_amount": "1050",
        "items": [{"item_name": "文具", "line_amount": "1000"}],
        **overrides,
    }


def test_wrong_checksum_does_not_block_submission_schema() -> None:
    request = InvoiceSubmitRequest.model_validate(
        _submit_payload(seller_tax_id="12345678", buyer_tax_id="12345679")
    )

    assert (request.seller_tax_id, request.buyer_tax_id) == ("12345678", "12345679")


def test_submission_schema_still_requires_ascii_8_digits_and_seller() -> None:
    from pydantic import ValidationError

    for bad in ("0459525", "045952577", "0459525A", "０４５９５２５７", "٠٤٥٩٥٢٥٧"):
        with pytest.raises(ValidationError):
            InvoiceSubmitRequest.model_validate(_submit_payload(seller_tax_id=bad))
    with pytest.raises(ValidationError):
        InvoiceSubmitRequest.model_validate(_submit_payload(seller_tax_id=""))
    assert (
        InvoiceSubmitRequest.model_validate(_submit_payload(buyer_tax_id="")).buyer_tax_id is None
    )


# 全形（U+FF10…）與阿拉伯-印度（U+0660…）數字：數學上能通過檢查碼，但不是 ASCII 數字，必須拒絕
NON_ASCII_DIGIT_IDS = [
    "０４５９５２５７",  # 全形，等同 04595257
    "０４５９５２５２",  # 全形，等同 04595252
    "１０４５８５７４",  # 全形，等同 10458574（第 7 碼例外）
    "٠٤٥٩٥٢٥٧",  # 阿拉伯-印度，等同 04595257
    "٠٠٠٠٠٠٠٠",  # 阿拉伯-印度，等同 00000000
    "0459５257",  # 半形與全形混合
    "0459525٧",  # 半形與阿拉伯-印度混合
]


@pytest.mark.parametrize("tax_id", NON_ASCII_DIGIT_IDS)
def test_valid_tax_id_rejects_non_ascii_digits(tax_id: str) -> None:
    assert invoice_format.valid_tax_id(tax_id) is False


def test_ascii_equivalents_of_the_non_ascii_ids_still_pass() -> None:
    # 確認上面的全形／阿拉伯-印度案例「只因字元集」被拒，而不是算式本身不過
    for tax_id in ("04595257", "04595252", "10458574", "00000000"):
        assert invoice_format.valid_tax_id(tax_id) is True


def test_normalize_converts_fullwidth_but_not_arabic_indic_digits() -> None:
    # 辨識路徑先 normalize_tax_id：全形會被轉成 ASCII（收緊後仍能通過檢查碼）；
    # 阿拉伯-印度數字不會被轉換，收緊後會被檢查碼警示攔下（以前會被誤判為通過）。
    assert invoice_format.normalize_tax_id("０４５９５２５７") == "04595257"
    assert invoice_format.valid_tax_id(invoice_format.normalize_tax_id("０４５９５２５７") or "")
    arabic_indic = invoice_format.normalize_tax_id("٠٤٥٩٥٢٥٧")
    assert arabic_indic == "٠٤٥٩٥٢٥٧"
    assert not invoice_format.valid_tax_id(arabic_indic or "")
