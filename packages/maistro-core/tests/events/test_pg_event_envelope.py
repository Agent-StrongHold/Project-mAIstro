"""PostgreSQL evidence for canonical Workspace Event ordering (#61)."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from maistro.events.envelope import EventEnvelope
from maistro.events.pg_envelope import PgEventStore, ensure_canonical_event_schema

DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")


def _require_postgres() -> str:
    if DATABASE_URL:
        return DATABASE_URL
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        raise RuntimeError("MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_DATABASE_URL is empty")
    pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; PostgreSQL evidence needs a real server")


async def _pool():
    import asyncpg

    pool = await asyncpg.create_pool(_require_postgres(), min_size=1, max_size=8)
    await ensure_canonical_event_schema(pool)
    return pool


async def test_workspace_sequence_survives_postgres_store_restart() -> None:
    workspace = f"ws-restart-{uuid4().hex}"
    stream = f"workspace:{workspace}"
    first_pool = await _pool()
    try:
        first = await PgEventStore(first_pool).append(
            EventEnvelope(
                event_id=f"event-{uuid4().hex}", type="run.started", workspace_id=workspace
            )
        )
        assert first.sequence == 1
    finally:
        await first_pool.close()

    restarted_pool = await _pool()
    try:
        store = PgEventStore(restarted_pool)
        second = await store.append(
            EventEnvelope(
                event_id=f"event-{uuid4().hex}", type="run.started", workspace_id=workspace
            )
        )
        history = await store.list_stream(stream)
        assert second.sequence == 2
        assert [event.sequence for event in history] == [1, 2]
    finally:
        await restarted_pool.execute("DELETE FROM canonical_event_log WHERE stream_id = $1", stream)
        await restarted_pool.close()


async def test_workspace_sequence_serializes_across_postgres_writers() -> None:
    workspace = f"ws-race-{uuid4().hex}"
    stream = f"workspace:{workspace}"
    pool = await _pool()
    try:
        left = PgEventStore(pool)
        right = PgEventStore(pool)
        events = [
            EventEnvelope(
                event_id=f"event-{uuid4().hex}",
                type="node.progress",
                workspace_id=workspace,
                run_id=f"run-{index % 3}",
            )
            for index in range(12)
        ]
        persisted = await asyncio.gather(
            *(
                (left if index % 2 == 0 else right).append(event)
                for index, event in enumerate(events)
            )
        )
        history = await left.list_stream(stream, limit=100)
        assert sorted(event.sequence for event in persisted) == list(range(1, 13))
        assert [event.sequence for event in history] == list(range(1, 13))
        assert {event.event_id for event in history} == {event.event_id for event in events}
    finally:
        await pool.execute("DELETE FROM canonical_event_log WHERE stream_id = $1", stream)
        await pool.close()


async def test_event_id_retry_is_idempotent_under_postgres_concurrency() -> None:
    workspace = f"ws-idempotent-{uuid4().hex}"
    stream = f"workspace:{workspace}"
    event_id = f"event-{uuid4().hex}"
    pool = await _pool()
    try:
        left = PgEventStore(pool)
        right = PgEventStore(pool)
        event = EventEnvelope(event_id=event_id, type="run.started", workspace_id=workspace)
        first, second = await asyncio.gather(left.append(event), right.append(event))
        history = await left.list_stream(stream)
        assert first == second
        assert first.sequence == 1
        assert [row.event_id for row in history] == [event_id]
    finally:
        await pool.execute("DELETE FROM canonical_event_log WHERE stream_id = $1", stream)
        await pool.close()
