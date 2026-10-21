"""
模組名稱：app.services.invoice_analysis_service
功能說明：發票 AI 風險分析——組合發票資料、呼叫 AI 服務、解析結果並寫回 risk_score / ai_result。
相依模組：app.integrations.ai_client、app.db.repositories.invoice_repository
注意事項：
    - 呼叫 AI 前先結束資料庫交易，避免外部服務延遲時長時間佔用連線。
    - ai_result 需保存模型名稱與版本，方便日後追查判斷依據。
"""

# TODO(JerryChien): analyze_invoice(db, invoice_id, *, force=False) -> InvoiceRead
