"""
模組名稱：app.core.config
功能說明：集中管理環境變數設定（pydantic-settings），全專案只從這裡讀取設定。
注意事項：
    - 禁止在其他模組直接使用 os.environ / os.getenv。
    - 新增設定時，必須同步更新根目錄 .env.example。
    - 本機從 .env 讀取；Vercel 上由 Project Settings → Environment Variables 注入。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 專案根目錄（InvoiceGuard-AI-API/）
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """應用程式設定。欄位名稱即環境變數名稱。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 基本 ----
    APP_NAME: str = "InvoiceGuard-AI-API"
    APP_ENV: str = "local"  # local / preview / production
    DEBUG: bool = False

    # ---- 資料庫 ----
    DATABASE_URL: str = ""
    DATABASE_URL_UNPOOLED: str = ""  # Alembic migration 用的直連字串

    # ---- 安全 ----
    JWT_SECRET_KEY: str = ""
    JWT_EXPIRE_MINUTES: int = 60
    CRON_SECRET: str = ""

    # ---- 外部服務 ----
    AI_API_KEY: str = ""
    EINVOICE_APP_ID: str = ""
    EINVOICE_API_KEY: str = ""
    BLOB_READ_WRITE_TOKEN: str = ""

    # ---- Vercel 系統變數（由 Vercel 自動注入，不需手動設定）----
    VERCEL: str = ""

    @property
    def is_vercel(self) -> bool:
        """是否執行於 Vercel 環境。"""
        return self.VERCEL == "1"

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
        return _to_psycopg_url(self.DATABASE_URL)

    @property
    def migration_database_url(self) -> str:
        """Alembic 使用的連線字串；優先使用直連，未設定時沿用 DATABASE_URL。"""
        return _to_psycopg_url(self.DATABASE_URL_UNPOOLED or self.DATABASE_URL)


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
