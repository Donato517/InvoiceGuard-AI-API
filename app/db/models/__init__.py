"""
模組名稱：app.db.models
功能說明：匯入全部 ORM Model，使其註冊到 Base.metadata。
注意事項：
    - 新增 Model 檔案後必須在此匯入，Alembic autogenerate 才偵測得到。
    - 同時更新 app/db/README.md 的「資料表索引」。
"""

from app.db.models.audit_log import AuditLog
from app.db.models.invoice import Invoice, InvoiceItem
from app.db.models.job_run import JobRun
from app.db.models.user import User

__all__ = ["AuditLog", "Invoice", "InvoiceItem", "JobRun", "User"]
