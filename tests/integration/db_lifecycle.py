"""
隔離 PostgreSQL 整合測試的專屬資料庫生命週期（建立、載入基線與 Migration、安全刪除）。
僅供 tests/integration 使用。
安全規則：
    - 管理連線（ISOLATED_ADMIN_URL）主機只能是本機回送位址。
    - 只刪除「本次工作階段自己建立」的資料庫：名稱符合固定格式，且資料庫註解的擁有者標記與本次 token 相同。
    - 不依賴「名稱含 test」判斷，也不使用萬用字元；不停用 Trigger 或 FK；不使用 alembic downgrade。
"""

import importlib.util
import os
import re
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
NAME_PATTERN = re.compile(r"^ig_it_[0-9a-f]{12}$")
TOKEN_PATTERN = re.compile(r"^[0-9a-f]{32}$")
COMMENT_PREFIX = "invoiceguard-it:"
DEFAULT_BASELINE = (
    Path(__file__).resolve().parents[1] / "fixtures/sql/v1_8_derived_test_baseline.sql"
)
MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "app/db/migrations/versions/r20261103_7c1d4e9a2b30_resubmit_structures.py"
)
_VECTOR_BLOCK = re.compile(
    r"CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;\s*"
    r"DO \$vector_check\$.*?\$vector_check\$;",
    re.DOTALL,
)
_VECTOR_TYPE = re.compile(r"extensions\.vector(\(\d+\))?")


class UnsafeTargetError(RuntimeError):
    """要操作的資料庫不符合安全條件，拒絕執行。"""


ALLOWED_QUERY_KEYS = frozenset({"sslmode"})
_TARGET_KEYS = ("host", "hostaddr", "service")


def require_loopback(raw_url: str) -> URL:
    """回傳解析後的 URL；主機不是本機回送位址、帶有白名單以外的查詢參數，或最終連線目標不是本機就拒絕。

    SQLAlchemy 會把查詢參數併入連線參數（例如 ?host= 會覆蓋網址主機），所以只允許 sslmode，
    並再檢查驅動程式最終解析出的連線目標。
    """
    url = make_url(raw_url)
    if url.host not in LOCAL_HOSTS:
        raise UnsafeTargetError("測試資料庫連線必須指向本機回送位址")
    unknown = sorted(set(url.query) - ALLOWED_QUERY_KEYS)
    if unknown:
        raise UnsafeTargetError(f"測試資料庫連線不允許的查詢參數：{', '.join(unknown)}")
    resolved = url.get_dialect()().create_connect_args(url)[1]
    if any(key in resolved for key in _TARGET_KEYS[1:]) or resolved.get("host") not in LOCAL_HOSTS:
        raise UnsafeTargetError("測試資料庫連線的最終目標不是本機回送位址")
    return url


def database_name(token: str) -> str:
    """由工作階段 token（32 位小寫十六進位）導出專屬資料庫名稱。"""
    if not TOKEN_PATTERN.fullmatch(token):
        raise UnsafeTargetError("token 格式不正確")
    return f"ig_it_{token[:12]}"


def ownership_comment(token: str) -> str:
    """寫入資料庫註解的擁有者標記。"""
    return f"{COMMENT_PREFIX}{token}"


def create_database(admin: Engine, token: str) -> str:
    """以管理連線（AUTOCOMMIT）建立專屬資料庫並寫入擁有者標記；已存在則拒絕。"""
    name = database_name(token)
    with admin.connect() as conn:
        if conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).first():
            raise UnsafeTargetError("專屬資料庫名稱已存在，拒絕覆蓋")
        conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
        conn.exec_driver_sql(f"COMMENT ON DATABASE \"{name}\" IS '{ownership_comment(token)}'")
    return name


def drop_owned_database(admin: Engine, name: str, token: str) -> None:
    """只在名稱格式、擁有者標記與 token 都相符時刪除資料庫；任何一項不符就拒絕並保留資料庫。

    Raises:
        UnsafeTargetError: 不符合安全條件。
    """
    if not NAME_PATTERN.fullmatch(name) or name != database_name(token):
        raise UnsafeTargetError("資料庫名稱與本次 token 不符，拒絕刪除")
    with admin.connect() as conn:
        if conn.execute(text("SELECT current_database()")).scalar_one() == name:
            raise UnsafeTargetError("管理連線不可位於要刪除的資料庫")
        comment = conn.execute(
            text(
                "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = :n"
            ),
            {"n": name},
        ).scalar_one_or_none()
        if comment != ownership_comment(token):
            raise UnsafeTargetError("資料庫擁有者標記不符，拒絕刪除")
        conn.exec_driver_sql(f'DROP DATABASE "{name}"')


def prepare_baseline_sql(raw: str, *, vector_available: bool) -> str:
    """基線 SQL 載入前處理：主機沒有 pgvector 時，移除擴充建立與檢查區塊，向量欄位改為 text（僅測試用）。"""
    if vector_available:
        return raw
    return _VECTOR_TYPE.sub("text", _VECTOR_BLOCK.sub("", raw))


def load_baseline(engine: Engine, baseline_path: Path) -> None:
    """把基線 SQL 檔以單一不帶參數的指令載入（保留 SQL 內的 %）。"""
    with engine.connect() as conn:
        available = conn.execute(
            text("SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'")
        ).scalar_one()
    sql = prepare_baseline_sql(
        baseline_path.read_text(encoding="utf-8"), vector_available=bool(available)
    )
    raw = engine.raw_connection()
    try:
        raw.driver_connection.autocommit = True  # type: ignore[attr-defined]
        raw.driver_connection.execute(sql)  # type: ignore[attr-defined]
    finally:
        raw.driver_connection.autocommit = False  # type: ignore[attr-defined]  # 連線會回到連線池，不可留下 autocommit
        raw.close()


def _migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("resubmit_migration_under_test", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apply_resubmit_migration(engine: Engine) -> None:
    """在單一交易內執行 Migration 的 upgrade()（不經 env.py，因此不寫 alembic_version）。"""
    module = _migration_module()
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        module.upgrade()


def create_isolated_engine(admin_url: str, token: str, baseline_path: Path) -> tuple[Engine, str]:
    """建立專屬資料庫、載入基線並套用 Migration；失敗時移除剛建立的資料庫後再拋出。"""
    admin_parsed = require_loopback(admin_url)
    admin = create_engine(admin_parsed, isolation_level="AUTOCOMMIT")
    name = create_database(admin, token)
    try:
        engine = create_engine(admin_parsed.set(database=name), pool_size=8)
        try:
            load_baseline(engine, baseline_path)
            apply_resubmit_migration(engine)
        except Exception:
            engine.dispose()
            raise
    except Exception:
        drop_owned_database(admin, name, token)
        raise
    finally:
        admin.dispose()
    return engine, name


def require_or_skip(reason: str) -> None:
    """缺少隔離資料庫設定時：一般情況略過；ISOLATED_REQUIRE_INTEGRATION=1（CI）則失敗，不得靜默略過。"""
    if os.environ.get("ISOLATED_REQUIRE_INTEGRATION") == "1":
        pytest.fail(f"必要的 PostgreSQL 整合測試無法執行（{reason}）")
    pytest.skip(reason)
