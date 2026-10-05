"""Restore the configured PostgreSQL service after migration integration tests.

The migration tests intentionally downgrade to base and create runtime-owned tables
while probing adoption.  Coverage runs durable suites against that same service
immediately afterwards, so leaving it at base makes their fixtures fail before
any application behavior is measured.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")


def _alembic_environment() -> dict[str, str]:
    """Point Alembic at the same database migration tests exercise."""
    return {**os.environ, "DATABASE_URL": _DATABASE_URL}


def _drop_public_tables() -> None:
    """Remove chain and runtime-provisioned tables before restoring head."""
    import psycopg

    with (
        psycopg.connect(_DATABASE_URL, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("select tablename from pg_tables where schemaname = 'public'")
        for (name,) in cursor.fetchall():
            quoted = str(name).replace('"', '""')
            cursor.execute(f'DROP TABLE IF EXISTS "{quoted}" CASCADE')


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Leave the shared CI service at Alembic head for its next coverage suite."""
    if not _DATABASE_URL:
        return

    _drop_public_tables()
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        env=_alembic_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        pytest.fail(f"could not restore PostgreSQL schema after migration tests:\n{result.stderr}")
