"""
模組名稱：app.core.config
功能說明：集中管理環境變數設定（pydantic-settings），全專案只從這裡讀取設定。
注意事項：
    - 禁止在其他模組直接使用 os.environ / os.getenv。
    - 新增設定時，必須同步更新根目錄 .env.example。
    - 預設不讀 .env 或 secrets 目錄；公司密鑰由雲端程序環境注入。
    - DB 連線不限制執行位置；本機已有合法 DATABASE_URL 時可直接使用（與 ADMIN DB 模組相同）。
"""

import re
from collections.abc import Callable
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Literal

from psycopg import pq
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.environment import (
    EnvironmentConfigurationError,
    environment_report,
    settings_sources,
    valid_service_url,
)
from app.core.module_errors import (
    ConfigurationIssue,
    ConfigurationReport,
    ConfigurationScope,
    ModuleConfigurationError,
)

# 專案根目錄（InvoiceGuard-AI-API/）
BASE_DIR = Path(__file__).resolve().parents[2]

# psycopg 將 URL 查詢參數原樣交給 libpq；不在此清單的參數只會在連線時才失敗
LIBPQ_OPTIONS = frozenset(option.keyword.decode() for option in pq.Conninfo.get_defaults())


class Settings(BaseSettings):
    """應用程式設定。欄位名稱即環境變數名稱。"""

    model_config = SettingsConfigDict(
        env_file=None,
        secrets_dir=None,
        extra="forbid",
        validate_assignment=True,
        hide_input_in_errors=True,
    )

    # ---- 基本 ----
    APP_NAME: str = "InvoiceGuard-AI-API"
    APP_ENV: Literal["local", "preview", "production"] = "local"
    DEBUG: bool = False
    LOCAL_SECRET_FIELDS: tuple[str, ...] = Field(default=(), exclude=True, repr=False)
    MODULE_BACKEND: Literal["auto", "remote", "cloud"] = "auto"
    REMOTE_API_BASE_URL: str = Field(default="", repr=False)

    # ---- 資料庫 ----
    DATABASE_URL: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    DATABASE_URL_UNPOOLED: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    DB_POOL_MODE: Literal["transaction", "session", "direct"] = "transaction"
    DB_SSL_MODE: Literal["require", "verify-full"] = "require"
    DB_CONNECT_TIMEOUT_SECONDS: int = Field(default=5, ge=1, le=30)

    # ---- 安全 ----
    JWT_SECRET_KEY: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    JWT_EXPIRE_MINUTES: int = 60
    CRON_SECRET: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)

    # ---- 外部服務 ----
    AI_API_KEY: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    GEMINI_API_KEY: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    OPENAI_API_KEY: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    EINVOICE_APP_ID: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    EINVOICE_API_KEY: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    BLOB_READ_WRITE_TOKEN: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    SUPABASE_URL: str = Field(default="", repr=False)
    SUPABASE_STORAGE_BUCKET: str = ""
    SUPABASE_SECRET_KEY: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    # Supabase Storage 的 S3 相容端點；本機由 START 經 Vercel CLI 注入（Bucket 沿用 SUPABASE_STORAGE_BUCKET）
    S3_ENDPOINT_URL: str = Field(default="", repr=False)
    S3_REGION: str = ""
    S3_ACCESS_KEY_ID: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    S3_SECRET_ACCESS_KEY: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)

    CLOUD_SECRET_FIELDS: ClassVar[tuple[str, ...]] = (
        "DATABASE_URL",
        "DATABASE_URL_UNPOOLED",
        "JWT_SECRET_KEY",
        "CRON_SECRET",
        "AI_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "EINVOICE_APP_ID",
        "EINVOICE_API_KEY",
        "BLOB_READ_WRITE_TOKEN",
        "SUPABASE_SECRET_KEY",
    )

    # ---- Vercel 系統變數（由 Vercel 自動注入，不需手動設定）----
    VERCEL: str = ""
    VERCEL_ENV: str = ""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource | Callable[[], dict[str, Any]], ...]:
        """只讀程序環境與核定本機 URL 設定；即使指定 _env_file 也不載入。"""
        return settings_sources(init_settings, env_settings, repo_root=BASE_DIR, platform="api")

    def check_environment(self) -> dict[str, Any]:
        """驗證本站邊界；依核定允許本機 DATABASE_URL，其他機密規則不變。"""
        report = environment_report(self, "api")
        report["issues"] = [
            issue
            for issue in report["issues"]
            if not (issue["field"] == "DATABASE_URL" and issue["code"] == "cloud_secret_in_local")
        ]
        if (
            self.APP_ENV == "local"
            and not self.VERCEL
            and not self.VERCEL_ENV
            and self.DATABASE_URL.get_secret_value()
        ):
            report["issues"].extend(asdict(issue) for issue in self._database_issues())
        report["configuration_valid"] = not any(
            issue["severity"] == "error" for issue in report["issues"]
        )
        return report

    def require_environment(self) -> None:
        """使用本站環境報告，允許已核定的本機 DB 設定並保留其他啟動檢查。"""
        report = self.check_environment()
        if not report["configuration_valid"]:
            codes = ", ".join(
                f"{issue['field']}:{issue['code']}"
                for issue in report["issues"]
                if issue["severity"] == "error"
            )
            raise EnvironmentConfigurationError("環境設定驗證失敗：" + codes)

    @property
    def is_vercel(self) -> bool:
        """是否執行於 Vercel 環境。"""
        return self.VERCEL == "1"

    @property
    def module_backend(self) -> Literal["remote", "cloud"]:
        """自動選擇傳輸模式，不代表身分或權限已通過驗證。"""
        if self.MODULE_BACKEND == "auto":
            return "cloud" if self.is_vercel else "remote"
        return self.MODULE_BACKEND

    @property
    def temp_dir(self) -> Path:
        """暫存目錄。

        Vercel Serverless 只有 /tmp 可寫入（且執行個體結束即消失），
        本機則使用專案內 tmp/（已列入 .gitignore）。
        """
        if self.is_vercel:
            return Path("/tmp/invoiceguard")
        return BASE_DIR / "tmp"

    @property
    def sqlalchemy_database_url(self) -> str:
        """應用程式使用的 SQLAlchemy 連線字串（pooled）。"""
        return _to_psycopg_url(self.DATABASE_URL.get_secret_value())

    @property
    def migration_database_url(self) -> str:
        """Alembic 使用的連線字串；優先使用直連，未設定時沿用 DATABASE_URL。"""
        url = self.DATABASE_URL_UNPOOLED.get_secret_value() or self.DATABASE_URL.get_secret_value()
        return _to_psycopg_url(url)

    def check_configuration(self, scope: ConfigurationScope) -> ConfigurationReport:
        """靜態檢查單一能力，不讀取外部服務或建立 DB Engine。"""
        if scope not in {"local", "database", "storage", "auth", "cron", "cloud"}:
            raise ValueError("不支援的設定檢查範圍")
        if scope == "local":
            issues = self._local_issues()
        elif scope == "database":
            # DB 能力只要求合法連線設定，不要求 Vercel 標記或雲端部署。
            issues = self._database_issues()
        else:
            issues = self._cloud_context_issues()
            checks = {
                "database": self._database_issues,
                "storage": self._storage_issues,
                "auth": self._auth_issues,
                "cron": self._cron_issues,
            }
            for capability, check in checks.items():
                if scope in {capability, "cloud"}:
                    issues.extend(check())
        issues.extend(ConfigurationIssue(**issue) for issue in self.check_environment()["issues"])
        issues.append(
            ConfigurationIssue(
                "modules",
                "contracts_only",
                "目前只完成靜態設定驗證與契約，尚未驗證連線或接線實際服務",
                "warning",
            )
        )
        unique: dict[tuple[str, str], ConfigurationIssue] = {}
        for issue in issues:
            unique.setdefault((issue.field, issue.code), issue)
        return ConfigurationReport(scope, tuple(unique.values()))

    def require_configuration(self, scope: ConfigurationScope) -> None:
        """不符合設定時阻擋能力，錯誤僅包含欄位名稱與固定代碼。"""
        report = self.check_configuration(scope)
        if not report.is_valid:
            raise ModuleConfigurationError(report)

    def _local_issues(self) -> list[ConfigurationIssue]:
        issues: list[ConfigurationIssue] = []
        if self.is_vercel or self.module_backend != "remote":
            issues.append(
                ConfigurationIssue("MODULE_BACKEND", "remote_required", "本機應使用遠端模式")
            )
        for name in self.CLOUD_SECRET_FIELDS:
            # DATABASE_URL 依核定可在本機使用（START 經 Vercel CLI 注入）
            if name != "DATABASE_URL" and getattr(self, name).get_secret_value():
                issues.append(
                    ConfigurationIssue(name, "cloud_secret_in_local", "本機不應載入公司機密")
                )
        if not self.REMOTE_API_BASE_URL and not self.DATABASE_URL.get_secret_value():
            issues.append(
                ConfigurationIssue(
                    "REMOTE_API_BASE_URL",
                    "remote_not_configured",
                    "尚未設定遠端服務，目前可執行離線契約測試",
                    "warning",
                )
            )
        elif self.REMOTE_API_BASE_URL and not _is_https_base_url(self.REMOTE_API_BASE_URL):
            issues.append(
                ConfigurationIssue(
                    "REMOTE_API_BASE_URL",
                    "invalid_https_url",
                    "需為不含帳密、查詢或片段的 HTTPS 基底網址",
                )
            )
        return issues

    def _cloud_context_issues(self) -> list[ConfigurationIssue]:
        issues: list[ConfigurationIssue] = []
        if not self.is_vercel or self.module_backend != "cloud":
            issues.append(
                ConfigurationIssue(
                    "MODULE_BACKEND",
                    "cloud_runtime_required",
                    "目前僅允許在 Vercel 雲端使用直接整合",
                )
            )
        if self.APP_ENV == "local":
            issues.append(
                ConfigurationIssue(
                    "APP_ENV", "cloud_environment_required", "雲端需使用 preview 或 production"
                )
            )
        if self.DEBUG:
            issues.append(ConfigurationIssue("DEBUG", "debug_in_cloud", "雲端需關閉除錯輸出"))
        return issues

    def _database_issues(self) -> list[ConfigurationIssue]:
        if not self.DATABASE_URL.get_secret_value().strip():
            return [ConfigurationIssue("DATABASE_URL", "required", "需設定 DATABASE_URL")]
        try:
            url = make_url(self.sqlalchemy_database_url)
            if (
                url.drivername != "postgresql+psycopg"
                or not all((url.host, url.username, url.password, url.database))
                or (url.port is not None and not 1 <= url.port <= 65535)
            ):
                raise ValueError
        except (ArgumentError, ValueError, TypeError):
            return [
                ConfigurationIssue(
                    "DATABASE_URL", "invalid_postgres_url", "需設定完整 PostgreSQL 連線字串"
                )
            ]
        issues: list[ConfigurationIssue] = []
        ssl_mode = url.query.get("sslmode")
        if ssl_mode is not None and ssl_mode not in {"require", "verify-ca", "verify-full"}:
            issues.append(
                ConfigurationIssue("DATABASE_URL", "unsafe_ssl_mode", "雲端資料庫連線必須使用 TLS")
            )
        # 例如 Supabase 整合的 supa、Prisma 的 pgbouncer；不提早擋下會被誤判成 DB 連線失敗
        if not set(url.query) <= LIBPQ_OPTIONS:
            issues.append(
                ConfigurationIssue(
                    "DATABASE_URL",
                    "unsupported_url_option",
                    "連線字串含 PostgreSQL 驅動不支援的參數（例如 supa、pgbouncer），需移除",
                )
            )
        return issues

    def _storage_issues(self) -> list[ConfigurationIssue]:
        issues: list[ConfigurationIssue] = []
        if not _is_https_base_url(self.SUPABASE_URL):
            issues.append(
                ConfigurationIssue(
                    "SUPABASE_URL", "invalid_https_url", "需設定 Supabase HTTPS 專案網址"
                )
            )
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", self.SUPABASE_STORAGE_BUCKET):
            issues.append(
                ConfigurationIssue(
                    "SUPABASE_STORAGE_BUCKET", "invalid_bucket", "需設定單一合法 Bucket 名稱"
                )
            )
        if not self.SUPABASE_SECRET_KEY.get_secret_value().strip():
            issues.append(
                ConfigurationIssue(
                    "SUPABASE_SECRET_KEY", "required", "雲端 Storage 需要伺服器端憑證"
                )
            )
        return issues

    def _auth_issues(self) -> list[ConfigurationIssue]:
        issues: list[ConfigurationIssue] = []
        if len(self.JWT_SECRET_KEY.get_secret_value().strip()) < 32:
            issues.append(
                ConfigurationIssue(
                    "JWT_SECRET_KEY",
                    "secret_too_short",
                    "JWT 簽署金鑰需至少 32 字元；使用者登入實作仍待完成",
                )
            )
        if not 1 <= self.JWT_EXPIRE_MINUTES <= 1440:
            issues.append(
                ConfigurationIssue(
                    "JWT_EXPIRE_MINUTES", "invalid_duration", "有效期間需介於 1 至 1440 分鐘"
                )
            )
        return issues

    def _cron_issues(self) -> list[ConfigurationIssue]:
        if len(self.CRON_SECRET.get_secret_value().strip()) < 16:
            return [
                ConfigurationIssue("CRON_SECRET", "secret_too_short", "Cron 驗證金鑰需至少 16 字元")
            ]
        return []


def _is_https_base_url(value: str) -> bool:
    return valid_service_url(value)


def _to_psycopg_url(url: str) -> str:
    """將 postgres:// 或 postgresql:// 轉為 SQLAlchemy 的 psycopg3 driver 格式。

    Neon / Vercel 提供的連線字串為 postgres:// 開頭，SQLAlchemy 需指定 driver。
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


@lru_cache
def get_settings() -> Settings:
    """取得設定單例（只在第一次呼叫時讀取環境變數）。"""
    return Settings()


settings = get_settings()
