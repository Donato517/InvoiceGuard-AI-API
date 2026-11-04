"""供應商 migration 真實 PostgreSQL 測試；僅可使用既有回送位址隔離庫 fixture。"""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from isolated_db import World
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError


def test_supplier_schema_constraints_and_soft_disable(engine: Engine, world: World) -> None:
    """DDL 與供應商測試資料全部在 rollback 交易內，不修改既有共享表內容。"""
    path = (
        Path(__file__).resolve().parents[2]
        / "app/db/migrations/versions/r20261104_5e8b11d0a941_suppliers.py"
    )
    spec = importlib.util.spec_from_file_location("supplier_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade()
            sql = text("""INSERT INTO public.suppliers
                (supplier_name,country_code,tax_id,payment_terms,payment_basis,payment_days,payment_method,currency,created_by,updated_by)
                VALUES ('合成供應商',:country,:tax,'net','invoice',30,'transfer','TWD',:actor,:actor)
                RETURNING supplier_id""")
            args = {"country": "TW", "tax": "00000101", "actor": world.user_id}
            key = connection.execute(sql, args).scalar_one()
            connection.execute(
                text("UPDATE public.suppliers SET is_active=false WHERE supplier_id=:id"),
                {"id": key},
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(sql, args)
            connection.execute(sql, args | {"country": "JP", "tax": ""})
            connection.execute(sql, args | {"country": "JP", "tax": ""})
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(sql, args | {"tax": "bad"})
            connection.execute(
                text("UPDATE public.suppliers SET is_active=true WHERE supplier_id=:id"),
                {"id": key},
            )
            assert (
                connection.execute(
                    text("SELECT is_active FROM public.suppliers WHERE supplier_id=:id"),
                    {"id": key},
                ).scalar_one()
                is True
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM public.department_permissions p JOIN public.app_functions f USING(function_id) WHERE f.function_code='suppliers'"
                    )
                ).scalar_one()
                == 0
            )
        finally:
            transaction.rollback()
