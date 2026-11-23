"""Create and reset the disposable database used by Playwright."""

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlmodel import Session, create_engine

from scripts.e2e_database import validate_e2e_database_url

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _psycopg_url(database_url: str) -> str:
    for scheme in ("postgres://", "postgresql://"):
        if database_url.startswith(scheme):
            return database_url.replace(scheme, "postgresql+psycopg://", 1)
    return database_url


def _with_database(database_url: str, database: str) -> str:
    parts = urlsplit(database_url)
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment)
    )


def _ensure_database(database_url: str, database_name: str) -> None:
    admin_url = _psycopg_url(_with_database(database_url, "postgres"))
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    quoted_name = database_name.replace('"', '""')
    try:
        with admin_engine.connect() as connection:
            exists = connection.execute(
                sa.text("select 1 from pg_database where datname = :name"),
                {"name": database_name},
            ).first()
            if not exists:
                connection.execute(sa.text(f'CREATE DATABASE "{quoted_name}"'))
    finally:
        admin_engine.dispose()


def _upgrade_database() -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "app" / "alembic"))
    command.upgrade(config, "head")


def _reset_business_tables(database_url: str) -> None:
    engine = create_engine(_psycopg_url(database_url))
    try:
        tables = [
            table
            for table in sa.inspect(engine).get_table_names()
            if table != "alembic_version"
        ]
        if not tables:
            return
        quoted_tables = ", ".join(f'"{table}"' for table in tables)
        with engine.begin() as connection:
            connection.execute(
                sa.text(f"TRUNCATE TABLE {quoted_tables} RESTART IDENTITY CASCADE")
            )
    finally:
        engine.dispose()


def _initialize_application_data() -> None:
    from app.core.db import engine, init_db

    with Session(engine) as session:
        init_db(session)
        session.commit()


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for E2E database preparation")
    database_name = validate_e2e_database_url(database_url)

    _ensure_database(database_url, database_name)
    _upgrade_database()
    _reset_business_tables(database_url)
    _initialize_application_data()


if __name__ == "__main__":
    main()
