"""
測試目標：專屬測試資料庫的安全生命週期（db_lifecycle.py）。
涵蓋：名稱／token／回送位址檢查與基線前處理（純函式，永遠執行）；以及需要 ISOLATED_ADMIN_URL 的實際建立／刪除——
只刪自己的庫、token 或擁有者標記不符一律拒絕、兩個工作階段互不影響。
真實資料庫測試需要 ISOLATED_ADMIN_URL（限本機回送位址）；未設定則略過。
"""

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from db_lifecycle import (
    UnsafeTargetError,
    create_database,
    database_name,
    drop_owned_database,
    ownership_comment,
    prepare_baseline_sql,
    require_loopback,
    require_or_skip,
)
from sqlalchemy import Engine, create_engine, text


def test_name_is_derived_from_a_valid_token_only() -> None:
    token = uuid4().hex
    assert database_name(token) == f"ig_it_{token[:12]}"
    for bad in ("", "ABC", token.upper(), token[:-1], f'{token[:30]}"x'):
        with pytest.raises(UnsafeTargetError):
            database_name(bad)


def test_admin_url_must_be_loopback() -> None:
    require_loopback("postgresql+psycopg://u:p@127.0.0.1:5432/postgres")
    require_loopback("postgresql+psycopg://u:p@localhost/postgres")
    with pytest.raises(UnsafeTargetError):
        require_loopback("postgresql+psycopg://u:p@db.example.com/postgres")


@pytest.mark.parametrize(
    "bad_url",
    [
        "postgresql+psycopg://u:p@127.0.0.1/postgres?host=db.example.com",
        "postgresql+psycopg://u:p@127.0.0.1/postgres?hostaddr=203.0.113.9",
        "postgresql+psycopg://u:p@localhost/postgres?service=remote",
        "postgresql+psycopg://u:p@127.0.0.1/postgres?options=-c%20search_path%3Dx",
        "postgresql+psycopg://u:p@127.0.0.1/postgres?passfile=/tmp/x",
        "postgresql+psycopg://u:p@127.0.0.1/postgres?sslmode=require&host=db.example.com",
        "postgresql+psycopg://u:p@127.0.0.1/postgres?unknown_param=1",
        "postgresql+psycopg://u:p@127.0.0.1,db.example.com/postgres",
    ],
)
def test_loopback_check_cannot_be_bypassed_by_url_parameters(bad_url: str) -> None:
    with pytest.raises(UnsafeTargetError):
        require_loopback(bad_url)


def test_loopback_check_resolves_to_a_local_target_and_allows_sslmode() -> None:
    url = require_loopback("postgresql+psycopg://u:p@127.0.0.1:55432/postgres?sslmode=require")
    assert url.get_dialect()().create_connect_args(url)[1]["host"] == "127.0.0.1"


def test_baseline_vector_block_is_removed_only_when_extension_is_missing() -> None:
    sql = (
        "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;\n"
        "DO $vector_check$ BEGIN RAISE EXCEPTION 'x'; END $vector_check$;\n"
        "CREATE TABLE t (embedding extensions.vector(1536), e2 extensions.vector);"
    )
    assert prepare_baseline_sql(sql, vector_available=True) == sql
    stripped = prepare_baseline_sql(sql, vector_available=False)
    assert "vector" not in stripped and "embedding text, e2 text" in stripped


def test_missing_configuration_skips_normally_but_fails_when_integration_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ISOLATED_REQUIRE_INTEGRATION", raising=False)
    with pytest.raises(pytest.skip.Exception):
        require_or_skip("x")
    monkeypatch.setenv("ISOLATED_REQUIRE_INTEGRATION", "1")
    with pytest.raises(pytest.fail.Exception):
        require_or_skip("x")


@pytest.fixture
def admin() -> Iterator[Engine]:
    raw = os.environ.get("ISOLATED_ADMIN_URL", "")
    if not raw:
        require_or_skip("未設定 ISOLATED_ADMIN_URL；略過專屬資料庫生命週期測試")
    require_loopback(raw)
    eng = create_engine(raw, isolation_level="AUTOCOMMIT")
    try:
        yield eng
    finally:
        eng.dispose()


def _exists(admin: Engine, name: str) -> bool:
    with admin.connect() as conn:
        return bool(
            conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).first()
        )


def test_two_sessions_only_drop_their_own_database(admin: Engine) -> None:
    token_a, token_b = uuid4().hex, uuid4().hex
    name_a, name_b = create_database(admin, token_a), create_database(admin, token_b)
    try:
        with pytest.raises(UnsafeTargetError):
            drop_owned_database(admin, name_b, token_a)  # 用別人的 token 刪不掉
        assert _exists(admin, name_a) and _exists(admin, name_b)
        drop_owned_database(admin, name_a, token_a)
        assert not _exists(admin, name_a) and _exists(admin, name_b)  # 另一個工作階段不受影響
        with pytest.raises(UnsafeTargetError):
            create_database(admin, token_b)  # 已存在則拒絕覆蓋
    finally:
        for name, token in ((name_a, token_a), (name_b, token_b)):
            if _exists(admin, name):
                drop_owned_database(admin, name, token)
    assert not _exists(admin, name_a) and not _exists(admin, name_b)


def test_database_with_matching_name_but_foreign_owner_marker_is_never_dropped(
    admin: Engine,
) -> None:
    token = uuid4().hex
    name = database_name(token)
    with admin.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{name}"')  # 同名但不是本程式建立（沒有擁有者標記）
    try:
        with pytest.raises(UnsafeTargetError):
            drop_owned_database(admin, name, token)
        with admin.connect() as conn:
            conn.exec_driver_sql(
                f"COMMENT ON DATABASE \"{name}\" IS '{ownership_comment(uuid4().hex)}'"
            )
        with pytest.raises(UnsafeTargetError):
            drop_owned_database(admin, name, token)  # 標記屬於別的 token
        assert _exists(admin, name)
    finally:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')  # 測試自己剛建立的庫


def test_name_pattern_blocks_unrelated_databases(admin: Engine) -> None:
    token = uuid4().hex
    for name in ("postgres", "template1", "ig_t_full_v14_attempt", database_name(uuid4().hex)):
        with pytest.raises(UnsafeTargetError):
            drop_owned_database(admin, name, token)
