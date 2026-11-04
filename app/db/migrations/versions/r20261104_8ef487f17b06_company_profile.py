"""本公司基本資料（單筆）；供 F09 申報檔讀取統一編號與稅籍編號，不自動授予部門權限。"""

from alembic import op

revision = "8ef487f17b06"
down_revision = "5e8b11d0a941"
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
    IF to_regclass('public.company_profile') IS NOT NULL THEN
        RAISE EXCEPTION 'company_profile 已存在；須先人工核對結構，不覆蓋既有公司資料';
    END IF;
    IF EXISTS (SELECT 1 FROM public.app_functions WHERE function_code = 'company_profile'
               AND (app_scope <> 'admin' OR function_name <> '公司基本資料')) THEN
        RAISE EXCEPTION 'company_profile 功能代碼已被使用，請先確認衝突';
    END IF;
END
$preflight$;

CREATE TABLE public.company_profile (
    profile_id smallint PRIMARY KEY DEFAULT 1 CHECK (profile_id = 1),
    company_name text NOT NULL CHECK (length(btrim(company_name)) BETWEEN 1 AND 120),
    ban text NOT NULL CHECK (ban ~ '^[0-9]{8}$'),
    tax_reg_no text NOT NULL CHECK (tax_reg_no ~ '^[0-9]{9}$'),
    representative_name text NOT NULL DEFAULT '' CHECK (length(representative_name) <= 80),
    business_zip_code text NOT NULL DEFAULT '' CHECK (business_zip_code ~ '^([0-9]{3})?$'),
    business_city text NOT NULL DEFAULT '' CHECK (length(business_city) <= 10),
    business_district text NOT NULL DEFAULT '' CHECK (length(business_district) <= 20),
    business_street text NOT NULL DEFAULT '' CHECK (length(business_street) <= 200),
    tax_office text NOT NULL DEFAULT '' CHECK (length(tax_office) <= 80),
    contact_name text NOT NULL DEFAULT '' CHECK (length(contact_name) <= 80),
    contact_phone text NOT NULL DEFAULT '' CHECK (length(contact_phone) <= 40),
    contact_email text NOT NULL DEFAULT '' CHECK (length(contact_email) <= 200),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by uuid NOT NULL REFERENCES public.user_profiles(user_id) ON DELETE RESTRICT,
    updated_by uuid NOT NULL REFERENCES public.user_profiles(user_id) ON DELETE RESTRICT
);
COMMENT ON TABLE public.company_profile IS '本公司基本資料，固定只有一筆（一個公司一個資料庫）；F09 申報檔讀取';
COMMENT ON COLUMN public.company_profile.ban IS '本公司統一編號 8 碼；檢查碼由程式驗證';
COMMENT ON COLUMN public.company_profile.tax_reg_no IS '稅籍編號 9 碼，不可用統一編號代替；沒有公開檢查碼';
COMMENT ON COLUMN public.company_profile.business_zip_code IS '營業地址 3 碼郵遞區號；由程式依縣市與鄉鎮市區帶出（中華郵政 103.12.25 一覽表）';
COMMENT ON COLUMN public.company_profile.business_street IS '營業地址的路街巷弄門牌；縣市與鄉鎮市區另存，程式驗證兩者對應';
COMMENT ON COLUMN public.company_profile.tax_office IS '主管稽徵機關，例如某國稅局某分局；僅記錄顯示';
COMMENT ON COLUMN public.company_profile.contact_name IS '申報聯絡窗口；負責人、地址與聯絡資料僅記錄顯示，系統邏輯不使用';
ALTER TABLE public.company_profile ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.company_profile FROM PUBLIC;
DO $security$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON public.company_profile FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON public.company_profile FROM authenticated;
    END IF;
END
$security$;
INSERT INTO public.app_functions (function_code, function_name, app_scope, is_active)
VALUES ('company_profile', '公司基本資料', 'admin', true)
ON CONFLICT (function_code) DO NOTHING;
"""


def upgrade() -> None:
    """同一交易新增公司資料表與功能目錄；失敗即整批回復。不寫入任何公司資料。"""
    op.execute(SQL)


def downgrade() -> None:
    """保護公司資料，不以回退部署作為刪除的理由。"""
    raise RuntimeError(
        "此 migration 不自動刪表；回退時先停用 company_profile 功能並保留資料，由資料庫維護者審查"
    )
