"""退役 Item 表

Revision ID: 2f3d4c5b6a71
Revises: e7a3c9d15b42
Create Date: 2026-11-20 16:00:00.000000

VS8 已将所有运行入口切换到 Ticket 领域；Item 表不再承载任何业务数据。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "2f3d4c5b6a71"
down_revision = "e7a3c9d15b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 旧表只属于模板示例，不得保留为隐藏业务入口。
    op.drop_table("item")


def downgrade() -> None:
    # 降级仅供开发环境回退；按原模板字段和外键恢复空表。
    op.create_table(
        "item",
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["user.id"],
            name="item_owner_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
