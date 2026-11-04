"""退回補正／申覆重送的資料結構（只新增，不改既有欄位語意）。

Revision ID: 7c1d4e9a2b30
Revises:
Create Date: 2026-11-03

狀態：已建立檔案，尚未執行，也尚未對照正式資料庫版本。執行 `alembic upgrade` 需使用者明確授權。

背景：正式資料表不是由 Alembic 建立（versions 目錄原本為空），本檔是第一個 revision，只做「新增」：
    - invoice_return_items            R8  結構化退件項目與申請人回覆、財務處理結果
    - invoice_submission_snapshots    R3  每輪正式提交的完整結構化快照（建立後不可改、不可刪）
    - invoice_resubmissions           R7  冪等紀錄（key、請求指紋、原結果）
    - invoice_field_review_carryovers R1  承接前輪確認效力的來源證據（不改前輪覆核列）
    - invoice_changes.event_seq       R9  同一交易內的編輯事件順序（changed_at 在同交易內相同，無法排序）
不新增欄位到 invoices／invoice_status_history：R2 的退件來源節點由「returned_to_applicant 那一列歷程的
old_status」表示，需確認 ADMIN 退回時確實寫入 old_status（尚未驗證）。

前置條件（依 v1.8 草案；本檔以預檢保護，缺任何一項會整個 rollback）：
    public.invoices／invoice_items／invoice_files／invoice_field_reviews／user_profiles 已存在且主鍵為 uuid，
    invoiceguard_internal schema 已存在，且 invoice_items 具 UNIQUE (invoice_id, item_id)。
所有 DDL 使用 IF NOT EXISTS，可重複執行；PostgreSQL 15+（UNIQUE NULLS NOT DISTINCT）。

對既有表的唯一異動（皆為新增，不改欄位語意）：invoice_changes.event_seq 欄位與其唯一索引，以及
invoice_field_reviews 上的兩個守門 Trigger（承接列與新覆核列互斥；已被承接的確認不得取消）。
歷史表（快照、冪等、承接、退件項目）禁止 UPDATE／DELETE／TRUNCATE 的規則會使「刪除發票」流程受限
（FK 為 RESTRICT），測試清理與 RUNBOOK_DELETE_TEST_INVOICES 需另行決定合法刪除路徑，本檔未提供。
"""

from alembic import op

revision = "7c1d4e9a2b30"
down_revision = None
branch_labels = None
depends_on = None

_PREFLIGHT = """
DO $preflight$
DECLARE
    missing text;
BEGIN
    IF current_setting('server_version_num')::int < 150000 THEN
        RAISE EXCEPTION 'resubmit migration 需要 PostgreSQL 15 以上';
    END IF;
    SELECT string_agg(t, ', ') INTO missing
    FROM unnest(ARRAY['invoices','invoice_items','invoice_files','invoice_field_reviews',
                      'invoice_changes','invoice_status_history','user_profiles']) AS t
    WHERE to_regclass('public.' || t) IS NULL;
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION '缺少前置資料表：%', missing;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'invoiceguard_internal') THEN
        RAISE EXCEPTION '缺少 schema invoiceguard_internal';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.invoice_items'::regclass AND contype = 'u'
          AND pg_get_constraintdef(oid) = 'UNIQUE (invoice_id, item_id)'
    ) THEN
        RAISE EXCEPTION 'invoice_items 缺少 UNIQUE (invoice_id, item_id)';
    END IF;
END
$preflight$;
"""

_TABLES = """
-- R8：結構化退件項目。reason 為財務原始原因，申請人回覆與財務處理結果另存欄位，原因不會被覆蓋。
CREATE TABLE IF NOT EXISTS public.invoice_return_items (
    return_item_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id        uuid NOT NULL REFERENCES public.invoices(invoice_id) ON DELETE RESTRICT,
    submission_round  integer NOT NULL CHECK (submission_round > 0),  -- 被退回的輪次
    item_kind         text NOT NULL CHECK (item_kind IN ('field','image','other')),
    field_scope       text CHECK (field_scope IN ('header','item')),
    item_id           uuid,
    field_name        text,
    reason            text NOT NULL CHECK (btrim(reason) <> ''),
    -- 財務授權的相依欄位：物件陣列，每個物件含 field_scope、field_name，明細欄位另含 item_id
    -- （注意：SQL 文字不可出現「冒號+名稱」寫法，op.execute 會把它當成綁定參數）
    allowed_fields    jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(allowed_fields) = 'array'),
    status            text NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open','corrected','appealed','accepted','rejected')),
    response_action   text CHECK (response_action IN ('corrected','appealed')),
    response_note     text,
    responded_by      uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    responded_at      timestamptz,
    response_round    integer CHECK (response_round > 0),             -- 回覆所屬的新提交輪次
    resolved_by       uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    resolved_at       timestamptz,
    resolution_note   text,
    created_by        uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT invoice_return_items_target_chk CHECK (
        (item_kind = 'field' AND field_scope IS NOT NULL AND field_name IS NOT NULL
            AND ((field_scope = 'header' AND item_id IS NULL)
              OR (field_scope = 'item' AND item_id IS NOT NULL)))
        OR (item_kind <> 'field' AND field_scope IS NULL AND item_id IS NULL
            AND field_name IS NULL AND allowed_fields = '[]'::jsonb)
    ),
    CONSTRAINT invoice_return_items_response_chk CHECK (
        (response_action IS NULL AND responded_at IS NULL AND response_round IS NULL)
        OR (response_action IS NOT NULL AND responded_at IS NOT NULL AND response_round IS NOT NULL
            AND (response_action <> 'appealed' OR btrim(coalesce(response_note, '')) <> ''))
    ),
    -- 圖片問題不接受補正或申覆，只能作廢重傳；other 類型是否可回覆尚無正式決議，DB 不限制
    CONSTRAINT invoice_return_items_kind_response_chk CHECK (
        item_kind <> 'image' OR response_action IS NULL
    ),
    -- 允許欄位的格式：陣列內每個元素是物件，含 field_scope（header／item）與字串 field_name，item 另需字串 item_id
    CONSTRAINT invoice_return_items_allowed_fields_chk CHECK (
        NOT jsonb_path_exists(allowed_fields, 'strict $[*] ? (@.type() != "object")')
        AND NOT jsonb_path_exists(allowed_fields,
            'lax $[*] ? (!(exists(@.field_scope) && (@.field_scope == "header" || @.field_scope == "item"))'
            ' || !(exists(@.field_name) && @.field_name.type() == "string")'
            ' || (@.field_scope == "item" && !(exists(@.item_id) && @.item_id.type() == "string")))')
    ),
    FOREIGN KEY (invoice_id, item_id)
        REFERENCES public.invoice_items(invoice_id, item_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_invoice_return_items_invoice_round
    ON public.invoice_return_items (invoice_id, submission_round, status);

-- R3：每輪正式提交的完整快照；圖片以 file_id 參照，不複製。
CREATE TABLE IF NOT EXISTS public.invoice_submission_snapshots (
    snapshot_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id        uuid NOT NULL REFERENCES public.invoices(invoice_id) ON DELETE RESTRICT,
    submission_round  integer NOT NULL CHECK (submission_round > 0),
    submission_kind   text NOT NULL
                      CHECK (submission_kind IN ('first','resubmit_corrected','resubmit_appeal')),
    header            jsonb NOT NULL,
    items             jsonb NOT NULL CHECK (jsonb_typeof(items) = 'array'),
    validation_results jsonb NOT NULL DEFAULT '{}'::jsonb,
    file_id           uuid REFERENCES public.invoice_files(file_id) ON DELETE RESTRICT,
    submitted_by      uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    submitted_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (invoice_id, submission_round)
);

-- R7：冪等紀錄；同一案件、同一操作者、同一 key 只會有一列。
CREATE TABLE IF NOT EXISTS public.invoice_resubmissions (
    resubmission_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id          uuid NOT NULL REFERENCES public.invoices(invoice_id) ON DELETE RESTRICT,
    idempotency_key     uuid NOT NULL,
    request_fingerprint text NOT NULL,
    from_round          integer NOT NULL CHECK (from_round > 0),
    to_round            integer NOT NULL,
    requested_by        uuid NOT NULL REFERENCES public.user_profiles(user_id) ON DELETE RESTRICT,
    requested_at        timestamptz NOT NULL DEFAULT now(),
    result              jsonb NOT NULL,
    UNIQUE (invoice_id, requested_by, idempotency_key),
    -- 同一案件的同一輪只能被推進一次（不同 key 也不行）
    UNIQUE (invoice_id, from_round),
    CHECK (to_round = from_round + 1)
);

-- R1：承接前輪確認效力。只指向前輪覆核列（原確認者、確認時間、來源輪次由該列保存），不複製也不改它。
CREATE TABLE IF NOT EXISTS public.invoice_field_review_carryovers (
    carryover_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id           uuid NOT NULL REFERENCES public.invoices(invoice_id) ON DELETE RESTRICT,
    submission_round     integer NOT NULL CHECK (submission_round > 1),  -- 承接到的新輪次
    field_scope          text NOT NULL CHECK (field_scope IN ('header','item')),
    item_id              uuid,
    field_name           text NOT NULL,
    source_field_review_id uuid NOT NULL
        REFERENCES public.invoice_field_reviews(field_review_id) ON DELETE RESTRICT,
    created_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT invoice_field_review_carryovers_scope_chk CHECK (
        (field_scope = 'header' AND item_id IS NULL)
        OR (field_scope = 'item' AND item_id IS NOT NULL)
    ),
    CONSTRAINT invoice_field_review_carryovers_unique
        UNIQUE NULLS NOT DISTINCT (invoice_id, submission_round, field_scope, item_id, field_name),
    FOREIGN KEY (invoice_id, item_id)
        REFERENCES public.invoice_items(invoice_id, item_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_invoice_field_review_carryovers_source
    ON public.invoice_field_review_carryovers (source_field_review_id);

-- R9：同一輪內的編輯順序（既有列為 NULL，新寫入由 API 填 1、2、3…）。
ALTER TABLE public.invoice_changes ADD COLUMN IF NOT EXISTS event_seq integer
    CHECK (event_seq IS NULL OR event_seq > 0);
CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_changes_round_seq
    ON public.invoice_changes (invoice_id, submission_round, event_seq) WHERE event_seq IS NOT NULL;
"""

_IMMUTABLE = """
CREATE OR REPLACE FUNCTION invoiceguard_internal.forbid_modification()
RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION '% 不可修改、刪除或清空（歷史紀錄）', TG_TABLE_NAME;
END
$fn$;

-- 退件項目：回覆與處理結果欄位可更新，退件本身（原因、目標、授權欄位、建立者）不可更動
CREATE OR REPLACE FUNCTION invoiceguard_internal.guard_return_item_update()
RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF (NEW.invoice_id, NEW.submission_round, NEW.item_kind, NEW.field_scope, NEW.item_id,
        NEW.field_name, NEW.reason, NEW.allowed_fields, NEW.created_by, NEW.created_at)
       IS DISTINCT FROM
       (OLD.invoice_id, OLD.submission_round, OLD.item_kind, OLD.field_scope, OLD.item_id,
        OLD.field_name, OLD.reason, OLD.allowed_fields, OLD.created_by, OLD.created_at) THEN
        RAISE EXCEPTION '退件項目的原因與授權範圍建立後不可更動';
    END IF;
    RETURN NEW;
END
$fn$;

-- 承接列的有效性：同發票、同欄位、來源已確認、來源早於本輪且為該欄位最新的確認、本輪沒有新覆核列
CREATE OR REPLACE FUNCTION invoiceguard_internal.check_review_carryover()
RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE
    src record;
    current_round integer;
BEGIN
    SELECT invoice_id, submission_round, field_scope, item_id, field_name, is_checked
      INTO src FROM public.invoice_field_reviews WHERE field_review_id = NEW.source_field_review_id;
    IF NOT FOUND OR src.invoice_id <> NEW.invoice_id OR src.field_scope <> NEW.field_scope
       OR src.item_id IS DISTINCT FROM NEW.item_id OR src.field_name <> NEW.field_name THEN
        RAISE EXCEPTION '承接來源與發票或欄位不符';
    END IF;
    IF NOT src.is_checked THEN
        RAISE EXCEPTION '承接來源尚未被財務確認';
    END IF;
    IF src.submission_round >= NEW.submission_round THEN
        RAISE EXCEPTION '承接來源必須早於承接輪次';
    END IF;
    SELECT submission_round INTO current_round FROM public.invoices WHERE invoice_id = NEW.invoice_id;
    IF current_round IS NULL OR NEW.submission_round > current_round THEN
        RAISE EXCEPTION '承接輪次超過發票目前輪次';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.invoice_field_reviews r
        WHERE r.invoice_id = NEW.invoice_id AND r.field_scope = NEW.field_scope
          AND r.item_id IS NOT DISTINCT FROM NEW.item_id AND r.field_name = NEW.field_name
          AND r.submission_round > src.submission_round AND r.submission_round <= NEW.submission_round
    ) THEN
        RAISE EXCEPTION '來源之後該欄位已有較新的覆核列，不可承接較舊的確認';
    END IF;
    RETURN NEW;
END
$fn$;

-- invoice_field_reviews 守門：新覆核列不可與同輪承接列並存；已被承接的確認不得更動或取消
CREATE OR REPLACE FUNCTION invoiceguard_internal.guard_field_review_insert()
RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.invoice_field_review_carryovers c
        WHERE c.invoice_id = NEW.invoice_id AND c.submission_round = NEW.submission_round
          AND c.field_scope = NEW.field_scope AND c.item_id IS NOT DISTINCT FROM NEW.item_id
          AND c.field_name = NEW.field_name
    ) THEN
        RAISE EXCEPTION '此欄位本輪已承接前輪確認，不可再建立覆核列';
    END IF;
    RETURN NEW;
END
$fn$;

CREATE OR REPLACE FUNCTION invoiceguard_internal.guard_field_review_update()
RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF (NEW.invoice_id, NEW.submission_round, NEW.field_scope, NEW.item_id, NEW.field_name,
        NEW.is_checked, NEW.checked_by, NEW.checked_at)
       IS DISTINCT FROM
       (OLD.invoice_id, OLD.submission_round, OLD.field_scope, OLD.item_id, OLD.field_name,
        OLD.is_checked, OLD.checked_by, OLD.checked_at)
       AND EXISTS (SELECT 1 FROM public.invoice_field_review_carryovers c
                   WHERE c.source_field_review_id = OLD.field_review_id) THEN
        RAISE EXCEPTION '此確認已被後續輪次承接，不可更動或取消';
    END IF;
    RETURN NEW;
END
$fn$;

DO $trg$
DECLARE
    t text;
BEGIN
    -- 歷史表：禁止逐列 UPDATE／DELETE 與 TRUNCATE
    FOREACH t IN ARRAY ARRAY['invoice_submission_snapshots','invoice_resubmissions',
                             'invoice_field_review_carryovers'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger
                       WHERE tgrelid = ('public.' || t)::regclass AND tgname = 'trg_' || t || '_immutable') THEN
            EXECUTE format(
                'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I '
                'FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.forbid_modification()',
                'trg_' || t || '_immutable', t);
        END IF;
    END LOOP;
    -- 含退件項目：任何歷史表都不可 TRUNCATE
    FOREACH t IN ARRAY ARRAY['invoice_submission_snapshots','invoice_resubmissions',
                             'invoice_field_review_carryovers','invoice_return_items'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger
                       WHERE tgrelid = ('public.' || t)::regclass AND tgname = 'trg_' || t || '_no_truncate') THEN
            EXECUTE format(
                'CREATE TRIGGER %I BEFORE TRUNCATE ON public.%I '
                'FOR EACH STATEMENT EXECUTE FUNCTION invoiceguard_internal.forbid_modification()',
                'trg_' || t || '_no_truncate', t);
        END IF;
    END LOOP;

    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'public.invoice_return_items'::regclass
                   AND tgname = 'trg_invoice_return_items_a_guard') THEN
        CREATE TRIGGER trg_invoice_return_items_a_guard BEFORE UPDATE ON public.invoice_return_items
        FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.guard_return_item_update();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'public.invoice_return_items'::regclass
                   AND tgname = 'trg_invoice_return_items_no_delete') THEN
        CREATE TRIGGER trg_invoice_return_items_no_delete BEFORE DELETE ON public.invoice_return_items
        FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.forbid_modification();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'public.invoice_field_review_carryovers'::regclass
                   AND tgname = 'trg_invoice_field_review_carryovers_a_check') THEN
        CREATE TRIGGER trg_invoice_field_review_carryovers_a_check
        BEFORE INSERT ON public.invoice_field_review_carryovers
        FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.check_review_carryover();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'public.invoice_field_reviews'::regclass
                   AND tgname = 'trg_invoice_field_reviews_carryover_insert_guard') THEN
        CREATE TRIGGER trg_invoice_field_reviews_carryover_insert_guard
        BEFORE INSERT ON public.invoice_field_reviews
        FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.guard_field_review_insert();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'public.invoice_field_reviews'::regclass
                   AND tgname = 'trg_invoice_field_reviews_carryover_update_guard') THEN
        CREATE TRIGGER trg_invoice_field_reviews_carryover_update_guard
        BEFORE UPDATE ON public.invoice_field_reviews
        FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.guard_field_review_update();
    END IF;
END
$trg$;

DO $trg$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgrelid = 'public.invoice_return_items'::regclass
          AND tgname = 'trg_invoice_return_items_touch'
    ) AND EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                  WHERE n.nspname = 'invoiceguard_internal' AND p.proname = 'touch_updated_at') THEN
        CREATE TRIGGER trg_invoice_return_items_touch BEFORE UPDATE ON public.invoice_return_items
        FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.touch_updated_at();
    END IF;
END
$trg$;
"""

_SECURITY = """
-- 比照 v1.8：預設拒絕。
ALTER TABLE public.invoice_return_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_submission_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_resubmissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_field_review_carryovers ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.invoice_return_items, public.invoice_submission_snapshots,
              public.invoice_resubmissions, public.invoice_field_review_carryovers FROM PUBLIC;
"""


def upgrade() -> None:
    """依序執行預檢、建表、不可變 Trigger 與預設拒絕；任一步失敗整個交易 rollback。"""
    for statement in (_PREFLIGHT, _TABLES, _IMMUTABLE, _SECURITY):
        op.execute(statement)


def downgrade() -> None:
    """移除本 revision 新增的物件。會刪除這些表內的所有資料，只能在隔離環境使用。"""
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_invoice_field_reviews_carryover_insert_guard ON public.invoice_field_reviews;
        DROP TRIGGER IF EXISTS trg_invoice_field_reviews_carryover_update_guard ON public.invoice_field_reviews;
        DROP TABLE IF EXISTS public.invoice_field_review_carryovers;
        DROP TABLE IF EXISTS public.invoice_resubmissions;
        DROP TABLE IF EXISTS public.invoice_submission_snapshots;
        DROP TABLE IF EXISTS public.invoice_return_items;
        DROP INDEX IF EXISTS public.ux_invoice_changes_round_seq;
        ALTER TABLE public.invoice_changes DROP COLUMN IF EXISTS event_seq;
        DROP FUNCTION IF EXISTS invoiceguard_internal.guard_field_review_insert();
        DROP FUNCTION IF EXISTS invoiceguard_internal.guard_field_review_update();
        DROP FUNCTION IF EXISTS invoiceguard_internal.check_review_carryover();
        DROP FUNCTION IF EXISTS invoiceguard_internal.guard_return_item_update();
        DROP FUNCTION IF EXISTS invoiceguard_internal.forbid_modification();
        """
    )
