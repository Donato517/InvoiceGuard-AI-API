"""
模組名稱：app.jobs.runner
功能說明：排程共用執行機制——防止重複執行、記錄 job_runs。
設計：
    1. 以 PostgreSQL advisory lock（pg_try_advisory_lock）取得 job 專屬鎖，取不到代表已有執行中的實例，直接略過。
    2. 新增 job_runs 紀錄（status=running）。
    3. 執行 job 本體；成功寫入 summary，失敗寫入 error_message。
    4. 更新 finished_at 與 status，釋放鎖。
"""

# TODO(JerryChien): run_job(job_name, func, *, trigger="cron") -> dict   依上述設計實作
