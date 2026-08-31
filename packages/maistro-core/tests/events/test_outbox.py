"""Transactional outbox tests for canonical event publication."""

from __future__ import annotations

import aiosqlite
import pytest

from maistro.events.envelope import EventEnvelope, SqliteEventStore
from maistro.events.outbox import SqliteEventOutbox
from maistro.observability.correlation import bind_execution_context


@pytest.fixture
async def connection() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    statement = "CREATE TABLE domain_state (id TEXT PRIMARY KEY, value TEXT NOT NULL)"
    await conn.execute(statement)
    await conn.commit()
    yield conn
    await conn.close()


async def _stores(
    connection: aiosqlite.Connection,
) -> tuple[SqliteEventOutbox, SqliteEventStore]:
    outbox = SqliteEventOutbox(connection)
    event_store = SqliteEventStore(connection)
    await outbox.ensure_schema()
    await event_store.ensure_schema()
    return outbox, event_store


def _event(event_type: str, event_id: str) -> EventEnvelope:
    return EventEnvelope(
        type=event_type,
        workspace_id="ws-1",
        run_id="run-1",
        event_id=event_id,
    )


async def _domain_value(connection: aiosqlite.Connection) -> str | None:
    query = "SELECT value FROM domain_state WHERE id = 'run-1'"
    cursor = await connection.execute(query)
    row = await cursor.fetchone()
    if row is None:
        return None
    return str(row[0])


async def test_domain_state_and_event_commit_together(
    connection: aiosqlite.Connection,
) -> None:
    outbox, event_store = await _stores(connection)
    event = _event("run.updated", "evt-commit")
    await connection.execute("BEGIN")
    await connection.execute(
        "INSERT INTO domain_state (id, value) VALUES (?, ?)",
        ("run-1", "running"),
    )
    await outbox.stage(event)
    await connection.commit()

    assert await _domain_value(connection) == "running"
    assert await outbox.pending_count() == 1
    assert await outbox.publish_pending(event_store) == 1
    persisted = await event_store.get("evt-commit")
    assert persisted is not None
    assert persisted.sequence == 1
    assert await outbox.pending_count() == 0


async def test_domain_state_and_event_roll_back_together(
    connection: aiosqlite.Connection,
) -> None:
    outbox, event_store = await _stores(connection)
    event = _event("run.updated", "evt-rollback")
    await connection.execute("BEGIN")
    await connection.execute(
        "INSERT INTO domain_state (id, value) VALUES (?, ?)",
        ("run-1", "running"),
    )
    await outbox.stage(event)
    await connection.rollback()

    assert await _domain_value(connection) is None
    assert await outbox.pending_count() == 0
    assert await outbox.publish_pending(event_store) == 0
    assert await event_store.get("evt-rollback") is None


async def test_stage_is_idempotent_by_event_id(
    connection: aiosqlite.Connection,
) -> None:
    outbox, _ = await _stores(connection)
    event = _event("run.updated", "stable")
    first = await outbox.stage(event)
    second = await outbox.stage(event)
    await connection.commit()
    assert first == second
    assert await outbox.pending_count() == 1


async def test_publish_recovers_after_append_before_outbox_mark(
    connection: aiosqlite.Connection,
) -> None:
    outbox, event_store = await _stores(connection)
    event = _event("attempt.completed", "evt-crash")
    await outbox.stage(event)
    await connection.commit()

    first = await event_store.append(event)
    assert first.sequence == 1
    assert await outbox.pending_count() == 1
    assert await outbox.publish_pending(event_store) == 1
    history = await event_store.list_stream("workspace:ws-1")
    assert [item.event_id for item in history] == ["evt-crash"]
    assert await outbox.pending_count() == 0


async def test_stage_rejects_presequenced_event(
    connection: aiosqlite.Connection,
) -> None:
    outbox, _ = await _stores(connection)
    event = EventEnvelope(
        type="x",
        workspace_id="ws-1",
        run_id="r1",
        sequence=9,
    )
    with pytest.raises(ValueError, match="store-assigned sequence"):
        await outbox.stage(event)


class TestAStagedEventKeepsItsProducersCorrelation:
    """The outbox splits producing an event from appending it. Correlating only
    at append means correlating in the publisher's context, which is not the
    producer's — and by then the producer's has usually ended (Codex, #707)."""

    async def test_the_producers_ids_are_captured_at_staging(
        self, connection: aiosqlite.Connection
    ) -> None:
        outbox, event_store = await _stores(connection)
        with bind_execution_context(run_id="r-producer", attempt_id="a-producer"):
            await outbox.stage(
                EventEnvelope(type="staged", workspace_id="ws-1", event_id="e-staged")
            )
        await connection.commit()

        # Published from somewhere else entirely, as a real publisher would be.
        with bind_execution_context(run_id="r-publisher", attempt_id="a-publisher"):
            assert await outbox.publish_pending(event_store) == 1

        stored = await event_store.get("e-staged")
        assert stored is not None
        assert stored.run_id == "r-producer"
        assert stored.attempt_id == "a-producer"

    async def test_a_publishers_execution_does_not_leak_onto_an_uncorrelated_event(
        self, connection: aiosqlite.Connection
    ) -> None:
        """Staged outside any execution, so there is nothing to capture. The
        event must reach the store naming no Run rather than the publisher's."""
        outbox, event_store = await _stores(connection)
        await outbox.stage(EventEnvelope(type="orphan", workspace_id="ws-1", event_id="e-orphan"))
        await connection.commit()

        with bind_execution_context(run_id="r-publisher", attempt_id="a-publisher"):
            assert await outbox.publish_pending(event_store) == 1

        stored = await event_store.get("e-orphan")
        assert stored is not None
        assert stored.run_id == ""
        assert stored.attempt_id == ""
        assert stored.correlation_id == ""
