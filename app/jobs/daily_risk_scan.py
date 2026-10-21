"""
模組名稱：app.jobs.daily_risk_scan
功能說明：每日排程——對 status=pending 的發票批次執行 AI 風險分析。
觸發方式：Vercel Cron → GET /api/cron/daily-risk-scan（排程見 vercel.json）
注意事項：
    - 單次執行受 Function maxDuration 限制（vercel.json），每批處理固定筆數，剩餘留待下次。
    - 只處理 pending，處理前先改為 analyzing，避免重複觸發時同一張發票被分析兩次。
"""

import logging

logger = logging.getLogger(__name__)

JOB_NAME = "daily_risk_scan"


def run() -> dict[str, int]:
    """執行風險掃描。

    Returns:
        執行摘要，例如 {"analyzed": 50, "flagged": 3, "failed": 0}。
    """
    # TODO(JerryChien): 透過 app.jobs.runner 執行，逐筆呼叫 invoice_analysis_service
    logger.warning("%s 尚未實作", JOB_NAME)
    return {"analyzed": 0, "flagged": 0, "failed": 0}
