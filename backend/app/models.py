import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import EmailStr
from sqlalchemy import BigInteger, CheckConstraint, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

# Fixed role codes. A user can hold several roles; permissions are the union.
ROLE_CODES = ("SUBMITTER", "DISPATCHER", "HANDLER", "ADMIN")

# 工单生命周期：
# PENDING_ASSIGNMENT -> ASSIGNED -> IN_PROGRESS -> PENDING_CONFIRMATION -> CLOSED
# 拒绝后由 ASSIGNED 回到 PENDING_ASSIGNMENT；重新派发保持 ASSIGNED；
# 已关闭工单重新打开后回到 PENDING_ASSIGNMENT。
TICKET_STATUSES = (
    "PENDING_ASSIGNMENT",
    "ASSIGNED",
    "IN_PROGRESS",
    "PENDING_CONFIRMATION",
    "CLOSED",
)

# 派发记录生命周期。只有 ASSIGNED 和 ACCEPTED 属于活动状态，并通过部分唯一索引
# 保证同一工单最多一条活动记录。REJECTED 和 SUPERSEDED 必须填写原因；
# COMPLETED 必须填写完成说明和完成时间。
ASSIGNMENT_STATUSES = (
    "ASSIGNED",
    "ACCEPTED",
    "REJECTED",
    "COMPLETED",
    "SUPERSEDED",
)

# MANUAL 表示由派单员指定处理人；AUTO 表示系统根据记录的策略选择合格处理人。
DISPATCH_MODES = ("MANUAL", "AUTO")

# 人工派发记录为 MANUAL；当前自动策略从合格候选中选择活动工单最少的处理人。
ASSIGNMENT_STRATEGY_CODES = ("MANUAL", "LEAST_OPEN_TICKET")

# 审计操作、实体和结果只允许使用契约中约定的稳定代码，避免后续查询
# 因大小写或临时文案不同而无法聚合。
AUDIT_ACTOR_TYPES = ("USER", "SYSTEM")
AUDIT_OUTCOMES = ("SUCCESS", "FAILED")
AUDIT_ACTIONS = (
    "TICKET_CREATED",
    "TICKET_UPDATED",
    "COMMENT_CREATED",
    "ASSIGNMENT_CREATED",
    "ASSIGNMENT_ACCEPTED",
    "ASSIGNMENT_REJECTED",
    "ASSIGNMENT_COMPLETED",
    "ASSIGNMENT_SUPERSEDED",
    "TICKET_COMPLETED",
    "TICKET_CLOSED",
    "TICKET_REOPENED",
    "USER_ROLES_CHANGED",
    "USER_STATUS_CHANGED",
    "TEAM_MEMBER_CHANGED",
    "AUTO_ASSIGN_FAILED",
)
AUDIT_ENTITY_TYPES = (
    "TICKET",
    "ASSIGNMENT",
    "USER",
    "USER_ROLE",
    "TEAM",
    "TEAM_MEMBERSHIP",
)
NOTIFICATION_TYPES = ("ASSIGNMENT_RECEIVED",)

# 幂等记录只覆盖短期网络重试和重复点击，不承担永久业务去重。
IDEMPOTENCY_RETENTION = timedelta(days=7)


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    version: int = Field(default=1, nullable=False, sa_column_kwargs={"server_default": text("1")})
    created_at: datetime | None = Field(default_factory=get_datetime_utc)
    items: list[Item] = Relationship(back_populates="owner", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Fixed role binding: one row per (user, role). UUID primary key keeps the
# audit log able to address a single binding without relying on a composite key.
class UserRole(SQLModel, table=True):
    __tablename__ = "user_role"  # pyright: ignore[reportAssignmentType]

    __table_args__ = (
        UniqueConstraint(
            "user_id", "role_code", name="uq_user_role_user_id_role_code"
        ),
        CheckConstraint(
            "role_code IN ('SUBMITTER', 'DISPATCHER', 'HANDLER', 'ADMIN')",
            name="ck_user_role_role_code",
        ),
        Index("ix_user_role_role_code_user_id", "role_code", "user_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    role_code: str = Field(max_length=20, nullable=False)
    granted_at: datetime = Field(default_factory=get_datetime_utc, nullable=False)


# PRD "Queue" is mapped 1:1 to Team; a Team is the dispatch pool.
# Only active teams reserve a name, so a retired pool can be recreated by name.
class Team(SQLModel, table=True):
    __table_args__ = (
        Index(
            "uq_team_name_active",
            "name",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=100, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    version: int = Field(default=1, nullable=False)
    created_at: datetime = Field(default_factory=get_datetime_utc, nullable=False)


# A Handler's membership in a Team: eligibility, availability and the
# denormalised last_assigned_at used by the deterministic dispatch ranking.
class TeamMembership(SQLModel, table=True):
    __tablename__ = "team_membership"  # pyright: ignore[reportAssignmentType]

    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_membership_team_user"),
        Index("ix_team_membership_team_available", "team_id", "is_available"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    team_id: uuid.UUID = Field(
        foreign_key="team.id", nullable=False, ondelete="CASCADE"
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    is_available: bool = Field(default=True, nullable=False)
    last_assigned_at: datetime | None = Field(default=None, nullable=True)
    joined_at: datetime = Field(default_factory=get_datetime_utc, nullable=False)


# The current handler is derived from the active Assignment. Keeping an
# assignee_id here would create two competing sources of truth.
class Ticket(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'PENDING_ASSIGNMENT', 'ASSIGNED', 'IN_PROGRESS', "
            "'PENDING_CONFIRMATION', 'CLOSED'"
            ")",
            name="ck_ticket_status",
        ),
        CheckConstraint(
            "char_length(btrim(title)) BETWEEN 1 AND 200",
            name="ck_ticket_title_length",
        ),
        CheckConstraint(
            "char_length(btrim(description)) BETWEEN 1 AND 10000",
            name="ck_ticket_description_length",
        ),
        Index(
            "ix_ticket_team_status_updated_id",
            "team_id",
            "status",
            text("updated_at DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_ticket_submitter_updated_id",
            "submitter_id",
            text("updated_at DESC"),
            text("id DESC"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    team_id: uuid.UUID = Field(
        foreign_key="team.id", nullable=False, ondelete="RESTRICT"
    )
    submitter_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="RESTRICT"
    )
    title: str = Field(max_length=200, nullable=False)
    description: str = Field(sa_type=Text, nullable=False)
    status: str = Field(default="PENDING_ASSIGNMENT", max_length=30, nullable=False)
    version: int = Field(
        default=1,
        nullable=False,
        sa_column_kwargs={"server_default": text("1")},
    )
    created_at: datetime = Field(default_factory=get_datetime_utc, nullable=False)
    updated_at: datetime = Field(default_factory=get_datetime_utc, nullable=False)


# Assignments are append-only dispatch history. A partial unique index below
# ensures that only one ASSIGNED/ACCEPTED record can be active for a ticket.
class Assignment(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'ASSIGNED', 'ACCEPTED', 'REJECTED', 'COMPLETED', 'SUPERSEDED'"
            ")",
            name="ck_assignment_status",
        ),
        CheckConstraint(
            "dispatch_mode IN ('MANUAL', 'AUTO')",
            name="ck_assignment_dispatch_mode",
        ),
        CheckConstraint(
            "strategy_code IN ('MANUAL', 'LEAST_OPEN_TICKET')",
            name="ck_assignment_strategy_code",
        ),
        CheckConstraint(
            "status NOT IN ('REJECTED', 'SUPERSEDED') OR "
            "(reason IS NOT NULL AND "
            "char_length(btrim(reason)) BETWEEN 1 AND 1000)",
            name="ck_assignment_terminal_reason",
        ),
        CheckConstraint(
            "status <> 'COMPLETED' OR "
            "(completion_note IS NOT NULL AND "
            "char_length(btrim(completion_note)) BETWEEN 1 AND 5000 "
            "AND finished_at IS NOT NULL)",
            name="ck_assignment_completed_fields",
        ),
        Index(
            "uq_assignment_ticket_active",
            "ticket_id",
            unique=True,
            postgresql_where=text("status IN ('ASSIGNED', 'ACCEPTED')"),
        ),
        Index(
            "ix_assignment_ticket_assigned_at",
            "ticket_id",
            text("assigned_at DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_assignment_handler_status_assigned_at",
            "handler_id",
            "status",
            text("assigned_at DESC"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    ticket_id: uuid.UUID = Field(
        foreign_key="ticket.id", nullable=False, ondelete="RESTRICT"
    )
    handler_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="RESTRICT"
    )
    assigned_by_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="RESTRICT"
    )
    status: str = Field(default="ASSIGNED", max_length=20, nullable=False)
    dispatch_mode: str = Field(max_length=10, nullable=False)
    strategy_code: str = Field(max_length=30, nullable=False)
    strategy_version: str = Field(max_length=20, nullable=False)
    selection_summary: dict[str, Any] | None = Field(
        default=None, nullable=True, sa_type=JSONB
    )
    reason: str | None = Field(default=None, sa_type=Text, nullable=True)
    completion_note: str | None = Field(default=None, sa_type=Text, nullable=True)
    assigned_at: datetime = Field(default_factory=get_datetime_utc, nullable=False)
    responded_at: datetime | None = Field(default=None, nullable=True)
    finished_at: datetime | None = Field(default=None, nullable=True)
    version: int = Field(
        default=1,
        nullable=False,
        sa_column_kwargs={"server_default": text("1")},
    )


# Comments are immutable in the MVP: no edit or delete API will be added.
class Comment(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(body)) BETWEEN 1 AND 5000",
            name="ck_comment_body",
        ),
        Index("ix_comment_ticket_created_id", "ticket_id", "created_at", "id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    ticket_id: uuid.UUID = Field(
        foreign_key="ticket.id", nullable=False, ondelete="RESTRICT"
    )
    author_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="RESTRICT"
    )
    body: str = Field(sa_type=Text, nullable=False)
    created_at: datetime = Field(default_factory=get_datetime_utc, nullable=False)


class AuditLog(SQLModel, table=True):
    """记录关键写操作、状态变化和可预期失败，供审计与业务时间线使用。"""

    __tablename__ = "audit_log"  # pyright: ignore[reportAssignmentType]

    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('USER', 'SYSTEM')",
            name="ck_audit_log_actor_type",
        ),
        CheckConstraint(
            "(actor_type = 'SYSTEM' AND actor_user_id IS NULL) OR "
            "(actor_type = 'USER' AND actor_user_id IS NOT NULL)",
            name="ck_audit_log_actor_binding",
        ),
        CheckConstraint(
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
        CheckConstraint(
            "entity_type IN ("
            "'TICKET', 'ASSIGNMENT', 'USER', 'USER_ROLE', "
            "'TEAM', 'TEAM_MEMBERSHIP'"
            ")",
            name="ck_audit_log_entity_type",
        ),
        CheckConstraint(
            "outcome IN ('SUCCESS', 'FAILED')",
            name="ck_audit_log_outcome",
        ),
        Index(
            "ix_audit_log_entity_created_at",
            "entity_type",
            "entity_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_audit_log_ticket_created_at",
            "ticket_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_audit_log_actor_created_at",
            "actor_user_id",
            text("created_at DESC"),
        ),
        Index("ix_audit_log_request_id", "request_id"),
    )

    # BIGINT IDENTITY 保证审计记录按写入顺序递增，不受 UUID 随机排序影响。
    id: int | None = Field(
        default=None,
        primary_key=True,
        sa_type=BigInteger,
    )
    actor_user_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="user.id",
        nullable=True,
        ondelete="RESTRICT",
    )
    actor_type: str = Field(max_length=20, nullable=False)
    action: str = Field(max_length=50, nullable=False)
    entity_type: str = Field(max_length=30, nullable=False)
    entity_id: uuid.UUID | None = Field(default=None, nullable=True)
    # 复合实体可能没有单一主键，使用稳定业务键保留可查询定位信息。
    entity_key: dict[str, str] | None = Field(
        default=None,
        nullable=True,
        sa_type=JSONB,
    )
    ticket_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="ticket.id",
        nullable=True,
        ondelete="RESTRICT",
    )
    before_state: dict[str, Any] | None = Field(
        default=None,
        nullable=True,
        sa_type=JSONB,
    )
    after_state: dict[str, Any] | None = Field(
        default=None,
        nullable=True,
        sa_type=JSONB,
    )
    outcome: str = Field(max_length=20, nullable=False)
    error_code: str | None = Field(default=None, max_length=100, nullable=True)
    request_id: uuid.UUID = Field(nullable=False)
    idempotency_key: str | None = Field(default=None, max_length=255, nullable=True)
    # detail 使用受控字段集合，业务服务不得把完整请求体或凭证写入这里。
    detail: dict[str, Any] = Field(
        default_factory=dict,
        nullable=False,
        sa_type=JSONB,
        sa_column_kwargs={"server_default": text("'{}'::jsonb")},
    )
    created_at: datetime = Field(default_factory=get_datetime_utc, nullable=False)


class Notification(SQLModel, table=True):
    """保存站内派发通知；MVP 不提供已读写入或外部投递。"""

    __table_args__ = (
        UniqueConstraint(
            "recipient_id",
            "assignment_id",
            "notification_type",
            name="uq_notification_recipient_assignment_type",
        ),
        CheckConstraint(
            "notification_type IN ('ASSIGNMENT_RECEIVED')",
            name="ck_notification_type",
        ),
        Index(
            "ix_notification_recipient_created_at",
            "recipient_id",
            text("created_at DESC"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    recipient_id: uuid.UUID = Field(
        foreign_key="user.id",
        nullable=False,
        ondelete="RESTRICT",
    )
    ticket_id: uuid.UUID = Field(
        foreign_key="ticket.id",
        nullable=False,
        ondelete="RESTRICT",
    )
    assignment_id: uuid.UUID = Field(
        foreign_key="assignment.id",
        nullable=False,
        ondelete="RESTRICT",
    )
    notification_type: str = Field(max_length=50, nullable=False)
    payload: dict[str, Any] = Field(nullable=False, sa_type=JSONB)
    created_at: datetime = Field(default_factory=get_datetime_utc, nullable=False)
    # 该字段为后续通知中心预留；MVP 保持为空且不暴露公开响应。
    read_at: datetime | None = Field(default=None, nullable=True)


class IdempotencyRecord(SQLModel, table=True):
    """保存短期幂等结果，使同键同载荷的重试返回首次响应。"""

    __tablename__ = "idempotency_record"  # pyright: ignore[reportAssignmentType]

    __table_args__ = (
        UniqueConstraint(
            "actor_user_id",
            "command_scope",
            "idempotency_key",
            name="uq_idempotency_actor_scope_key",
        ),
        CheckConstraint(
            "response_status BETWEEN 100 AND 599",
            name="ck_idempotency_response_status",
        ),
        CheckConstraint(
            "expires_at = created_at + INTERVAL '7 days'",
            name="ck_idempotency_expiry",
        ),
        Index("ix_idempotency_record_expires_at", "expires_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    actor_user_id: uuid.UUID = Field(
        foreign_key="user.id",
        nullable=False,
        ondelete="RESTRICT",
    )
    command_scope: str = Field(max_length=100, nullable=False)
    idempotency_key: str = Field(max_length=255, nullable=False)
    request_hash: str = Field(max_length=128, nullable=False)
    response_status: int = Field(nullable=False)
    response_body: dict[str, Any] = Field(nullable=False, sa_type=JSONB)
    resource_type: str | None = Field(default=None, max_length=50, nullable=True)
    resource_id: uuid.UUID | None = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=get_datetime_utc, nullable=False)
    expires_at: datetime = Field(nullable=False)


# Shared properties
class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(default_factory=get_datetime_utc)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
