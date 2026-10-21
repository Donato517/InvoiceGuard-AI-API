"""
模組名稱：app.db.models.job_run
功能說明：排程執行紀錄。每次 Vercel Cron（或手動）執行 job 都新增一筆，供後台查看與補跑判斷。

==============================================================================
資料表：job_runs（排程執行紀錄）                                   狀態：草案
==============================================================================
欄位             型別            NULL  預設        說明
---------------  --------------  ----  ----------  ------------------------------
id               BIGINT          NO    IDENTITY    主鍵
job_name         VARCHAR(100)    NO                工作名稱（對應 app/jobs/ 模組名），例：sync_einvoice
trigger          VARCHAR(20)     NO    'cron'      觸發方式：cron / manual
status           VARCHAR(20)     NO    'running'   狀態：running / success / failed
started_at       TIMESTAMPTZ     NO    now()       開始時間
finished_at      TIMESTAMPTZ     YES               結束時間（執行中為 NULL）
summary          JSONB           YES               執行摘要，例：{"synced": 120, "failed": 2}
error_message    TEXT            YES               失敗原因
------------------------------------------------------------------------------
主鍵：pk_job_runs (id)
檢查：ck_job_runs_trigger_valid  trigger IN ('cron', 'manual')
      ck_job_runs_status_valid   status IN ('running', 'success', 'failed')
索引：ix_job_runs_job_name_started_at (job_name, started_at)
外鍵：—
特性：紀錄表——只新增與更新自身狀態，不刪除；以 started_at / finished_at 取代共用時間戳
------------------------------------------------------------------------------
異動紀錄（新到舊；上線後須附 migration revision）
2026-10-21  JerryChien  初版草案（尚未產生 migration）
==============================================================================
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, in_values_check


class JobTrigger(StrEnum):
    """排程觸發方式。"""

    CRON = "cron"  # Vercel Cron 自動觸發
    MANUAL = "manual"  # scripts/run_job.py 或後台手動觸發


class JobStatus(StrEnum):
    """排程執行狀態。"""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class JobRun(IdMixin, Base):
    """排程執行紀錄。欄位定義見本檔開頭 Schema 備註。"""

    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint(in_values_check("trigger", JobTrigger), name="trigger_valid"),
        CheckConstraint(in_values_check("status", JobStatus), name="status_valid"),
        Index(None, "job_name", "started_at"),
    )

    job_name: Mapped[str] = mapped_column(String(100))
    trigger: Mapped[str] = mapped_column(String(20), server_default=JobTrigger.CRON.value)
    status: Mapped[str] = mapped_column(String(20), server_default=JobStatus.RUNNING.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
