"""全公司共用供應商主檔；不匯入模擬資料、不自動授予部門權限。"""

from alembic import op

revision = "5e8b11d0a941"
down_revision = "7c1d4e9a2b30"
branch_labels = None
depends_on = None

SQL = """
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '15s';
DO $preflight$
BEGIN
    IF to_regclass('public.user_profiles') IS NULL OR to_regclass('public.app_functions') IS NULL THEN
        RAISE EXCEPTION '缺少 user_profiles 或 app_functions 前置表';
    END IF;
    IF to_regclass('public.suppliers') IS NOT NULL THEN
        RAISE EXCEPTION 'suppliers 已存在；須先人工核對結構，不覆蓋既有供應商資料';
    END IF;
    IF EXISTS (SELECT 1 FROM public.app_functions WHERE function_code = 'suppliers'
               AND (app_scope <> 'admin' OR function_name <> '供應商管理')) THEN
        RAISE EXCEPTION 'suppliers 功能代碼已被使用，請先確認衝突';
    END IF;
END
$preflight$;

CREATE TABLE public.suppliers (
    supplier_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    supplier_name text NOT NULL CHECK (length(btrim(supplier_name)) BETWEEN 1 AND 120),
    country_code text NOT NULL CHECK (country_code ~ '^[A-Z]{2}$'),
    tax_id text NOT NULL DEFAULT '' CHECK (length(tax_id) <= 40 AND tax_id = upper(btrim(tax_id))),
    aliases text NOT NULL DEFAULT '' CHECK (length(aliases) <= 600),
    contact_name text NOT NULL DEFAULT '' CHECK (length(contact_name) <= 80),
    phone text NOT NULL DEFAULT '' CHECK (length(phone) <= 40),
    email text NOT NULL DEFAULT '' CHECK (length(email) <= 200),
    address text NOT NULL DEFAULT '' CHECK (length(address) <= 300),
    payment_terms text NOT NULL CHECK (payment_terms IN ('immediate','net','monthly','prepaid','installment')),
    payment_basis text NOT NULL CHECK (payment_basis IN ('invoice','acceptance','received','month_end','contract')),
    payment_days integer NOT NULL CHECK (payment_days BETWEEN 0 AND 3650),
    payment_method text NOT NULL CHECK (payment_method IN ('transfer','check','cash','other')),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    notes text NOT NULL DEFAULT '' CHECK (length(notes) <= 1500),
    credit_rating text NOT NULL DEFAULT 'unassessed' CHECK (credit_rating IN ('unassessed','A','B','C')),
    delivery_terms text NOT NULL DEFAULT '' CHECK (length(delivery_terms) <= 300),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by uuid NOT NULL REFERENCES public.user_profiles(user_id) ON DELETE RESTRICT,
    updated_by uuid NOT NULL REFERENCES public.user_profiles(user_id) ON DELETE RESTRICT,
    CHECK (country_code <> 'TW' OR tax_id ~ '^[0-9]{8}$'),
    CHECK (payment_terms <> 'immediate' OR payment_days = 0),
    CHECK (payment_terms NOT IN ('prepaid','installment') OR (payment_basis = 'contract' AND length(btrim(notes)) > 0))
);
CREATE UNIQUE INDEX ux_suppliers_country_tax ON public.suppliers(country_code, tax_id) WHERE tax_id <> '';
COMMENT ON TABLE public.suppliers IS '全公司共用供應商主檔；ADMIN 依目前部門四操作授權，不刪除歷史';
COMMENT ON COLUMN public.suppliers.credit_rating IS '人工內部評估標籤，非外部徵信查核結果';
ALTER TABLE public.suppliers ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.suppliers FROM PUBLIC;
DO $security$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON public.suppliers FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON public.suppliers FROM authenticated;
    END IF;
END
$security$;
INSERT INTO public.app_functions (function_code, function_name, app_scope, is_active)
VALUES ('suppliers', '供應商管理', 'admin', true)
ON CONFLICT (function_code) DO NOTHING;
"""


def upgrade() -> None:
    """同一交易新增主檔與功能目錄；失敗即整批回復。"""
    op.execute(SQL)


def downgrade() -> None:
    """保護主檔，不以回退部署作為刪除供應商資料的理由。"""
    raise RuntimeError(
        "此 migration 不自動刪表；回退時先停用 suppliers 功能並保留主檔，由資料庫維護者審查"
    )
