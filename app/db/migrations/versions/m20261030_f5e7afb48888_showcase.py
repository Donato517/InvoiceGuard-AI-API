"""showcase

Revision ID: f5e7afb48888
Revises:
Create Date: 2026-10-30 15:56:30.771246

異動說明：
    - 新增私有 Show Case schema；使用固定 SQL repository，不新增 ORM 副本。
提醒：
    - 此新增私有 schema 採固定 SQL repository，沒有 ORM Model。
    - 正式套用前核對既有 migration 歷史、backend role 與私有儲存設定。
    - 只建立停用的功能目錄，不指派任何部門 grant，不執行破壞性 downgrade。
"""

from collections.abc import Sequence

from alembic import op

# Alembic 版本識別碼（請勿手動修改）
revision: str = "f5e7afb48888"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """只建立新增範例資料，不變更既有身分、發票或授權資料。"""
    op.execute("CREATE SCHEMA invoiceguard_showcase")
    op.execute("REVOKE ALL ON SCHEMA invoiceguard_showcase FROM PUBLIC")
    op.execute("""
        CREATE TABLE invoiceguard_showcase.suppliers (
          id uuid PRIMARY KEY, department_id uuid NOT NULL,
          tax_id varchar(8) NOT NULL CHECK(tax_id ~ '^[0-9]{8}$'),
          name varchar(120) NOT NULL, UNIQUE(department_id,tax_id)
        )
    """)
    op.execute("""
        CREATE TABLE invoiceguard_showcase.samples (
          id uuid PRIMARY KEY, department_id uuid NOT NULL,
          version integer NOT NULL CHECK(version>0), payload jsonb NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
          CHECK(jsonb_typeof(payload)='object'),
          CHECK(jsonb_typeof(payload->'revisions')='array')
        )
    """)
    op.execute(
        "CREATE INDEX showcase_samples_dept ON invoiceguard_showcase.samples(department_id,updated_at DESC,id)"
    )
    op.execute("""
        CREATE TABLE invoiceguard_showcase.events (
          id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          department_id uuid NOT NULL, sample_id uuid NOT NULL REFERENCES invoiceguard_showcase.samples(id),
          actor_id uuid NOT NULL, action varchar(40) NOT NULL, reason varchar(500) NOT NULL,
          version integer NOT NULL, details jsonb NOT NULL,
          occurred_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )
    """)
    op.execute(
        "CREATE INDEX showcase_events_sample ON invoiceguard_showcase.events(department_id,sample_id,id DESC)"
    )
    op.execute("""
        CREATE TABLE invoiceguard_showcase.uploads (
          object_key text PRIMARY KEY, department_id uuid NOT NULL, actor_id uuid NOT NULL,
          mime varchar(40) NOT NULL, digest varchar(64) NOT NULL,
          state varchar(20) NOT NULL DEFAULT 'reserved' CHECK(state IN ('reserved','uploaded','linked')),
          created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )
    """)
    op.execute("""
        CREATE TABLE invoiceguard_showcase.tests (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), department_id uuid NOT NULL,
          actor_id uuid NOT NULL, sample_id uuid NOT NULL REFERENCES invoiceguard_showcase.samples(id),
          revision_id uuid NOT NULL, source jsonb NOT NULL, note varchar(2000) NOT NULL,
          created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )
    """)
    for name in ("suppliers", "samples", "events", "uploads", "tests"):
        op.execute(f"ALTER TABLE invoiceguard_showcase.{name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON invoiceguard_showcase.{name} FROM PUBLIC")
    op.execute("""
        CREATE FUNCTION invoiceguard_showcase.reject_event_mutation() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog AS $$
        BEGIN RAISE EXCEPTION 'Show Case events are append-only'; END; $$
    """)
    op.execute("""
        CREATE TRIGGER showcase_events_immutable BEFORE UPDATE OR DELETE
        ON invoiceguard_showcase.events FOR EACH ROW
        EXECUTE FUNCTION invoiceguard_showcase.reject_event_mutation()
    """)
    op.execute("""
        INSERT INTO public.app_functions(function_code,function_name,app_scope,is_active)
        VALUES ('show_case','供應商 Show Case 管理','admin',false),
               ('supplier.showcase-activation','Show Case 啟用管理','admin',false)
        ON CONFLICT(function_code) DO NOTHING
    """)
    # 私有 schema 無匿名或 authenticated 存取；部署者須核定 backend role 的最小權限與 RLS。
    # 不自動 grant service_role，不新增可從瀏覽器呼叫的繞過函式。


def downgrade() -> None:
    """第一版保留全部來源與歷史；禁止自動破壞性 rollback。"""
    raise RuntimeError("Show Case 歷史必須保留；回復採停用程式，資料移除需另行審查")
