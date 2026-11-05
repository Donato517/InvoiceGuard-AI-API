"""接入 v2.0 供應商 OCR 範例，既有 Show Case 歷程由先前分支保留。"""

from alembic import op

revision = "4c7c7c1d26b0"
down_revision = ("8ef487f17b06", "f5e7afb48888")
branch_labels = None
depends_on = None

SQL = """
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '15s';

ALTER TABLE public.suppliers ADD CONSTRAINT suppliers_ocr_identity_key
    UNIQUE (supplier_id, country_code, tax_id);

CREATE TABLE public.supplier_invoice_examples (
    example_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    supplier_id          uuid NOT NULL,
    supplier_country_code text NOT NULL DEFAULT 'TW'
                          CONSTRAINT supplier_invoice_examples_country_chk CHECK (supplier_country_code = 'TW'),
    example_name         text NOT NULL
                         CONSTRAINT supplier_invoice_examples_name_chk
                         CHECK (pg_catalog.length(pg_catalog.btrim(example_name)) BETWEEN 1 AND 120),
    example_version      integer NOT NULL DEFAULT 1
                         CONSTRAINT supplier_invoice_examples_version_chk CHECK (example_version > 0),
    status               text NOT NULL DEFAULT 'candidate'
                         CONSTRAINT supplier_invoice_examples_status_chk
                         CHECK (status IN ('candidate','verified','revoked','retired')),
    invoice_kind         text NOT NULL DEFAULT 'triplicate_handwritten'
                         CONSTRAINT supplier_invoice_examples_kind_chk CHECK (invoice_kind = 'triplicate_handwritten'),
    template_key         text
                         CONSTRAINT supplier_invoice_examples_template_chk
                         CHECK (template_key IS NULL OR pg_catalog.length(pg_catalog.btrim(template_key)) BETWEEN 1 AND 120),
    bucket_name          text NOT NULL CHECK (pg_catalog.btrim(bucket_name) <> ''),
    storage_path         text NOT NULL CHECK (pg_catalog.btrim(storage_path) <> ''),
    original_filename    text NOT NULL CHECK (pg_catalog.btrim(original_filename) <> ''),
    mime_type            text NOT NULL CHECK (mime_type IN ('image/jpeg','image/png','application/pdf')),
    size_bytes           bigint NOT NULL CHECK (size_bytes > 0),
    content_sha256       text NOT NULL
                         CONSTRAINT supplier_invoice_examples_sha256_chk CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    source_invoice_id    uuid REFERENCES public.invoices(invoice_id) ON DELETE RESTRICT,
    source_file_id       uuid REFERENCES public.invoice_files(file_id) ON DELETE RESTRICT,
    source_file_version  integer NOT NULL DEFAULT 1 CHECK (source_file_version > 0),
    source_recognition_id uuid REFERENCES public.ai_recognition_logs(recognition_id) ON DELETE RESTRICT,
    document_group_id    text CHECK (document_group_id IS NULL OR pg_catalog.btrim(document_group_id) <> ''),
    invoice_track        text CHECK (invoice_track IS NULL OR invoice_track ~ '^[A-Z]{2}$'),
    invoice_number       text CHECK (invoice_number IS NULL OR invoice_number ~ '^[0-9]{8}$'),
    invoice_date         date,
    tax_period           text,
    seller_tax_id        text NOT NULL CHECK (seller_tax_id ~ '^[0-9]{8}$'),
    seller_name          text,
    buyer_tax_id         text CHECK (buyer_tax_id IS NULL OR buyer_tax_id ~ '^[0-9]{8}$'),
    buyer_name           text,
    sales_amount         numeric(18,2),
    tax_type             text CHECK (tax_type IN ('taxable','zero_rated','tax_exempt')),
    tax_amount           numeric(18,2),
    total_amount         numeric(18,2),
    total_amount_zh      text,
    notes                text,
    verified_field_keys  text[] NOT NULL DEFAULT ARRAY[]::text[],
    verified_by          uuid REFERENCES public.user_profiles(user_id) ON DELETE RESTRICT,
    verified_at          timestamptz,
    expires_at           timestamptz,
    verification_note    text NOT NULL DEFAULT '',
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    created_by           uuid NOT NULL REFERENCES public.user_profiles(user_id) ON DELETE RESTRICT,
    updated_by           uuid NOT NULL REFERENCES public.user_profiles(user_id) ON DELETE RESTRICT,
    CONSTRAINT supplier_invoice_examples_supplier_fkey
        FOREIGN KEY (supplier_id, supplier_country_code, seller_tax_id)
        REFERENCES public.suppliers(supplier_id, country_code, tax_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT supplier_invoice_examples_storage_unique UNIQUE (bucket_name, storage_path),
    CONSTRAINT supplier_invoice_examples_source_unique UNIQUE (supplier_id, content_sha256),
    CONSTRAINT supplier_invoice_examples_verified_keys_chk CHECK (
        COALESCE(pg_catalog.array_ndims(verified_field_keys), 1) = 1
        AND pg_catalog.array_position(verified_field_keys, NULL) IS NULL
        AND pg_catalog.array_position(verified_field_keys, '') IS NULL
    ),
    CONSTRAINT supplier_invoice_examples_verifier_pair_chk
        CHECK ((verified_by IS NULL) = (verified_at IS NULL)),
    CONSTRAINT supplier_invoice_examples_verified_chk CHECK (
        status <> 'verified' OR
        (verified_by IS NOT NULL AND verified_at IS NOT NULL AND pg_catalog.cardinality(verified_field_keys) > 0)
    ),
    CONSTRAINT supplier_invoice_examples_expiry_chk CHECK (expires_at IS NULL OR expires_at > created_at)
);
CREATE INDEX ix_supplier_invoice_examples_lookup
    ON public.supplier_invoice_examples (supplier_id, invoice_kind, template_key, verified_at DESC)
    WHERE status = 'verified';

CREATE TABLE public.supplier_invoice_example_items (
    example_item_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    example_id      uuid NOT NULL REFERENCES public.supplier_invoice_examples(example_id) ON DELETE CASCADE,
    line_no         integer NOT NULL
                    CONSTRAINT supplier_invoice_example_items_line_chk CHECK (line_no BETWEEN 1 AND 50),
    item_name       text,
    quantity        numeric(18,4),
    unit_price      numeric(18,4),
    line_amount     numeric(18,2),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT supplier_invoice_example_items_line_unique UNIQUE (example_id, line_no)
);

CREATE TRIGGER supplier_invoice_examples_touch_updated_at
BEFORE UPDATE ON public.supplier_invoice_examples
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.touch_updated_at();

CREATE TRIGGER supplier_invoice_example_items_touch_updated_at
BEFORE UPDATE ON public.supplier_invoice_example_items
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.touch_updated_at();

ALTER TABLE public.supplier_invoice_examples ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.supplier_invoice_example_items ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.supplier_invoice_examples, public.supplier_invoice_example_items FROM PUBLIC;

DO $acl$
DECLARE
    role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'service_role']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = role_name) THEN
            EXECUTE format(
                'REVOKE ALL ON TABLE public.supplier_invoice_examples, public.supplier_invoice_example_items FROM %I',
                role_name
            );
        END IF;
    END LOOP;
END
$acl$;
"""


def upgrade() -> None:
    """建立 v2.0 範例表與兩個更新時間觸發器。"""
    op.execute(SQL)


def downgrade() -> None:
    """保留既有票面資料，回復策略由部署者審核。"""
    raise RuntimeError("需保留供應商 OCR 範例與驗證紀錄")
