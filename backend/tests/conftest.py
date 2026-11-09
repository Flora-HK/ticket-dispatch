"""Test fixtures backed by a dedicated PostgreSQL database.

The development database is never touched: the URL is rewritten to
``app_test`` before the application settings are imported. Transactional
behaviour, partial unique indexes and CHECK constraints are PostgreSQL
specific, so SQLite is intentionally not supported here.
"""

import os
from collections.abc import Generator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent


def _base_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    # dotenv expands ${POSTGRES_PASSWORD}; reading the line verbatim would use
    # the literal placeholder as the password.
    values = dotenv_values(PROJECT_DIR / ".env")
    url = values.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not found in environment or .env")
    return str(url)


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment)
    )


def _psycopg_url(url: str) -> str:
    """SQLAlchemy needs an explicit driver; only psycopg 3 is installed."""
    for scheme in ("postgres://", "postgresql://"):
        if url.startswith(scheme):
            return url.replace(scheme, "postgresql+psycopg://", 1)
    return url


TEST_DATABASE_NAME = os.environ.get("TEST_DATABASE_NAME", "app_test")
TEST_DATABASE_URL = _with_database(_base_database_url(), TEST_DATABASE_NAME)

# app.core.config resolves DATABASE_URL once at import time, so the test
# database has to be selected before any application module is imported.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app.core.config import settings  # noqa: E402
from app.core.db import engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from tests.utils.user import authentication_token_from_email  # noqa: E402
from tests.utils.utils import get_superuser_token_headers  # noqa: E402


def _ensure_test_database() -> None:
    admin_url = _psycopg_url(_with_database(_base_database_url(), "postgres"))
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        exists = connection.execute(
            sa.text("select 1 from pg_database where datname = :name"),
            {"name": TEST_DATABASE_NAME},
        ).first()
        if not exists:
            connection.execute(sa.text(f'CREATE DATABASE "{TEST_DATABASE_NAME}"'))
    admin_engine.dispose()


def _upgrade_test_database() -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "app" / "alembic"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")


def truncate_all_tables() -> None:
    """Reset every business table without disabling the AuditLog trigger."""
    tables = [
        table
        for table in sa.inspect(engine).get_table_names()
        if table != "alembic_version"
    ]
    if not tables:
        return
    quoted = ", ".join(f'"{table}"' for table in tables)
    with engine.begin() as connection:
        connection.execute(sa.text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session]:
    _ensure_test_database()
    _upgrade_test_database()
    with Session(engine) as session:
        init_db(session)
        yield session
    truncate_all_tables()


@pytest.fixture()
def clean_db(db: Session) -> Generator[Session]:
    """Isolated starting point for schema-constraint tests.

    The seeded administrator is recreated after the reset so later modules can
    still authenticate.
    """
    db.rollback()
    truncate_all_tables()
    # 清表后丢弃 Session 身份映射，避免 BIGINT IDENTITY 从 1 重启时复用旧对象。
    db.expunge_all()
    db.expire_all()
    init_db(db)
    yield db
    db.rollback()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
