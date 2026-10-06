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

#: Revision 001 opens with ``CREATE EXTENSION IF NOT EXISTS vector`` (the
#: memory embedding column), so ``alembic upgrade head`` — which is what the
#: restore runs — can only ever apply where that statement succeeds. The
#: `durable-events` CI job owns a plain ``postgres:17`` service: no pgvector,
#: and its schema-agreement suite is that job's last step, so the restore
#: could never succeed there and no later suite needs it. Probe the exact
#: prerequisite rather than reading ``pg_available_extensions``:
#: availability is not creatability — a non-superuser on a pgvector image is
#: equally unable to apply the chain (the extension is not `trusted`).
_FIRST_CHAIN_STATEMENT = "CREATE EXTENSION IF NOT EXISTS vector"


def _chain_can_apply(database_url: str) -> bool:
    """Whether revision 001's first statement can run on this server at all.

    Runs the statement inside a transaction that is rolled back, so a capable
    server is left exactly as it was found. A connect failure also means the
    restore cannot run; the suites that follow in the same job fail on their
    own connections, so failing the session here would add nothing.
    """
    import psycopg

    try:
        with psycopg.connect(database_url) as connection:
            connection.execute(_FIRST_CHAIN_STATEMENT)
            connection.rollback()
    except psycopg.Error:
        return False
    return True


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

    # A server that cannot apply revision 001 cannot be restored to head, and
    # failing the session for it would red a job whose every test passed —
    # exactly what run 37472873061 did to `durable-events`, whose service is
    # a pgvector-less postgres:17 and whose schema-agreement suite is the
    # job's last step. Skip the restore there; jobs with a pgvector-capable
    # service (ci.yml `postgres`, the quality.yml coverage producer) are
    # unaffected and behave as before.
    if not _chain_can_apply(_DATABASE_URL):
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
