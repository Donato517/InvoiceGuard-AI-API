"""測試目標：app.utils.datetime_utils"""

from datetime import UTC, date, datetime

import pytest

from app.utils.datetime_utils import to_invoice_term, to_taipei


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2024, 1, 5), "11302"),
        (date(2024, 2, 29), "11302"),
        (date(2024, 9, 15), "11310"),
        (date(2024, 12, 31), "11312"),
    ],
)
def test_to_invoice_term(value: date, expected: str) -> None:
    assert to_invoice_term(value) == expected


def test_to_taipei_converts_utc_to_utc_plus_8() -> None:
    result = to_taipei(datetime(2026, 10, 20, 16, 30, tzinfo=UTC))

    assert (result.year, result.month, result.day, result.hour) == (2026, 10, 21, 0)


def test_to_taipei_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        to_taipei(datetime(2026, 10, 21, 8, 0))
