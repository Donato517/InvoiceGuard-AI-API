"""
模組名稱：app.integrations.vercel
功能說明：Vercel 執行資訊與離線設定檢查；不呼叫 Vercel 管理 API。
注意事項：CLI 不連網、不讀取 .env、不輸出環境變數值。
"""

import argparse
import json
from dataclasses import dataclass
from typing import Literal, cast

from app.core.config import Settings, settings
from app.core.module_errors import ConfigurationReport, ConfigurationScope


@dataclass(frozen=True)
class VercelPlatform:
    """安全的執行資訊；不包含任何公司機密或用戶端。"""

    environment: str
    backend: Literal["remote", "cloud"]
    is_vercel: bool
    contract_version: str = "1.0"
    operations_implemented: bool = False


def get_platform(configuration: Settings | None = None) -> VercelPlatform:
    """取得執行資訊；取得此物件不代表設定、登入或連線已驗證。"""
    configuration = configuration if configuration is not None else settings
    return VercelPlatform(
        configuration.APP_ENV, configuration.module_backend, configuration.is_vercel
    )


def check_configuration(
    scope: ConfigurationScope = "local", configuration: Settings | None = None
) -> ConfigurationReport:
    """執行指定能力的靜態設定驗證，不建立任何外部連線。"""
    configuration = configuration if configuration is not None else settings
    return configuration.check_configuration(scope)


def main(argv: list[str] | None = None) -> int:
    """CLI：設定有效回傳 0，設定錯誤回傳 2；均不代表整合測試通過。"""
    parser = argparse.ArgumentParser(description="API 模組離線設定檢查")
    parser.add_argument(
        "--check",
        choices=["local", "database", "storage", "auth", "cron", "cloud"],
        default="local",
    )
    arguments = parser.parse_args(argv)
    report = check_configuration(cast(ConfigurationScope, arguments.check))
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.is_valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
