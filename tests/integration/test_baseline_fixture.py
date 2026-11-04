"""
測試目標：tests/fixtures/sql 的 test-only 基線 SQL 沒有被悄悄改動，且仍是純結構、無機密的測試資源。
涵蓋：標頭聲明 test-only；本體指紋與標頭記錄一致；沒有 pgvector 擴充、種子資料或疑似機密。不連資料庫，永遠執行。
更新基線時必須同步更新標頭指紋與 tests/fixtures/sql/README.md，不可只改測試。
"""

import hashlib
import re

from db_lifecycle import DEFAULT_BASELINE

MARKER = "-- ===== END TEST-ONLY HEADER; the lines below are the derived body ====="


def _split() -> tuple[str, str]:
    text = DEFAULT_BASELINE.read_text(encoding="utf-8")
    header, marker, body = text.partition(MARKER + "\n")
    assert marker, "找不到標頭結束標記"
    return header, body


def test_header_declares_test_only_and_lists_source_and_changes() -> None:
    header, _ = _split()
    assert header.startswith("-- TEST-ONLY FIXTURE")
    assert "NOT an Alembic baseline" in header
    assert "Source SHA-256" in header and "InvoiceGuard_AI_PostgreSQL_Schema_v1_8" in header
    assert "pgvector" in header


def test_body_fingerprint_matches_the_recorded_one() -> None:
    header, body = _split()
    recorded = re.search(r"Derived body SHA-256[^:]*: ([0-9a-f]{64})", header)
    assert recorded is not None
    assert hashlib.sha256(body.encode()).hexdigest() == recorded.group(1)


def test_baseline_is_structure_only_without_vector_or_secrets() -> None:
    _, body = _split()
    code = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("--"))
    assert not re.search(r"CREATE EXTENSION[^;]*vector", code, re.IGNORECASE)
    assert "extensions.vector" not in code
    assert not re.search(r"^\s*INSERT\s+INTO", code, re.IGNORECASE | re.MULTILINE)
    assert not re.search(r"\b(eyJ[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{12,})", code)
    assert not re.search(r"[\w.+-]+@[\w-]+\.(com|tw|org|net)\b", code)
