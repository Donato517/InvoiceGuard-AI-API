"""Show Case migration 離線 PostgreSQL 輸出驗證，不建立連線或執行 DDL。"""

import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations


def migration() -> object:
    """只載入 migration 本體，不載入 Alembic env 或雲端設定。"""
    path = (
        Path(__file__).resolve().parents[2]
        / "app/db/migrations/versions/m20261030_f5e7afb48888_showcase.py"
    )
    spec = importlib.util.spec_from_file_location("showcase_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_schema_and_default_denial() -> None:
    """產生 PostgreSQL 方言輸出，檢查私有表、RLS 與停用功能項目。"""
    out = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": out}
    )
    with Operations.context(context):
        migration().upgrade()
    sql = out.getvalue()
    assert sql.count("CREATE TABLE invoiceguard_showcase.") == 5
    assert sql.count("ENABLE ROW LEVEL SECURITY") == 5
    assert "CREATE TRIGGER showcase_events_immutable" in sql
    assert "SECURITY DEFINER" not in sql
    assert "'show_case'" in sql
    assert "'admin',false" in sql
    assert "ON CONFLICT(function_code) DO NOTHING" in sql
    assert "GRANT " not in sql
    assert "DROP TABLE" not in sql


def test_no_destructive_rollback() -> None:
    """不因 downgrade 清空原圖引用及歷史。"""
    with pytest.raises(RuntimeError, match="Show Case"):
        migration().downgrade()
