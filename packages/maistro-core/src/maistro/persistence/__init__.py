"""PostgreSQL persistence layer."""

from __future__ import annotations

import json
import logging

import asyncpg

logger = logging.getLogger("maistro.persistence")

# Sized from Little's Law: concurrency = throughput x latency. A pool of 10
# with ~10ms queries tops out around 1,000 queries/s in the ideal case, but
# real request handling holds a connection across more than one query, so the
# effective ceiling is far lower — and once the pool is full, `acquire()` is a
# silent queue, indistinguishable from a slow database in every metric.
#
# These are ceilings, not a throttle. Admission control belongs in
# `tasks.lanes.LaneGate`; see `maistro.http` for why capping a shared resource
# to shed load is the worst of the available options.
DEFAULT_DB_POOL_MIN_SIZE = 2
DEFAULT_DB_POOL_MAX_SIZE = 50
DEFAULT_DB_COMMAND_TIMEOUT_S = 30

#: One pool per database, keyed by DSN. This was a single `_pool` that ignored
#: its argument after the first call, so `get_pool(".../db_a")` followed by
#: `get_pool(".../db_b")` handed back db_a's connections -- and a container given
#: a pool for one database could open a second against another and never notice
#: (#335, ADR-082926-730d).
_pools: dict[str, asyncpg.Pool] = {}


async def _register_json_codecs(conn: asyncpg.Connection) -> None:
    """Teach a connection to pass Python values through `json`/`jsonb` columns.

    asyncpg has no default codec for either type: it hands `jsonb` back as a raw
    string and refuses a Python list or dict on the way in —

        asyncpg.exceptions.DataError: invalid input for query argument $2:
        ['deploy', 'rollback'] (expected str, got list)

    which is what `PgLearningStore.store` hit on `trigger_keys`, a JSONB column
    it passes a list to. Registering the codec once per connection is the fix
    asyncpg documents, and it belongs here rather than in each store: the
    alternative is every call site remembering to `json.dumps` on write and
    `json.loads` on read, and the read half is the one that gets forgotten,
    because a JSON string is truthy and iterable and fails much later.
    """
    for type_name in ("json", "jsonb"):
        await conn.set_type_codec(
            type_name,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


async def get_pool(
    database_url: str,
    *,
    min_size: int = DEFAULT_DB_POOL_MIN_SIZE,
    max_size: int = DEFAULT_DB_POOL_MAX_SIZE,
    command_timeout: int = DEFAULT_DB_COMMAND_TIMEOUT_S,
) -> asyncpg.Pool:
    """Get or create the connection pool for `database_url`.

    One pool per database. Asking twice for the same DSN returns the same pool;
    asking for a different database opens a different pool rather than handing
    back connections to the one that happened to be opened first.

    Sizing applies only to the first call *for that DSN* — later calls return the
    existing pool and their arguments are ignored.
    """
    existing = _pools.get(database_url)
    if existing is not None:
        return existing
    if min_size > max_size:
        raise ValueError(f"min_size ({min_size}) exceeds max_size ({max_size})")
    pool = await asyncpg.create_pool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        command_timeout=command_timeout,
        init=_register_json_codecs,
    )
    # Registered after the await, not before: two coroutines racing on the same
    # DSN would otherwise both see an empty registry, and recording a
    # not-yet-created pool would hand the loser a `None`.
    _pools[database_url] = pool
    logger.info(
        "PostgreSQL pool created: %s (min_size=%d, max_size=%d)",
        database_url.split("@")[-1],
        min_size,
        max_size,
    )
    return pool


def pool_count() -> int:
    """How many pools this process has open.

    Exists so a test can assert that building a container opened one pool and
    not two, which is the only way the leak this replaces was ever visible.
    """
    return len(_pools)


def forget_pool(pool: asyncpg.Pool) -> None:
    """Drop a pool from the registry without closing it.

    For an owner that closed the pool itself: leaving it registered would hand
    the next `get_pool` for that DSN a closed pool, which fails on first use
    rather than at the moment the mistake was made.
    """
    for dsn, registered in list(_pools.items()):
        if registered is pool:
            del _pools[dsn]


async def close_pool(database_url: str | None = None) -> None:
    """Close one database's pool, or every pool this process opened.

    No argument closes all of them, which is what every caller of the old
    single-pool form meant: test teardown, and the preflight failure that has to
    leave nothing holding connections to a database the operator is about to fix.
    """
    if database_url is not None:
        pool = _pools.pop(database_url, None)
        if pool is not None:
            await pool.close()
            logger.info("PostgreSQL pool closed: %s", database_url.split("@")[-1])
        return
    # Emptied before the first await: a close that raises half way through must
    # not leave the registry holding pools that are already closing.
    open_pools = list(_pools.items())
    _pools.clear()
    for dsn, pool in open_pools:
        await pool.close()
        logger.info("PostgreSQL pool closed: %s", dsn.split("@")[-1])


async def run_migrations(pool: asyncpg.Pool, migrations_dir: str = "") -> None:
    """Run pending SQL migrations."""
    from pathlib import Path

    if not migrations_dir:
        candidates = [
            Path("/app/migrations"),
            Path(__file__).parent.parent.parent.parent / "migrations",
            Path("migrations"),
        ]
        for candidate in candidates:
            if candidate.exists():
                migrations_dir = str(candidate)
                break
        else:
            migrations_dir = str(candidates[0])

    mig_path = Path(migrations_dir)
    if not mig_path.exists():
        logger.warning("Migrations directory not found: %s", migrations_dir)
        return

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        applied: set[str] = {r["name"] for r in await conn.fetch("SELECT name FROM _migrations")}

        if not applied:
            has_tables = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='agents')"
            )
            if has_tables:
                for sql_file in sorted(mig_path.glob("*.sql")):
                    await conn.execute("INSERT INTO _migrations (name) VALUES ($1)", sql_file.name)
                    logger.info("Marked pre-existing migration: %s", sql_file.name)
                return

        for sql_file in sorted(mig_path.glob("*.sql")):
            if sql_file.name not in applied:
                logger.info("Applying migration: %s", sql_file.name)
                sql = sql_file.read_text()
                await conn.execute(sql)
                await conn.execute("INSERT INTO _migrations (name) VALUES ($1)", sql_file.name)
                logger.info("Migration applied: %s", sql_file.name)
