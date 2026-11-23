"""Helpers for selecting and preparing disposable end-to-end databases."""

from urllib.parse import urlsplit, urlunsplit

E2E_DATABASE_SUFFIX = "_e2e"


def _database_name(database_url: str) -> str:
    name = urlsplit(database_url).path.lstrip("/")
    if not name or "/" in name:
        raise ValueError("Database URL must contain exactly one database name")
    return name


def derive_e2e_database_url(database_url: str) -> str:
    """Return the matching E2E database URL for a base application URL."""

    name = _database_name(database_url)
    if name.endswith(E2E_DATABASE_SUFFIX):
        return database_url
    parts = urlsplit(database_url)
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{name}{E2E_DATABASE_SUFFIX}", parts.query, "")
    )


def validate_e2e_database_url(database_url: str) -> str:
    """Reject any cleanup target that is not explicitly marked as E2E."""

    name = _database_name(database_url)
    if not name.endswith(E2E_DATABASE_SUFFIX):
        raise ValueError(
            f"E2E database name '{name}' must end with '{E2E_DATABASE_SUFFIX}'"
        )
    return name
