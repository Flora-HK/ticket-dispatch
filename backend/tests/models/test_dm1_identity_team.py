"""DM1 schema guarantees: identity roles, Team and TeamMembership.

These tests run against the dedicated PostgreSQL test database. They assert the
database-level guards, because application code alone cannot enforce them.
"""

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.db import init_db
from app.models import Team, TeamMembership, User, UserCreate, UserRole


def _create_user(session: Session, email: str = "alice@example.com") -> User:
    return crud.create_user(
        session=session,
        user_create=UserCreate(email=email, password="changethis-password"),
    )


def test_dm1_user_version_defaults_to_one(clean_db: Session) -> None:
    user = _create_user(clean_db, "version@example.com")
    assert user.version == 1


def test_dm1_user_accepts_multiple_roles(clean_db: Session) -> None:
    user = _create_user(clean_db, "multi@example.com")
    crud.ensure_user_role(session=clean_db, user_id=user.id, role_code="HANDLER")
    crud.ensure_user_role(session=clean_db, user_id=user.id, role_code="SUBMITTER")

    roles = clean_db.exec(select(UserRole).where(UserRole.user_id == user.id)).all()
    assert {role.role_code for role in roles} == {"HANDLER", "SUBMITTER"}


def test_dm1_duplicate_role_rejected_by_unique_constraint(clean_db: Session) -> None:
    user = _create_user(clean_db, "duplicate-role@example.com")
    crud.ensure_user_role(session=clean_db, user_id=user.id, role_code="HANDLER")

    clean_db.add(UserRole(user_id=user.id, role_code="HANDLER"))
    with pytest.raises(IntegrityError):
        clean_db.commit()
    clean_db.rollback()

    roles = clean_db.exec(select(UserRole).where(UserRole.user_id == user.id)).all()
    assert len(roles) == 1


def test_dm1_role_code_check_rejects_unknown_role(clean_db: Session) -> None:
    user = _create_user(clean_db, "bad-role@example.com")

    clean_db.add(UserRole(user_id=user.id, role_code="OWNER"))
    with pytest.raises(IntegrityError):
        clean_db.commit()
    clean_db.rollback()


def test_dm1_duplicate_team_membership_rejected(clean_db: Session) -> None:
    user = _create_user(clean_db, "member@example.com")
    team = crud.create_team(session=clean_db, name="账号与权限")
    crud.create_team_membership(session=clean_db, team_id=team.id, user_id=user.id)

    clean_db.add(TeamMembership(team_id=team.id, user_id=user.id))
    with pytest.raises(IntegrityError):
        clean_db.commit()
    clean_db.rollback()

    memberships = clean_db.exec(
        select(TeamMembership).where(TeamMembership.team_id == team.id)
    ).all()
    assert len(memberships) == 1


def test_dm1_team_name_is_unique_among_active_teams(clean_db: Session) -> None:
    team = crud.create_team(session=clean_db, name="硬件支持")
    assert team.version == 1
    assert team.is_active is True

    with pytest.raises(IntegrityError):
        crud.create_team(session=clean_db, name="硬件支持")
    clean_db.rollback()

    # A retired pool releases its name, so the name can be reused ...
    team.is_active = False
    clean_db.add(team)
    clean_db.commit()
    replacement = crud.create_team(session=clean_db, name="硬件支持")
    assert replacement.id != team.id

    # ... but two active Teams can never share one name.
    team = clean_db.get(Team, team.id)
    assert team is not None
    team.is_active = True
    clean_db.add(team)
    with pytest.raises(IntegrityError):
        clean_db.commit()
    clean_db.rollback()


def test_dm1_deleting_user_cascades_roles_and_memberships(clean_db: Session) -> None:
    user = _create_user(clean_db, "cascade@example.com")
    team = crud.create_team(session=clean_db, name="网络支持")
    crud.ensure_user_role(session=clean_db, user_id=user.id, role_code="HANDLER")
    crud.create_team_membership(session=clean_db, team_id=team.id, user_id=user.id)

    clean_db.delete(user)
    clean_db.commit()

    assert clean_db.exec(
        select(UserRole).where(UserRole.user_id == user.id)
    ).all() == []
    assert clean_db.exec(
        select(TeamMembership).where(TeamMembership.user_id == user.id)
    ).all() == []
    assert clean_db.get(Team, team.id) is not None


def test_dm1_init_db_creates_single_admin_role(clean_db: Session) -> None:
    init_db(clean_db)
    init_db(clean_db)

    admins = clean_db.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).all()
    assert len(admins) == 1

    admin_roles = clean_db.exec(
        select(UserRole).where(
            UserRole.user_id == admins[0].id, UserRole.role_code == "ADMIN"
        )
    ).all()
    assert len(admin_roles) == 1


def test_dm1_critical_constraints_exist_in_catalog(clean_db: Session) -> None:
    connection = clean_db.connection()

    index_names = {
        row[0]
        for row in connection.execute(
            sa.text(
                "select indexname from pg_indexes where schemaname = 'public'"
            )
        )
    }
    assert {
        "uq_user_role_user_id_role_code",
        "ix_user_role_role_code_user_id",
        "uq_team_membership_team_user",
        "ix_team_membership_team_available",
        "uq_team_name_active",
    } <= index_names

    team_name_index = connection.execute(
        sa.text(
            "select indexdef from pg_indexes "
            "where schemaname = 'public' and indexname = 'uq_team_name_active'"
        )
    ).scalar_one()
    assert "WHERE is_active" in team_name_index

    check_names = {
        row[0]
        for row in connection.execute(
            sa.text(
                "select conname from pg_constraint "
                "where conrelid = 'user_role'::regclass and contype = 'c'"
            )
        )
    }
    assert "ck_user_role_role_code" in check_names


def test_dm1_unknown_user_role_fk_is_rejected(clean_db: Session) -> None:
    clean_db.add(UserRole(user_id=uuid.uuid4(), role_code="ADMIN"))
    with pytest.raises(IntegrityError):
        clean_db.commit()
    clean_db.rollback()
