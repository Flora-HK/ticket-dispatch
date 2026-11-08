import uuid
from datetime import UTC, datetime

from pydantic import EmailStr
from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text
from sqlmodel import Field, Relationship, SQLModel

# Fixed role codes. A user can hold several roles; permissions are the union.
ROLE_CODES = ("SUBMITTER", "DISPATCHER", "HANDLER", "ADMIN")


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
    __tablename__ = "user_role" # type: ignore

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
    __tablename__ = "team_membership" #type: ignore

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
