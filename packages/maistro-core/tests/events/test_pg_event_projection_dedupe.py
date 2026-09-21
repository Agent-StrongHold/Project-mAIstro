"""PostgreSQL cross-writer proof for canonical Event projection dedupe (#1093)."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from maistro.events.bus import EventBus, Trigger
from maistro.events.envelope import EventEnvelope
from maistro.events.pg_envelope import PgEventStore, ensure_canonical_event_schema
from maistro.events.publisher import CanonicalEventPublisher

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


@pytest.mark.asyncio
async def test_two_postgres_publishers_deliver_one_legacy_side_effect_for_same_event() -> None:
    workspace = f"ws-projection-race-{uuid4().hex}"
    stream = f"workspace:{workspace}"
    event_id = f"event-{uuid4().hex}"
    pool = await _pool()
    side_effects: list[str] = []
    bus = EventBus()

    async def capture(_trigger: Trigger, event) -> None:
        side_effects.append(event.event_id)

    bus.register_handler("capture", capture)
    bus.add_trigger(
        Trigger(
            name="capture raced recovery",
            event_types=["run.recovery_disposition"],
            action_type="capture",
            cooldown_seconds=0,
        )
    )

    try:
        left = CanonicalEventPublisher(PgEventStore(pool), legacy_bus=bus)
        right = CanonicalEventPublisher(PgEventStore(pool), legacy_bus=bus)
        event = EventEnvelope(
            event_id=event_id,
            type="run.recovery_disposition",
            workspace_id=workspace,
            run_id="run-race",
            provenance={"legacy_event_category": "system"},
            payload={"disposition": "recovered_and_parked"},
        )

        first, second = await asyncio.gather(left.emit(event), right.emit(event))
        history = await left.store.list_stream(stream)

        assert first == second
        assert first.sequence == 1
        assert side_effects == [event_id]
        assert [item.event_id for item in bus.get_history()] == [event_id]
        assert [item.event_id for item in history] == [event_id]
    finally:
        await pool.execute("DELETE FROM canonical_event_log WHERE stream_id = $1", stream)
        await pool.close()
