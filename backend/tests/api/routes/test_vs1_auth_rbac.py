"""VS1 认证与角色最小闭环验收。"""

import uuid
from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.api.deps import ActorContext, require_roles
from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.core.seed import (
    VS1_DEMO_PASSWORD,
    VS1_DISPATCHER_EMAIL,
    VS1_HANDLER_EMAILS,
    VS1_SUBMITTER_EMAIL,
    VS1_TEAM_NAME,
    seed_vs1_demo_data,
)
from app.models import Item, Team, TeamMembership, User, UserRole

pytestmark = pytest.mark.usefixtures("vs1_seeded_db")


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.parametrize(
    ("email", "password", "role"),
    (
        (
            str(settings.FIRST_SUPERUSER),
            settings.FIRST_SUPERUSER_PASSWORD,
            "ADMIN",
        ),
        (VS1_SUBMITTER_EMAIL, VS1_DEMO_PASSWORD, "SUBMITTER"),
        (VS1_DISPATCHER_EMAIL, VS1_DEMO_PASSWORD, "DISPATCHER"),
        (VS1_HANDLER_EMAILS[0], VS1_DEMO_PASSWORD, "HANDLER"),
    ),
)
def test_vs1_four_roles_login_and_read_me(
    client: TestClient,
    email: str,
    password: str,
    role: str,
) -> None:
    headers = _login(client, email, password)
    response = client.get(f"{settings.API_V1_STR}/users/me", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == email
    assert role in payload["roles"]
    assert payload["version"] == 1
    assert "is_superuser" not in payload


def test_vs1_missing_and_invalid_tokens_return_401(
    client: TestClient,
) -> None:
    missing = client.get(f"{settings.API_V1_STR}/users/me")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "AUTH_REQUIRED"
    assert missing.headers["X-Request-ID"] == missing.json()["error"]["request_id"]

    invalid = client.get(
        f"{settings.API_V1_STR}/users/me",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "INVALID_TOKEN"


def test_vs1_expired_token_returns_401(
    client: TestClient,
) -> None:
    with Session(engine) as session:
        user = crud.get_user_by_email(session=session, email=VS1_SUBMITTER_EMAIL)
        assert user is not None
        token = security.create_access_token(
            user.id,
            expires_delta=timedelta(seconds=-1),
        )

    response = client.get(
        f"{settings.API_V1_STR}/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_vs1_inactive_user_is_denied_before_write(
    client: TestClient,
) -> None:
    headers = _login(client, VS1_SUBMITTER_EMAIL, VS1_DEMO_PASSWORD)
    with Session(engine) as session:
        user = crud.get_user_by_email(session=session, email=VS1_SUBMITTER_EMAIL)
        assert user is not None
        user.is_active = False
        session.add(user)
        session.commit()
        before_count = len(session.exec(select(Item)).all())

    response = client.post(
        f"{settings.API_V1_STR}/items/",
        headers=headers,
        json={"title": "不应创建", "description": "停用用户写入"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INACTIVE_USER"

    with Session(engine) as session:
        assert len(session.exec(select(Item)).all()) == before_count
        user = crud.get_user_by_email(session=session, email=VS1_SUBMITTER_EMAIL)
        assert user is not None
        user.is_active = True
        session.add(user)
        session.commit()


def test_vs1_roles_are_not_in_jwt_and_refresh_from_database(
    client: TestClient,
) -> None:
    headers = _login(client, VS1_HANDLER_EMAILS[0], VS1_DEMO_PASSWORD)
    token = headers["Authorization"].removeprefix("Bearer ")
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[security.ALGORITHM])
    assert set(payload) == {"exp", "sub"}

    denied = client.get(f"{settings.API_V1_STR}/users", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ROLE_REQUIRED"

    with Session(engine) as session:
        user = crud.get_user_by_email(session=session, email=VS1_HANDLER_EMAILS[0])
        assert user is not None
        crud.ensure_user_role(session=session, user_id=user.id, role_code="ADMIN")

    # 同一个 JWT 不重新登录；下一次请求从数据库读取新增 ADMIN 角色。
    allowed = client.get(f"{settings.API_V1_STR}/users", headers=headers)
    assert allowed.status_code == 200
    me = client.get(f"{settings.API_V1_STR}/users/me", headers=headers)
    assert set(me.json()["roles"]) == {"ADMIN", "HANDLER"}

    with Session(engine) as session:
        user = crud.get_user_by_email(session=session, email=VS1_HANDLER_EMAILS[0])
        assert user is not None
        admin_role = crud.get_user_role(session=session, user_id=user.id, role_code="ADMIN")
        assert admin_role is not None
        session.delete(admin_role)
        session.commit()


def test_vs1_require_roles_uses_union_of_multiple_roles() -> None:
    with Session(engine) as session:
        user = crud.get_user_by_email(session=session, email=VS1_HANDLER_EMAILS[0])
        assert user is not None
        actor = ActorContext(
            user=user,
            roles=frozenset({"HANDLER", "DISPATCHER"}),
            request_id=str(uuid.uuid4()),
        )
    dependency = require_roles("DISPATCHER", "ADMIN")
    assert dependency(actor) is actor


def test_vs1_seed_data_is_idempotent() -> None:
    demo_emails = (
        VS1_SUBMITTER_EMAIL,
        VS1_DISPATCHER_EMAIL,
        *VS1_HANDLER_EMAILS,
    )
    with Session(engine) as session:
        seed_vs1_demo_data(session)
        seed_vs1_demo_data(session)

        users = session.exec(select(User).where(User.email.in_(demo_emails))).all()
        assert len(users) == 4
        assert len(session.exec(select(UserRole)).all()) == 5
        assert len(
            session.exec(select(Team).where(Team.name == VS1_TEAM_NAME)).all()
        ) == 1
        assert len(session.exec(select(TeamMembership)).all()) == 2


def test_vs1_public_registration_is_disabled(
    client: TestClient,
) -> None:
    signup = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={
            "email": "public@example.com",
            "password": "password123",
            "full_name": "Public User",
        },
    )
    assert signup.status_code == 404
    assert signup.json()["error"]["code"] == "REGISTRATION_DISABLED"

    private = client.post(
        f"{settings.API_V1_STR}/private/users/",
        json={
            "email": "private@example.com",
            "password": "password123",
            "full_name": "Private User",
        },
    )
    assert private.status_code == 404


def test_vs1_team_visibility_and_admin_only_inactive_filter(
    client: TestClient,
) -> None:
    submitter_headers = _login(client, VS1_SUBMITTER_EMAIL, VS1_DEMO_PASSWORD)
    active = client.get(f"{settings.API_V1_STR}/teams", headers=submitter_headers)
    assert active.status_code == 200
    assert active.json()["items"][0]["name"] == VS1_TEAM_NAME

    with Session(engine) as session:
        inactive = Team(name="已停用团队", is_active=False)
        session.add(inactive)
        session.commit()
        session.refresh(inactive)
        inactive_id = inactive.id

    forbidden = client.get(
        f"{settings.API_V1_STR}/teams",
        params={"include_inactive": "true"},
        headers=submitter_headers,
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "ROLE_REQUIRED"

    hidden = client.get(
        f"{settings.API_V1_STR}/teams/{inactive_id}",
        headers=submitter_headers,
    )
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "TEAM_NOT_FOUND"

    admin_headers = _login(
        client,
        str(settings.FIRST_SUPERUSER),
        settings.FIRST_SUPERUSER_PASSWORD,
    )
    visible = client.get(
        f"{settings.API_V1_STR}/teams",
        params={"include_inactive": "true"},
        headers=admin_headers,
    )
    assert visible.status_code == 200
    assert {item["name"] for item in visible.json()["items"]} == {
        VS1_TEAM_NAME,
        "已停用团队",
    }
