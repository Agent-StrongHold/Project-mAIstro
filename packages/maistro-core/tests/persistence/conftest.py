"""A real PostgreSQL for the persistence tests, when one is configured.

Every existing `test_pg_*.py` module in this directory mocks the connection and
asserts on the SQL *string*. That proves the query was composed; it cannot prove
the query runs, that the table exists, or that the column types accept what the
store writes — and the answer to all three was "no" until #122, because no
migration created the tables these stores read.

`MAISTRO_TEST_PG_DSN` points at a migrated database (CI runs a `postgres`
service and `alembic upgrade head` before pytest). Without it every test that
needs one skips, so the suite still runs on a laptop with no server.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest

#: Tables the conformance tests write to, truncated between tests. Listed rather
#: than discovered: truncating everything would take out the alembic version
#: table and make the migrated database look unmigrated.
_SCRATCH_TABLES = (
    "quota_usage",
    "sessions",
    "session_turns",
    "audit_log",
    "learnings",
    "outcomes",
    "prompts",
    "prompt_labels",
    "agents",
)


def postgres_dsn() -> str:
    return os.getenv("MAISTRO_TEST_PG_DSN", "").strip()


requires_postgres = pytest.mark.skipif(
    not postgres_dsn(),
    reason="set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database to run these",
)


@pytest.fixture
async def pg_pool() -> AsyncIterator[Any]:
    """An asyncpg pool on a migrated database, truncated before each test.

    Yields ``None`` rather than skipping when no server is configured, so a
    parametrized fixture can request it unconditionally and skip only the
    PostgreSQL parametrization. Skipping here would take the whole suite with it.

    Built directly rather than through `maistro.persistence.get_pool`, which is a
    process singleton: one test's pool would outlive it and be handed to the
    next, along with whatever event loop it was created on.
    """
    dsn = postgres_dsn()
    if not dsn:
        yield None
        return
    asyncpg = pytest.importorskip("asyncpg")

    from maistro.persistence import _register_json_codecs

    # Same codec registration the production pool uses; a test pool without it
    # would exercise a different connection than the one that ships.
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4, init=_register_json_codecs)
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE {} RESTART IDENTITY CASCADE".format(", ".join(_SCRATCH_TABLES))
            )
        yield pool
    finally:
        await pool.close()


@pytest.fixture
async def sa_engine() -> AsyncIterator[Any]:
    """A SQLAlchemy async engine on the same migrated database.

    `PgAgentRegistry` takes an engine rather than an asyncpg pool, so the
    `pg_pool` fixture above cannot serve it. Yields ``None`` when no server is
    configured, for the same reason `pg_pool` does.
    """
    dsn = postgres_dsn()
    if not dsn:
        yield None
        return
    pytest.importorskip("asyncpg")
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        yield engine
    finally:
        await engine.dispose()
