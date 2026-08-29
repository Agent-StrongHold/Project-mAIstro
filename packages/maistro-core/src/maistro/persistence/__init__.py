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
#: How many callers hold each registered pool. The registry owns the pool; this
#: is what decides when the last one lets go. Keyed by the same DSN as `_pools`
#: and kept in step with it — every write to one writes the other.
_users: dict[str, int] = {}


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

    Each call registers a **user**. The registry owns the pool; a caller that
    finishes with it calls `release_pool`, and the pool closes when the last
    user lets go. Treating the first caller as the owner would be wrong for the
    same reason the shared registry exists: two containers built from one DSN
    get the same object, and whichever closed first would take the pool out
    from under the other (Codex, #335).
    """
    existing = _pools.get(database_url)
    if existing is not None:
        _users[database_url] += 1
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
    _users[database_url] = 1
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

    For a caller that closed the pool itself: leaving it registered would hand
    the next `get_pool` for that DSN a closed pool, which fails on first use
    rather than at the moment the mistake was made.
    """
    for dsn, registered in list(_pools.items()):
        if registered is pool:
            del _pools[dsn]
            _users.pop(dsn, None)


async def release_pool(pool: asyncpg.Pool) -> bool:
    """Let go of a registered pool, closing it when the last user does.

    Returns whether this call closed it.

    The alternative — the caller that opened the pool owns it — is wrong here,
    and wrong for the same reason the registry exists: `get_pool` hands the same
    object to every caller of a DSN, so an "owner" closing it takes the pool out
    from under everyone still using it, and their next query fails somewhere far
    from the mistake (Codex, #335).

    A pool that is not registered is not this registry's to close: releasing one
    is a no-op rather than an error, because a caller that supplied its own pool
    and a caller whose pool was already force-closed both reach here and neither
    is doing anything wrong.
    """
    for dsn, registered in list(_pools.items()):
        if registered is not pool:
            continue
        remaining = _users.get(dsn, 1) - 1
        if remaining > 0:
            _users[dsn] = remaining
            return False
        del _pools[dsn]
        _users.pop(dsn, None)
        await pool.close()
        logger.info("PostgreSQL pool closed: %s", dsn.split("@")[-1])
        return True
    return False


async def close_pool(database_url: str | None = None) -> None:
    """Close one database's pool, or every pool this process opened.

    Unconditional, unlike `release_pool`: this is the teardown form. Test
    teardown and the preflight failure that has to leave nothing holding
    connections to a database the operator is about to fix both need the pool
    gone regardless of who still holds a reference.
    """
    if database_url is not None:
        pool = _pools.pop(database_url, None)
        _users.pop(database_url, None)
        if pool is not None:
            await pool.close()
            logger.info("PostgreSQL pool closed: %s", database_url.split("@")[-1])
        return
    # Emptied before the first await: a close that raises half way through must
    # not leave the registry holding pools that are already closing.
    open_pools = list(_pools.items())
    _pools.clear()
    _users.clear()
    # Every pool is closed before any failure is raised. Stopping at the first
    # one would leave the rest open *and* unreachable, because the registry is
    # already cleared — so the close-all contract would be broken precisely by
    # the error path that most needs it to hold (Codex, #335).
    failures: list[Exception] = []
    for dsn, pool in open_pools:
        try:
            await pool.close()
        except Exception as exc:
            logger.exception("PostgreSQL pool did not close cleanly: %s", dsn.split("@")[-1])
            failures.append(exc)
        else:
            logger.info("PostgreSQL pool closed: %s", dsn.split("@")[-1])
    if failures:
        raise ExceptionGroup("PostgreSQL pools did not all close cleanly", failures)


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
