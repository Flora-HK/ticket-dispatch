import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.core.db import engine
from app.models import User


def test_database_sessions_apply_bounded_timeouts() -> None:
    with engine.connect() as connection:
        statement_timeout = connection.execute(
            text("SHOW statement_timeout")
        ).scalar_one()
        lock_timeout = connection.execute(text("SHOW lock_timeout")).scalar_one()
        idle_transaction_timeout = connection.execute(
            text("SHOW idle_in_transaction_session_timeout")
        ).scalar_one()

    assert statement_timeout == "15s"
    assert lock_timeout == "5s"
    assert idle_transaction_timeout == "30s"


def test_real_postgres_lock_timeout_uses_lock_not_available_sqlstate() -> None:
    with engine.connect() as setup_connection:
        user_id = setup_connection.execute(select(User.id).limit(1)).scalar_one()

    blocker = engine.connect()
    contender = engine.connect()
    blocker_transaction = blocker.begin()
    contender_transaction = contender.begin()
    try:
        blocker.execute(
            text('SELECT id FROM "user" WHERE id = :user_id FOR UPDATE'),
            {"user_id": user_id},
        )
        contender.execute(text("SET LOCAL lock_timeout = '50ms'"))

        with pytest.raises(OperationalError) as raised:
            contender.execute(
                text('UPDATE "user" SET version = version WHERE id = :user_id'),
                {"user_id": user_id},
            )

        assert getattr(raised.value.orig, "sqlstate", None) == "55P03"
    finally:
        contender_transaction.rollback()
        contender.close()
        blocker_transaction.rollback()
        blocker.close()
