"""Backend composition evidence for the canonical governed effect context."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.capabilities.effect_context import (
    new_backend_effect_context,
    new_in_memory_effect_context,
)
from maistro.events.envelope import EventEnvelope, InMemoryEventStore, SqliteEventStore


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
