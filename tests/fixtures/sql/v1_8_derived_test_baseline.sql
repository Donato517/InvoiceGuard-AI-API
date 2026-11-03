-- TEST-ONLY FIXTURE. NOT the team's official schema, NOT a deployed baseline, NOT an Alembic baseline/stamp target.
-- Purpose: build throwaway PostgreSQL databases for tests/integration (see tests/fixtures/sql/README.md).
-- Source file : InvoiceGuard_AI_PostgreSQL_Schema_v1_8_PortableAuth_draft.sql (design draft v1.8, dated 2026-11-01, never executed in production)
-- Source SHA-256 (whole file): 426f0fe0a602dd03c3ef17f519367f95451240d1ff9f7c631a2f9dc4681b0ba9
-- Derived body SHA-256 (everything after the END marker line): a16414c6f6c7cf7768ed421ac03f3a8fc70c829595acdf588cb624fb5ed641ca
-- Changes from the source (the only ones): (1) removed the block "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;"
--   plus the following DO $vector_check$ ... $vector_check$; check; (2) the column rag_chunks.embedding changed from
--   extensions.vector(1536) to text because the test PostgreSQL image has no pgvector. Comments were left untouched.
-- Contains no seed data, credentials or personal data (DDL only).
-- ===== END TEST-ONLY HEADER; the lines below are the derived body =====
-- InvoiceGuard AI / 可搬移 PostgreSQL 建表設計草案 v1.8
-- v1.8 日期：2026-11-01，由 v1.7 增修（見下方「與 v1.7 的差異」）。
-- 已套用 v1.7 的資料庫請改執行 InvoiceGuard_AI_v1_7_to_v1_8_ALTER.sql；本檔供新建資料庫與完整審閱。
-- v1.7 日期：2026-10-31，由 v1.6 增修（見下方「與 v1.6 的差異」）。
-- 已套用 v1.6 的資料庫請改執行 InvoiceGuard_AI_v1_6_to_v1_7_ALTER.sql；本檔供新建資料庫與完整審閱。
-- v1.6 日期：2026-10-30，由 v1.5 增修（見下方「與 v1.5 的差異」）。
-- 已套用 v1.5 的資料庫請改執行 InvoiceGuard_AI_v1_5_to_v1_6_ALTER.sql；本檔供新建資料庫與完整審閱。
-- v1.5 日期：2026-10-29，由 v1.4 增修（見下方「與 v1.4 的差異」）。
-- 已套用 v1.4 的資料庫請改執行 InvoiceGuard_AI_v1_4_to_v1_5_ALTER.sql；
--   仍在 v1.3 的資料庫先執行 InvoiceGuard_AI_v1_3_to_v1_4_ALTER.sql 再執行上述檔案。本檔供新建資料庫與完整審閱。
-- v1.4 日期：2026-10-29，由 v1.3 增修（見下方「與 v1.3 的差異」）。
-- v1.3 日期：2026-10-23；2026-10-24 獨立靜態審查修訂（見檔尾「審查處理紀錄」R1–R7，
-- 權限註解補正 R8–R9）。
-- 此檔僅供審閱；尚未執行、尚未驗證實際建表，也未做任何功能測試。
-- 來源：InvoiceGuard_AI_Supabase_Schema_v1_2_FieldReview_draft.sql
-- 來源檔案原始位元組 SHA256：308d602d5813daebdba47c41cfa71be51985302a7bc3f232f5c6411434a2f35c
--
-- 範圍／物件數（靜態計數，未實際建立）：
--   新建 2 個私有 schema（invoiceguard_identity、invoiceguard_internal）；
--   extensions schema 與 pgvector 只在不存在時建立。
--   23 張應用資料表（身分／部門／權限 8＋發票／OCR／審核 7＋RAG 8）、6 個唯讀 View、
--   4 個 Trigger 函式、14 個 Trigger、19 個獨立 CREATE INDEX（不含 PK/UNIQUE 約束自帶索引）。
-- 本稿採 Email＋密碼，由專案自己的 Python 程式處理登入及重設密碼。
-- 帳密、個資、Session 與部門資料皆在 PostgreSQL，不依賴 Supabase Auth。
-- Vercel 僅為可替換的執行環境；使用者資料不得寫入其環境變數或日誌。
--
-- 與 v1.7 的差異（2026-11-01）：
-- 1. 檔案獨立於知識庫：新增 public.rag_knowledge_base_files（知識庫 × 檔案）。知識庫只是檔案的組合，勾選或取消不重新索引。
--    外鍵 ON DELETE RESTRICT：檔案仍被任何知識庫引用時不可刪除；刪除知識庫只刪關聯，檔案與索引保留。
-- 2. public.rag_knowledge_bases.file_count：由 Trigger 同交易維護，降到 0 時清除所有部門的 use_for_qa；重新加入檔案不恢復。
-- 3. 新增 public.rag_function_knowledge_bases（功能 × 知識庫），供 ADMIN 功能管理指派。
-- 4. public.rag_files 新增 source_type、effective_date、effective_date_status、source_note、content_sha256。
-- 5. public.rag_files.knowledge_base_id 改為過渡欄位（可為 NULL、ON DELETE SET NULL），新程式不再讀寫，下一版移除。
-- 6. 兩個 RAG View 只納入 file_count >= 1 的知識庫，欄位不變。
-- 7. 新增 2 張表、1 個 Trigger 函式、1 個 Trigger、3 個索引；身分／部門／發票各表、rag_chunks、rag_jobs 不變。
--
-- 與 v1.6 的差異（2026-10-31）：
-- 1. 一個部門可同時選用多個知識庫：移除唯一索引 ux_rag_department_access_qa，改為一般索引 ix_rag_department_access_qa；
--    既有資料不用移轉，獨立 CREATE INDEX 數量不變。
-- 2. 部門使用知識庫內全部文件，不再依文件逐一選用：檢索條件改為四項（知識庫 approved 且 is_active、部門 use_for_qa、
--    文件 is_approved、parse_status = 'ready'）。public.rag_file_department_usage 停用，保留表與既有資料，程式不再讀寫。
--
-- 與 v1.5 的差異（2026-10-30）：
-- 1. public.rag_chunks.embedding 固定為 extensions.vector(1536)，對應向量模型 gemini-embedding-2；
--    只動這一欄，其他物件逐字相同。不建 HNSW 索引：檢索先依部門與文件條件過濾，資料量小時精確比對即可。
--
-- 與 v1.4 的差異（2026-10-29）：
-- 1. 依原型 invoiceguard_final.html 的「知識庫管理」與「問答輔助」補齊 RAG 的審核與部門選用；
--    只動 C 節 RAG 區、兩個 RAG View、RLS／ACL 清單與 COMMENT，身分／部門／發票各表、函式、既有 Trigger 不變。
-- 2. public.rag_knowledge_bases 新增審核流程：approval_status pending（所有新知識庫固定預設，含資訊部自己
--    建立）／approved／rejected，以及 submitted_by、submitted_department_id、reviewed_by、reviewed_at、
--    review_comment；rejected 可重新送審回 pending（程式同交易更新 submitted_*、清空 reviewed_*）。
--    is_active 保留為另一個開關（停用已核准者），View 以 approved AND is_active 判斷可用。
--    knowledge_name 依原型 NFKC → lower → JavaScript trim 空白集合後唯一（ux_rag_knowledge_bases_name）；knowledge_code 由程式產生。
-- 3. public.rag_department_access 新增 use_for_qa（該部門選用此知識庫問答）與 updated_at（Trigger）；
--    部分唯一索引 ux_rag_department_access_qa 保證一個部門同時只選用一個知識庫；use_for_qa 需 can_read。
--    退回知識庫時由程式在同一交易清除所有部門的 use_for_qa；列存在＝已指派，can_manage＝該部門可編輯。
-- 4. public.rag_files 新增 title（顯示名稱、非空白）、is_approved（新上傳固定 false）、approved_by、approved_at、
--    owner_department_id（上傳部門）、size_bytes。內容替換或改文字時由程式在同一交易：file_version +1、
--    is_approved 重設 false、清空 approved_by／approved_at、parse_status 重設 uploaded、新增 rag_jobs（reindex）。
--    新版本索引完成前不得沿用舊 ready；worker 寫入 chunks／ready 前須核對 file_version，與核准仍互相獨立。
-- 5. 新增 public.rag_file_department_usage：文件 × 部門選用（use_document）。新文件由程式替上傳部門建立一列
--    true，其他部門無列或 false 即不選用。檢索條件（程式）：知識庫 approved 且 is_active、部門 use_for_qa、
--    文件於該部門 use_document、文件 is_approved、parse_status = 'ready'，五項皆成立才納入。
-- 6. v_user_effective_rag_access、v_user_department_rag_access 多加 approval_status = 'approved' 條件，
--    並在末尾新增 use_for_qa 欄位（既有欄位與順序不變，CREATE OR REPLACE 可直接套用）。
-- 7. 新表比照既有：ENABLE RLS、REVOKE FROM PUBLIC、列入 ACL 清理清單；rag_department_access 與
--    rag_file_department_usage 掛 updated_at Trigger。原型的 companyId 不對應任何表：一個公司一個資料庫。
-- 8. 問答為即時對話（如同搜尋引擎的 AI 對話，重新整理即清空；使用者核定）：不保存問題、回答或對話歷史，
--    故不建問答紀錄表；對話歷史由前端隨請求送出、後端視為不可信；剩餘 Token 如需顯示由程式自行取得，不入 DB。
--
-- 與 v1.3 的差異（2026-10-29）：
-- 1. public.invoices 新增 tax_type 課稅別：taxable（應稅）／zero_rated（零稅率）／tax_exempt（免稅），
--    一張發票只有一種（應稅、零稅率、免稅之銷售額應分別開立統一發票）；草稿可為 NULL，
--    稅額與課稅別的一致性由程式檢核並寫入 validation_results，不另加 DB CHECK。
-- 2. 請款單簽核狀態（9 種）取代 v1.2／v1.3 的 6 種發票狀態，invoices.status 與
--    invoice_status_history.new_status 使用相同清單；CHECK 改為具名約束：
--    draft 待申請中（請款單位－經辦人）、pending_department_approval 待單位核准（請款單位－核准人）、
--    pending_accounting_review 待會計覆核（會計部－經辦人）、pending_accounting_approval 待會計核准
--    （會計部－核准人）、approved 已核准、returned_to_applicant 退回申請單位補正、
--    returned_to_accounting 退回會計補正、rejected 已駁回、voided 已作廢。
--    舊值對應：submitted → pending_department_approval、reviewing → pending_accounting_review、
--    returned → returned_to_applicant。
-- 3. v_invoice_return_fields 改以 returned_to_applicant 判斷退回採購補正（欄位不變）。
-- 4. public.ai_recognition_logs 新增 source_deleted_at：辨識後未上傳的影像保留 1 小時，
--    刪除 Storage 物件後記錄時間；新增部分索引 ix_ai_recognition_logs_source_cleanup。
-- 5. Storage 路徑（程式約定，不是 DB 約束）：invoices bucket 內 {user_id}/INVOICES_{YYYYMMDDHHMMSS 台灣時間}_{recognition_id}.{副檔名}。
--    其他領域（例如 RAG）各自記錄 bucket_name，不共用 invoices bucket。
--
-- 與 v1.2 的差異：
-- 1. 新增 invoiceguard_identity.user_accounts：自管帳號及 Argon2id PHC 雜湊（僅結構 CHECK）。
-- 2. public.user_profiles.user_id 改參照自管帳號，移除供應商 Auth 外鍵；
--    另加 display_name／employee_code 非空白、resigned_at 必須 is_active=false 的 CHECK。
-- 3. 新增 password_reset_tokens、user_sessions，僅保存高熵 Token 的 SHA256 摘要。
-- 4. 保留 user_departments 多對多；主要部門改由帳號單一指標決定。
--    移除可獨立寫入的 is_primary 及 ux_user_departments_one_primary，改由 v_user_departments 推導。
--    user_departments 新增生成欄位 is_current 及 (user_id, department_id, is_current) UNIQUE；
--    departments 新增 (department_id, is_active) UNIQUE，兩者只供複合外鍵參照。
--    啟用帳號必有一個主要部門；延遲複合外鍵於 COMMIT 時保證為本人現行成員關係且部門啟用。
-- 5. 保留原有跨部門 OR/UNION 權限 View（兩者只各加 user_accounts active 條件）；
--    新增按部門的功能／RAG 權限 View。部門模式採目前選取部門的授權，不以跨部門聯集擴權；
--    此為比 v1.2 更嚴格的用法，須業務核定。
-- 6. 發票及 RAG 的 12 張資料表欄位、型別、預設值、約束、索引與 v1.2 逐字相同；
--    只有 invoice_files、rag_files 兩行註解將 Supabase Storage 改稱私有物件儲存。
--    另對其中有 updated_at 的 5 張表加時間 Trigger（不改欄位）。
--    Storage 只存 bucket/key 等中繼資料，不綁定檔案服務供應商。
-- 7. 移除 v1.2 對 anon/authenticated/service_role 的 REVOKE/GRANT 及供應商角色依賴；
--    此稿不建立 LOGIN role、不包含密碼或管理員種子。
--    RLS 保持 fail closed；正式 runtime role 的最小權限／Policy 另行核定。
-- 8. 補上 updated_at Trigger；密碼變更時遞增憑證版本，並由 SECURITY DEFINER Trigger
--    撤銷 Session／未用重設 Token；若撤銷會被 RLS 過濾則報錯 rollback，不假成功。
--
-- 使用界線：
-- * 僅供「沒有這批同名物件」的獨立測試資料庫新建，並非既有資料庫 migration。
-- * PostgreSQL 15+（UNIQUE NULLS NOT DISTINCT、security_invoker View）。
--   PG18 起生成欄位預設為 VIRTUAL；本稿生成欄位須保留 STORED 才能建 UNIQUE／外鍵。
-- * pgvector 是可搬移擴充，不是 Auth 服務；主機須已安裝其套件檔。
--   本 DDL 的 rag_chunks.embedding 固定為 extensions.vector(1536)，不建向量索引。
--   若執行者無權建立該擴充，須由 DBA 預先建立在 extensions schema；本稿不自動搬移或升級。
--   日後 HNSW 索引需 pgvector 0.5.0+ 並固定維度（vector 型別索引上限 2,000 維，依 pgvector 文件）。
--   runtime role 若要使用向量運算子，須另授 extensions schema USAGE。
-- * 不自動搬資料、不刪既有物件、不回填帳號、不建立 Storage bucket。
-- * 所有帳號／員工／權限資料由受控後端處理；不將私有身分 schema 暴露給 Data API。
-- * SQL 不會實作登入網頁、寄信、SMTP、忘記密碼回呼、限流或 HTTP 授權。
-- * 備份須涵蓋 public、invoiceguard_identity、invoiceguard_internal、擴充需求；
--   Storage 實體檔案及部署秘密需另外安全搬移。不可只備份 public schema。
--
-- 官方設計依據：
-- https://www.postgresql.org/docs/15/sql-createtable.html
-- https://www.postgresql.org/docs/15/ddl-generated-columns.html
-- https://www.postgresql.org/docs/15/ddl-rowsecurity.html
-- https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
-- https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html
-- 審查修訂另參考：
-- https://www.postgresql.org/docs/15/sql-createfunction.html（Writing SECURITY DEFINER Functions Safely）
-- https://www.postgresql.org/docs/15/functions-info.html（row_security_active）
-- https://www.postgresql.org/docs/15/runtime-config-client.html（search_path、pg_temp）
-- https://www.postgresql.org/docs/15/sql-createtrigger.html（Trigger 權限與觸發順序）
-- https://www.postgresql.org/docs/18/ddl-generated-columns.html（PG18 VIRTUAL 預設）
-- https://www.rfc-editor.org/rfc/rfc9106.html（Argon2；salt／tag 長度建議）

BEGIN;

-- [R5] 建立期間固定名稱解析：pg_catalog 優先、暫存 schema 最後；
-- SET LOCAL 只在本交易有效，不改資料庫／角色／伺服器設定。
SET LOCAL search_path = pg_catalog, pg_temp;

DO $preflight$
BEGIN
    IF pg_catalog.current_setting('server_version_num')::integer < 150000 THEN
        RAISE EXCEPTION 'InvoiceGuard v1.3 requires PostgreSQL 15 or later';
    END IF;
END;
$preflight$;

-- 私有 schema 以普通 CREATE 建立；若已存在就停止，不覆蓋舊物件。
CREATE SCHEMA invoiceguard_identity;
CREATE SCHEMA invoiceguard_internal;
REVOKE ALL ON SCHEMA invoiceguard_identity, invoiceguard_internal FROM PUBLIC;

CREATE SCHEMA IF NOT EXISTS extensions;


-- ==================== A. 自管身分與員工資料 ====================

-- 登入帳號使用 Email；大小寫不區分，輸入先 strip/lower，再查詢此唯一值。
-- employee_code 為業務識別，不自動當作另一套登入名稱。
-- password_hash 必須由應用使用 Argon2id 產生完整 PHC 字串（含 salt/參數）。
-- [R2] 結構 CHECK 只能擋下明文、'$argon2id$明文' 或截斷字串等明顯誤填；
-- 它無法證明字串真由 Argon2id 計算，也不檢查 m/t/p 是否達 OWASP 最低值，
-- 不能取代密碼雜湊程式、參數設定或強度驗證。
-- pending 可尚未分配部門；active 只在資料／部門完整後設定。
CREATE TABLE invoiceguard_identity.user_accounts (
    user_id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email                      text NOT NULL,
    password_hash              text NOT NULL,
    account_status             text NOT NULL DEFAULT 'pending'
                               CHECK (account_status IN ('pending', 'active', 'disabled')),
    email_verified_at          timestamptz,
    credential_version         bigint NOT NULL DEFAULT 1 CHECK (credential_version > 0),
    password_changed_at        timestamptz NOT NULL DEFAULT now(),
    failed_login_count         integer NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    locked_until               timestamptz,
    last_login_at              timestamptz,
    primary_department_id      uuid,
    primary_department_active  boolean GENERATED ALWAYS AS (true) STORED,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT user_accounts_email_normalized
        CHECK (email = pg_catalog.lower(pg_catalog.btrim(email)) AND email <> ''),
    CONSTRAINT user_accounts_email_basic_shape
        CHECK (email LIKE '%_@_%'),
    -- PHC：$argon2id$v=19$m=<n>,t=<n>,p=<n>$<salt>$<hash>；B64 無補位，
    -- salt 與 hash 各至少 22 字元（約 16 bytes）。以 [$] 表示字面 $，不依賴反斜線設定。
    CONSTRAINT user_accounts_password_hash_format
        CHECK (password_hash ~ '^[$]argon2id[$]v=19[$]m=[1-9][0-9]*,t=[1-9][0-9]*,p=[1-9][0-9]*[$][A-Za-z0-9+/]{22,}[$][A-Za-z0-9+/]{22,}$'),
    CONSTRAINT user_accounts_active_requires_primary
        CHECK (account_status <> 'active' OR primary_department_id IS NOT NULL)
);
CREATE UNIQUE INDEX ux_user_accounts_email
    ON invoiceguard_identity.user_accounts (email);

-- 不因新增帳號而自動核准、分配部門或授權；後端以同一交易完成帳號/profile/部門。
CREATE TABLE public.user_profiles (
    user_id         uuid PRIMARY KEY
                    REFERENCES invoiceguard_identity.user_accounts(user_id) ON DELETE CASCADE,
    employee_code   text UNIQUE,
    display_name    text NOT NULL CHECK (pg_catalog.btrim(display_name) <> ''),
    phone           text,
    is_active       boolean NOT NULL DEFAULT true,
    resigned_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT user_profiles_employee_code_nonblank
        CHECK (employee_code IS NULL OR pg_catalog.btrim(employee_code) <> ''),
    CONSTRAINT user_profiles_resigned_inactive
        CHECK (resigned_at IS NULL OR is_active = false)
);

CREATE TABLE public.departments (
    department_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    department_code text NOT NULL UNIQUE,
    department_name text NOT NULL,
    is_active       boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT departments_id_active_unique UNIQUE (department_id, is_active)
);

-- 一個人可屬於多個部門，一個部門可有多人。
-- 延續 v1.2：unassigned_at IS NULL 表示現行關係；不是未來排程生效機制。
-- 同一 user/department 保留一列；重新加入須明確更新 assigned_at/unassigned_at。
-- 若需完整多次任職歷史，另行核定歷史表；此稿不擴張該業務設計。
CREATE TABLE public.user_departments (
    user_id        uuid NOT NULL REFERENCES public.user_profiles(user_id) ON DELETE CASCADE,
    department_id  uuid NOT NULL REFERENCES public.departments(department_id) ON DELETE RESTRICT,
    assigned_at    timestamptz NOT NULL DEFAULT now(),
    unassigned_at  timestamptz,
    is_current     boolean GENERATED ALWAYS AS (unassigned_at IS NULL) STORED,
    PRIMARY KEY (user_id, department_id),
    CONSTRAINT user_department_dates_chk
        CHECK (unassigned_at IS NULL OR unassigned_at >= assigned_at),
    CONSTRAINT user_departments_current_reference_unique
        UNIQUE (user_id, department_id, is_current)
);
CREATE INDEX ix_user_departments_active_department
    ON public.user_departments (department_id, user_id)
    WHERE unassigned_at IS NULL;

-- 單一主要部門指標，不額外保存可寫的 is_primary。
-- true 生成欄位使外鍵只能指向 is_current=true、is_active=true。
-- MATCH SIMPLE 允許 pending/disabled 帳號暫無主要部門；
-- active_requires_primary CHECK 則禁止 active 帳號缺少主要部門。
-- NO ACTION＋延遲檢查允許同一交易中調整關係及主要部門，提交時必須完整。
-- （RESTRICT 不能延遲；CASCADE/SET NULL 會自動改寫主要部門，且 PostgreSQL 對含生成欄位的
--   外鍵限制這類動作，此點官方文件未明列，須實測確認。）
-- 交易內的中間狀態只有本交易看得到；COMMIT 才檢查。active CHECK 則是逐句立即檢查。
-- 表 owner／superuser 可停用 Trigger 或用 session_replication_role=replica 略過外鍵檢查，
-- 故 runtime／還原流程不得使用這類身分或設定（見檔尾 R 紀錄之待實測項目）。
ALTER TABLE invoiceguard_identity.user_accounts
    ADD CONSTRAINT user_accounts_primary_membership_fk
        FOREIGN KEY (user_id, primary_department_id, primary_department_active)
        REFERENCES public.user_departments(user_id, department_id, is_current)
        MATCH SIMPLE ON UPDATE NO ACTION ON DELETE NO ACTION
        DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT user_accounts_primary_department_enabled_fk
        FOREIGN KEY (primary_department_id, primary_department_active)
        REFERENCES public.departments(department_id, is_active)
        MATCH SIMPLE ON UPDATE NO ACTION ON DELETE NO ACTION
        DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE public.app_functions (
    function_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    function_code  text NOT NULL UNIQUE,
    function_name  text NOT NULL,
    app_scope      text NOT NULL DEFAULT 'admin'
                   CHECK (app_scope IN ('frontend','admin','both')),
    is_active      boolean NOT NULL DEFAULT true
);

CREATE TABLE public.department_permissions (
    department_id  uuid NOT NULL REFERENCES public.departments(department_id) ON DELETE CASCADE,
    function_id    uuid NOT NULL REFERENCES public.app_functions(function_id) ON DELETE CASCADE,
    can_view       boolean NOT NULL DEFAULT false,
    can_create     boolean NOT NULL DEFAULT false,
    can_edit       boolean NOT NULL DEFAULT false,
    can_delete     boolean NOT NULL DEFAULT false,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (department_id, function_id)
);

-- Session 採可攜的 opaque Token 模式，DB 只存摘要，不需依賴平台 JWT 金鑰。
-- 原始 Token 由應用以 CSPRNG 產生至少 32 bytes；僅透過安全 Cookie／Bearer 傳遞。
-- 發行版本每次須與帳號 credential_version 比對，不能只看 expires_at 或 revoked_at：
-- 建立 Session 與改密碼並行時，新 Session 可能帶舊版本且未被 Trigger 標記撤銷。
-- selected_department_id 只是本次操作情境，不會改寫主要部門或額外授權；
-- SQL 不保證它仍是本人現行、啟用部門，每次請求須以部門 View 重新核對。
-- 故意不對 credential_version 設外鍵：改密碼後舊版本必須能保留並被拒絕。
CREATE TABLE invoiceguard_identity.user_sessions (
    session_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 uuid NOT NULL
                            REFERENCES invoiceguard_identity.user_accounts(user_id) ON DELETE CASCADE,
    session_token_digest    bytea NOT NULL UNIQUE
                            CHECK (pg_catalog.octet_length(session_token_digest) = 32),
    credential_version      bigint NOT NULL CHECK (credential_version > 0),
    selected_department_id  uuid REFERENCES public.departments(department_id) ON DELETE SET NULL,
    created_at              timestamptz NOT NULL DEFAULT now(),
    expires_at              timestamptz NOT NULL,
    last_seen_at            timestamptz,
    revoked_at              timestamptz,
    CONSTRAINT user_sessions_expiry_chk CHECK (expires_at > created_at),
    CONSTRAINT user_sessions_last_seen_chk
        CHECK (last_seen_at IS NULL OR last_seen_at >= created_at),
    CONSTRAINT user_sessions_revoked_chk
        CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
CREATE INDEX ix_user_sessions_user_active
    ON invoiceguard_identity.user_sessions (user_id, expires_at)
    WHERE revoked_at IS NULL;

-- 忘記密碼：DB 不存原始 Token，也不存可還原密碼。
-- SHA256 只用於高熵隨機 Token，不用於使用者密碼。
-- 建立時記錄 credential_version；消耗時一併核對，避免舊連結恢復效力。
CREATE TABLE invoiceguard_identity.password_reset_tokens (
    reset_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             uuid NOT NULL
                        REFERENCES invoiceguard_identity.user_accounts(user_id) ON DELETE CASCADE,
    token_digest        bytea NOT NULL UNIQUE
                        CHECK (pg_catalog.octet_length(token_digest) = 32),
    credential_version  bigint NOT NULL CHECK (credential_version > 0),
    created_at          timestamptz NOT NULL DEFAULT now(),
    expires_at          timestamptz NOT NULL,
    used_at             timestamptz,
    revoked_at          timestamptz,
    CONSTRAINT password_reset_expiry_chk CHECK (expires_at > created_at),
    CONSTRAINT password_reset_used_chk CHECK (used_at IS NULL OR used_at >= created_at),
    CONSTRAINT password_reset_revoked_chk CHECK (revoked_at IS NULL OR revoked_at >= created_at),
    CONSTRAINT password_reset_terminal_state_chk
        CHECK (used_at IS NULL OR revoked_at IS NULL)
);
CREATE INDEX ix_password_reset_tokens_user_pending
    ON invoiceguard_identity.password_reset_tokens (user_id, expires_at)
    WHERE used_at IS NULL AND revoked_at IS NULL;

-- ==================== B. Invoices / OCR / workflow / field review (7) ====================
-- 06. One invoice header; all OCR fields nullable during initial/draft review.
CREATE TABLE public.invoices (
    invoice_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_track       text,                    -- 字軌, e.g. AB
    invoice_number      text,                    -- 8-digit handwritten invoice number
    invoice_date        date,
    tax_period          text,                    -- e.g. YYYYMM; validation is application logic
    seller_tax_id       text,
    seller_name         text,
    buyer_tax_id        text,
    buyer_name          text,
    sales_amount        numeric(18,2),
    tax_amount          numeric(18,2),
    total_amount        numeric(18,2),
    total_amount_zh     text,                    -- 國字大寫
    invoice_kind        text NOT NULL DEFAULT 'triplicate_handwritten'
                        CHECK (invoice_kind = 'triplicate_handwritten'),
    submission_round    integer NOT NULL DEFAULT 0 CHECK (submission_round >= 0),
    -- v1.4：請款單簽核狀態（9 種），見檔頭「與 v1.3 的差異」
    status              text NOT NULL DEFAULT 'draft'
                        CONSTRAINT invoices_status_chk CHECK (status IN
                          ('draft','pending_department_approval','pending_accounting_review',
                           'pending_accounting_approval','approved','returned_to_applicant',
                           'returned_to_accounting','rejected','voided')),
    validation_results  jsonb NOT NULL DEFAULT '{}'::jsonb,
    submitted_by        uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    department_id       uuid REFERENCES public.departments(department_id) ON DELETE SET NULL,
    submitted_at        timestamptz,
    reviewed_by         uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    reviewed_at         timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    -- v1.4：課稅別；一張發票只有一種，草稿可為 NULL
    tax_type            text CONSTRAINT invoices_tax_type_chk
                        CHECK (tax_type IN ('taxable','zero_rated','tax_exempt'))
);
-- Non-unique: allow duplicate uploaded invoice data to be flagged/reviewed.
CREATE INDEX ix_invoices_number_supplier
    ON public.invoices (invoice_track, invoice_number, seller_tax_id);
CREATE INDEX ix_invoices_department_status
    ON public.invoices (department_id, status, created_at DESC);

-- 07. Line items; nullable OCR values are intentionally allowed.
CREATE TABLE public.invoice_items (
    item_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id       uuid NOT NULL REFERENCES public.invoices(invoice_id) ON DELETE CASCADE,
    line_no          integer NOT NULL CHECK (line_no > 0),
    item_name        text,
    quantity         numeric(18,4),
    unit_price       numeric(18,4),
    line_amount      numeric(18,2),
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (invoice_id, line_no),
    UNIQUE (invoice_id, item_id) -- allows invoice+item consistency foreign keys
);

-- 08. Private object storage metadata / replacement versions, not file contents.
CREATE TABLE public.invoice_files (
    file_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id         uuid NOT NULL REFERENCES public.invoices(invoice_id) ON DELETE CASCADE,
    bucket_name        text NOT NULL DEFAULT 'invoices' CHECK (bucket_name = 'invoices'),
    storage_path       text NOT NULL,
    original_filename  text,
    mime_type          text CHECK (mime_type IN ('image/jpeg','image/png','application/pdf')),
    size_bytes         bigint CHECK (size_bytes IS NULL OR size_bytes > 0),
    version_no         integer NOT NULL DEFAULT 1 CHECK (version_no > 0),
    is_current         boolean NOT NULL DEFAULT true,
    uploaded_by        uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    uploaded_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (bucket_name, storage_path),
    UNIQUE (invoice_id, version_no)
);
-- Assumes one active image/PDF per invoice; adapt if multiple pages are allowed.
CREATE UNIQUE INDEX ux_invoice_files_current
    ON public.invoice_files(invoice_id) WHERE is_current = true;

-- 09. Immutable-intent audit history: every field change, including all interim edits.
-- Keep this separate from the single checkbox per affected field/per submission round.
CREATE TABLE public.invoice_changes (
    change_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id       uuid NOT NULL REFERENCES public.invoices(invoice_id) ON DELETE RESTRICT,
    item_id          uuid, -- NULL: invoice header; non-NULL: invoice line-item
    submission_round integer NOT NULL DEFAULT 0 CHECK (submission_round >= 0),
    field_name       text NOT NULL,
    old_value        jsonb,
    new_value        jsonb,
    change_source    text NOT NULL DEFAULT 'user'
                     CHECK (change_source IN ('user','ai','system')),
    changed_by       uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    changed_at       timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (invoice_id, item_id)
      REFERENCES public.invoice_items(invoice_id, item_id) ON DELETE RESTRICT
);
CREATE INDEX ix_invoice_changes_invoice_time
    ON public.invoice_changes(invoice_id, changed_at DESC);

-- 10. Status transitions, including returns and approvals.
CREATE TABLE public.invoice_status_history (
    history_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id      uuid NOT NULL REFERENCES public.invoices(invoice_id) ON DELETE CASCADE,
    old_status      text,
    new_status      text NOT NULL
                    CONSTRAINT invoice_status_history_new_status_chk CHECK (new_status IN
                          ('draft','pending_department_approval','pending_accounting_review',
                           'pending_accounting_approval','approved','returned_to_applicant',
                           'returned_to_accounting','rejected','voided')),
    reason          text,
    changed_by      uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    changed_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_invoice_status_history_invoice_time
    ON public.invoice_status_history(invoice_id, changed_at DESC);

-- 11. Recognition/classification attempts. For rejected non-invoice uploads,
--     invoice_id may be NULL and source_storage_path identifies the attempt.
CREATE TABLE public.ai_recognition_logs (
    recognition_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id           uuid REFERENCES public.invoices(invoice_id) ON DELETE SET NULL,
    invoice_file_id      uuid REFERENCES public.invoice_files(file_id) ON DELETE SET NULL,
    source_storage_path  text,
    ai_provider          text NOT NULL,
    model_name           text,
    is_triplicate        boolean,
    confidence_score     numeric(5,4) CHECK
                         (confidence_score IS NULL OR confidence_score BETWEEN 0 AND 1),
    extracted_fields     jsonb,
    raw_response         jsonb,
    result_status        text NOT NULL DEFAULT 'pending'
                         CHECK (result_status IN ('pending','success','partial','failed')),
    error_message        text,
    requested_by         uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    completed_at         timestamptz,
    -- v1.4：未上傳影像（保留 1 小時）自 Storage 刪除的時間
    source_deleted_at    timestamptz,
    CONSTRAINT ai_recognition_logs_source_deleted_chk
        CHECK (source_deleted_at IS NULL OR source_deleted_at >= created_at),
    CHECK (invoice_id IS NOT NULL OR invoice_file_id IS NOT NULL
           OR source_storage_path IS NOT NULL)
);
CREATE INDEX ix_ai_recognition_logs_invoice_time
    ON public.ai_recognition_logs(invoice_id, created_at DESC);
-- v1.4：清理尚未連到正式檔案、超過保留時間的暫存影像
CREATE INDEX ix_ai_recognition_logs_source_cleanup
    ON public.ai_recognition_logs (created_at)
    WHERE invoice_file_id IS NULL
      AND source_storage_path IS NOT NULL
      AND source_deleted_at IS NULL;

-- 17. One finance checkbox per manually modified field PER SUBMISSION ROUND.
-- Snapshot AI value vs final submitted value; leave interim edits in invoice_changes.
-- A FALSE checkbox means "not accepted" (possibly still waiting for review).
-- Only present FALSE as RED on the procurement RETURN screen after status='returned_to_applicant'.
-- Note: PostgreSQL 15+ UNIQUE NULLS NOT DISTINCT handles header rows (item_id IS NULL).
CREATE TABLE public.invoice_field_reviews (
    field_review_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id           uuid NOT NULL REFERENCES public.invoices(invoice_id) ON DELETE RESTRICT,
    submission_round     integer NOT NULL CHECK (submission_round > 0),
    field_scope          text NOT NULL CHECK (field_scope IN ('header','item')),
    item_id              uuid,
    field_name           text NOT NULL,
    recognition_id       uuid REFERENCES public.ai_recognition_logs(recognition_id) ON DELETE RESTRICT,
    ai_original_value    jsonb,
    submitted_value      jsonb,
    is_checked           boolean NOT NULL DEFAULT false,
    checked_by           uuid REFERENCES public.user_profiles(user_id) ON DELETE RESTRICT,
    checked_at           timestamptz,
    review_comment       text,  -- reason/expected correction for unchecked field
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT invoice_field_reviews_scope_chk CHECK (
        (field_scope = 'header' AND item_id IS NULL)
        OR (field_scope = 'item' AND item_id IS NOT NULL)
    ),
    CONSTRAINT invoice_field_reviews_check_actor_chk CHECK (
        (is_checked = true AND checked_by IS NOT NULL AND checked_at IS NOT NULL)
        OR (is_checked = false AND checked_by IS NULL AND checked_at IS NULL)
    ),
    CONSTRAINT invoice_field_reviews_unique_field_per_round
       UNIQUE NULLS NOT DISTINCT
       (invoice_id, submission_round, field_scope, item_id, field_name),
    FOREIGN KEY (invoice_id, item_id)
       REFERENCES public.invoice_items(invoice_id, item_id) ON DELETE RESTRICT
);
CREATE INDEX ix_invoice_field_reviews_invoice_round
    ON public.invoice_field_reviews(invoice_id, submission_round, is_checked);

-- Backend invariant (needs API transaction/trigger, not implemented by this DDL):
-- * On each submission, increment invoices.submission_round and create field review
--   rows for net differences between the ORIGINAL AI recognition and user-confirmed data.
-- * Do not create a second review row for multiple intermediate edits of one field.
-- * Finance may check approved fields; permission + reviewer identity must be validated.
-- * On whole-invoice RETURN (returned_to_applicant), only unchecked current-round review rows are red.
-- * On resubmission, create a fresh round and decide whether unchanged approvals
--   carry forward (with explicit audit linkage); never auto-approve edited values.
-- * To avoid self-approval under UNION permissions, enforce separation of duties
--   in the API if business rules require reviewer != submitter.

-- ==================== C. RAG Knowledge Base (8) ====================
-- 名稱正規化使用 PostgreSQL 內建 normalize(text,text)，僅支援 UTF8；25 個 trim 字元依原型 JavaScript。
DO $rag_utf8_preflight$
BEGIN
    IF pg_catalog.current_setting('server_encoding') <> 'UTF8' THEN
        RAISE EXCEPTION 'v1.5 RAG 名稱正規化需要 UTF8 資料庫，交易將全部回復';
    END IF;
END;
$rag_utf8_preflight$;

-- 12. Knowledge base. RAG is optional in phase one.
--     v1.5：資訊部審核流程。所有新知識庫固定 pending（含資訊部建立）；approved 才可供部門選用與問答；
--     rejected 可重新送審回 pending。is_active 是另一個開關（停用已核准者），View 以兩者 AND 判斷可用。
CREATE TABLE public.rag_knowledge_bases (
    knowledge_base_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_code    text NOT NULL UNIQUE,
    knowledge_name    text NOT NULL,
    description       text,
    is_active         boolean NOT NULL DEFAULT true,
    created_by        uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    -- v1.5：審核流程，見檔頭「與 v1.4 的差異」；重新送審時程式更新 submitted_*、清空 reviewed_*
    approval_status         text NOT NULL DEFAULT 'pending'
                            CONSTRAINT rag_knowledge_bases_approval_status_chk
                            CHECK (approval_status IN ('pending','approved','rejected')),
    submitted_by            uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    submitted_department_id uuid REFERENCES public.departments(department_id) ON DELETE SET NULL,
    reviewed_by             uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    reviewed_at             timestamptz,
    review_comment          text,
    -- v1.8：引用檔案數，由 Trigger 維護，程式與表單不可直接寫入
    file_count              integer NOT NULL DEFAULT 0
                            CONSTRAINT rag_knowledge_bases_file_count_chk CHECK (file_count >= 0),
    CONSTRAINT rag_knowledge_bases_review_chk
        CHECK (approval_status = 'pending' OR reviewed_at IS NOT NULL)
);
-- v1.5：原型 norm() 的 NFKC／小寫／25 個 JavaScript trim 空白；內建函式為 IMMUTABLE，可用運算式索引。
-- lower 依資料庫 locale，特殊 Unicode 大小寫仍須以部署環境實測；knowledge_code 由程式產生。
CREATE UNIQUE INDEX ux_rag_knowledge_bases_name
    ON public.rag_knowledge_bases (pg_catalog.btrim(pg_catalog.lower(pg_catalog.normalize(knowledge_name, 'NFKC')), E'\u0009\u000A\u000B\u000C\u000D\u0020\u00A0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200A\u2028\u2029\u202F\u205F\u3000\uFEFF'));

-- 13. Which departments may access/manage each knowledge base.
--     v1.5：列存在＝已指派該部門（可見）；can_manage＝該部門可否編輯；use_for_qa＝該部門選用此知識庫問答，
--     v1.7 起一個部門可同時選用多個；退回知識庫時由程式在同一交易清除所有部門的 use_for_qa。
CREATE TABLE public.rag_department_access (
    knowledge_base_id uuid NOT NULL REFERENCES public.rag_knowledge_bases(knowledge_base_id) ON DELETE CASCADE,
    department_id     uuid NOT NULL REFERENCES public.departments(department_id) ON DELETE CASCADE,
    can_read          boolean NOT NULL DEFAULT true,
    can_manage        boolean NOT NULL DEFAULT false,
    -- v1.5：該部門選用此知識庫問答；v1.7 起一個部門可同時選用多個
    use_for_qa        boolean NOT NULL DEFAULT false,
    updated_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (knowledge_base_id, department_id),
    CONSTRAINT rag_department_access_qa_requires_read_chk
        CHECK (use_for_qa = false OR can_read = true)
);
CREATE INDEX ix_rag_department_access_qa
    ON public.rag_department_access (department_id)
    WHERE use_for_qa = true;

-- 14. RAG source files in private object storage (create a separate PRIVATE bucket later).
--     v1.5：title 顯示名稱（可改名）；is_approved 資訊部核准（新上傳固定 false）；owner_department_id 上傳部門。
--     內容替換或改文字時，程式同交易：file_version +1、is_approved=false、清空 approved_*、parse_status=uploaded，新增 reindex。
--     parse_status 是索引進度（uploaded≈排隊中），與核准互相獨立。
CREATE TABLE public.rag_files (
    rag_file_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- v1.8：過渡欄位，新程式改用 rag_knowledge_base_files，下一版移除
    knowledge_base_id uuid CONSTRAINT rag_files_knowledge_base_id_fkey
                      REFERENCES public.rag_knowledge_bases(knowledge_base_id) ON DELETE SET NULL,
    bucket_name       text NOT NULL,
    storage_path      text NOT NULL,
    original_filename text NOT NULL,
    mime_type         text,
    file_version      integer NOT NULL DEFAULT 1 CHECK (file_version > 0),
    parse_status      text NOT NULL DEFAULT 'uploaded'
                      CHECK (parse_status IN ('uploaded','processing','ready','failed')),
    uploaded_by       uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    -- v1.5：顯示名稱、資訊部核准、上傳部門、檔案大小，見檔頭「與 v1.4 的差異」
    title               text NOT NULL
                        CONSTRAINT rag_files_title_nonblank CHECK (pg_catalog.btrim(title, E'\u0009\u000A\u000B\u000C\u000D\u0020\u00A0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200A\u2028\u2029\u202F\u205F\u3000\uFEFF') <> ''),
    is_approved         boolean NOT NULL DEFAULT false,
    approved_by         uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    approved_at         timestamptz,
    owner_department_id uuid REFERENCES public.departments(department_id) ON DELETE SET NULL,
    size_bytes          bigint CONSTRAINT rag_files_size_bytes_chk
                        CHECK (size_bytes IS NULL OR size_bytes > 0),
    -- v1.8：來源資訊。unclassified 只供 v1.8 之前的既有檔案，新上傳由程式要求選擇；來源類型只作分類，不代表效力或優先順序。
    source_type           text NOT NULL DEFAULT 'unclassified'
                          CONSTRAINT rag_files_source_type_chk
                          CHECK (source_type IN ('government_regulation','company_policy','operations_manual','mixed','other','unclassified')),
    effective_date        date,
    effective_date_status text NOT NULL DEFAULT 'unknown',
    source_note           text,
    content_sha256        text
                          CONSTRAINT rag_files_content_sha256_chk
                          CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'),
    UNIQUE (bucket_name, storage_path),
    CONSTRAINT rag_files_effective_date_chk
        CHECK ((effective_date_status IN ('unknown','not_applicable') AND effective_date IS NULL)
               OR (effective_date_status = 'known' AND effective_date IS NOT NULL)),
    CONSTRAINT rag_files_approval_chk
        CHECK ((is_approved = false AND approved_at IS NULL AND approved_by IS NULL)
               OR (is_approved = true AND approved_at IS NOT NULL))
);
CREATE INDEX ix_rag_files_kb ON public.rag_files(knowledge_base_id);
CREATE INDEX ix_rag_files_content_sha256
    ON public.rag_files (content_sha256)
    WHERE content_sha256 IS NOT NULL;

-- 18. v1.7 停用：部門使用知識庫內全部文件，程式不再讀寫本表；保留表與既有資料，日後另行移除。
--     v1.5 原用途：文件 × 部門選用。
CREATE TABLE public.rag_file_department_usage (
    rag_file_id    uuid NOT NULL REFERENCES public.rag_files(rag_file_id) ON DELETE CASCADE,
    department_id  uuid NOT NULL REFERENCES public.departments(department_id) ON DELETE CASCADE,
    use_document   boolean NOT NULL DEFAULT true,
    updated_by     uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (rag_file_id, department_id)
);

-- 19. v1.8：知識庫 × 檔案。段落與向量掛在檔案上，關聯異動不重新索引；檔案被引用時不可刪除。
CREATE TABLE public.rag_knowledge_base_files (
    knowledge_base_id uuid NOT NULL REFERENCES public.rag_knowledge_bases(knowledge_base_id) ON DELETE CASCADE,
    rag_file_id       uuid NOT NULL REFERENCES public.rag_files(rag_file_id) ON DELETE RESTRICT,
    added_by          uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    added_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (knowledge_base_id, rag_file_id)
);
CREATE INDEX ix_rag_knowledge_base_files_file
    ON public.rag_knowledge_base_files (rag_file_id);

-- 20. v1.8：功能 × 知識庫。功能聊天使用此清單與部門指派的交集。
CREATE TABLE public.rag_function_knowledge_bases (
    function_id       uuid NOT NULL REFERENCES public.app_functions(function_id) ON DELETE CASCADE,
    knowledge_base_id uuid NOT NULL REFERENCES public.rag_knowledge_bases(knowledge_base_id) ON DELETE CASCADE,
    assigned_by       uuid REFERENCES public.user_profiles(user_id) ON DELETE SET NULL,
    assigned_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (function_id, knowledge_base_id)
);
CREATE INDEX ix_rag_function_knowledge_bases_kb
    ON public.rag_function_knowledge_bases (knowledge_base_id);

-- 15. RAG text chunks and embedding vectors.
--     v1.6: fixed to gemini-embedding-2 (1536 dimensions). Changing model or dimension requires re-embedding all chunks.
CREATE TABLE public.rag_chunks (
    chunk_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rag_file_id     uuid NOT NULL REFERENCES public.rag_files(rag_file_id) ON DELETE CASCADE,
    chunk_index     integer NOT NULL CHECK (chunk_index >= 0),
    content         text NOT NULL,
    token_count     integer CHECK (token_count IS NULL OR token_count >= 0),
    embedding_model text,
    embedding       text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (rag_file_id, chunk_index)
);

-- 16. Queue/status metadata for extract -> chunk -> embed jobs.
CREATE TABLE public.rag_jobs (
    job_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rag_file_id    uuid NOT NULL REFERENCES public.rag_files(rag_file_id) ON DELETE CASCADE,
    job_type       text NOT NULL CHECK (job_type IN ('extract','chunk','embed','reindex')),
    job_status     text NOT NULL DEFAULT 'pending'
                   CHECK (job_status IN ('pending','running','succeeded','failed')),
    attempts       integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    error_message  text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    started_at     timestamptz,
    finished_at    timestamptz
);
CREATE INDEX ix_rag_jobs_status_created ON public.rag_jobs(job_status, created_at);


-- ==================== D. 共用時間與密碼生命週期 ====================

CREATE FUNCTION invoiceguard_internal.touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $touch_updated_at$
BEGIN
    NEW.updated_at := pg_catalog.statement_timestamp();
    RETURN NEW;
END;
$touch_updated_at$;

-- 每次修改密碼雜湊，至少遞增一版；禁止將 credential_version 往回調。
-- 此函式不驗證原密碼／重設連結，也不會自動啟用或解鎖帳號。
CREATE FUNCTION invoiceguard_internal.prepare_password_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $prepare_password_change$
BEGIN
    IF NEW.credential_version < OLD.credential_version THEN
        RAISE EXCEPTION 'credential_version cannot decrease';
    END IF;
    IF NEW.password_hash IS DISTINCT FROM OLD.password_hash THEN
        NEW.credential_version := GREATEST(NEW.credential_version, OLD.credential_version + 1);
        NEW.password_changed_at := pg_catalog.statement_timestamp();
    END IF;
    RETURN NEW;
END;
$prepare_password_change$;

-- 密碼或憑證版本改變後，撤銷原有 Session 與尚未使用的重設連結。
-- [R1] 原 SECURITY INVOKER 時，非 owner runtime role 若無涵蓋這些列的 UPDATE Policy，
-- RLS 會靜默更新 0 列，密碼卻改成功。改為 SECURITY DEFINER，以本稿表 owner 執行；
-- 只更新 NEW.user_id 的未撤銷列，無動態 SQL、不回傳資料。觸發此函式的前提是呼叫者
-- 已能依自身權限／RLS 更新該 user_accounts 列；函式本身不授予其他讀寫能力。
-- 若 owner 對這兩表仍受 RLS（例如日後 FORCE ROW LEVEL SECURITY），直接報錯 rollback。
-- search_path 依官方建議把 pg_temp 放最後；型別也完整限定。
-- [R3] revoked_at 取 GREATEST(statement_timestamp, created_at)，避免應用時鐘寫入的
-- 未來 created_at 觸發 revoked_at >= created_at CHECK，讓撤銷整筆失敗。
CREATE FUNCTION invoiceguard_internal.revoke_stale_credentials()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $revoke_stale_credentials$
DECLARE
    revoke_time pg_catalog.timestamptz := pg_catalog.statement_timestamp();
BEGIN
    IF NEW.password_hash IS DISTINCT FROM OLD.password_hash
       OR NEW.credential_version IS DISTINCT FROM OLD.credential_version THEN
        IF pg_catalog.row_security_active(
               'invoiceguard_identity.user_sessions'::pg_catalog.regclass)
           OR pg_catalog.row_security_active(
               'invoiceguard_identity.password_reset_tokens'::pg_catalog.regclass) THEN
            RAISE EXCEPTION 'credential revocation would be filtered by row level security';
        END IF;

        UPDATE invoiceguard_identity.user_sessions
        SET revoked_at = GREATEST(revoke_time, created_at)
        WHERE user_id = NEW.user_id AND revoked_at IS NULL;

        UPDATE invoiceguard_identity.password_reset_tokens
        SET revoked_at = GREATEST(revoke_time, created_at)
        WHERE user_id = NEW.user_id AND used_at IS NULL AND revoked_at IS NULL;
    END IF;
    RETURN NEW;
END;
$revoke_stale_credentials$;

-- v1.8：新增或移除關聯時，同一交易維護 file_count；最後一份檔案移除時收回部門指派。
-- 重新加入檔案不會恢復舊的部門指派。知識庫被刪除時關聯連帶刪除，UPDATE 不命中任何列，不影響刪除。
-- SECURITY DEFINER 與 revoke_stale_credentials 相同：若會被 RLS 過濾就報錯 rollback，不假成功。
CREATE FUNCTION invoiceguard_internal.sync_rag_knowledge_base_file_count()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $sync_rag_knowledge_base_file_count$
DECLARE
    remaining pg_catalog.int4;
BEGIN
    IF pg_catalog.row_security_active(
           'public.rag_knowledge_bases'::pg_catalog.regclass)
       OR pg_catalog.row_security_active(
           'public.rag_department_access'::pg_catalog.regclass) THEN
        RAISE EXCEPTION 'file count sync would be filtered by row level security';
    END IF;

    IF TG_OP = 'INSERT' THEN
        UPDATE public.rag_knowledge_bases
        SET file_count = file_count + 1
        WHERE knowledge_base_id = NEW.knowledge_base_id;
        RETURN NEW;
    END IF;

    UPDATE public.rag_knowledge_bases
    SET file_count = GREATEST(file_count - 1, 0)
    WHERE knowledge_base_id = OLD.knowledge_base_id
    RETURNING file_count INTO remaining;

    IF remaining = 0 THEN
        UPDATE public.rag_department_access
        SET use_for_qa = false
        WHERE knowledge_base_id = OLD.knowledge_base_id AND use_for_qa;
    END IF;
    RETURN OLD;
END;
$sync_rag_knowledge_base_file_count$;

CREATE TRIGGER user_accounts_prepare_password_change
BEFORE UPDATE ON invoiceguard_identity.user_accounts
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.prepare_password_change();

CREATE TRIGGER user_accounts_revoke_stale_credentials
AFTER UPDATE ON invoiceguard_identity.user_accounts
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.revoke_stale_credentials();

CREATE TRIGGER user_accounts_touch_updated_at
BEFORE UPDATE ON invoiceguard_identity.user_accounts
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.touch_updated_at();

CREATE TRIGGER user_profiles_touch_updated_at
BEFORE UPDATE ON public.user_profiles
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.touch_updated_at();

CREATE TRIGGER departments_touch_updated_at
BEFORE UPDATE ON public.departments
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.touch_updated_at();

CREATE TRIGGER department_permissions_touch_updated_at
BEFORE UPDATE ON public.department_permissions
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.touch_updated_at();

CREATE TRIGGER invoices_touch_updated_at
BEFORE UPDATE ON public.invoices
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.touch_updated_at();

CREATE TRIGGER invoice_items_touch_updated_at
BEFORE UPDATE ON public.invoice_items
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.touch_updated_at();

CREATE TRIGGER invoice_field_reviews_touch_updated_at
BEFORE UPDATE ON public.invoice_field_reviews
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.touch_updated_at();

CREATE TRIGGER rag_knowledge_bases_touch_updated_at
BEFORE UPDATE ON public.rag_knowledge_bases
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.touch_updated_at();

CREATE TRIGGER rag_files_touch_updated_at
BEFORE UPDATE ON public.rag_files
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.touch_updated_at();

-- v1.5
CREATE TRIGGER rag_department_access_touch_updated_at
BEFORE UPDATE ON public.rag_department_access
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.touch_updated_at();

CREATE TRIGGER rag_file_department_usage_touch_updated_at
BEFORE UPDATE ON public.rag_file_department_usage
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.touch_updated_at();

-- v1.8
CREATE TRIGGER rag_knowledge_base_files_sync_file_count
AFTER INSERT OR DELETE ON public.rag_knowledge_base_files
FOR EACH ROW EXECUTE FUNCTION invoiceguard_internal.sync_rag_knowledge_base_file_count();

-- ==================== E. 權限與導覽 View（全部只供受控後端） ====================
-- security_invoker 保持呼叫者 DB 權限及 RLS，不替呼叫者繞過存取控制。
-- 下列兩個 effective View 保留 v1.2 跨部門 OR/UNION 摘要定義，
-- 另加入帳號必須 active 的條件；它們不是目前部門的資料存取許可。
-- 與 v1.2 的唯一差異是各多一個 JOIN user_accounts(active)，理由：pending/disabled 帳號
-- 不得取得任何權限；其餘 SELECT/JOIN/WHERE/GROUP BY 逐字相同。v_invoice_return_fields 逐字相同。
-- security_invoker 會以呼叫者身分檢查底層表權限與 RLS。以下為職責區分（R8，R9 補正）：
-- * 部門查詢職責：對 user_accounts 只需 (user_id, account_status, primary_department_id)、
--   對 user_profiles 只需 (user_id, is_active, resigned_at) 欄位級 SELECT 與對應 RLS Policy；
--   不因查詢部門功能而取得 email／password_hash、phone 等個資或整表讀取權。
-- * 登入驗證職責：受控後端另核定 email、password_hash、帳號狀態等必要欄位的
--   最小讀取權限及 RLS Policy，供 Python 查找帳號、驗證 Argon2id 與檢查登入資格。
-- 職責區分不要求專案初期立即拆成兩套服務，或為兩種職責各建一組 DB 角色。
-- 若初期共用同一 runtime role，「部門查詢不讀 email／password_hash」只能靠程式碼限制，
-- 不能宣稱已由 DB 隔離；角色拆分後才由欄位級權限強制。
-- 密碼雜湊不得輸出至瀏覽器、HTTP 回應或日誌。Email 僅能依核定業務用途及使用者授權顯示，
-- 不隨部門 View 洩出。
CREATE VIEW public.v_user_effective_permissions
WITH (security_invoker = true)
AS
SELECT
    u.user_id,
    f.function_id,
    f.function_code,
    f.function_name,
    f.app_scope,
    bool_or(dp.can_view)   AS can_view,
    bool_or(dp.can_create) AS can_create,
    bool_or(dp.can_edit)   AS can_edit,
    bool_or(dp.can_delete) AS can_delete
FROM public.user_profiles AS u
JOIN invoiceguard_identity.user_accounts AS a
  ON a.user_id = u.user_id AND a.account_status = 'active'
JOIN public.user_departments AS ud
  ON ud.user_id = u.user_id
 AND ud.unassigned_at IS NULL
JOIN public.departments AS d
  ON d.department_id = ud.department_id
 AND d.is_active = true
JOIN public.department_permissions AS dp
  ON dp.department_id = d.department_id
JOIN public.app_functions AS f
  ON f.function_id = dp.function_id
 AND f.is_active = true
WHERE u.is_active = true
  AND u.resigned_at IS NULL
GROUP BY u.user_id, f.function_id, f.function_code, f.function_name, f.app_scope;

-- B. Knowledge-base permissions obey the same cross-department UNION rule.
-- v1.5：只納入已核准的知識庫；末尾新增 use_for_qa（跨部門 OR 摘要，不是目前部門的選用）。
CREATE VIEW public.v_user_effective_rag_access
WITH (security_invoker = true)
AS
SELECT
    u.user_id,
    kb.knowledge_base_id,
    kb.knowledge_code,
    bool_or(kda.can_read) AS can_read,
    bool_or(kda.can_manage) AS can_manage,
    bool_or(kda.use_for_qa) AS use_for_qa
FROM public.user_profiles AS u
JOIN invoiceguard_identity.user_accounts AS a
  ON a.user_id = u.user_id AND a.account_status = 'active'
JOIN public.user_departments AS ud
  ON ud.user_id = u.user_id
 AND ud.unassigned_at IS NULL
JOIN public.departments AS d
  ON d.department_id = ud.department_id
 AND d.is_active = true
JOIN public.rag_department_access AS kda
  ON kda.department_id = d.department_id
JOIN public.rag_knowledge_bases AS kb
  ON kb.knowledge_base_id = kda.knowledge_base_id
 AND kb.is_active = true
 AND kb.approval_status = 'approved'
 AND kb.file_count >= 1
WHERE u.is_active = true
  AND u.resigned_at IS NULL
GROUP BY u.user_id, kb.knowledge_base_id, kb.knowledge_code;

-- C. Server-only list of red-highlight fields for the procurement return screen.
-- Only unapproved manual-edit fields from the CURRENT returned submission round.
CREATE VIEW public.v_invoice_return_fields
WITH (security_invoker = true)
AS
SELECT
    fr.invoice_id, fr.field_review_id, fr.submission_round,
    fr.field_scope, fr.item_id, fr.field_name,
    fr.ai_original_value, fr.submitted_value, fr.review_comment
FROM public.invoice_field_reviews AS fr
JOIN public.invoices AS i ON i.invoice_id = fr.invoice_id
WHERE i.status = 'returned_to_applicant'
  AND fr.submission_round = i.submission_round
  AND fr.is_checked = false;


-- 登入後：後端由已驗證 Session 的 user_id 查此 View，
-- 以 is_primary=true 的唯一一列作為預設部門；沒有資料則拒絕進入後台。
-- 部門切換清單只顯示本人現行、啟用的部門；不接受任意 department_id。
CREATE VIEW public.v_user_departments
WITH (security_invoker = true)
AS
SELECT
    u.user_id,
    d.department_id,
    d.department_code,
    d.department_name,
    (a.primary_department_id = d.department_id) AS is_primary,
    ud.assigned_at
FROM public.user_profiles AS u
JOIN invoiceguard_identity.user_accounts AS a
  ON a.user_id = u.user_id AND a.account_status = 'active'
JOIN public.user_departments AS ud
  ON ud.user_id = u.user_id AND ud.is_current = true
JOIN public.departments AS d
  ON d.department_id = ud.department_id AND d.is_active = true
WHERE u.is_active = true AND u.resigned_at IS NULL;

-- 部門模式的功能授權：必須用 verified_user_id＋selected_department_id＋function_code 查詢。
-- A 部門的 can_edit 不會因跨部門 UNION 被帶到 B 部門。
-- 這是本稿為部門切換採取的明確收斂；若改採全域 UNION，須另核定業務規則。
CREATE VIEW public.v_user_department_permissions
WITH (security_invoker = true)
AS
SELECT
    ud.user_id,
    ud.department_id,
    ud.is_primary,
    f.function_id,
    f.function_code,
    f.function_name,
    f.app_scope,
    dp.can_view,
    dp.can_create,
    dp.can_edit,
    dp.can_delete
FROM public.v_user_departments AS ud
JOIN public.department_permissions AS dp ON dp.department_id = ud.department_id
JOIN public.app_functions AS f ON f.function_id = dp.function_id AND f.is_active = true;

-- v1.5：只納入已核准的知識庫；use_for_qa 為目前部門的選用，問答檢索以此列為準。
CREATE VIEW public.v_user_department_rag_access
WITH (security_invoker = true)
AS
SELECT
    ud.user_id,
    ud.department_id,
    ud.is_primary,
    kb.knowledge_base_id,
    kb.knowledge_code,
    kda.can_read,
    kda.can_manage,
    kda.use_for_qa
FROM public.v_user_departments AS ud
JOIN public.rag_department_access AS kda ON kda.department_id = ud.department_id
JOIN public.rag_knowledge_bases AS kb
  ON kb.knowledge_base_id = kda.knowledge_base_id AND kb.is_active = true
 AND kb.approval_status = 'approved'
 AND kb.file_count >= 1;

-- ==================== F. 初始存取控制（預設拒絕） ====================
-- 不使用任何供應商預設角色，也不建立高權限 LOGIN 帳號。
-- 所有表開啟 RLS；本稿不建立允許一般客戶端的 Policy。
-- 一般非 owner runtime role 在配置最小 GRANT/Policy 前不能操作，這是刻意的 fail closed。
-- table owner/superuser/BYPASSRLS 可以繞過 RLS，不能拿來當正式應用帳號。
-- 未來後端專用 role 的 Policy 僅是服務存取門檻，不能取代每位使用者的授權。
ALTER TABLE invoiceguard_identity.user_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.departments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_departments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.app_functions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.department_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoiceguard_identity.user_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoiceguard_identity.password_reset_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_changes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_status_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_recognition_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_field_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_knowledge_bases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_department_access ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_file_department_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_knowledge_base_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_function_knowledge_bases ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE invoiceguard_identity.user_accounts FROM PUBLIC;
REVOKE ALL ON TABLE public.user_profiles FROM PUBLIC;
REVOKE ALL ON TABLE public.departments FROM PUBLIC;
REVOKE ALL ON TABLE public.user_departments FROM PUBLIC;
REVOKE ALL ON TABLE public.app_functions FROM PUBLIC;
REVOKE ALL ON TABLE public.department_permissions FROM PUBLIC;
REVOKE ALL ON TABLE invoiceguard_identity.user_sessions FROM PUBLIC;
REVOKE ALL ON TABLE invoiceguard_identity.password_reset_tokens FROM PUBLIC;
REVOKE ALL ON TABLE public.invoices FROM PUBLIC;
REVOKE ALL ON TABLE public.invoice_items FROM PUBLIC;
REVOKE ALL ON TABLE public.invoice_files FROM PUBLIC;
REVOKE ALL ON TABLE public.invoice_changes FROM PUBLIC;
REVOKE ALL ON TABLE public.invoice_status_history FROM PUBLIC;
REVOKE ALL ON TABLE public.ai_recognition_logs FROM PUBLIC;
REVOKE ALL ON TABLE public.invoice_field_reviews FROM PUBLIC;
REVOKE ALL ON TABLE public.rag_knowledge_bases FROM PUBLIC;
REVOKE ALL ON TABLE public.rag_department_access FROM PUBLIC;
REVOKE ALL ON TABLE public.rag_files FROM PUBLIC;
REVOKE ALL ON TABLE public.rag_chunks FROM PUBLIC;
REVOKE ALL ON TABLE public.rag_jobs FROM PUBLIC;
REVOKE ALL ON TABLE public.rag_file_department_usage FROM PUBLIC;
REVOKE ALL ON TABLE public.rag_knowledge_base_files FROM PUBLIC;
REVOKE ALL ON TABLE public.rag_function_knowledge_bases FROM PUBLIC;
REVOKE ALL ON TABLE public.v_user_effective_permissions FROM PUBLIC;
REVOKE ALL ON TABLE public.v_user_effective_rag_access FROM PUBLIC;
REVOKE ALL ON TABLE public.v_invoice_return_fields FROM PUBLIC;
REVOKE ALL ON TABLE public.v_user_departments FROM PUBLIC;
REVOKE ALL ON TABLE public.v_user_department_permissions FROM PUBLIC;
REVOKE ALL ON TABLE public.v_user_department_rag_access FROM PUBLIC;

-- 只清除本稿列出之新建物件的非 owner 顯式 ACL。
-- 可移除主機既有 default privileges 自動加上的權限，但不更動其設定／其他物件。
-- 依實際 ACL 找角色，因此一般 PostgreSQL 不需要存在任何供應商角色。
-- [R4] 找不到物件或清理後仍有非 owner（含 PUBLIC）權限時直接報錯，不靜默略過。
DO $revoke_object_acl$
DECLARE
    object_name text;
    object_oid oid;
    grantee_record record;
BEGIN
    FOREACH object_name IN ARRAY ARRAY[
        'invoiceguard_identity.user_accounts',
        'public.user_profiles',
        'public.departments',
        'public.user_departments',
        'public.app_functions',
        'public.department_permissions',
        'invoiceguard_identity.user_sessions',
        'invoiceguard_identity.password_reset_tokens',
        'public.invoices',
        'public.invoice_items',
        'public.invoice_files',
        'public.invoice_changes',
        'public.invoice_status_history',
        'public.ai_recognition_logs',
        'public.invoice_field_reviews',
        'public.rag_knowledge_bases',
        'public.rag_department_access',
        'public.rag_files',
        'public.rag_chunks',
        'public.rag_jobs',
        'public.rag_file_department_usage',
        'public.rag_knowledge_base_files',
        'public.rag_function_knowledge_bases',
        'public.v_user_effective_permissions',
        'public.v_user_effective_rag_access',
        'public.v_invoice_return_fields',
        'public.v_user_departments',
        'public.v_user_department_permissions',
        'public.v_user_department_rag_access'
    ]
    LOOP
        object_oid := pg_catalog.to_regclass(object_name);
        IF object_oid IS NULL THEN
            RAISE EXCEPTION 'ACL cleanup target not found: %', object_name;
        END IF;
        FOR grantee_record IN
            SELECT DISTINCT r.rolname
            FROM pg_catalog.pg_class AS c
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(c.relacl, pg_catalog.acldefault('r', c.relowner))
            ) AS x
            JOIN pg_catalog.pg_roles AS r ON r.oid = x.grantee
            WHERE c.oid = object_oid AND x.grantee <> c.relowner
        LOOP
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON TABLE %s FROM %I',
                object_oid::pg_catalog.regclass, grantee_record.rolname
            );
        END LOOP;
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class AS c
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(c.relacl, pg_catalog.acldefault('r', c.relowner))
            ) AS x
            WHERE c.oid = object_oid AND x.grantee <> c.relowner
        ) THEN
            RAISE EXCEPTION 'non-owner privileges remain on %', object_oid::pg_catalog.regclass;
        END IF;
    END LOOP;
END;
$revoke_object_acl$;

REVOKE ALL ON FUNCTION invoiceguard_internal.touch_updated_at() FROM PUBLIC;
REVOKE ALL ON FUNCTION invoiceguard_internal.prepare_password_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION invoiceguard_internal.revoke_stale_credentials() FROM PUBLIC;
REVOKE ALL ON FUNCTION invoiceguard_internal.sync_rag_knowledge_base_file_count() FROM PUBLIC;

-- 同樣只清理本稿的兩個私有 schema 與四個函式，避免主機自訂
-- default privileges 留下其他角色的 USAGE/EXECUTE；不影響其他物件或預設設定。
-- [R4] 同樣在找不到物件或清理後仍有非 owner（含 PUBLIC）權限時報錯。
-- revoke_stale_credentials 為 SECURITY DEFINER，EXECUTE 只留 owner；Trigger 觸發不需呼叫者 EXECUTE。
DO $revoke_private_acl$
DECLARE
    schema_name text;
    function_name text;
    grantee_record record;
BEGIN
    FOREACH schema_name IN ARRAY ARRAY['invoiceguard_identity', 'invoiceguard_internal']
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_namespace AS n WHERE n.nspname = schema_name
        ) THEN
            RAISE EXCEPTION 'ACL cleanup schema not found: %', schema_name;
        END IF;
        FOR grantee_record IN
            SELECT DISTINCT r.rolname
            FROM pg_catalog.pg_namespace AS n
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(n.nspacl, pg_catalog.acldefault('n', n.nspowner))
            ) AS x
            JOIN pg_catalog.pg_roles AS r ON r.oid = x.grantee
            WHERE n.nspname = schema_name AND x.grantee <> n.nspowner
        LOOP
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON SCHEMA %I FROM %I',
                schema_name, grantee_record.rolname
            );
        END LOOP;
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_namespace AS n
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(n.nspacl, pg_catalog.acldefault('n', n.nspowner))
            ) AS x
            WHERE n.nspname = schema_name AND x.grantee <> n.nspowner
        ) THEN
            RAISE EXCEPTION 'non-owner privileges remain on schema %', schema_name;
        END IF;
    END LOOP;

    FOREACH function_name IN ARRAY ARRAY[
        'invoiceguard_internal.touch_updated_at()',
        'invoiceguard_internal.prepare_password_change()',
        'invoiceguard_internal.revoke_stale_credentials()',
        'invoiceguard_internal.sync_rag_knowledge_base_file_count()'
    ]
    LOOP
        IF pg_catalog.to_regprocedure(function_name) IS NULL THEN
            RAISE EXCEPTION 'ACL cleanup function not found: %', function_name;
        END IF;
        FOR grantee_record IN
            SELECT DISTINCT r.rolname
            FROM pg_catalog.pg_proc AS p
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(p.proacl, pg_catalog.acldefault('f', p.proowner))
            ) AS x
            JOIN pg_catalog.pg_roles AS r ON r.oid = x.grantee
            WHERE p.oid = pg_catalog.to_regprocedure(function_name)
              AND x.grantee <> p.proowner
        LOOP
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON FUNCTION %s FROM %I',
                pg_catalog.to_regprocedure(function_name), grantee_record.rolname
            );
        END LOOP;
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS p
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(p.proacl, pg_catalog.acldefault('f', p.proowner))
            ) AS x
            WHERE p.oid = pg_catalog.to_regprocedure(function_name)
              AND x.grantee <> p.proowner
        ) THEN
            RAISE EXCEPTION 'non-owner privileges remain on function %', function_name;
        END IF;
    END LOOP;
END;
$revoke_private_acl$;

COMMENT ON SCHEMA invoiceguard_identity IS
    'Private portable identity data; never expose through public API or logs.';
COMMENT ON COLUMN invoiceguard_identity.user_accounts.password_hash IS
    'Full application-generated Argon2id PHC string; never plaintext or public response.';
COMMENT ON COLUMN invoiceguard_identity.user_accounts.primary_department_id IS
    'Single login default; must be an enabled current membership; grants no extra permission.';
COMMENT ON COLUMN invoiceguard_identity.user_sessions.session_token_digest IS
    'SHA256 of a high-entropy random session token; never store the raw token.';
COMMENT ON COLUMN invoiceguard_identity.password_reset_tokens.token_digest IS
    'SHA256 of a high-entropy single-use reset token; never store the raw token.';
COMMENT ON COLUMN public.user_departments.is_current IS
    'Derived from unassigned_at IS NULL; not a future scheduling mechanism.';
COMMENT ON VIEW public.v_user_effective_permissions IS
    'Cross-department OR summary; not authorization for a selected-department operation.';
COMMENT ON VIEW public.v_user_department_permissions IS
    'Server-only selected-department permissions; always filter verified user, department and function.';
-- [R7] 補齊 RAG／部門 View 說明，避免把跨部門聯集誤用為目前部門授權。
COMMENT ON VIEW public.v_user_effective_rag_access IS
    'Cross-department OR summary of RAG access; not authorization for a selected-department operation.';
COMMENT ON VIEW public.v_user_department_rag_access IS
    'Server-only selected-department RAG access; always filter verified user, department and knowledge base.';
COMMENT ON VIEW public.v_user_departments IS
    'Current memberships in enabled departments for active users; is_primary is derived, not writable.';
COMMENT ON FUNCTION invoiceguard_internal.revoke_stale_credentials() IS
    'SECURITY DEFINER trigger; revokes sessions and unused reset tokens of NEW.user_id or raises if RLS would filter.';

COMMENT ON COLUMN public.invoices.tax_type IS
    'Tax type: taxable / zero_rated / tax_exempt; one per invoice. NULL while draft.';
COMMENT ON COLUMN public.invoices.status IS
    'Approval status: draft, pending_department_approval, pending_accounting_review, '
    'pending_accounting_approval, approved, returned_to_applicant, returned_to_accounting, rejected, voided.';
COMMENT ON COLUMN public.ai_recognition_logs.source_deleted_at IS
    'When the unsubmitted source image was deleted from storage (kept 1 hour); NULL if kept or linked.';
-- v1.5：RAG 審核與部門選用
COMMENT ON COLUMN public.rag_knowledge_bases.approval_status IS
    'IT review: pending (default for every new knowledge base), approved, rejected; rejected may be resubmitted as pending.';
COMMENT ON COLUMN public.rag_department_access.use_for_qa IS
    'Department selected this knowledge base for QA; a department may select several.';
COMMENT ON COLUMN public.rag_files.is_approved IS
    'IT approval of the stored content version; the application resets it to false whenever content changes.';
COMMENT ON TABLE public.rag_file_department_usage IS
    'Deprecated in v1.7: departments use every document in a selected knowledge base; the application no longer reads or writes this table.';
-- v1.8：檔案庫、功能指派與來源資訊
COMMENT ON COLUMN public.rag_knowledge_bases.file_count IS
    'Number of linked files, maintained by trigger; reaching 0 clears department QA selection.';
COMMENT ON COLUMN public.rag_files.knowledge_base_id IS
    'Transitional in v1.8: the application uses rag_knowledge_base_files; this column will be removed.';
COMMENT ON COLUMN public.rag_files.source_type IS
    'Document source category: government_regulation, company_policy, operations_manual, mixed, other; unclassified is only for files that predate v1.8.';
COMMENT ON COLUMN public.rag_files.effective_date_status IS
    'known requires effective_date; unknown and not_applicable keep effective_date NULL. Never use the upload date instead.';
COMMENT ON COLUMN public.rag_files.source_note IS
    'Free text for issuer, URL or version; recommended for mixed and other.';
COMMENT ON COLUMN public.rag_files.content_sha256 IS
    'SHA-256 of the original upload, computed by the server; NULL for files that predate v1.8.';
COMMENT ON TABLE public.rag_knowledge_base_files IS
    'Knowledge base × file. Linking never re-indexes; a referenced file cannot be deleted.';
COMMENT ON TABLE public.rag_function_knowledge_bases IS
    'Function × knowledge base assigned in ADMIN; function chat uses this intersected with department assignment.';

COMMIT;

-- ==================== 後續接線與驗收（尚未實作／尚未執行） ====================
-- 1. 帳號建立交易：
--    pending user_accounts → user_profiles → 一個或多個 user_departments →
--    設定 primary_department_id → 核准後設為 active → COMMIT。
--    不建立預設管理員／密碼；後台管理能力由部門功能權限配置。
-- 2. 登入由受控 Python 驗證 Argon2id；核對帳號狀態、locked_until、
--    profile.is_active/resigned_at 及主要部門；成功後建立新 Session Token。
--    預設選取主要部門，實際 HTTP 轉址／頁面切換由網站程式處理。
-- 3. 每次受保護請求驗證 Session 摘要、到期、撤銷、credential_version，
--    並重新核對帳號/profile／目前部門關係；不可只依賴舊 Cookie 或選單顯示。
--    切換選取部門只修改 Session 操作情境，不改使用者主要部門。
-- 4. 結束主要部門關係／停用主要部門時，須同交易改派有效主要部門，
--    或將帳號設 disabled/pending 並清除主要部門；否則延遲外鍵在 COMMIT 拒絕。
--    因 active CHECK 立即檢查，「改狀態＋清除主要部門」須在同一句 UPDATE，或先改狀態再清除。
--    停用部門前，連 pending/disabled 帳號仍指向該部門者也須先改派或清除。
--    不自動跳到未授權部門；部門代碼／網址參數不能當作授權證明。
-- 5. 忘記密碼 HTTP 回應不可透露帳號存在與否；加入限流、寄信與核准的回呼 URL。
--    不將原始 Reset Token 放日誌；設定短效期限與一次性使用規則。
--    SQL 未限制 expires_at 上限、未限制同一帳號同時有效的 Token 數，也不阻止把 used_at／
--    revoked_at 改回 NULL；這些由應用與 runtime role 權限／Policy 負責。
-- 6. 重設交易應以一致次序鎖定帳號（SELECT … FOR UPDATE），再條件更新未過期、未使用、
--    未撤銷、user_id 與版本皆相符的 Reset Token（used_at），確認恰好一筆後才更新 password_hash。
--    次序不可顛倒：若先改密碼，Trigger 會先撤銷該 Token，之後的消耗更新必為 0 筆，應 rollback。
--    Trigger 會提升版本並撤銷其餘未用 Token／所有原 Session；交易失敗全部 rollback。
--    不在重設時自動啟用、解除停權或自動登入；是否允許 pending/disabled 帳號申請重設由應用核定。
--    failed_login_count／locked_until 是否於重設後清除亦由應用決定，Trigger 不會改動。
--    新密碼由使用者重新登入驗證。
-- 7. 管理員改密碼／撤銷所有 Session 也須經授權；可增加 credential_version。
--    停用帳號時建議在同一 UPDATE 遞增 credential_version，Trigger 才會撤銷 Session／Token；
--    只改 account_status 不會自動撤銷，仍靠每次請求重新核對狀態。
--    使用者自助改密碼後若要保留本人登入，須在 password UPDATE 之後於同交易建立新 Session。
--    本稿不包含權限變更稽核表或通知寄送實作，不得宣稱已完成完整帳號安全流程。
-- 8. 配置獨立非 owner／非 BYPASSRLS 的受控後端 DB role，逐物件給最小 GRANT/Policy。
--    密碼／Session／Reset 表不可授權給一般瀏覽器；稽核表依 append-only 原則授權。
--    以下是職責區分（R8，R9 補正），不是要求初期建立兩組角色：
--    部門查詢職責：查詢 v_user_* View 只需 user_accounts(user_id, account_status,
--    primary_department_id)、user_profiles(user_id, is_active, resigned_at) 及其他底層表
--    所需欄位的 SELECT，另配對應 RLS Policy；不因部門查詢授予 email／password_hash、
--    phone 等個資或整表讀取權。
--    登入驗證職責：另核定 email、password_hash 及驗證資格所需狀態欄位的最小 SELECT／
--    RLS Policy，讓受控 Python 能查找帳號並驗證密碼；不可把部門查詢的限制套用到此職責。
--    建立 Session、更新登入失敗計數／最後登入時間、改密碼等寫入權限另依流程核定，不在此列。
--    兩者可以是同一後端程式、同一 runtime role 的不同職責；此稿不要求初期先拆服務，
--    或為兩種職責各建一組 DB 角色，但該 runtime role 仍須非 owner／非 BYPASSRLS。
--    若共用單一角色，部門查詢不讀帳密只能靠程式碼限制，不能宣稱已由 DB 隔離。
--    實際角色與權限配置留待模組接線核定。
--    密碼雜湊不得進入瀏覽器、HTTP 回應或日誌；Email 依業務授權最小揭露，不隨部門 View 洩出。
--    本稿表 owner 同時是 revoke_stale_credentials 的 SECURITY DEFINER 身分：
--    不可把 owner 當 runtime 帳號，也不建議以 superuser 執行本稿。
--    表 owner 仍能修改資料，本稿不宣稱已達不可竄改稽核。
-- 9. 後端用已驗證 user_id＋目前部門＋功能碼查部門 View，
--    再檢查發票 department_id／RAG 範圍及職務分離，不以聯集或主要部門擴權。
-- 10. 保留 v1.2 待定業務：退回欄位、重新提交沿用核准規則、發票驗證、
--     認識結果與明細一致性、修改稽核、狀態轉換及其原子性，仍需應用實作。
-- 11. Storage bucket／上傳授權／實體檔案搬移另行處理；本 SQL 不建立 bucket。
--     RAG embedding 固定 1536 維（gemini-embedding-2），目前不建向量索引。
-- 12. 新舊 ORM、介面與程式尚未對齊；這不是既有 v1.2 的直接升級／資料搬移指令。
-- 13. 未執行驗收項目：
--     真實建表、主要部門外鍵與並行異動、登入／錯誤密碼、Session 撤銷、
--     重設連結過期／重用、部門切換與跨部門拒絕、RLS、備份／還原及 pgvector。
--     另見下方審查紀錄的「仍需實測」清單。

-- ==================== v1.3 獨立靜態審查處理紀錄（2026-10-24） ====================
-- 審查方式：只讀檔、逐行文字比對與人工靜態解析。未執行任何 SQL，未連線任何資料庫或服務，
--           未建立測試庫／容器，未讀取任何秘密。下列「驗證」皆為靜態檢查，
--           不代表實際建表、外鍵、Trigger、RLS 或任何功能測試已通過。
-- 審查前 SHA256（原始位元組）：
--   本檔 v1.3 草稿：016abe4147ebacc1a5c582d21c663b4eec95adbfb101a907460463d617af3342
--   v1.2 來源檔：  308d602d5813daebdba47c41cfa71be51985302a7bc3f232f5c6411434a2f35c（未修改）
-- 修改後本檔 SHA256 無法寫入本檔自身，另見審查回報。
--
-- [R1] 中｜密碼變更後的撤銷可能「0 列卻成功」
--   原因：revoke_stale_credentials 原為 SECURITY INVOKER。官方 RLS 文件說明 UPDATE 遇到
--         Policy 不允許的既有列會靜默略過；非 owner runtime role 若無完整 UPDATE Policy，
--         密碼與版本照樣更新，Session／Reset Token 卻沒標記撤銷，與檔頭宣稱不符。
--   修改：改 SECURITY DEFINER、SET search_path = pg_catalog, pg_temp、型別完整限定；
--         先以 row_security_active() 檢查，若對 owner 仍啟用 RLS 即 RAISE（fail closed）。
--   靜態驗證：函式內所有表名均為 schema 限定、無動態 SQL；EXECUTE 只留 owner（R4 會驗證）；
--         只會撤銷 NEW.user_id 的列，屬收緊而非放寬授權。
--   仍需實測：非 owner runtime role 改密碼後兩表是否確實撤銷；FORCE RLS 時是否報錯 rollback。
-- [R2] 中｜password_hash CHECK 只看前綴
--   原因：'$argon2id$' 後接明文也能通過，不足以表達「只能存完整 Argon2id 雜湊」。
--   修改：改為 PHC 結構 regex（v=19；m/t/p 正整數；salt、hash 各至少 22 個 B64 字元）。
--   靜態驗證：以 argon2-cffi／libsodium 常見輸出（16-byte salt、32-byte hash）比對格式。
--   限制：仍不能證明真為 Argon2id 計算結果，也不檢查 OWASP 最低參數 m≥19 MiB、t≥2、p≥1；
--         若改用會輸出 keyid/data 參數或更短 salt/hash 的函式庫，須重新審核此 CHECK。
-- [R3] 低｜撤銷時間可能違反 revoked_at >= created_at
--   原因：若應用以自身時鐘寫入未來的 created_at，Trigger 以 DB 時間寫 revoked_at 會違反 CHECK，
--         導致改密碼／撤銷整筆失敗。修改：revoked_at = GREATEST(statement_timestamp, created_at)。
--   建議：created_at／expires_at 以 DB 時間產生。仍需實測時鐘偏差情境。
-- [R4] 低｜ACL 清理可能靜默略過
--   原因：to_regclass／to_regprocedure 回傳 NULL 或 REVOKE 未生效時，原 DO 區塊不報錯。
--   修改：找不到物件即 RAISE；清理後重讀 ACL，若仍有非 owner（含 PUBLIC）權限即 RAISE。
--   靜態驗證：以腳本比對 CREATE TABLE／VIEW、ENABLE RLS、REVOKE FROM PUBLIC 與 DO 清單，
--         20 表 RLS 全覆蓋，26 個表／View 三份清單完全一致；3 個函式、2 個私有 schema 亦一致。
-- [R5] 低｜建立期間名稱解析依賴執行者 search_path
--   修改：BEGIN 後 SET LOCAL search_path = pg_catalog, pg_temp（交易結束失效）。
--   靜態驗證：所有 CREATE/ALTER/REVOKE/COMMENT 目標均已 schema 限定；索引名稱隨表所在 schema。
-- [R6] 文件｜檔頭差異摘要、物件數與 pgvector 前置條件不完整；已補（user_profiles 新 CHECK、
--   departments／user_departments 新 UNIQUE 與生成欄位、移除供應商 GRANT、PG18 VIRTUAL 預設）。
-- [R7] 文件｜補 RAG／部門 View 與 definer 函式 COMMENT；補重設次序、停用帳號、自助改密碼、
--   欄位級授權、Session 並行建立的說明。
--
-- 逐項靜態結論（未列為 R 項者，本輪靜態審查未發現需改 SQL 的問題）：
-- 1. 自管帳號：user_id 為 uuid PK（gen_random_uuid）；email 需已 trim/lower、非空、含 @，並有唯一索引；
--    帳號狀態 pending/active/disabled；active 必有主要部門，經外鍵鏈必有 user_profiles；
--    profile 以 FK 指向帳號（ON DELETE CASCADE）。全檔無 INSERT／GRANT／CREATE ROLE、無預設帳號、
--    無寫死密碼、無自動管理員；無 auth.users、auth.uid()、anon、authenticated、service_role 依賴。
--    公開 View 不輸出 email、password_hash 或其他私有身分欄位。
--    帳號 active 與 profile is_active/resigned_at 是兩個可寫狀態；SQL 只在 View 中以 AND 取交集
--    （fail closed），登入時仍須三者一起核對。
-- 2. 忘記密碼：只存 32-byte 摘要；有 expires/used/revoked/credential_version 及終態互斥 CHECK；
--    文件化的「鎖帳號→條件消耗 Token→更新密碼」次序與 Trigger 相容（見後續第 6 點）；
--    改密碼必遞增版本並撤銷原 Session 與其他未用 Token；Trigger 不改 account_status、不自動登入。
--    寄信、防列舉、限流、一次性消耗的條件更新與筆數檢查均屬應用程式，欄位存在不代表已實作。
-- 3. Session：只存 32-byte 摘要；有 expires/revoked/credential_version、使用者索引；
--    prepare_password_change 禁止版本倒退且改密碼至少加 1；BEFORE Trigger 依名稱順序
--    prepare → touch，兩者互不影響。selected_department_id 不會改寫主要部門、也不授權。
-- 4. 部門：多對多由 user_departments PK(user_id, department_id) 表示；主要部門為帳號單一欄位，
--    無第二個可寫的 is_primary。生成欄位恆為 true 且不可寫，user_id NOT NULL，故 MATCH SIMPLE
--    只在 primary_department_id 為 NULL 時不檢查，而 active CHECK 禁止此情形；MATCH FULL 會擋下
--    pending 帳號的 (user_id, NULL, true)，故此處 MATCH SIMPLE 是必要的。NO ACTION＋DEFERRABLE
--    讓改派／結束關係／停用部門可在同交易完成（見後續第 4 點）。並行一致性只靠 PostgreSQL
--    外鍵鎖定機制推論，未實測。按部門 View 以 (user_id, department_id) 逐列輸出、不聚合，
--    A 部門權限不會帶到 B；但若應用改用跨部門聯集 View 授權，就會擴權，須在程式中禁止。
-- 5. v1.2 保留：12 張發票／RAG 表逐行 diff，僅 2 行註解不同（Storage 用語），欄位、型別、預設、
--    CHECK、PK、FK、UNIQUE、索引全同；逐欄審核、提交輪次、狀態歷程、修改紀錄、檔案版本、
--    RAG 關聯皆未變。新增的只有 5 個 updated_at Trigger 與 RLS／ACL 清理。三個原 View 差異見 E 節註解。
-- 6. 全檔：建立順序可解（帳號→profile→部門→成員→ALTER 加延遲 FK→其餘表）；唯一外鍵循環
--    帳號→成員→profile→帳號 靠延遲＋可為 NULL 的外鍵解開；單一 BEGIN/COMMIT，任何失敗全部 rollback；
--    無 DROP／DELETE／TRUNCATE、無 IF NOT EXISTS 掩蓋同名物件（extensions／vector 除外並有檢查）、
--    無伺服器層級設定。ACL 清理只針對本稿 26 個表／View、2 個私有 schema、3 個函式。
--    沒有任何 Policy 與 runtime role：非 owner 角色目前無法讀寫（fail closed）；但表 owner、
--    superuser、BYPASSRLS 不受 RLS 限制，這不是安全保證，只是尚未開放。
--
-- SQL 已強制（建表成功後由 PostgreSQL 執行，尚未實測）：
--   email 正規化／唯一；Argon2id PHC 結構；帳號狀態值域；active 必有主要部門；
--   主要部門於 COMMIT 時須為本人現行成員關係且部門啟用；Token／Session 摘要 32 bytes 且唯一；
--   時間先後與 Reset 終態互斥 CHECK；改密碼版本遞增、版本不可倒退、撤銷原 Session／未用 Token；
--   updated_at 自動更新；20 表 RLS 啟用及本稿物件 ACL 清空；v1.2 發票／RAG 全部約束。
-- 應用程式仍須實作：
--   Argon2id 雜湊／驗證與參數（OWASP 最低值）、密碼強度；登入失敗計數與鎖定；
--   每次請求重新核對 Session 摘要、到期、撤銷、credential_version、帳號 active、
--   profile is_active／未離職、選取部門仍為本人現行啟用部門與該部門功能權限；
--   登入預設主要部門、只允許切換到本人有效部門、轉址／選單；
--   忘記密碼寄信、一致回應防列舉、限流、短效期限、條件消耗並檢查恰好一筆；
--   發票 department_id／RAG 範圍、職務分離、提交輪次與欄位審核流程；
--   runtime role、欄位級 GRANT 與 RLS Policy；Storage bucket 與實體檔案備份。
-- 仍需實測（靜態審查無法證明）：
--   1. 實際建表：生成欄位常數 (true) STORED、含生成欄位的複合外鍵、regex CHECK、
--      SECURITY DEFINER Trigger、DO 區塊 ACL 清理在 PG15／16／17／18 是否都成功。
--   2. 主要部門：改派、結束關係、停用部門、刪除 profile 的成功與拒絕案例；
--      兩交易並行改派與結束關係時是否一方被拒絕（READ COMMITTED 與 SERIALIZABLE）。
--   3. 密碼：以非 owner runtime role 改密碼／重設後 Session 與 Token 是否撤銷、
--      版本是否遞增；FORCE RLS 時是否報錯；未來時間 created_at 的情境。
--   4. 重設：過期、重用、撤銷、版本不符、先改密碼後消耗（應 0 筆）、並行雙重消耗。
--   5. 權限：部門切換後跨部門拒絕；pending/disabled 帳號、停用部門、停用功能無權限；
--      部門查詢職責能查 v_user_* View 且讀不到 email／password_hash
--      （拆分角色時以 DB 權限驗證；共用單一角色時以程式碼審查與測試確認查詢路徑）；
--      登入驗證職責能受控讀取必要帳號欄位、完成密碼驗證，且雜湊不出現在瀏覽器、
--      HTTP 回應或日誌。
--   6. 稽核與還原：pg_dump／pg_restore（含 --disable-triggers、session_replication_role=replica）
--      後重新驗證外鍵與 Trigger 效果；備份須含兩個私有 schema 與 pgvector 版本。
--   7. email lower() 對非 ASCII 字元在不同 collation／作業系統版本下是否一致。
--   8. pgvector：主機版本、是否需 DBA 預先建立、extensions schema USAGE、日後 HNSW 維度。
-- ==================== 權限說明補正紀錄（2026-10-24，R8） ====================
-- 問題：原註解將部門查詢的最小 SELECT 範圍泛稱為 runtime role 的共同限制，
--       容易被解讀成登入驗證服務也不能讀取 email／password_hash，與自管登入需求矛盾。
-- 處理：區分部門查詢角色與受控登入驗證服務，補正 E 節、後續接線第 8 點及權限待測項目；
--       只修改註解，不新增／變更資料表、欄位、約束、View、函式、Trigger、GRANT 或 Policy。
--       密碼雜湊仍不得回傳瀏覽器／一般 HTTP 回應或寫入日誌；Email 依業務授權最小揭露。
--       職責區分不等於要求初期拆成兩套服務；實際 DB 角色配置留待模組接線時核定。
-- 初期驗收範圍：目前主要目的是模組測驗，不要求一次補齊完整業務資料結構。
--       只要當次測試所需的帳號、雜湊、使用者識別、部門關聯等關鍵欄位與必要約束充足，
--       即可列為該階段的結構條件符合；其他欄位可隨需求另行增加，不因尚未齊備而誤判失敗。
--       登入授權、資料隔離及當次測試必要的完整性檢查不因此省略；結構條件符合也不代表
--       模組測試已通過，仍須以當次真實測試結果判定。本次未測模組、未執行任何 SQL。
-- 靜態驗證：比對修改前後非註解行與文字差異，確認只有上述權限註解及本紀錄有變動；
--       確認部門查詢不取得帳密、登入驗證可核定必要讀取，以及外部輸出限制三者不矛盾。
-- 修改前 SHA256：11ab806f1d0f05c1fc6c7bc7c88cffc37b05d5f1ae23de4f22032208e9d53fc3
-- 修改後 SHA256 另於回報提供，不將本檔自身雜湊寫回本檔。

-- ==================== 權限註解與初期模組測驗限定範圍檢查紀錄（2026-10-24，R9） ====================
-- 範圍：只檢查 R8 權限註解的一致性，以及初期模組測驗所需的結構；不重做 R1–R7、
--       不重新設計帳號系統、不新增測試程式。R8 紀錄原文保留，不改寫歷史。
-- 方法：只讀檔、文字比對、靜態解析；未執行 SQL、未連線資料庫、未建立測試庫或容器、未讀秘密。
-- 修改前 SHA256：8155c80ef6e1d733c609cc7abd7d32b1be9f67f74357969d2c426eeb8a39c626（與交付預期相符）
-- 修改後 SHA256 另於回報提供，不寫回本檔。
-- 交叉核對位置：E 節 View 權限說明、後續接線第 8 點、仍需實測第 5 點、R8 紀錄。
-- R8 主體正確：部門查詢只取 View 必要欄位；登入驗證職責可經核定讀取 email／password_hash；
--   禁止的是把雜湊輸出到瀏覽器、HTTP 回應或日誌，而不是禁止登入驗證讀取；
--   Email 依核定用途與使用者授權揭露，沒有被一概禁止，也不隨部門 View 輸出。
-- [R9-1] 低｜「新增 DB 角色」用語與第 8 點首句及 R1 衝突
--   原因：第 8 點寫「不要求初期新增 DB 角色」，同點首句與 R1 卻要求非 owner runtime role；
--         E 節只說不必拆服務，未提 DB 角色。原意應是不必為兩種職責各建一組角色。
--   修正：E 節與第 8 點改為「不要求初期拆服務，或為兩種職責各建一組 DB 角色」，
--         並保留 runtime role 須非 owner／非 BYPASSRLS；實際配置留待模組接線核定。
-- [R9-2] 中｜共用單一角色時，「部門查詢讀不到帳密」並非 DB 強制
--   原因：初期若同一 runtime role 兼任登入驗證，該角色本來就能讀 email／password_hash；
--         原註解容易被理解成 DB 已在部門查詢上隔離帳密。
--   修正：E 節、第 8 點、待測第 5 點註明此時只能靠程式碼限制，須以程式碼審查與測試確認；
--         角色拆分後才可宣稱由 DB 欄位級權限強制。
-- [R9-3] 低｜最小欄位只列 user_accounts
--   原因：v_user_* View 也讀 user_profiles，該表另含 phone、employee_code 等個資。
--   修正：E 節與第 8 點補 user_profiles 只需 (user_id, is_active, resigned_at)。
--   靜態驗證：逐一比對 5 個 v_user_* View（含經 v_user_departments 間接引用者），
--         user_accounts 只用 user_id、account_status、primary_department_id，
--         user_profiles 只用 user_id、is_active、resigned_at，與註解一致。
-- [R9-4] 低｜登入驗證只寫 SELECT，可能被誤讀為已足夠或已含寫入
--   修正：第 8 點註明建立 Session、登入失敗計數／最後登入時間、改密碼等寫入權限另依流程核定。
-- [R9-5] 低｜輸出限制用語不一致
--   原因：待測第 5 點只寫「不向外回傳」未含日誌；E 節、第 8 點的用語也不一致。
--   修正：現行註解統一為「瀏覽器、HTTP 回應或日誌」（不以「一般」限縮）；檔頭第 2 行補指向 R8–R9。
--
-- 初期模組測驗結構檢查（靜態，只看當次測驗必要條件）：
--   帳號識別：user_accounts.user_id uuid PK，預設 gen_random_uuid()。
--   Email：NOT NULL、trim／lower 正規化 CHECK、基本格式 CHECK、唯一索引。
--   密碼雜湊：password_hash NOT NULL＋Argon2id PHC 結構 CHECK。
--   帳號狀態：account_status NOT NULL，預設 pending，值域 CHECK。
--   使用者資料與帳號關聯：user_profiles.user_id 同為 PK 與指向帳號的 FK（一對一）；
--         display_name NOT NULL 且非空白。
--   部門：departments PK、department_code NOT NULL UNIQUE、department_name NOT NULL、
--         is_active 預設 true。
--   多對多成員關係：user_departments PK(user_id, department_id)，兩個 FK 分指 profile 與部門。
--   主要部門指標：user_accounts.primary_department_id＋兩個延遲複合 FK＋active 必填 CHECK。
--   結論：當次登入／部門模組測驗所需的關鍵欄位及 PK、FK、唯一性、空值、預設值條件充足，
--         列為本階段結構條件符合；未要求也未新增其他業務欄位。
--         這不代表登入、DB 串接或模組測試已通過，仍以實際測試結果判定。
-- 測試準備注意（屬測試資料／接線條件，不是結構缺陷）：
--   * 測試帳號的 password_hash 須由實際 Argon2id 函式庫產生，假字串會被 PHC CHECK 拒絕；
--     本 SQL 不含種子帳號或密碼，測試資料與密碼也不得寫回本檔。
--   * Email 須先 trim／lower 再寫入，否則正規化 CHECK 會拒絕。
--   * active 帳號須在同一交易內備妥 profile、現行成員關係與 primary_department_id；
--     延遲外鍵在 COMMIT 時才檢查，缺任一項會在 COMMIT 失敗。
--   * 20 表啟用 RLS 且 ACL 已清空：非 owner 測試角色須另配 GRANT／Policy（不在本 SQL）。
--     以 owner／superuser／BYPASSRLS 連線只能驗證結構與約束，不能作為授權、RLS 或資料隔離的測試結果。
-- 本輪結論：R8 主體正確，R9-1～R9-5 為註解補正。只改註解，非註解 SQL 與修改前逐字相同
--   （以去除 -- 註解、保留字串與 dollar-quote 函式本體後的內容比對）。未執行任何模組測驗或 SQL。
-- 尚待實際模組測驗：
--   1. 以核定的登入驗證權限讀 email／password_hash，完成 Argon2id 驗證、狀態與鎖定檢查。
--   2. 部門查詢路徑讀不到 email／password_hash（拆分角色以 DB 權限驗證；共用角色以程式碼審查與測試確認）。
--   3. 雜湊不出現在瀏覽器、HTTP 回應或日誌；Email 只在核定畫面與授權範圍顯示。
--   4. 以非 owner 測試角色配置最小 GRANT／Policy 後，v_user_* View 能正常回傳且跨部門被拒。
--   5. 帳號／profile／成員關係／主要部門的建立交易，以及缺項時 COMMIT 失敗的情形。

-- ==================== v1.4 增修紀錄（2026-10-29） ====================
-- 來源：使用者核定的課稅別辨識需求、請款單簽核狀態清單（發票狀態欄位.jpg）、未上傳影像保留 1 小時。
-- 只修改：invoices（tax_type、status 狀態清單與具名約束）、invoice_status_history（new_status 狀態清單與具名約束）、
--   v_invoice_return_fields（returned_to_applicant）、ai_recognition_logs（source_deleted_at、清理索引）及相關註解。
--   其餘表、欄位、約束、View、Trigger、RLS、ACL 與 v1.3 相同。
-- 已套用 v1.3 的資料庫：執行 InvoiceGuard_AI_v1_3_to_v1_4_ALTER.sql（單一交易、可重複執行、含舊狀態值對應）。
-- 欄位順序：新欄位接在表尾，與 ALTER 套用後的實際順序一致。
-- 驗證：本次只做靜態比對，未在任何資料庫執行本檔或 ALTER；套用後請執行 ALTER 檔尾的唯讀檢查查詢。

-- ==================== v1.5 增修紀錄（2026-10-29） ====================
-- 來源：原型 invoiceguard_final.html 的「知識庫管理」與「問答輔助」（審核流程、部門選用、文件選用、問答 Token 顯示）；
--   只補 RAG 區，發票／身分／部門不變。
-- 只修改：rag_knowledge_bases（審核 6 欄、名稱唯一索引）、rag_department_access（use_for_qa、updated_at、部分唯一索引、
--   Trigger）、rag_files（title、is_approved、approved_by、approved_at、owner_department_id、size_bytes）、
--   新表 rag_file_department_usage（Trigger）、兩個 RAG View（approved 條件、末尾 use_for_qa）、
--   RLS／REVOKE／ACL 清單、COMMENT、檔頭差異與物件數。rag_chunks、rag_jobs 與其餘物件逐字相同。
-- 不建問答紀錄表：問答為即時對話、重新整理即清空（使用者核定），不保存問題、回答或對話歷史。
-- 已套用 v1.4 的資料庫：執行 InvoiceGuard_AI_v1_4_to_v1_5_ALTER.sql（單一交易、可重複執行）。
--   既有知識庫升級後為 pending、既有文件為未核准（fail closed），須由資訊部核准；rag_files.title 由原始檔名回填。
-- 欄位順序：新欄位接在表尾，與 ALTER 套用後的實際順序一致。
-- 程式須負責（SQL 不強制）：新建知識庫與文件固定未審核；退回知識庫時清除所有部門 use_for_qa；選用知識庫時同交易
--   清除該部門其他選用（部分唯一索引會擋下未清除者）；內容變更時 file_version +1、is_approved=false、清空 approved_*、parse_status=uploaded，新增 reindex
--   工作，完成時按 file_version 核對後才設 ready；檢索五項條件。
-- 驗證：本次只做靜態比對（兩檔新表與 View 定義逐字相同、新欄位集合一致、物件計數），未在任何資料庫執行本檔或 ALTER；
--   套用後請執行 ALTER 檔尾的唯讀檢查查詢。

-- v1.5 獨立靜態審查修訂（2026-10-29，Codex；未執行 SQL）：
-- 1. 名稱唯一索引改為 NFKC／lower／JavaScript trim 的 25 字元集合，修正 ABC 與全形名稱、Tab 等邊界；ALTER 前置重複檢查同步。
-- 2. title 非空白 CHECK、ALTER 空白原始檔名檢查及回填使用同一 trim 集合；回填只移除非空的最後副檔名，保留 report.。
-- 3. 明列內容變更須清空核准資訊、重設 parse_status=uploaded；worker 必須核對 file_version，避免舊索引沿用。
-- 物件數與 RLS／ACL 清單不變；不新增問答紀錄。新表與 View 本體仍與 ALTER 相同；身分／部門／發票／既有函式及 Trigger 未改。
-- 本輪只做靜態檢查；PG15／16／17／18 的實際約束、外鍵、索引、View 替換及 locale 行為均待實測。
