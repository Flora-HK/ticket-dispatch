"""add identity roles and team tables

Revision ID: 3c1a7f9e2b64
Revises: fe56fa70289e
Create Date: 2026-11-07 18:30:00.000000

DM1 of the ticket dispatch plan: User.version, UserRole, Team and
TeamMembership. Constraints and indexes are created together with the tables so
an empty database and the template baseline converge on the same schema.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "3c1a7f9e2b64"
down_revision = "fe56fa70289e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )

    op.create_table(
        "user_role",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role_code", sa.String(length=20), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role_code IN ('SUBMITTER', 'DISPATCHER', 'HANDLER', 'ADMIN')",
            name="ck_user_role_role_code",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "role_code", name="uq_user_role_user_id_role_code"
        ),
    )
    op.create_index(
        "ix_user_role_role_code_user_id", "user_role", ["role_code", "user_id"]
    )

    op.create_table(
        "team",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # Only an active Team reserves its name. Re-activating a name that is already
    # taken by another active Team must fail with TEAM_NAME_CONFLICT (VS6).
    op.create_index(
        "uq_team_name_active",
        "team",
        ["name"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "team_membership",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("team_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column("last_assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_membership_team_user"),
    )
    op.create_index(
        "ix_team_membership_team_available", "team_membership", ["team_id", "is_available"]
    )


def downgrade() -> None:
    op.drop_index("ix_team_membership_team_available", table_name="team_membership")
    op.drop_table("team_membership")
    op.drop_index("uq_team_name_active", table_name="team")
    op.drop_table("team")
    op.drop_index("ix_user_role_role_code_user_id", table_name="user_role")
    op.drop_table("user_role")
    op.drop_column("user", "version")
