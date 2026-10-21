"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

異動說明：
    - <描述本次結構異動與原因>
提醒：
    - 已同步更新對應 models/*.py 的 Schema 備註與「異動紀錄」（附本 revision id）
    - 已同步更新 app/db/README.md「資料表索引」（新增 / 刪除資料表時）
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

# Alembic 版本識別碼（請勿手動修改）
revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
