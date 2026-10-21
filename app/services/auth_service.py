"""
模組名稱：app.services.auth_service
功能說明：登入驗證、簽發 token、更新最後登入時間。
相依模組：app.db.repositories.user_repository、app.core.security
注意事項：
    - 帳號不存在與密碼錯誤回傳相同訊息，避免帳號被列舉。
"""

# TODO(JerryChien): authenticate(db, email, password) -> TokenResponse
