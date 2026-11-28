"""Container entrypoint: serialize schema migration, then start the API."""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import psycopg
from alembic import command
from alembic.config import Config

from maistro.config.database import resolve_migration_target_url

_MIGRATION_LOCK_ID = 0x4D41495354524F  # ASCII-ish "MAISTRO", within signed bigint.

#: Default seconds Uvicorn may spend closing open connections and cancelling
#: remaining request tasks before it starts the lifespan shutdown (#2249).
DEFAULT_CONNECTION_GRACE_S = 10.0


def _connection_grace_s() -> float:
    """`MAISTRO_SHUTDOWN_CONNECTION_GRACE` in seconds, defaulting to 10.

    The deadline must sit strictly below the deployment's container stop grace
    (`stop_grace_period: 30s` in the shipped compose file): what follows the
    deadline — the lifespan teardown, task drain included — still needs time
    to run inside the same grace window. A deployment whose grace period
    differs overrides here rather than in code. A non-numeric or negative
    value falls back to the default rather than poisoning the exec.
    """
    raw = os.environ.get("MAISTRO_SHUTDOWN_CONNECTION_GRACE", "").strip()
    if not raw:
        return DEFAULT_CONNECTION_GRACE_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_CONNECTION_GRACE_S
    return max(value, 0.0)


def _uvicorn_args() -> list[str]:
    """The exact argv this entrypoint execs, as data.

    `--timeout-graceful-shutdown` is the #2249 fix. Without it Uvicorn's
    shutdown waits **forever** for in-flight requests to finish:
    `Server._wait_tasks_to_complete` spins while any connection exists, and
    the `wait_for` around it uses `timeout_graceful_shutdown=None`. The
    lifespan shutdown — where the task drain, sandbox cleanup, shared-client
    close and engine disposal live — runs only after that wait, so it never
    ran at all. One wedged in-flight request or an open streaming response
    during a drain window (a load generator's pooled clients across the
    soak's kill/drain phase) is that hang: the process never exits, the drain
    window fills with 5xx, and the container's grace deadline ends in SIGKILL.
    """
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "maistro_server.main:app",
        "--host",
        "0.0.0.0",  # nosec B104 - container must accept traffic from its network.
        "--port",
        "8000",
        "--timeout-graceful-shutdown",
        str(_connection_grace_s()),
    ]


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
    """Upgrade to head while holding a session-level PostgreSQL advisory lock.

    Lock and upgrade both target `resolve_migration_target_url()`: postgresql
    whenever the runtime is postgresql, else the `DB_*` composition when
    DATABASE_URL names a sqlite/memory runtime (whose stores self-schema at
    wiring time and carry no alembic chain).
    """
    database_url = resolve_migration_target_url()
    timeout_s = float(os.environ.get("MAISTRO_MIGRATION_LOCK_TIMEOUT", "120"))
    with psycopg.connect(_psycopg_dsn(database_url), autocommit=True) as connection:
        _wait_for_migration_lock(connection, timeout_s=timeout_s)
        try:
            command.upgrade(Config(os.environ.get("ALEMBIC_CONFIG", "alembic.ini")), "head")
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_ID,))


def main() -> None:
    run_migrations()
    os.execvp(sys.executable, _uvicorn_args())


if __name__ == "__main__":
    main()
