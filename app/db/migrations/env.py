"""
模組名稱：app/db/migrations/env.py
功能說明：Alembic 執行環境設定。
注意事項：
    - 連線字串一律取自 app.core.config.settings.migration_database_url
      （優先使用 DATABASE_URL_UNPOOLED 直連，pooler 不適合執行 DDL）。
    - target_metadata 指向 Base.metadata；新增 Model 後須在 app/db/models/__init__.py 匯入，
      autogenerate 才偵測得到。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.db import models  # noqa: F401  匯入以註冊所有 Model 到 metadata
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# alembic.ini 使用 configparser，連線字串中的 % 需跳脫為 %%
config.set_main_option("sqlalchemy.url", settings.migration_database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """離線模式：只輸出 SQL，不連線資料庫（alembic upgrade head --sql）。"""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """連線模式：直接對資料庫執行 migration。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
