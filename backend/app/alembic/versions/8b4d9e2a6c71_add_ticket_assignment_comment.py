"""add ticket assignment comment tables

Revision ID: 8b4d9e2a6c71
Revises: 3c1a7f9e2b64
Create Date: 2026-11-08 17:00:00.000000

DM2 of the ticket dispatch plan. Business history is protected with RESTRICT
foreign keys, terminal-state checks and a partial unique index for the single
active assignment.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "8b4d9e2a6c71"
down_revision = "3c1a7f9e2b64"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticket",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("team_id", sa.UUID(), nullable=False),
        sa.Column("submitter_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ("
            "'PENDING_ASSIGNMENT', 'ASSIGNED', 'IN_PROGRESS', "
            "'PENDING_CONFIRMATION', 'CLOSED'"
            ")",
            name="ck_ticket_status",
        ),
        sa.CheckConstraint(
            "char_length(btrim(title)) BETWEEN 1 AND 200",
            name="ck_ticket_title_length",
        ),
        sa.CheckConstraint(
            "char_length(btrim(description)) BETWEEN 1 AND 10000",
            name="ck_ticket_description_length",
        ),
        sa.ForeignKeyConstraint(["submitter_id"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ticket_team_status_updated_id",
        "ticket",
        [
            "team_id",
            "status",
            sa.text("updated_at DESC"),
            sa.text("id DESC"),
        ],
    )
    op.create_index(
        "ix_ticket_submitter_updated_id",
        "ticket",
        ["submitter_id", sa.text("updated_at DESC"), sa.text("id DESC")],
    )

    op.create_table(
        "assignment",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("handler_id", sa.UUID(), nullable=False),
        sa.Column("assigned_by_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("dispatch_mode", sa.String(length=10), nullable=False),
        sa.Column("strategy_code", sa.String(length=30), nullable=False),
        sa.Column("strategy_version", sa.String(length=20), nullable=False),
        sa.Column(
            "selection_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("completion_note", sa.Text(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ("
            "'ASSIGNED', 'ACCEPTED', 'REJECTED', 'COMPLETED', 'SUPERSEDED'"
            ")",
            name="ck_assignment_status",
        ),
        sa.CheckConstraint(
            "dispatch_mode IN ('MANUAL', 'AUTO')",
            name="ck_assignment_dispatch_mode",
        ),
        sa.CheckConstraint(
            "strategy_code IN ('MANUAL', 'LEAST_OPEN_TICKET')",
            name="ck_assignment_strategy_code",
        ),
        sa.CheckConstraint(
            "status NOT IN ('REJECTED', 'SUPERSEDED') OR "
            "(reason IS NOT NULL AND "
            "char_length(btrim(reason)) BETWEEN 1 AND 1000)",
            name="ck_assignment_terminal_reason",
        ),
        sa.CheckConstraint(
            "status <> 'COMPLETED' OR "
            "(completion_note IS NOT NULL AND "
            "char_length(btrim(completion_note)) BETWEEN 1 AND 5000 "
            "AND finished_at IS NOT NULL)",
            name="ck_assignment_completed_fields",
        ),
        sa.ForeignKeyConstraint(["assigned_by_id"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["handler_id"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ticket_id"], ["ticket.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_assignment_ticket_active",
        "assignment",
        ["ticket_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('ASSIGNED', 'ACCEPTED')"),
    )
    op.create_index(
        "ix_assignment_ticket_assigned_at",
        "assignment",
        ["ticket_id", sa.text("assigned_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_assignment_handler_status_assigned_at",
        "assignment",
        ["handler_id", "status", sa.text("assigned_at DESC")],
    )

    op.create_table(
        "comment",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(btrim(body)) BETWEEN 1 AND 5000",
            name="ck_comment_body",
        ),
        sa.ForeignKeyConstraint(["author_id"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ticket_id"], ["ticket.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_comment_ticket_created_id", "comment", ["ticket_id", "created_at", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_comment_ticket_created_id", table_name="comment")
    op.drop_table("comment")
    op.drop_index("ix_assignment_handler_status_assigned_at", table_name="assignment")
    op.drop_index("ix_assignment_ticket_assigned_at", table_name="assignment")
    op.drop_index("uq_assignment_ticket_active", table_name="assignment")
    op.drop_table("assignment")
    op.drop_index("ix_ticket_submitter_updated_id", table_name="ticket")
    op.drop_index("ix_ticket_team_status_updated_id", table_name="ticket")
    op.drop_table("ticket")
