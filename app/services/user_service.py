"""
模組名稱：app.services.user_service
功能說明：使用者查詢與帳號狀態管理（後台）。
相依模組：app.db.repositories.user_repository
注意事項：
    - 啟用 / 停用帳號必須寫入 audit_logs。
"""

# TODO(JerryChien): list_users(db, query) -> Page[UserRead]
# TODO(JerryChien): set_user_active(db, user_id, is_active, operator) -> UserRead
