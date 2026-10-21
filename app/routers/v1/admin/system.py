"""
模組名稱：app.routers.v1.admin.system
功能說明：後台系統紀錄 API——排程執行紀錄（job_runs）、操作稽核紀錄（audit_logs）。
路由前綴：/api/v1/admin
"""

from fastapi import APIRouter

router = APIRouter(tags=["admin-system"])

# TODO(JerryChien): GET /admin/job-runs    排程執行紀錄（依 job_name 篩選、分頁）
# TODO(JerryChien): GET /admin/audit-logs  操作稽核紀錄（依 action / 操作者篩選、分頁）
