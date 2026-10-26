"""
模組名稱：scripts.run_job
功能說明：在本機手動執行排程工作，用於開發測試與補跑。
使用方式：
    python -m scripts.run_job sync_einvoice
    python -m scripts.run_job daily_risk_scan
注意事項：
    - 程式預設不讀 .env；未來維運僅在受控雲端使用程序注入的設定。
    - 本階段只驗證契約與離線單元測試，不執行此腳本。
"""

import argparse
import importlib
import logging

from app.core.logging_config import setup_logging

# 可手動執行的 job（對應 app/jobs/ 模組名稱）
JOBS = ("sync_einvoice", "daily_risk_scan")

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="手動執行排程工作")
    parser.add_argument("job", choices=JOBS, help="工作名稱")
    args = parser.parse_args()

    setup_logging()
    module = importlib.import_module(f"app.jobs.{args.job}")
    result = module.run()
    logger.info("%s 執行完成：%s", args.job, result)


if __name__ == "__main__":
    main()
