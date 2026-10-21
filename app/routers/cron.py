"""
模組名稱：app.routers.cron
功能說明：Vercel Cron 觸發端點。只負責驗證與呼叫 app/jobs/ 內的工作，不寫業務邏輯。
路由前綴：/api/cron（於 app.main 掛載）
注意事項：
    - 排程時間設定於 vercel.json → crons（時區固定為 UTC）。
    - Vercel Cron 以 GET 呼叫，並帶入 Authorization: Bearer <CRON_SECRET>。
    - 新增排程時：1) 在 app/jobs/ 新增模組 2) 在此新增端點 3) 在 vercel.json 新增 crons 設定
      4) 更新 docs/ARCHITECTURE.md「排程工作一覽」。
"""

from fastapi import APIRouter, Depends

from app.core.security import verify_cron_secret
from app.jobs import daily_risk_scan, sync_einvoice

router = APIRouter(
    tags=["cron"],
    dependencies=[Depends(verify_cron_secret)],
    include_in_schema=False,  # 不列入公開 API 文件
)


@router.get("/sync-einvoice")
def trigger_sync_einvoice() -> dict[str, object]:
    """同步財政部電子發票資料（每日 02:00 台灣時間）。"""
    return {"job": sync_einvoice.JOB_NAME, "result": sync_einvoice.run()}


@router.get("/daily-risk-scan")
def trigger_daily_risk_scan() -> dict[str, object]:
    """對待分析發票執行 AI 風險分析（每日 03:00 台灣時間）。"""
    return {"job": daily_risk_scan.JOB_NAME, "result": daily_risk_scan.run()}
