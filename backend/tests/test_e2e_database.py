import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.e2e_database import derive_e2e_database_url, validate_e2e_database_url

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_derives_app_e2e_from_development_database_url() -> None:
    development_url = (
        "postgresql://postgres:secret@localhost:5432/app?sslmode=disable"
    )

    assert (
        derive_e2e_database_url(development_url)
        == "postgresql://postgres:secret@localhost:5432/app_e2e?sslmode=disable"
    )


@pytest.mark.parametrize("database_name", ["app", "app_test", "production"])
def test_rejects_cleanup_targets_that_are_not_explicit_e2e_databases(
    database_name: str,
) -> None:
    with pytest.raises(ValueError, match="must end with '_e2e'"):
        validate_e2e_database_url(
            f"postgresql://postgres:secret@localhost:5432/{database_name}"
        )


def test_prepare_script_refuses_to_reset_the_development_database() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/e2e_prepare.py"],
        cwd=BACKEND_DIR,
        env={
            **os.environ,
            "DATABASE_URL": "postgresql://postgres:secret@localhost:5432/app",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "must end with '_e2e'" in result.stderr
