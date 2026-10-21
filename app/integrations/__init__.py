"""
第三方服務串接層：每個外部服務一個 client 模組。
規則：
    - 只負責「呼叫 + 轉換格式」，不含商業邏輯。
    - 一律使用 httpx 並設定 timeout；失敗時拋出 ExternalServiceError。
    - 金鑰只從 app.core.config.settings 讀取。
"""
