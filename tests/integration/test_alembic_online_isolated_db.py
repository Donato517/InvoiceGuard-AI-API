"""
測試目標：Alembic 線上模式（env.py 實際連線）在專屬隔離 PostgreSQL 上套用重送 Migration。
涵蓋：只載入基線的專屬庫 → 升級到重送 Migration（REVISION）成功並寫入 alembic_version；重複 upgrade 無動作；
`alembic downgrade base` 只在這個一次性專屬庫內驗證重送 Migration 可回復（不是清理手段，庫之後整個刪除）；
再次升級後 `alembic upgrade head` 成功到目前最新版本（HEAD 由 Alembic 讀取，不寫死）。
之後的 Migration（供應商 5e8b11d0a941、公司基本資料 8ef487f17b06）刻意不提供自動刪表的 downgrade，
所以可回復性只驗證到 REVISION，不對 head 執行 downgrade。
env.py 強制 TLS（resolve_ssl_mode），因此需要啟用 TLS 的本機 PostgreSQL；伺服器未啟用 TLS 時略過，
設定 ISOLATED_REQUIRE_ALEMBIC_ONLINE=1（例如 CI）則改為失敗，避免靜默不驗證。
需要專屬資料庫模式（ISOLATED_ADMIN_URL）；僅用合成的測試連線，子程序只傳入 PATH、HOME 與 DATABASE_URL。
"""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from db_lifecycle import (
    DEFAULT_BASELINE,
    create_database,
    drop_owned_database,
    load_baseline,
    require_loopback,
    require_or_skip,
)
from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[2]
# 重送 Migration：本測試驗證它可升級、可回復
REVISION = "7c1d4e9a2b30"
NEW_TABLES = (
    "invoice_return_items",
    "invoice_submission_snapshots",
    "invoice_resubmissions",
    "invoice_field_review_carryovers",
)


def alembic(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "DATABASE_URL": url,
    }
    return subprocess.run(
        [sys.executable, "-B", "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.fixture
def baseline_only_database() -> Iterator[str]:
    raw = os.environ.get("ISOLATED_ADMIN_URL", "")
    if not raw:
        require_or_skip("未設定 ISOLATED_ADMIN_URL；略過 Alembic 線上模式測試")
    admin_url = require_loopback(raw)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        tls = conn.execute(text("SHOW ssl")).scalar_one()
    if tls != "on":
        admin.dispose()
        if os.environ.get("ISOLATED_REQUIRE_ALEMBIC_ONLINE") == "1":
            pytest.fail("伺服器未啟用 TLS，無法驗證 Alembic 線上模式（env.py 強制 TLS）")
        pytest.skip("伺服器未啟用 TLS；env.py 強制 TLS，略過 Alembic 線上模式測試")
    with create_engine(admin_url, connect_args={"sslmode": "require"}).connect() as conn:
        in_tls = conn.execute(
            text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
        ).scalar_one()
    if not in_tls:  # sslmode=require 的連線必為 TLS；這裡直接向伺服器確認
        admin.dispose()
        pytest.fail("測試連線沒有使用 TLS（pg_stat_ssl.ssl 不是 true）")
    token = uuid4().hex
    name = create_database(admin, token)
    try:
        target = admin_url.set(database=name)
        engine = create_engine(target)
        try:
            load_baseline(engine, DEFAULT_BASELINE)  # 只有基線，尚未套用 Migration
        finally:
            engine.dispose()
        yield target.set(query={"sslmode": "require"}).render_as_string(hide_password=False)
    finally:
        try:
            drop_owned_database(admin, name, token)
        finally:
            admin.dispose()


def _state(url: str) -> tuple[str | None, int]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            exists = conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar_one()
            version = (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                if exists
                else None
            )
            tables = conn.execute(
                text("SELECT count(*) FROM pg_tables WHERE tablename = ANY(:t)"),
                {"t": list(NEW_TABLES)},
            ).scalar_one()
        return version, tables
    finally:
        engine.dispose()


def _head_revision() -> str:
    """目前 Migration 目錄的最新版本；之後新增 Migration 時不必改本測試。"""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(Config(str(REPO_ROOT / "alembic.ini"))).get_current_head()
    assert head is not None
    return head


def test_alembic_upgrade_runs_online_and_is_reversible_in_a_disposable_database(
    baseline_only_database: str,
) -> None:
    url = baseline_only_database
    assert _state(url) == (None, 0)
    result = alembic(url, "upgrade", REVISION)
    assert result.returncode == 0, result.stderr[-800:].replace(url, "<url>")
    assert _state(url) == (REVISION, 4)
    assert alembic(url, "upgrade", REVISION).returncode == 0  # 已在 REVISION，無動作
    assert REVISION in alembic(url, "current").stdout
    down = alembic(url, "downgrade", "base")
    assert down.returncode == 0, down.stderr[-800:].replace(url, "<url>")
    assert _state(url) == (None, 0)  # alembic_version 表仍在但已空
    assert alembic(url, "upgrade", REVISION).returncode == 0
    assert _state(url) == (REVISION, 4)
    # 之後的 Migration 只驗證可升級到最新，不 downgrade（刻意不自動刪表）
    head = alembic(url, "upgrade", "head")
    assert head.returncode == 0, head.stderr[-800:].replace(url, "<url>")
    assert _state(url) == (_head_revision(), 4)
    assert alembic(url, "upgrade", "head").returncode == 0  # 已在 head，無動作
