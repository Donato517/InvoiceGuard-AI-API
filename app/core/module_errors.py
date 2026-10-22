"""模組名稱：app.core.module_errors；功能說明：不含設定值的模組驗證結果與例外。"""

from dataclasses import asdict, dataclass
from typing import Literal

ConfigurationScope = Literal["local", "database", "storage", "auth", "cron", "cloud"]


@dataclass(frozen=True)
class ConfigurationIssue:
    """僅包含欄位名稱與固定訊息，禁止放入設定值。"""

    field: str
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"


@dataclass(frozen=True)
class ConfigurationReport:
    """靜態設定檢查結果，不代表已連線或可執行業務操作。"""

    scope: ConfigurationScope
    issues: tuple[ConfigurationIssue, ...]

    @property
    def is_valid(self) -> bool:
        """是否沒有設定錯誤；警告不視為連線或功能通過。"""
        return not any(issue.severity == "error" for issue in self.issues)

    def as_dict(self) -> dict[str, object]:
        """產生供 CLI 使用的安全結果，不包含任何設定值。"""
        return {
            "scope": self.scope,
            "configuration_valid": self.is_valid,
            "connectivity_checked": False,
            "operations_implemented": False,
            "issues": [asdict(issue) for issue in self.issues],
        }


class ModuleConfigurationError(RuntimeError):
    """設定不符合指定能力；例外文字僅列欄位與錯誤代碼。"""

    def __init__(self, report: ConfigurationReport) -> None:
        self.report = report
        errors = [
            f"{issue.field}:{issue.code}" for issue in report.issues if issue.severity == "error"
        ]
        super().__init__("模組設定驗證失敗：" + ", ".join(errors))


class ModuleNotReadyError(RuntimeError):
    """契約已定義，實際服務尚未接線；不得假裝操作成功。"""

    def __init__(self) -> None:
        super().__init__("目前僅完成設定驗證與介面契約，尚未提供真實資料或檔案操作")
