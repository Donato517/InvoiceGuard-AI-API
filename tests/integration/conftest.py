"""
隔離 PostgreSQL 整合測試的共用 fixture。
規則：
    - 需設定 ISOLATED_DB_URL，且主機必須是本機回送位址（127.0.0.1／::1／localhost）；未設定則略過，
      指向其他主機則直接失敗，不會連線。
    - 資料庫須已載入 Schema 草案（v1.8，可去除 pgvector）；測試只寫入合成資料並在結束時清除，
      絕對不可指向正式資料庫。
"""

import os
from collections.abc import Iterator

import pytest
from isolated_db import World
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def block_external_services() -> None:
    """覆寫根 conftest 的封鎖；連線目標由 engine fixture 限制為本機回送位址。"""


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    raw = os.environ.get("ISOLATED_DB_URL", "")
    if not raw:
        pytest.skip("未設定 ISOLATED_DB_URL；略過隔離 PostgreSQL 整合測試")
    if make_url(raw).host not in LOCAL_HOSTS:
        pytest.fail("ISOLATED_DB_URL 必須指向本機回送位址，拒絕連線")
    eng = create_engine(raw, pool_size=8)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def world(engine: Engine) -> Iterator[World]:
    instance = World(engine)
    try:
        yield instance
    finally:
        instance.cleanup()
