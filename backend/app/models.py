import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, ClassVar, Literal

from pydantic import EmailStr, SecretStr, field_validator, model_validator
from sqlalchemy import BigInteger, CheckConstraint, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

# Fixed role codes. A user can hold several roles; permissions are the union.
ROLE_CODES = ("SUBMITTER", "DISPATCHER", "HANDLER", "ADMIN")
type RoleCode = Literal["SUBMITTER", "DISPATCHER", "HANDLER", "ADMIN"]

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
type TicketStatus = Literal[
    "PENDING_ASSIGNMENT",
    "ASSIGNED",
    "IN_PROGRESS",
    "PENDING_CONFIRMATION",
    "CLOSED",
]
type TicketAction = Literal[
    "EDIT",
    "DISPATCH",
    "COMMENT",
    "ACCEPT",
    "REJECT",
    "COMPLETE",
    "CLOSE",
    "REOPEN",
]

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
TIMELINE_EVENT_TYPES = (
    "TICKET_CREATED",
    "COMMENT_CREATED",
    "ASSIGNMENT_CREATED",
    "ASSIGNMENT_ACCEPTED",
    "ASSIGNMENT_REJECTED",
    "ASSIGNMENT_COMPLETED",
    "ASSIGNMENT_SUPERSEDED",
    "TICKET_COMPLETED",
    "TICKET_CLOSED",
    "TICKET_REOPENED",
)

type AuditActorType = Literal["USER", "SYSTEM"]
type AuditOutcome = Literal["SUCCESS", "FAILED"]
type AssignmentStrategyCode = Literal["MANUAL", "LEAST_OPEN_TICKET"]
type NotificationType = Literal["ASSIGNMENT_RECEIVED"]
type AuditAction = Literal[
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
]
type AuditEntityType = Literal[
    "TICKET",
    "ASSIGNMENT",
    "USER",
    "USER_ROLE",
    "TEAM",
    "TEAM_MEMBERSHIP",
]
type TimelineEventType = Literal[
    "TICKET_CREATED",
    "COMMENT_CREATED",
    "ASSIGNMENT_CREATED",
    "ASSIGNMENT_ACCEPTED",
    "ASSIGNMENT_REJECTED",
    "ASSIGNMENT_COMPLETED",
    "ASSIGNMENT_SUPERSEDED",
    "TICKET_COMPLETED",
    "TICKET_CLOSED",
    "TICKET_REOPENED",
]

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


class StrictRequestModel(SQLModel):
    """业务写请求不接受契约外字段，避免客户端误把服务端事实当作可写输入。"""

    model_config: ClassVar[Any] = {"extra": "forbid"}  # ClassVar 为类级配置


class UserSelfUpdateRequest(StrictRequestModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    expected_user_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_profile_change(self) -> UserSelfUpdateRequest:
        if self.email is None and self.full_name is None:
            raise ValueError("at least one profile field is required")
        return self


class UserAdminUpdateRequest(StrictRequestModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    password: SecretStr | None = None
    expected_user_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_admin_change(self) -> UserAdminUpdateRequest:
        if all(
            value is None
            for value in (
                self.email,
                self.full_name,
                self.is_active,
                self.password,
            )
        ):
            raise ValueError("at least one user field is required")
        return self


class RoleSetReplaceRequest(StrictRequestModel):
    roles: list[RoleCode] = Field(min_length=1)
    expected_user_version: int = Field(ge=1)


class UserCreateRequest(StrictRequestModel):
    email: EmailStr = Field(max_length=255)
    password: SecretStr = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    roles: list[RoleCode] = Field(min_length=1)


class TicketCreateRequest(StrictRequestModel):
    """"""
    team_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10000)

    @field_validator("title", "description")
    @classmethod
    def strip_business_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class TicketUpdateRequest(StrictRequestModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=10000)
    expected_version: int = Field(ge=1)

    @field_validator("title", "description")
    @classmethod
    def strip_optional_business_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @model_validator(mode="after")
    def require_body_change(self) -> TicketUpdateRequest:
        if self.title is None and self.description is None:
            raise ValueError("at least one of title or description is required")
        return self


class CommentCreateRequest(StrictRequestModel):
    body: str = Field(min_length=1, max_length=5000)
    expected_ticket_version: int = Field(ge=1)

    @field_validator("body")
    @classmethod
    def strip_comment_body(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


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


# 用户摘要不包含 is_superuser，最终权限事实只来自 UserRole。
class UserSummary(SQLModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None = None
    is_active: bool


class UserPublic(UserSummary):
    """用户公开信息，角色在每次请求时从数据库加载。"""

    roles: list[RoleCode]
    version: int
    created_at: datetime | None = None


class UserPage(SQLModel):
    items: list[UserPublic]
    next_cursor: str | None = None


class TeamSummary(SQLModel):
    id: uuid.UUID
    name: str


class AssignmentPublic(SQLModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    handler_id: uuid.UUID
    handler: UserSummary
    assigned_by_id: uuid.UUID
    assigned_by: UserSummary | None
    status: str
    dispatch_mode: str
    strategy_code: str
    strategy_version: str
    reason: str | None
    completion_note: str | None
    assigned_at: datetime
    responded_at: datetime | None
    finished_at: datetime | None
    version: int


class AssignmentPage(SQLModel):
    items: list[AssignmentPublic]
    next_cursor: str | None = None


class ActiveAssignmentResponse(SQLModel):
    ticket_id: uuid.UUID
    assignment: AssignmentPublic | None


class TicketSummaryPublic(SQLModel):
    id: uuid.UUID
    team_id: uuid.UUID
    team: TeamSummary
    submitter_id: uuid.UUID
    submitter: UserSummary
    title: str
    status: TicketStatus
    version: int
    created_at: datetime
    updated_at: datetime


class TicketDetailPublic(TicketSummaryPublic):
    description: str
    active_assignment: AssignmentPublic | None
    allowed_actions: list[TicketAction]


class TicketPage(SQLModel):
    items: list[TicketSummaryPublic]
    next_cursor: str | None = None


class CommentPublic(SQLModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    author: UserSummary
    body: str
    created_at: datetime


class CommentPage(SQLModel):
    items: list[CommentPublic]
    next_cursor: str | None = None


class StateSnapshot(SQLModel):
    status: TicketStatus
    version: int


class AuditDetail(SQLModel):
    """审计公开详情只允许契约列出的受控字段，避免 JSONB 透传敏感内容。"""

    changed_fields: list[str] | None = None
    previous_status: TicketStatus | None = None
    next_status: TicketStatus | None = None
    strategy_code: AssignmentStrategyCode | None = None
    strategy_version: str | None = None
    candidate_count: int | None = None
    selected_handler_id: uuid.UUID | None = None
    role_codes: list[RoleCode] | None = None
    note: str | None = None


class TimelineMetadata(SQLModel):
    """业务时间线只展示状态、派发定位和受控说明，不复用原始审计 detail。"""

    previous_status: TicketStatus | None = None
    next_status: TicketStatus | None = None
    assignment_id: uuid.UUID | None = None
    handler_id: uuid.UUID | None = None
    strategy_code: AssignmentStrategyCode | None = None
    note: str | None = None


class AuditLogPublic(SQLModel):
    id: int
    actor: UserSummary | None
    actor_type: AuditActorType
    action: AuditAction
    entity_type: AuditEntityType
    entity_id: uuid.UUID | None
    entity_key: dict[str, str] | None
    ticket_id: uuid.UUID | None
    before_state: StateSnapshot | None
    after_state: StateSnapshot | None
    outcome: AuditOutcome
    error_code: str | None
    request_id: uuid.UUID
    created_at: datetime
    detail: AuditDetail


class AuditLogPage(SQLModel):
    items: list[AuditLogPublic]
    next_cursor: str | None = None


class TimelineEventPublic(SQLModel):
    id: int
    event_type: TimelineEventType
    actor: UserSummary | None
    ticket_id: uuid.UUID
    summary: str
    occurred_at: datetime
    event_metadata: TimelineMetadata = Field(serialization_alias="metadata")


class TimelineEventPage(SQLModel):
    items: list[TimelineEventPublic]
    next_cursor: str | None = None


class NotificationPublic(SQLModel):
    """通知公开模型不包含 recipient_id、payload 或下一版预留的 read_at。"""

    id: uuid.UUID
    notification_type: NotificationType
    ticket_id: uuid.UUID
    assignment_id: uuid.UUID
    title: str
    message: str
    created_at: datetime


class NotificationPage(SQLModel):
    items: list[NotificationPublic]
    next_cursor: str | None = None


class DispatchCandidatePublic(SQLModel):
    """候选预览展示处理人资格与负载，不替代正式派发时的锁内重算。"""

    handler_id: uuid.UUID
    handler: UserSummary
    open_ticket_count: int
    last_assigned_at: datetime | None
    rank: int


class DispatchCandidateListResponse(SQLModel):
    ticket_id: uuid.UUID
    team_id: uuid.UUID
    items: list[DispatchCandidatePublic]
    candidate_count: int


class ManualDispatchRequest(StrictRequestModel):
    mode: Literal["MANUAL"]
    handler_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=1000)
    expected_ticket_version: int = Field(ge=1)
    expected_assignment_id: uuid.UUID | None = None
    expected_assignment_version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class AutoDispatchRequest(StrictRequestModel):
    mode: Literal["AUTO"]
    strategy: Literal["LEAST_OPEN_TICKET"]
    reason: str | None = Field(default=None, max_length=1000)
    expected_ticket_version: int = Field(ge=1)
    expected_assignment_id: uuid.UUID | None = None
    expected_assignment_version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def strip_auto_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


type DispatchRequest = Annotated[
    ManualDispatchRequest | AutoDispatchRequest,
    Field(discriminator="mode"),
]


class AcceptAssignmentRequest(StrictRequestModel):
    expected_ticket_version: int = Field(ge=1)
    expected_assignment_version: int = Field(ge=1)


class RejectAssignmentRequest(StrictRequestModel):
    reason: str = Field(min_length=1, max_length=1000)
    expected_ticket_version: int = Field(ge=1)
    expected_assignment_version: int = Field(ge=1)

    @field_validator("reason")
    @classmethod
    def strip_rejection_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class CompleteAssignmentRequest(StrictRequestModel):
    completion_note: str = Field(min_length=1, max_length=5000)
    expected_ticket_version: int = Field(ge=1)
    expected_assignment_version: int = Field(ge=1)

    @field_validator("completion_note")
    @classmethod
    def strip_completion_note(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class CloseTicketRequest(StrictRequestModel):
    resolution_note: str | None = Field(default=None, max_length=5000)
    expected_ticket_version: int = Field(ge=1)

    @field_validator("resolution_note")
    @classmethod
    def strip_resolution_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class ReopenTicketRequest(StrictRequestModel):
    reason: str = Field(min_length=1, max_length=1000)
    expected_ticket_version: int = Field(ge=1)

    @field_validator("reason")
    @classmethod
    def strip_reopen_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class TicketStatePublic(SQLModel):
    id: uuid.UUID
    status: TicketStatus
    version: int
    updated_at: datetime


class CandidateRankingEntry(SQLModel):
    rank: int
    handler_id: uuid.UUID
    open_ticket_count: int
    last_assigned_at: datetime | None
    selected: bool


class DispatchExplanation(SQLModel):
    candidate_count: int
    selected_handler_id: uuid.UUID
    selected_open_ticket_count: int
    ranked_candidates: list[CandidateRankingEntry]


class DispatchResponse(SQLModel):
    ticket: TicketStatePublic
    assignment: AssignmentPublic
    superseded_assignment_id: uuid.UUID | None
    explanation: DispatchExplanation


class TicketMutationResponse(SQLModel):
    ticket: TicketStatePublic
    changed_assignment: AssignmentPublic | None
    superseded_assignment_id: uuid.UUID | None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


class TeamPublic(SQLModel):
    """Team 的稳定公开表示，version 用于后续成员和启停的乐观锁。"""

    id: uuid.UUID
    name: str
    is_active: bool
    version: int
    created_at: datetime


class TeamPage(SQLModel):
    """Team 查询使用 opaque cursor，避免偏移分页在数据变化时跳过记录。"""

    items: list[TeamPublic]
    next_cursor: str | None = None


class TeamCreateRequest(StrictRequestModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def strip_team_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class TeamUpdateRequest(StrictRequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None
    expected_version: int = Field(ge=1)

    @field_validator("name")
    @classmethod
    def strip_optional_team_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @model_validator(mode="after")
    def require_team_change(self) -> TeamUpdateRequest:
        if self.name is None and self.is_active is None:
            raise ValueError("at least one team field is required")
        return self


class TeamMembershipPublic(SQLModel):
    id: uuid.UUID
    user: UserSummary
    is_available: bool
    last_assigned_at: datetime | None
    joined_at: datetime


class TeamMembershipPage(SQLModel):
    team_id: uuid.UUID
    team_version: int
    items: list[TeamMembershipPublic]
    next_cursor: str | None = None


class TeamMembershipUpsertRequest(StrictRequestModel):
    is_available: bool
    expected_team_version: int = Field(ge=1)


class TeamMembershipMutationResponse(SQLModel):
    membership: TeamMembershipPublic | None
    removed_user_id: uuid.UUID | None
    team_version: int


class ErrorDetail(SQLModel):
    """统一错误中的稳定业务码、可展示消息和请求追踪 ID。"""

    code: str
    message: str
    request_id: uuid.UUID
    details: dict[str, Any] | None = None


class ErrorResponse(SQLModel):
    error: ErrorDetail


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
    """记录关键写操作、状态变化和可预期失败；数据库 Trigger 保证记录不可变。"""

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
