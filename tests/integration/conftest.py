"""
隔離 PostgreSQL 整合測試的共用 fixture。
兩種模式（皆限本機回送位址；都未設定則略過整合測試）：
    - 專屬資料庫模式（建議）：設定 ISOLATED_ADMIN_URL（可建立資料庫的本機帳號）；ISOLATED_BASELINE_SQL 可另外
      指定基線 Schema SQL 檔，未指定則使用 tests/fixtures/sql 的 test-only 基線（不是正式 Schema）。每個測試工作階段建立一個專屬資料庫，載入基線並套用重送 Migration，
      結束時只刪除自己建立的資料庫（名稱格式、擁有者標記與 token 皆相符才刪，見 db_lifecycle.py）。
    - 既有資料庫模式（向下相容）：設定 ISOLATED_DB_URL，指向已載入 Schema 草案的本機測試庫；
      測試只寫入合成資料並於結束時逐筆清除，不建立也不刪除資料庫。限制：該庫若已套用重送 Migration，
      歷史表有資料的發票無法逐筆清除（FK RESTRICT 與不可變 Trigger，不可繞過），請改用專屬資料庫模式。
絕對不可指向正式或共享資料庫。需要寫入歷史表的測試只在專屬資料庫模式執行（歷史表禁止刪除）。
"""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from db_lifecycle import (
    DEFAULT_BASELINE,
    UnsafeTargetError,
    create_isolated_engine,
    drop_owned_database,
    require_loopback,
    require_or_skip,
)
from isolated_db import World
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import DBAPIError


@pytest.fixture(autouse=True)
def block_external_services() -> None:
    """覆寫根 conftest 的封鎖；連線目標由 engine fixture 限制為本機回送位址。"""


def _managed_settings() -> tuple[str, Path] | None:
    admin = os.environ.get("ISOLATED_ADMIN_URL", "")
    if not admin:
        return None
    # 未指定 ISOLATED_BASELINE_SQL 時使用 Repo 內的 test-only 基線（tests/fixtures/sql/README.md）
    return admin, Path(os.environ.get("ISOLATED_BASELINE_SQL") or DEFAULT_BASELINE)


@pytest.fixture(scope="session")
def managed_database() -> Iterator[bool]:
    """True 表示本次工作階段使用自己建立的專屬資料庫；engine fixture 依此決定模式。"""
    yield _managed_settings() is not None


@pytest.fixture(scope="session")
def engine(managed_database: bool) -> Iterator[Engine]:
    settings = _managed_settings()
    if settings is not None:
        admin_url, baseline = settings
        if not baseline.is_file():
            pytest.fail("ISOLATED_BASELINE_SQL 指向的檔案不存在")
        try:
            require_loopback(admin_url)
        except UnsafeTargetError as error:
            pytest.fail(str(error))
        token = uuid4().hex
        eng, name = create_isolated_engine(admin_url, token, baseline)
        try:
            yield eng
        finally:
            eng.dispose()
            admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
            try:
                drop_owned_database(admin, name, token)
            except Exception as error:  # 清理失敗必須報告，且不擴大刪除範圍
                pytest.fail(f"專屬測試資料庫 {name} 未能刪除，請依 RUNBOOK 人工處理：{error}")
            finally:
                admin.dispose()
        return

    raw = os.environ.get("ISOLATED_DB_URL", "")
    if not raw:
        require_or_skip("未設定 ISOLATED_ADMIN_URL 或 ISOLATED_DB_URL；略過隔離整合測試")
    try:
        require_loopback(raw)
    except UnsafeTargetError as error:
        pytest.fail(f"ISOLATED_DB_URL 必須指向本機回送位址，拒絕連線：{error}")
    eng = create_engine(raw, pool_size=8)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def world(engine: Engine, managed_database: bool) -> Iterator[World]:
    instance = World(engine)
    try:
        yield instance
    finally:
        if not managed_database:  # 專屬資料庫整個刪除；既有資料庫逐筆清除
            try:
                instance.cleanup()
            except DBAPIError as error:
                pytest.fail(
                    "既有資料庫模式無法清除有重送歷史的資料（歷史表受保護，不可繞過）；"
                    "請改用專屬資料庫模式（ISOLATED_ADMIN_URL），並人工處理這個庫的殘留測試資料。"
                    f"原始錯誤類型：{type(error.orig).__name__}"
                )


@pytest.fixture
def managed_engine(engine: Engine, managed_database: bool) -> Engine:
    """需要寫入不可刪除歷史表的測試使用；既有資料庫模式略過。"""
    if not managed_database:
        require_or_skip("需要專屬資料庫模式（歷史表禁止刪除，無法在既有資料庫清理）")
    return engine
