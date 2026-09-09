"""Transactional outbox tests for canonical event publication."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import aiosqlite
import pytest

from maistro.events.envelope import EventEnvelope, SqliteEventStore
from maistro.events.outbox import SqliteEventOutbox
from maistro.observability.correlation import bind_execution_context


@pytest.fixture
async def connection() -> AsyncIterator[aiosqlite.Connection]:
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("CREATE TABLE domain_state (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
    await conn.commit()
    yield conn
    await conn.close()


async def _stores(
    connection: aiosqlite.Connection,
    **outbox_kwargs: Any,
) -> tuple[SqliteEventOutbox, SqliteEventStore]:
    outbox = SqliteEventOutbox(connection, **outbox_kwargs)
    event_store = SqliteEventStore(connection)
    await outbox.ensure_schema()
    await event_store.ensure_schema()
    return outbox, event_store


def _event(
    event_type: str,
    event_id: str,
    *,
    workspace_id: str = "ws-1",
) -> EventEnvelope:
    return EventEnvelope(
        type=event_type,
        workspace_id=workspace_id,
        run_id="run-1",
        event_id=event_id,
    )


async def _row(connection: aiosqlite.Connection, event_id: str) -> dict[str, Any]:
    """Return the outbox row's fault-state columns keyed by column name."""
    cursor = await connection.execute(
        """SELECT outbox_id, stream_id, attempts, last_error, next_attempt_at,
                  published_at, failed_at
           FROM canonical_event_outbox WHERE event_id = ?""",
        (event_id,),
    )
    values = await cursor.fetchone()
    assert values is not None
    names = (
        "outbox_id",
        "stream_id",
        "attempts",
        "last_error",
        "next_attempt_at",
        "published_at",
        "failed_at",
    )
    return dict(zip(names, values, strict=True))


class _PoisonedEventStore(SqliteEventStore):
    """A real EventStore whose append fails deterministically for chosen IDs.

    The failure happens before the store touches its transaction, so it models
    a durable append that cannot commit -- the deterministic poison the old
    drain turned into a permanent head-of-line stall (#1162).
    """

    def __init__(self, conn: aiosqlite.Connection, poison: frozenset[str]) -> None:
        super().__init__(conn)
        self._poison = poison

    async def append(self, event: EventEnvelope) -> EventEnvelope:
        if event.event_id in self._poison:
            raise RuntimeError(f"poisoned append for {event.event_id}")
        return await super().append(event)


class _Clock:
    """Manually advanced clock so backoff gating is testable without sleeping."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def _domain_value(connection: aiosqlite.Connection) -> str | None:
    cursor = await connection.execute("SELECT value FROM domain_state WHERE id = 'run-1'")
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


class TestPoisonRowIsolation:
    """One deterministically failing append must not starve the outbox (#1162).

    Per-stream order is preserved -- a failing row holds back only its own
    stream, and only until it publishes or dead-letters -- while rows of
    unrelated streams keep flowing, and the failing row itself converges on a
    bounded, durable dead-letter disposition instead of being retried forever.
    """

    async def test_failing_head_does_not_block_independent_rows(
        self, connection: aiosqlite.Connection
    ) -> None:
        outbox, event_store = await _stores(connection)
        poisoned = _PoisonedEventStore(connection, frozenset({"evt-poison"}))
        await outbox.stage(_event("run.updated", "evt-poison", workspace_id="ws-a"))
        await outbox.stage(_event("run.updated", "evt-b", workspace_id="ws-b"))
        await outbox.stage(_event("run.updated", "evt-c", workspace_id="ws-c"))
        await connection.commit()

        assert await outbox.publish_pending(poisoned) == 2

        row = await _row(connection, "evt-poison")
        assert row["attempts"] == 1
        assert "poisoned append for evt-poison" in str(row["last_error"])
        assert row["failed_at"] is None
        assert row["published_at"] is None
        assert await outbox.pending_count() == 1
        assert await event_store.get("evt-poison") is None
        assert await event_store.get("evt-b") is not None
        assert await event_store.get("evt-c") is not None

    async def test_failing_row_dead_letters_after_attempt_bound(
        self, connection: aiosqlite.Connection
    ) -> None:
        outbox, event_store = await _stores(connection, retry_backoff_seconds=0.0)
        poisoned = _PoisonedEventStore(connection, frozenset({"evt-poison"}))
        await outbox.stage(_event("run.updated", "evt-poison"))
        await connection.commit()

        for expected_attempts in (1, 2):
            assert await outbox.publish_pending(poisoned) == 0
            row = await _row(connection, "evt-poison")
            assert row["attempts"] == expected_attempts
            assert row["failed_at"] is None

        # The third recorded attempt reaches the bound: terminal disposition.
        assert await outbox.publish_pending(poisoned) == 0
        row = await _row(connection, "evt-poison")
        assert row["attempts"] == 3
        assert row["failed_at"] is not None
        assert await outbox.pending_count() == 0

        # Dead-lettered rows are never attempted again.
        assert await outbox.publish_pending(poisoned) == 0
        assert (await _row(connection, "evt-poison"))["attempts"] == 3

        letters = await outbox.dead_letters()
        assert len(letters) == 1
        assert letters[0].event_id == "evt-poison"
        assert letters[0].stream_id == "workspace:ws-1"
        assert letters[0].attempts == 3
        assert "poisoned append for evt-poison" in letters[0].last_error
        assert await event_store.get("evt-poison") is None

    async def test_dead_letter_releases_same_stream_followers(
        self, connection: aiosqlite.Connection
    ) -> None:
        outbox, event_store = await _stores(connection, max_attempts=2, retry_backoff_seconds=0.0)
        poisoned = _PoisonedEventStore(connection, frozenset({"evt-a1"}))
        await outbox.stage(_event("run.updated", "evt-a1", workspace_id="ws-a"))
        await outbox.stage(_event("run.updated", "evt-a2", workspace_id="ws-a"))
        await outbox.stage(_event("run.updated", "evt-b", workspace_id="ws-b"))
        await connection.commit()

        # Pass 1: the poisoned head burns attempt 1; its same-stream follower
        # is held back (per-stream FIFO) while the unrelated stream publishes.
        assert await outbox.publish_pending(poisoned) == 1
        assert await event_store.get("evt-b") is not None
        assert await event_store.get("evt-a2") is None
        assert (await _row(connection, "evt-a1"))["attempts"] == 1
        assert (await _row(connection, "evt-a2"))["published_at"] is None

        # Pass 2: the head reaches its bound and dead-letters, releasing the
        # stream; the follower publishes in that same pass.
        assert await outbox.publish_pending(poisoned) == 1
        letters = await outbox.dead_letters()
        assert [letter.event_id for letter in letters] == ["evt-a1"]
        assert letters[0].attempts == 2

        stored = await event_store.get("evt-a2")
        assert stored is not None
        # The quarantined event never occupies a stream sequence: the stream
        # continues from the dead letter rather than closing behind it.
        assert stored.sequence == 1
        history = await event_store.list_stream("workspace:ws-a")
        assert [item.event_id for item in history] == ["evt-a2"]

    async def test_backoff_defers_failed_row_retry(self, connection: aiosqlite.Connection) -> None:
        clock = _Clock()
        outbox, event_store = await _stores(
            connection, max_attempts=3, retry_backoff_seconds=10.0, clock=clock
        )
        poisoned = _PoisonedEventStore(connection, frozenset({"evt-poison"}))
        await outbox.stage(_event("run.updated", "evt-poison"))
        await connection.commit()

        assert await outbox.publish_pending(poisoned) == 0
        row = await _row(connection, "evt-poison")
        assert row["attempts"] == 1
        assert row["next_attempt_at"] == clock.now + 10.0

        # Before the backoff lapses the row is not a drain candidate at all.
        clock.advance(5.0)
        assert await outbox.publish_pending(poisoned) == 0
        assert (await _row(connection, "evt-poison"))["attempts"] == 1

        clock.advance(5.0)
        assert await outbox.publish_pending(poisoned) == 0
        assert (await _row(connection, "evt-poison"))["attempts"] == 2

        # A same-stream follower must not leapfrog a head that is merely
        # waiting out its backoff.
        await outbox.stage(_event("run.updated", "evt-follower"))
        await connection.commit()
        clock.advance(1.0)
        assert await outbox.publish_pending(poisoned) == 0
        assert (await _row(connection, "evt-follower"))["published_at"] is None

        # Attempt 3 dead-letters the head and releases the follower.
        clock.advance(9.0)
        assert await outbox.publish_pending(poisoned) == 1
        assert [letter.event_id for letter in await outbox.dead_letters()] == ["evt-poison"]
        stored = await event_store.get("evt-follower")
        assert stored is not None
        assert stored.sequence == 1

    async def test_republish_and_unrelated_failure_never_duplicate(
        self, connection: aiosqlite.Connection
    ) -> None:
        outbox, event_store = await _stores(connection)
        await outbox.stage(_event("attempt.completed", "evt-x"))
        await connection.commit()

        assert await outbox.publish_pending(event_store) == 1
        first = await event_store.get("evt-x")
        assert first is not None
        assert first.sequence == 1

        # Redelivery of a published row appends nothing.
        assert await outbox.publish_pending(event_store) == 0

        # An unrelated poison row exhausting its bound must not disturb evt-x.
        poisoned = _PoisonedEventStore(connection, frozenset({"evt-poison"}))
        await outbox.stage(_event("run.updated", "evt-poison", workspace_id="ws-2"))
        await connection.commit()
        for _ in range(3):
            assert await outbox.publish_pending(poisoned) == 0

        assert await outbox.publish_pending(event_store) == 0
        assert await event_store.get("evt-x") == first
        history = await event_store.list_stream("workspace:ws-1")
        assert [item.event_id for item in history] == ["evt-x"]

    async def test_ensure_schema_upgrades_legacy_table(
        self, connection: aiosqlite.Connection
    ) -> None:
        await connection.executescript(
            """
            CREATE TABLE canonical_event_outbox (
                outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                event_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                published_at REAL
            );
            """
        )
        await connection.commit()
        legacy_event = _event("run.updated", "evt-legacy")
        await connection.execute(
            """INSERT INTO canonical_event_outbox (event_id, event_json, created_at)
               VALUES (?, ?, ?)""",
            (
                "evt-legacy",
                json.dumps(legacy_event.to_dict(), sort_keys=True),
                time.time(),
            ),
        )
        await connection.commit()

        outbox, event_store = await _stores(connection)

        # The upgrade found the legacy shape, added the fault-state columns,
        # and derived the legacy row's stream from its stored envelope.
        row = await _row(connection, "evt-legacy")
        assert row["stream_id"] == "workspace:ws-1"
        assert row["attempts"] == 0
        assert row["failed_at"] is None

        await outbox.stage(_event("run.updated", "evt-new"))
        await connection.commit()
        assert await outbox.publish_pending(event_store) == 2
        assert await event_store.get("evt-legacy") is not None
        assert await event_store.get("evt-new") is not None
