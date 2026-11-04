"""公司基本資料 migration 的離線輸出與資料保護，不連線正式服務。"""

import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

PATH = (
    Path(__file__).resolve().parents[2]
    / "app/db/migrations/versions/r20261104_8ef487f17b06_company_profile.py"
)


def migration():
    """只匯入獨立 migration，不啟動應用程式。"""
    spec = importlib.util.spec_from_file_location("company_profile_migration", PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_creates_single_row_table_without_data_or_grants() -> None:
    module = migration()
    assert module.down_revision == "5e8b11d0a941"
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE public.company_profile" in sql
    assert "CHECK (profile_id = 1)" in sql
    assert "ban ~ '^[0-9]{8}$'" in sql and "tax_reg_no ~ '^[0-9]{9}$'" in sql
    for column in (
        "representative_name",
        "business_zip_code",
        "business_city",
        "business_district",
        "business_street",
        "tax_office",
        "contact_name",
        "contact_phone",
        "contact_email",
    ):
        assert f"{column} text NOT NULL DEFAULT ''" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "REVOKE ALL ON public.company_profile FROM anon" in sql
    assert "VALUES ('company_profile', '公司基本資料', 'admin', true)" in sql
    assert "INSERT INTO public.company_profile" not in sql
    assert "INSERT INTO public.department_permissions" not in sql


def test_downgrade_never_drops_company_data() -> None:
    with pytest.raises(RuntimeError, match="不自動刪表"):
        migration().downgrade()
