# 供應商結構變更審查

Migration：`app/db/migrations/versions/r20261104_5e8b11d0a941_suppliers.py`。
Revision `5e8b11d0a941`，parent `7c1d4e9a2b30`。

使用者確認全公司共用主檔，各部門依查看、新增、修改及停用／啟用權限操作。
ADMIN 直接透過既有 DB Session 使用此結構；API 本次不新增供應商 REST API，前台沒有供應商入口。

變更只新增：

- `public.suppliers`：UUID 主鍵、業務欄位、狀態、建立／修改時間與操作者；欄位細節以 migration 固定 SQL 為準。
- `(country_code, tax_id)` 非空統編唯一索引，包含停用資料。
- `app_functions` 的 `suppliers`、名稱「供應商管理」、平台 `admin`、啟用項目。若已有同碼但定義不同，整批拒絕。

不建立部門 grant、不匯入模擬資料、不修改發票或帳號 Schema。
`created_by`／`updated_by` 參照 `public.user_profiles(user_id)`，非舊版 `users`。
本次使用固定 SQL 存取，沒有新增 ORM Model。ADMIN 的輸入契約為 `app/schemas/supplier.py`，輸出欄位見 `suppliers_repository.DISPLAY_COLUMNS`。

啟用 RLS 並撤銷 PUBLIC、anon、authenticated 的表權限；不新增匿名政策。
正式 runtime DB role 需由維護者確認，ADMIN 不繞過受限 RLS。未啟用前應保持部門無供應商權限。

正式套用需另外確認：資料庫備份、現有 Alembic revision、DDL 執行身分／runtime 身分及要授予哪些部門的四項權限。
禁止直接 `upgrade head` 帶入其他未核准變更；parent 尚未套用時先停止討論。
執行需使用者明確授權，本文件與 migration 提交不代表已套用。
因保護主檔，不提供刪表 downgrade；程式回退時先停用功能目錄，保留資料。

隔離整合測試：`tests/integration/test_supplier_migration_isolated_db.py`，沿用回送位址 fixture，所有本測試 DDL 與主檔資料在交易結束 rollback。
未設定隔離 PostgreSQL 時必須報告略過，不能宣稱真實 DB 驗收完成。
