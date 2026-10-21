"""
模組名稱：app.jobs.sync_einvoice
功能說明：每日排程——向財政部電子發票整合服務平台同步使用者的發票資料。
觸發方式：Vercel Cron → GET /api/cron/sync-einvoice（排程見 vercel.json）
注意事項：
    - 以「上次成功執行時間」之後的資料為同步範圍，漏跑時下次會自動補齊。
    - 以 (user_id, invoice_number, invoice_date) 判斷是否已存在，重複執行不會產生重複資料。
"""

import logging

logger = logging.getLogger(__name__)

JOB_NAME = "sync_einvoice"


def run() -> dict[str, int]:
    """執行同步。

    Returns:
        執行摘要，例如 {"synced": 120, "failed": 2}。
    """
    # TODO(JerryChien): 透過 app.jobs.runner 取得鎖並記錄 job_runs，再呼叫 einvoice_client 同步
    logger.warning("%s 尚未實作", JOB_NAME)
    return {"synced": 0, "failed": 0}
