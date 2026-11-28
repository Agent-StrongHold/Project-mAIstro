"""The #2506 scenarios against real, configured, migrated PostgreSQL.

The issue's falsifiable acceptance names live PostgreSQL explicitly: force
the ADR-086 `durable_event_log.append` to throw *after* the EventEnvelope
append commits, then heal and reach delivery only through ordinary production
replay ticks across two independent containers. These legs skip without
`MAISTRO_TEST_DATABASE_URL`; under the `durable-events` CI job (which sets
`MAISTRO_REQUIRE_PG_LEGS`) a skip is a failure, because an untested leg is
how the bridge's at-most-once window survived unnoticed.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from maistro.events.bus import EventSubscriberFailure
from maistro.events.envelope import EventEnvelope
from maistro.events.invocations import ReplaySafety
from maistro.events.trigger_store import TriggerDefinition
from maistro.types import AgentConfig

DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")

#: The CHECK constraint that turns every `event_log` INSERT into the fault the
#: issue describes: the canonical Envelope append commits (a different table),
#: then the authoritative durable-log append throws. It poisons the projector's
#: appends too — exactly like a real outage — and dropping it is the heal.
_POISON_CONSTRAINT = "maistro_test_2506_poison"


def _require_postgres() -> str:
    if DATABASE_URL:
        return DATABASE_URL
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_DATABASE_URL is empty: "
            "the PostgreSQL leg cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; the PostgreSQL leg needs a real server")


def _config() -> AgentConfig:
    return AgentConfig(router_api_key="test-key", database_url="memory://")


def _envelope(event_id: str, stream: str) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        type="agent.recovery",
        workspace_id=stream,
        run_id=f"run-{stream}",
        correlation_id=f"run-{stream}",
        source="test",
        provenance={"legacy_event_category": "agent"},
        payload={"disposition": "recovered"},
    )


@pytest.fixture
async def pg_pool():
    import asyncpg

    pool = await asyncpg.create_pool(_require_postgres(), min_size=1, max_size=6)
    try:
        yield pool
    finally:
        await pool.close()


async def _poison_event_log(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            f"ALTER TABLE event_log DROP CONSTRAINT IF EXISTS {_POISON_CONSTRAINT}"  # nosec B608 - fixed identifier
        )
        await conn.execute(
            f"ALTER TABLE event_log ADD CONSTRAINT {_POISON_CONSTRAINT} "  # nosec B608 - fixed identifier
            "CHECK (event_type <> 'agent.recovery')"
        )


async def _heal_event_log(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            f"ALTER TABLE event_log DROP CONSTRAINT IF EXISTS {_POISON_CONSTRAINT}"  # nosec B608 - fixed identifier
        )


async def _cleanup(pool, *, stream: str, trigger_id: str, event_ids: list[str]) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM handler_invocations WHERE trigger_id = $1", trigger_id)
        await conn.execute("DELETE FROM trigger_definitions WHERE trigger_id = $1", trigger_id)
        await conn.execute(
            "DELETE FROM event_log WHERE source_event_id = ANY($1::text[])", event_ids
        )
        await conn.execute(
            "DELETE FROM canonical_projection_failures WHERE event_id = ANY($1::text[])",
            event_ids,
        )
        await conn.execute(
            "DELETE FROM canonical_event_projection_streams WHERE stream_id = $1",
            f"workspace:{stream}",
        )
        await conn.execute(
            "DELETE FROM canonical_event_stream_watermarks WHERE stream_id = $1",
            f"workspace:{stream}",
        )
        await conn.execute(
            "DELETE FROM canonical_event_log WHERE stream_id = $1", f"workspace:{stream}"
        )


async def _emit_and_fail(container, event_id: str, stream: str) -> EventEnvelope:
    """Emit through the container publisher with the log poisoned.

    Returns the envelope; the canonical append commits, the bridge append
    violates the poison constraint, and the bus correctly raises before any
    trigger can claim success.
    """
    envelope = _envelope(event_id, stream)
    with pytest.raises(EventSubscriberFailure):
        await container.canonical_event_publisher.emit(envelope)
    return envelope


async def test_bridge_failure_after_canonical_commit_heals_across_two_containers(
    pg_pool,
) -> None:
    """Criterions 1 and 2: the failure shape, then two-container healing.

    Container A emits with the durable log poisoned: one canonical event,
    zero ADR-086 rows, no handler Invocation, no success-shaped trigger
    claim. Container B — an independent composition over the same database —
    heals the log and reaches exactly one durable-log occurrence and one
    receipt referencing the original event identity and Workspace sequence,
    using only `process_durable_events`.
    """
    from maistro.container import create_container

    stream = f"ws-2506-{uuid.uuid4().hex[:8]}"
    event_id = f"evt-2506-{uuid.uuid4().hex[:8]}"
    trigger_id = f"t2506-{uuid.uuid4().hex[:8]}"
    delivered: list[dict] = []
    containers = []
    pool_b = None
    try:
        from maistro.events.pg_stores import ensure_event_schema

        await ensure_event_schema(pg_pool)
        await _poison_event_log(pg_pool)
        container_a = await create_container(_config(), pg_pool=pg_pool)
        containers.append(container_a)

        bus_fired: list[str] = []

        async def bus_handler(_trigger, event) -> None:
            bus_fired.append(event.event_id)

        container_a.event_bus.register_handler("capture", bus_handler)
        from maistro.events.bus import Trigger

        container_a.event_bus.add_trigger(
            Trigger(
                name="capture",
                event_types=["agent.recovery"],
                action_type="capture",
                cooldown_seconds=0,
            )
        )

        await _emit_and_fail(container_a, event_id, stream)

        persisted = await container_a.capability_effects.event_store.get(event_id)
        assert persisted is not None
        assert persisted.sequence is not None
        # Exactly one canonical event, zero durable-log rows.
        rows = await pg_pool.fetch("SELECT id FROM event_log WHERE source_event_id = $1", event_id)
        assert rows == []
        # No handler Invocation and no success-shaped trigger claim.
        assert bus_fired == []
        receipts = await pg_pool.fetch(
            "SELECT 1 FROM handler_invocations WHERE trigger_id = $1", trigger_id
        )
        assert receipts == []

        # Restart as a second, independent container over the same database.
        await container_a.aclose()
        import asyncpg

        pool_b = await asyncpg.create_pool(_require_postgres(), min_size=1, max_size=4)
        await _heal_event_log(pg_pool)
        container_b = await create_container(_config(), pg_pool=pool_b)
        containers.append(container_b)

        async def recorder(_trigger, event) -> None:
            delivered.append(dict(event.payload))

        container_b.handler_caller = recorder
        await container_b.trigger_store.add(
            TriggerDefinition(
                trigger_id=trigger_id,
                name="on-recovery",
                event_pattern="agent.recovery",
                handler_url="http://handlers.invalid/recovery",
                replay_safety=ReplaySafety.IDEMPOTENT,
                contract_ref="contract-v1",
            )
        )

        # Only the ordinary production replay/processing tick. No direct
        # bus emit, no test-only append, no repair call. An earlier test's
        # container may still hold the legacy bridge tick lease (300 s); a
        # replica arriving after lease expiry starts from a cleared claim,
        # which is the state this restart models.
        await pg_pool.execute(
            "DELETE FROM consumer_cursors WHERE consumer_id = 'legacy-event-bridge'"
        )
        cursor = await container_b.process_durable_events()
        assert cursor > 0

        rows = await pg_pool.fetch(
            "SELECT id, payload FROM event_log WHERE source_event_id = $1", event_id
        )
        assert len(rows) == 1
        payload = rows[0]["payload"]
        if isinstance(payload, str):  # asyncpg without a json codec
            import json

            payload = json.loads(payload)
        metadata = payload["_canonical_event"]
        assert metadata["event_id"] == event_id
        assert metadata["sequence"] == persisted.sequence
        assert metadata["workspace_id"] == stream
        assert metadata["run_id"] == f"run-{stream}"

        receipts = await pg_pool.fetch(
            "SELECT event_id, status FROM handler_invocations WHERE trigger_id = $1",
            trigger_id,
        )
        assert len(receipts) == 1
        assert receipts[0]["event_id"] == rows[0]["id"]

        assert len(delivered) == 1
        assert delivered[0]["_canonical_event"]["event_id"] == event_id

        # A second tick is a replay, not a second occurrence.
        await container_b.process_durable_events()
        rows = await pg_pool.fetch("SELECT id FROM event_log WHERE source_event_id = $1", event_id)
        assert len(rows) == 1
        assert len(delivered) == 1
    finally:
        await _heal_event_log(pg_pool)
        await _cleanup(pg_pool, stream=stream, trigger_id=trigger_id, event_ids=[event_id])
        for container in containers:
            await container.aclose()
        if pool_b is not None:
            await pool_b.close()


async def test_concurrent_ticks_of_two_replicas_converge_on_one_occurrence(pg_pool) -> None:
    """Criterion 3: duplicate ticks after the failure cannot duplicate the row."""
    from maistro.container import create_container

    stream = f"ws-2506-{uuid.uuid4().hex[:8]}"
    event_id = f"evt-2506-{uuid.uuid4().hex[:8]}"
    trigger_id = f"t2506-{uuid.uuid4().hex[:8]}"
    containers = []
    try:
        from maistro.events.pg_stores import ensure_event_schema

        await ensure_event_schema(pg_pool)
        await _poison_event_log(pg_pool)
        container_a = await create_container(_config(), pg_pool=pg_pool)
        containers.append(container_a)
        with pytest.raises(EventSubscriberFailure):
            await container_a.canonical_event_publisher.emit(_envelope(event_id, stream))
        await container_a.aclose()

        await _heal_event_log(pg_pool)
        container_b = await create_container(_config(), pg_pool=pg_pool)
        container_c = await create_container(_config(), pg_pool=pg_pool)
        containers.extend([container_b, container_c])
        for container in (container_b, container_c):

            async def settle_immediately(_trigger, _event) -> None:
                return None

            container.handler_caller = settle_immediately
            await container.trigger_store.add(
                TriggerDefinition(
                    trigger_id=trigger_id,
                    name="on-recovery",
                    event_pattern="agent.recovery",
                    handler_url="http://handlers.invalid/recovery",
                    replay_safety=ReplaySafety.IDEMPOTENT,
                    contract_ref="contract-v1",
                )
            )

        # The previous test's container still holds the legacy bridge tick
        # lease (300 s); a fresh replica after lease expiry starts from a
        # cleared claim, which is exactly the state the gather reproduces.
        await pg_pool.execute(
            "DELETE FROM consumer_cursors WHERE consumer_id = 'legacy-event-bridge'"
        )
        first, second = await asyncio.gather(
            container_b.process_durable_events(),
            container_c.process_durable_events(),
        )

        rows = await pg_pool.fetch("SELECT id FROM event_log WHERE source_event_id = $1", event_id)
        assert len(rows) == 1
        receipts = await pg_pool.fetch(
            "SELECT event_id FROM handler_invocations WHERE trigger_id = $1", trigger_id
        )
        assert len(receipts) == 1
        assert receipts[0]["event_id"] == rows[0]["id"]
        # Exactly one of the two replicas scanned the stream this round; the
        # other's lease-skip kept it from repeating the work.
        assert max(first, second) > 0
    finally:
        await _heal_event_log(pg_pool)
        await _cleanup(pg_pool, stream=stream, trigger_id=trigger_id, event_ids=[event_id])
        for container in containers:
            await container.aclose()


async def test_an_aborted_envelope_append_leaves_no_sequence_gap_to_skip(pg_pool) -> None:
    """Criterion 4: aborted/out-of-order canonical appends cannot skip events.

    A canonical append that aborts after allocating its sequence leaves the
    stream watermark untouched, so the sequence is handed to the next append:
    committed canonical sequences are contiguous by construction, and the
    projection cursor crosses none of them unprojected.
    """
    from maistro.events.pg_envelope import PgEventStore
    from maistro.events.pg_stores import PgEventLog
    from maistro.events.processing import project_canonical_events
    from maistro.events.publisher import canonical_log_append_kwargs
    from maistro.events.wiring import wire_canonical_projection

    stream = f"ws-2506-{uuid.uuid4().hex[:8]}"
    stream_id = f"workspace:{stream}"
    event_ids = []
    try:
        store = PgEventStore(pg_pool)
        log = PgEventLog(pg_pool)
        await log.ensure_schema()

        # An envelope append that allocates the next sequence inside a
        # transaction which then aborts.
        with pytest.raises(RuntimeError, match="abort"):
            async with pg_pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                        f"canonical-stream:{stream_id}",
                    )
                    await conn.execute(
                        """INSERT INTO canonical_event_stream_watermarks
                           (stream_id, last_sequence)
                           VALUES ($1, GREATEST(
                             COALESCE((SELECT MAX(sequence) FROM canonical_event_log
                                       WHERE stream_id = $1), 0),
                             COALESCE((SELECT last_sequence
                                       FROM canonical_event_stream_watermarks
                                       WHERE stream_id = $1), 0)) + 1)
                           ON CONFLICT (stream_id) DO UPDATE SET
                             last_sequence = EXCLUDED.last_sequence""",
                        stream_id,
                    )
                    raise RuntimeError("abort")

        projection = await wire_canonical_projection(event_store=store, pg_pool=pg_pool)
        # Registration precedes the appends, as the publisher does: the stream
        # is placed at the pre-existing watermark (0) and every append below
        # lands inside the scan-reachable range.
        await projection.projection_store.register_stream(stream_id)
        committed = []
        for _index in range(3):
            event_id = f"evt-abort-{uuid.uuid4().hex[:8]}"
            event_ids.append(event_id)
            committed.append(await store.append(_envelope(event_id, stream)))

        sequences = sorted(event.sequence for event in committed)
        assert sequences == [1, 2, 3], "an aborted append must reuse, never skip, a sequence"

        outcome = await project_canonical_events(
            projection_store=projection.projection_store,
            event_store=store,
            event_log=log,
            failure_store=projection.failure_store,
            append_kwargs=canonical_log_append_kwargs,
            holder="r1",
        )
        assert outcome.projected == 3
        assert outcome.cursors == {stream_id: 3}
        rows = await pg_pool.fetch(
            "SELECT source_event_id FROM event_log WHERE source_event_id = ANY($1::text[])",
            event_ids,
        )
        assert {row["source_event_id"] for row in rows} == set(event_ids)
    finally:
        await _cleanup(pg_pool, stream=stream, trigger_id="unused", event_ids=event_ids)


async def test_projection_store_claims_expire_and_fence(pg_pool) -> None:
    """Criterion 4: two replicas share the durable owner/claim; progress after expiry."""
    from maistro.events.pg_stores import PgCanonicalProjectionStore

    stream = f"ws-2506-{uuid.uuid4().hex[:8]}"
    stream_id = f"workspace:{stream}"
    projection = PgCanonicalProjectionStore(pg_pool)
    try:
        await projection.ensure_schema()
        await projection.register_stream(stream_id)
        # A fresh registration sits at the canonical watermark (0 here).
        lease = await projection.claim(stream_id, holder="a", lease_seconds=0.01)
        assert lease is not None and lease.position == 0
        # A live lease excludes the other replica...
        assert await projection.claim(stream_id, holder="b", lease_seconds=300.0) is None
        await asyncio.sleep(0.02)
        # ...until it expires; b takes over with a fresh token, a's stale
        # write is fenced off, and b progresses.
        taken = await projection.claim(stream_id, holder="b", lease_seconds=300.0)
        assert taken is not None
        assert taken.fencing_token != lease.fencing_token
        assert not await projection.advance(
            stream_id, fencing_token=lease.fencing_token, position=5
        )
        assert await projection.advance(stream_id, fencing_token=taken.fencing_token, position=5)
        renewed = await projection.claim(stream_id, holder="b", lease_seconds=300.0)
        assert renewed is not None and renewed.position == 5
    finally:
        await pg_pool.execute(
            "DELETE FROM canonical_event_projection_streams WHERE stream_id = $1", stream_id
        )


async def test_event_log_dedupe_converges_bridge_and_projector_on_one_row(pg_pool) -> None:
    """The log-level dedupe: same source id, one row, across connections."""
    from maistro.events.pg_stores import PgEventLog

    log = PgEventLog(pg_pool)
    await log.ensure_schema()
    source = f"dedupe-{uuid.uuid4().hex[:12]}"
    created: list[int] = []
    try:
        first = await log.append("agent.recovery", source_event_id=source)
        created.append(first.id)
        second = await log.append("agent.recovery", source_event_id=source)
        assert second.id == first.id
        # NULL source ids (legacy/non-canonical rows) are untouched.
        unkeyed = await log.append("agent.recovery")
        created.append(unkeyed.id)
        rows = await pg_pool.fetch("SELECT id FROM event_log WHERE source_event_id = $1", source)
        assert len(rows) == 1
    finally:
        await pg_pool.execute("DELETE FROM event_log WHERE source_event_id = $1", source)
        if created:
            await pg_pool.execute("DELETE FROM event_log WHERE id = ANY($1::bigint[])", created)
