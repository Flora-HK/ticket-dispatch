import uuid
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session, select

from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.core.errors import APIError
from app.models import ROLE_CODES, TokenPayload, User, UserRole

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token",
    auto_error=False,
)


def get_db() -> Generator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str | None, Depends(reusable_oauth2)]


@dataclass(frozen=True, slots=True)
class ActorContext:
    """一次请求的认证上下文；角色只来自数据库，不信任 JWT 内权限。"""

    user: User
    roles: frozenset[str]
    request_id: str

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    def has_any_role(self, required_roles: tuple[str, ...]) -> bool:
        return bool(self.roles.intersection(required_roles))


def get_current_actor(
    request: Request,
    session: SessionDep,
    token: TokenDep,
) -> ActorContext:
    """解析 JWT、加载用户和最新角色，并返回统一的 ActorContext。"""

    if not token:
        raise APIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTH_REQUIRED",
            message="Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[security.ALGORITHM],
        )
        token_data = TokenPayload(**payload)
        if token_data.sub is None:
            raise ValueError("missing token subject")
        user_id = uuid.UUID(token_data.sub)
    except (InvalidTokenError, ValidationError, TypeError, ValueError):
        raise APIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_TOKEN",
            message="The access token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = session.get(User, user_id)
    if user is None:
        raise APIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_TOKEN",
            message="The access token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="INACTIVE_USER",
            message="The user account is inactive.",
        )

    stored_roles = set(
        session.exec(
            select(UserRole.role_code).where(UserRole.user_id == user.id)
        ).all()
    )
    ordered_roles = tuple(role for role in ROLE_CODES if role in stored_roles)
    return ActorContext(
        user=user,
        roles=frozenset(ordered_roles),
        request_id=str(getattr(request.state, "request_id", uuid.uuid4())),
    )


CurrentActor = Annotated[ActorContext, Depends(get_current_actor)]


def get_current_user(current_actor: CurrentActor) -> User:
    """兼容现有路由签名；认证和角色加载已经由 ActorContext 完成。"""

    return current_actor.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*required_roles: str) -> Callable[[ActorContext], ActorContext]:
    """生成粗粒度角色门禁；多角色用户只要命中任一要求即可通过。"""

    def dependency(current_actor: CurrentActor) -> ActorContext:
        if not current_actor.has_any_role(required_roles):
            raise APIError(
                status_code=status.HTTP_403_FORBIDDEN,
                code="ROLE_REQUIRED",
                message="The user does not have the required role.",
            )
        return current_actor

    return dependency


def get_current_admin(current_actor: CurrentActor) -> User:
    """ADMIN 是账号、Team 和审计管理门禁的唯一权限来源。"""

    if "ADMIN" not in current_actor.roles:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="ROLE_REQUIRED",
            message="The ADMIN role is required.",
        )
    return current_actor.user


CurrentAdmin = Annotated[User, Depends(get_current_admin)]


def get_current_active_superuser(current_actor: CurrentActor) -> User:
    """兼容模板旧名称；实际门禁已切换为 ADMIN 数据库角色。"""

    return get_current_admin(current_actor)
