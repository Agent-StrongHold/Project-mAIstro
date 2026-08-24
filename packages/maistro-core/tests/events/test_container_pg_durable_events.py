"""A container handed a PostgreSQL pool gets PostgreSQL durable events (#135).

The selection used to be `db_pool is not None`, and `db_pool` is a *SQLite*
connection. So a deployment on PostgreSQL got `InMemoryEventLog`,
`InMemoryTriggerStore` and `InMemoryInvocationStore` — the event log, the
trigger registry and the invocation history all lost on restart, and the
idempotency guarantee that makes a redelivered event safe holding only within
one process.

These tests are about the *selection*, which is why they assert on types and on
one round trip rather than re-testing store behaviour: the behaviour is covered
once, for all three backends, in `test_durable_store_conformance.py`.

`pg_pool` is a parameter rather than something derived from
`config.database_url`: building a pool from a URL is #122's work, and this
container still refuses `postgresql://` outright. What #135 fixes is that a
caller who already held a pool had no way to reach the durable stores at all.
"""

from __future__ import annotations

import os

import pytest

from maistro.container import create_container
from maistro.events.durable_log import InMemoryEventLog, SqliteEventLog
from maistro.events.invocations import InMemoryInvocationStore, SqliteInvocationStore
from maistro.events.trigger_store import InMemoryTriggerStore, SqliteTriggerStore
from maistro.types import AgentConfig

DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")


def _require_postgres() -> str:
    """The URL, or a skip — unless the caller declared a server is guaranteed.

    See `test_durable_store_conformance._require_postgres`. `MAISTRO_REQUIRE_PG_LEGS`
    is set by the `durable-events` CI job, where skipping would leave the job
    green with the wiring never exercised.
    """
    if DATABASE_URL:
        return DATABASE_URL
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_DATABASE_URL is empty: "
            "the container wiring leg cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; wiring a real pool needs a real server")


def _config(url: str = "memory://") -> AgentConfig:
    return AgentConfig(router_api_key="test-key", database_url=url)


@pytest.fixture
async def wire():
    """Build containers and close the SQLite connections they open.

    `_wire_sqlite_backend` opens an `aiosqlite` connection, and aiosqlite runs
    it on a **non-daemon** worker thread. A container built and dropped leaves
    that thread alive, and a live non-daemon thread blocks interpreter shutdown
    — so a suite that builds sqlite-backed containers and never closes them can
    finish every test and then hang on exit, which reads as a stuck CI job
    rather than a leak. Observed while writing these tests.
    """
    built = []

    async def _build(config: AgentConfig, **kwargs):
        container = await create_container(config, **kwargs)
        built.append(container)
        return container

    try:
        yield _build
    finally:
        for container in built:
            if container.db_pool is not None:
                await container.db_pool.close()


@pytest.fixture
async def pg_pool():
    import asyncpg

    pool = await asyncpg.create_pool(_require_postgres(), min_size=1, max_size=4)
    try:
        yield pool
    finally:
        await pool.close()


class TestPoolSelectsThePostgresStores:
    async def test_a_pool_selects_the_postgres_stores(self, pg_pool, wire):
        from maistro.events.pg_stores import PgEventLog, PgInvocationStore, PgTriggerStore

        container = await wire(_config(), pg_pool=pg_pool)

        assert isinstance(container.durable_event_log, PgEventLog)
        assert isinstance(container.trigger_store, PgTriggerStore)
        assert isinstance(container.invocation_store, PgInvocationStore)

    async def test_the_wired_stores_reach_the_server(self, pg_pool, wire):
        """Types alone would pass against a store holding a dead pool."""
        await pg_pool.execute("TRUNCATE handler_invocations, trigger_definitions, event_log")
        container = await wire(_config(), pg_pool=pg_pool)

        appended = await container.durable_event_log.append("task.created", entity_id="e1")
        rows = await pg_pool.fetch("SELECT id, event_type, entity_id FROM event_log")

        assert [(r["id"], r["event_type"], r["entity_id"]) for r in rows] == [
            (appended.id, "task.created", "e1")
        ]

    async def test_wiring_creates_the_schema_it_needs(self, pg_pool, wire):
        """A container wired against a database that has never run migration 004
        must still come up: `_wire_pg_durable_events` calls `ensure_event_schema`
        once for all three stores."""
        await pg_pool.execute(
            "DROP TABLE IF EXISTS handler_invocations, trigger_definitions, event_log"
        )
        container = await wire(_config(), pg_pool=pg_pool)

        await container.invocation_store.get_or_create("t1", 1)
        assert len(await container.invocation_store.list_for_event(1)) == 1


class TestTheOtherTwoBackendsAreUnchanged:
    """#135 must not move the SQLite or in-memory selection it sits in front of."""

    async def test_no_pool_and_no_sqlite_url_stays_in_memory(self, wire):
        container = await wire(_config("memory://"))

        assert isinstance(container.durable_event_log, InMemoryEventLog)
        assert isinstance(container.trigger_store, InMemoryTriggerStore)
        assert isinstance(container.invocation_store, InMemoryInvocationStore)

    async def test_a_sqlite_url_and_no_pool_stays_on_sqlite(self, wire):
        container = await wire(_config("sqlite://"))

        assert isinstance(container.durable_event_log, SqliteEventLog)
        assert isinstance(container.trigger_store, SqliteTriggerStore)
        assert isinstance(container.invocation_store, SqliteInvocationStore)

    async def test_a_pool_wins_over_a_sqlite_connection(self, pg_pool, wire):
        """Both can be set at once — they cover different stores. Preferring
        SQLite would hand a multi-worker deployment the one backend whose
        idempotency guarantee does not cross process boundaries."""
        from maistro.events.pg_stores import PgEventLog

        container = await wire(_config("sqlite://"), pg_pool=pg_pool)

        assert isinstance(container.durable_event_log, PgEventLog)
