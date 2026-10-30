"""初始迁移：建 30 张表（架构 6.2）。

ponytail: 首版建表用 Base.metadata.create_all 而不是逐表 op.create_table——
30 张表逐行写 700 行迁移没有收益。从下一个迁移起必须用 op.*，否则 downgrade 不可用。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.domain.models import Base

revision: str = "0001_init"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
