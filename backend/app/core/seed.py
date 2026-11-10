from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import Team, TeamMembership, User, UserCreate, UserUpdate

# 开发种子仅用于本地演示和自动化测试；真实人员账号仍由管理员创建。
VS1_DEMO_PASSWORD = "changethis-password"
VS1_TEAM_NAME = "账号与权限"
VS1_SUBMITTER_EMAIL = "submitter@example.com"
VS1_DISPATCHER_EMAIL = "dispatcher@example.com"
VS1_HANDLER_EMAILS = ("handler1@example.com", "handler2@example.com")


def _ensure_demo_user(
    *,
    session: Session,
    email: str,
    full_name: str,
) -> User:
    user = crud.get_user_by_email(session=session, email=email)
    if user is None:
        return crud.create_user(
            session=session,
            user_create=UserCreate(
                email=email,
                password=VS1_DEMO_PASSWORD,
                full_name=full_name,
            ),
        )
    # 幂等重跑时恢复固定本地密码，避免旧开发库无法用种子凭据登录。
    return crud.update_user(
        session=session,
        db_user=user,
        user_in=UserUpdate(password=VS1_DEMO_PASSWORD),
    )


def _ensure_active_team(*, session: Session, name: str) -> Team:
    team = crud.get_team_by_name(session=session, name=name)
    if team is not None and team.is_active:
        return team
    return crud.create_team(session=session, name=name)


def seed_vs1_demo_data(session: Session) -> None:
    """幂等创建 VS1 所需的四类角色、Team 与两名可派发处理人。"""

    admin = crud.get_user_by_email(
        session=session,
        email=settings.FIRST_SUPERUSER,
    )
    if admin is None:
        raise RuntimeError("first administrator must be initialized before seeding")
    crud.ensure_user_role(session=session, user_id=admin.id, role_code="ADMIN")

    team = _ensure_active_team(session=session, name=VS1_TEAM_NAME)

    submitter = _ensure_demo_user(
        session=session,
        email=VS1_SUBMITTER_EMAIL,
        full_name="测试提交人",
    )
    crud.ensure_user_role(
        session=session,
        user_id=submitter.id,
        role_code="SUBMITTER",
    )

    dispatcher = _ensure_demo_user(
        session=session,
        email=VS1_DISPATCHER_EMAIL,
        full_name="测试派单员",
    )
    crud.ensure_user_role(
        session=session,
        user_id=dispatcher.id,
        role_code="DISPATCHER",
    )

    for index, email in enumerate(VS1_HANDLER_EMAILS, start=1):
        handler = _ensure_demo_user(
            session=session,
            email=email,
            full_name=f"测试处理人 {index}",
        )
        crud.ensure_user_role(
            session=session,
            user_id=handler.id,
            role_code="HANDLER",
        )
        membership = session.exec(
            select(TeamMembership).where(
                TeamMembership.team_id == team.id,
                TeamMembership.user_id == handler.id,
            )
        ).first()
        if membership is None:
            crud.create_team_membership(
                session=session,
                team_id=team.id,
                user_id=handler.id,
            )
