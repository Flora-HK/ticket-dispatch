"""新增审计、通知与幂等记录表

Revision ID: c4e8a1f62d90
Revises: 8b4d9e2a6c71
Create Date: 2026-11-09 10:00:00.000000

DM3 建立业务历史、站内通知和短期幂等重放所需的治理表。
AuditLog 的不可变 Trigger 按计划在 DM4 中添加。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# 以下 revision 标识由 Alembic 使用，不能被后续迁移修改。
revision = "c4e8a1f62d90"
down_revision = "8b4d9e2a6c71"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column(
            "entity_key",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("ticket_id", sa.UUID(), nullable=True),
        sa.Column(
            "before_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "after_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "actor_type IN ('USER', 'SYSTEM')",
            name="ck_audit_log_actor_type",
        ),
        sa.CheckConstraint(
            "(actor_type = 'SYSTEM' AND actor_user_id IS NULL) OR "
            "(actor_type = 'USER' AND actor_user_id IS NOT NULL)",
            name="ck_audit_log_actor_binding",
        ),
        sa.CheckConstraint(
            "action IN ("
            "'TICKET_CREATED', 'TICKET_UPDATED', 'COMMENT_CREATED', "
            "'ASSIGNMENT_CREATED', 'ASSIGNMENT_ACCEPTED', "
            "'ASSIGNMENT_REJECTED', 'ASSIGNMENT_COMPLETED', "
            "'ASSIGNMENT_SUPERSEDED', 'TICKET_COMPLETED', 'TICKET_CLOSED', "
            "'TICKET_REOPENED', 'USER_ROLES_CHANGED', "
            "'USER_STATUS_CHANGED', 'TEAM_MEMBER_CHANGED', "
            "'AUTO_ASSIGN_FAILED'"
            ")",
            name="ck_audit_log_action",
        ),
        sa.CheckConstraint(
            "entity_type IN ("
            "'TICKET', 'ASSIGNMENT', 'USER', 'USER_ROLE', "
            "'TEAM', 'TEAM_MEMBERSHIP'"
            ")",
            name="ck_audit_log_entity_type",
        ),
        sa.CheckConstraint(
            "outcome IN ('SUCCESS', 'FAILED')",
            name="ck_audit_log_outcome",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ticket_id"], ["ticket.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_log_entity_created_at",
        "audit_log",
        ["entity_type", "entity_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_audit_log_ticket_created_at",
        "audit_log",
        ["ticket_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_audit_log_actor_created_at",
        "audit_log",
        ["actor_user_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_audit_log_request_id", "audit_log", ["request_id"])

    op.create_table(
        "notification",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("recipient_id", sa.UUID(), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("assignment_id", sa.UUID(), nullable=False),
        sa.Column("notification_type", sa.String(length=50), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "notification_type IN ('ASSIGNMENT_RECEIVED')",
            name="ck_notification_type",
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignment.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recipient_id"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ticket_id"], ["ticket.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recipient_id",
            "assignment_id",
            "notification_type",
            name="uq_notification_recipient_assignment_type",
        ),
    )
    op.create_index(
        "ix_notification_recipient_created_at",
        "notification",
        ["recipient_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "idempotency_record",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("command_scope", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=128), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column(
            "response_body",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(length=50), nullable=True),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "response_status BETWEEN 100 AND 599",
            name="ck_idempotency_response_status",
        ),
        sa.CheckConstraint(
            "expires_at = created_at + INTERVAL '7 days'",
            name="ck_idempotency_expiry",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_user_id",
            "command_scope",
            "idempotency_key",
            name="uq_idempotency_actor_scope_key",
        ),
    )
    op.create_index(
        "ix_idempotency_record_expires_at",
        "idempotency_record",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_idempotency_record_expires_at",
        table_name="idempotency_record",
    )
    op.drop_table("idempotency_record")
    op.drop_index(
        "ix_notification_recipient_created_at",
        table_name="notification",
    )
    op.drop_table("notification")
    op.drop_index("ix_audit_log_request_id", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_ticket_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_entity_created_at", table_name="audit_log")
    op.drop_table("audit_log")
