"""
模組名稱：app.integrations.ai_client
功能說明：AI 模型服務串接（發票影像辨識、風險判斷）。
相依設定：settings.AI_API_KEY
注意事項：
    - 送出的資料需先遮罩不必要的個資。
    - 回應需驗證格式後再交給 service，避免模型輸出異常直接寫入資料庫。
"""

# TODO(JerryChien): extract_invoice(file_bytes, mime_type) -> dict   影像 / PDF 轉結構化資料
# TODO(JerryChien): assess_risk(invoice_data) -> dict               回傳風險分數與判斷理由
