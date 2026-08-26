"""Container entrypoint: serialize schema migration, then start the API."""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import psycopg
from alembic import command
from alembic.config import Config

from maistro.config.database import require_database_url

_MIGRATION_LOCK_ID = 0x4D41495354524F  # ASCII-ish "MAISTRO", within signed bigint.


def _psycopg_dsn(database_url: str) -> str:
    """Return a libpq DSN from any PostgreSQL spelling accepted by MAIstro."""
    for scheme in (
        "postgresql+asyncpg://",
        "postgresql+psycopg://",
        "postgres://",
    ):
        if database_url.startswith(scheme):
            return "postgresql://" + database_url[len(scheme) :]
    return database_url


def _wait_for_migration_lock(
    connection: Any,
    *,
    timeout_s: float,
    poll_s: float = 0.25,
) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        row = connection.execute(
            "SELECT pg_try_advisory_lock(%s)", (_MIGRATION_LOCK_ID,)
        ).fetchone()
        if row and row[0] is True:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Timed out after {timeout_s:g}s waiting for the schema migration lock."
            )
        time.sleep(poll_s)


def run_migrations() -> None:
    """Upgrade to head while holding a session-level PostgreSQL advisory lock."""
    database_url = require_database_url()
    timeout_s = float(os.environ.get("MAISTRO_MIGRATION_LOCK_TIMEOUT", "120"))
    with psycopg.connect(_psycopg_dsn(database_url), autocommit=True) as connection:
        _wait_for_migration_lock(connection, timeout_s=timeout_s)
        try:
            command.upgrade(Config(os.environ.get("ALEMBIC_CONFIG", "alembic.ini")), "head")
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_ID,))


def main() -> None:
    run_migrations()
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "maistro_server.main:app",
            "--host",
            "0.0.0.0",  # nosec B104 - container must accept traffic from its network.
            "--port",
            "8000",
        ],
    )


if __name__ == "__main__":
    main()
