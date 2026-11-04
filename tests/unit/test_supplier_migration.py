"""供應商 migration 的離線輸出與資料保護，不連線正式服務。"""

import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

PATH = (
    Path(__file__).resolve().parents[2]
    / "app/db/migrations/versions/r20261104_5e8b11d0a941_suppliers.py"
)


def migration():
    """只匯入獨立 migration，不啟動應用程式。"""
    spec = importlib.util.spec_from_file_location("supplier_migration", PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_generates_postgres_sql_and_does_not_grant_departments() -> None:
    module = migration()
    assert module.down_revision == "7c1d4e9a2b30"
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE public.suppliers" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "REVOKE ALL ON public.suppliers FROM anon" in sql
    assert "ON DELETE RESTRICT" in sql
    assert "CREATE UNIQUE INDEX ux_suppliers_country_tax" in sql
    assert "INSERT INTO public.department_permissions" not in sql
    assert "ALTER TABLE public.invoices" not in sql


def test_downgrade_never_drops_supplier_data() -> None:
    with pytest.raises(RuntimeError, match="不自動刪表"):
        migration().downgrade()
