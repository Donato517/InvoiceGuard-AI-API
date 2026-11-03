"""測試目標：scripts.golden_eval 的評分與清單；全部離線，不呼叫 API、DB 或 Storage。"""

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import golden_eval as ge

MANIFEST = Path(__file__).resolve().parents[1] / "golden" / "manifest.json"

EXPECTED = {
    "invoice_track": "RT",
    "invoice_number": "39560800",
    "invoice_date": "2025-10-03",
    "sales_amount": "14150",
    "total_amount": "14858",
    "total_amount_zh": "14858",
    "items": [{"item_name": "卡", "quantity": "203", "unit_price": "14", "line_amount": "2842"}],
}


def recognition(**overrides: Any) -> dict[str, Any]:
    invoice: dict[str, Any] = {
        "invoice_track": "RT",
        "invoice_number": "39560800",
        "invoice_date": "2025-10-03",
        "sales_amount": "14150.00",
        "total_amount": "14858",
        "total_amount_zh": "壹萬肆仟捌佰伍拾捌元",
        "items": [
            {"item_name": "卡", "quantity": "203", "unit_price": "14", "line_amount": "2842"}
        ],
    }
    invoice.update(overrides.pop("invoice", {}))
    return {"invoice": invoice, "warnings": overrides.pop("warnings", [])}


def test_a_fully_correct_recognition_scores_all_fields_correct() -> None:
    score = ge.score_invoice("a.jpg", EXPECTED, recognition())

    assert score.all_correct and score.wrong_uncaught == []


def test_amounts_compare_numerically_not_as_text() -> None:
    score = ge.score_invoice("a.jpg", {"sales_amount": "14150"}, recognition())

    assert score.all_correct  # "14150.00" == "14150"


def test_wrong_value_without_warning_is_reported_as_uncaught() -> None:
    score = ge.score_invoice("a.jpg", EXPECTED, recognition(invoice={"invoice_date": "2025-10-04"}))

    assert score.wrong_uncaught == ["invoice_date"]


def test_empty_value_or_a_warning_on_the_field_counts_as_intercepted() -> None:
    empty = ge.score_invoice("a.jpg", EXPECTED, recognition(invoice={"invoice_date": None}))
    warned = ge.score_invoice(
        "a.jpg",
        EXPECTED,
        recognition(
            invoice={"total_amount": "14860"},
            warnings=[{"field": "total_amount", "code": "total_amount_mismatch"}],
        ),
    )

    assert empty.wrong_uncaught == [] and warned.wrong_uncaught == []
    assert not empty.all_correct and not warned.all_correct


def test_chinese_amount_is_compared_by_value_with_struck_through_places() -> None:
    struck = recognition(invoice={"total_amount_zh": "億仟佰拾壹萬肆仟捌佰伍拾捌元"})

    assert ge.score_invoice("a.jpg", {"total_amount_zh": "14858"}, struck).all_correct


def test_item_misread_is_scored_per_cell_and_line_warning_intercepts_it() -> None:
    bad = recognition(
        invoice={
            "items": [
                {"item_name": "卡", "quantity": "203", "unit_price": "14", "line_amount": "2942"}
            ]
        },
        warnings=[{"field": "items.0.line_amount", "code": "item_line_amount_mismatch"}],
    )

    score = ge.score_invoice("a.jpg", EXPECTED, bad)

    assert [f.name for f in score.fields if not f.correct] == ["items.0.line_amount"]
    assert score.wrong_uncaught == []


def test_missing_item_row_is_wrong_and_counted() -> None:
    score = ge.score_invoice("a.jpg", EXPECTED, recognition(invoice={"items": []}))

    assert "items.count" in [f.name for f in score.fields if not f.correct]


def test_summary_reports_exact_match_interception_and_uncaught_list() -> None:
    good = ge.score_invoice("good.jpg", EXPECTED, recognition())
    bad = ge.score_invoice("bad.jpg", EXPECTED, recognition(invoice={"invoice_date": "2025-10-04"}))

    report = ge.summarize([good, bad])

    assert report["invoices"] == 2 and report["invoices_all_correct"] == 1
    assert report["wrong_fields"] == 1 and report["interception_rate"] == 0.0
    assert report["wrong_uncaught"] == {"bad.jpg": ["invoice_date"]}
    assert report["by_field"]["invoice_date"]["exact_match"] == 0.5


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("invoice_0100_RT39560800.jpg", ("RT", "39560800")),
        ("invoice_0007_HT383XX246.jpg", None),
    ],
)
def test_track_number_from_filename(filename: str, expected: tuple[str, str] | None) -> None:
    assert ge.track_number_from_filename(filename) == expected


def test_manifest_lists_100_invoices_with_70_correct_and_only_annotated_have_full_fields() -> None:
    entries = ge.load_manifest(MANIFEST)

    assert len(entries) == 100
    assert sum(e["folder"] == "correct" for e in entries) == 70
    assert {e["file"] for e in entries if e["annotated"]} == {
        "invoice_0100_RT39560800.jpg",
        "invoice_0096_RT30630655.jpg",
        "invoice_0057_MT07940088.jpg",
    }
    for entry in entries:
        if entry["annotated"]:
            items = entry["expected"]["items"]
            assert sum(int(i["line_amount"]) for i in items) == int(
                entry["expected"]["sales_amount"]
            )
            assert all(
                int(i["quantity"]) * int(i["unit_price"]) == int(i["line_amount"]) for i in items
            )
            assert int(entry["expected"]["sales_amount"]) + int(
                entry["expected"]["tax_amount"]
            ) == int(entry["expected"]["total_amount"])


def test_real_run_refuses_without_explicit_write_flag(capsys: pytest.CaptureFixture[str]) -> None:
    code = ge.main(
        ["run", "--api-base", "http://127.0.0.1:8000", "--token-file", "x", "--images-dir", "y"]
    )

    assert code == 2 and "--yes-write" in capsys.readouterr().out


def test_manifest_is_valid_json_with_no_secrets_or_image_data() -> None:
    text = MANIFEST.read_text(encoding="utf-8")

    json.loads(text)
    assert "Bearer" not in text and "base64" not in text.lower()
