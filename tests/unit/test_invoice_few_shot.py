"""
模組名稱：tests.unit.test_invoice_few_shot
功能說明：測試統一發票多模態 Few-Shot 範例載入與結構規格。
"""

from app.services.invoice_few_shot import get_invoice_few_shot_examples


def test_get_invoice_few_shot_examples_loads_two_samples() -> None:
    examples = get_invoice_few_shot_examples()
    assert len(examples) == 2

    # 範例 1：手寫三聯式發票
    ex1 = examples[0]
    assert ex1["mime_type"] == "image/jpeg"
    assert isinstance(ex1["content"], bytes) and len(ex1["content"]) > 1000
    assert ex1["reply"]["is_triplicate"] is True
    assert ex1["reply"]["invoice_number"] == "GE09299250"
    assert ex1["reply"]["buyer_tax_id"] == "53287735"
    assert ex1["reply"]["seller_tax_id"] == "89308241"
    assert ex1["reply"]["total_amount"] == "470000"
    assert ex1["reply"]["total_amount_zh"] == "肆拾柒萬"

    # 範例 2：點陣列印三聯式發票
    ex2 = examples[1]
    assert ex2["mime_type"] == "image/jpeg"
    assert isinstance(ex2["content"], bytes) and len(ex2["content"]) > 1000
    assert ex2["reply"]["is_triplicate"] is True
    assert ex2["reply"]["invoice_number"] == "HP65010301"
    assert ex2["reply"]["buyer_tax_id"] == "29141556"
    assert ex2["reply"]["seller_tax_id"] == "53718208"
    assert ex2["reply"]["total_amount"] == "44730"
    assert ex2["reply"]["total_amount_zh"] == "肆萬肆仟柒佰參拾零元"


def test_get_invoice_few_shot_examples_is_cached() -> None:
    first = get_invoice_few_shot_examples()
    second = get_invoice_few_shot_examples()
    assert first is second
