"""
模組名稱：app.integrations.einvoice_client
功能說明：財政部電子發票整合服務平台 API 串接（查詢發票表頭 / 明細）。
相依設定：settings.EINVOICE_APP_ID、settings.EINVOICE_API_KEY
注意事項：
    - 平台有呼叫頻率限制，批次同步需控制速率。
    - 期別參數格式為民國年＋雙月後月（例：11310），轉換見 app.utils.datetime_utils.to_invoice_term。
"""

# TODO(JerryChien): fetch_invoice_header(invoice_number, invoice_date) -> dict
# TODO(JerryChien): fetch_invoice_detail(invoice_number, invoice_date) -> dict
