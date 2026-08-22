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

_pool: asyncpg.Pool | None = None


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
    """Get or create the connection pool.

    Sizing applies only to the first call — the pool is a process singleton, so
    later calls return the existing one and their arguments are ignored.
    """
    global _pool
    if _pool is None:
        if min_size > max_size:
            raise ValueError(f"min_size ({min_size}) exceeds max_size ({max_size})")
        _pool = await asyncpg.create_pool(
            database_url,
            min_size=min_size,
            max_size=max_size,
            command_timeout=command_timeout,
            init=_register_json_codecs,
        )
        logger.info(
            "PostgreSQL pool created: %s (min_size=%d, max_size=%d)",
            database_url.split("@")[-1],
            min_size,
            max_size,
        )
    return _pool


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL pool closed")


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
