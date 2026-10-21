"""
模組名稱：app.db.repositories.user_repository
功能說明：users 資料表的資料存取（依 email 查詢、建立、更新最後登入時間）。
注意事項：
    - 只負責 ORM 操作，不含商業邏輯，不自行 commit（交易由 service 控制）。
    - 查詢預設排除軟刪除資料（deleted_at IS NULL）。
    - email 查詢前一律轉小寫，與寫入規則一致。
"""

# TODO(JerryChien): get_by_id(db, user_id) -> User | None
# TODO(JerryChien): get_by_email(db, email) -> User | None
# TODO(JerryChien): create(db, *, email, password_hash, display_name, role) -> User
