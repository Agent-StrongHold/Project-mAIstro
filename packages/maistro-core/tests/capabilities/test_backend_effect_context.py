"""Backend composition evidence for the canonical governed effect context."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.capabilities.effect_context import (
    new_backend_effect_context,
    new_in_memory_effect_context,
)
from maistro.events.envelope import EventEnvelope, InMemoryEventStore, SqliteEventStore

DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")


@pytest.fixture
async def sqlite_connection() -> AsyncIterator[aiosqlite.Connection]:
    connection = await aiosqlite.connect(":memory:")
    try:
        yield connection
    finally:
        await connection.close()


async def test_backend_context_injects_one_sqlite_event_store(
    sqlite_connection: aiosqlite.Connection,
) -> None:
    context = await new_backend_effect_context(db_pool=sqlite_connection)

    assert isinstance(context.event_store, SqliteEventStore)
    event = await context.event_store.append(
        EventEnvelope(
            type="capability.invocation.policy_decision",
            workspace_id="workspace-1",
            run_id="run-1",
        )
    )
    assert event.sequence == 1
    assert await context.event_store.get(event.event_id) == event


async def test_ephemeral_context_remains_explicitly_in_memory() -> None:
    context = await new_backend_effect_context()
    explicit = new_in_memory_effect_context()

    assert isinstance(context.event_store, InMemoryEventStore)
    assert isinstance(explicit.event_store, InMemoryEventStore)
    assert context.event_store is not explicit.event_store


def _require_postgres() -> str:
    """The URL, or a skip — unless the caller declared a server is guaranteed.

    See `test_durable_store_conformance._require_postgres`. `MAISTRO_REQUIRE_PG_LEGS`
    is set by the `durable-events` CI job, where skipping would leave the job
    green with the pool-selected canonical EventStore never exercised (#1133).
    """
    if DATABASE_URL:
        return DATABASE_URL
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_DATABASE_URL is empty: "
            "the governed-effect PostgreSQL leg cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; wiring a real pool needs a real server")


async def test_backend_context_injects_one_postgres_event_store() -> None:
    """A supplied `pg_pool` selects the PostgreSQL canonical EventStore (#1133).

    Types alone would pass against a dead pool: the appended event must reach
    the server and read back with the Workspace sequence the server assigned,
    proving governed effects hold no private in-memory event authority on the
    PostgreSQL backend either.
    """
    import asyncpg

    from maistro.events.pg_envelope import PgEventStore

    pool = await asyncpg.create_pool(_require_postgres(), min_size=1, max_size=4)
    try:
        context = await new_backend_effect_context(pg_pool=pool)
        from uuid import uuid4

        workspace = f"ws-effects-{uuid4().hex}"

        assert isinstance(context.event_store, PgEventStore)
        event = await context.event_store.append(
            EventEnvelope(
                type="capability.invocation.policy_decision",
                workspace_id=workspace,
                run_id="run-1",
            )
        )
        assert event.sequence == 1
        assert await context.event_store.get(event.event_id) == event
        row = await pool.fetchval(
            "SELECT count(*) FROM canonical_event_log WHERE workspace_id = $1", workspace
        )
        assert row == 1
    finally:
        await pool.close()
