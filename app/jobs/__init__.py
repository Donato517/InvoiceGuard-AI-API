"""
排程工作（由 app/routers/cron.py 或 scripts/run_job.py 觸發）。
規則：
    - 每個 job 一個模組，提供 JOB_NAME 常數與 run() 函式。
    - 必須具冪等性：Vercel Cron 可能漏觸發或重複觸發，且失敗不會自動重試。
"""
