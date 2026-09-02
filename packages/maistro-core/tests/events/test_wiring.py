"""Direct composition tests for canonical Event backend selection (#61).

``wire_canonical_events`` is the one place a process chooses its canonical Event
sequencing authority. These tests hold that selection to the #61 rule:
PostgreSQL when a pool is supplied, SQLite when a connection is, in-memory
otherwise — and never two authorities at once.
"""

from __future__ import annotations

from typing import Any

from maistro.events.bus import EventBus
from maistro.events.envelope import EventEnvelope, InMemoryEventStore, SqliteEventStore
from maistro.events.pg_envelope import PgEventStore
from maistro.events.publisher import CANONICAL_EVENT_METADATA, CanonicalEventPublisher
from maistro.events.wiring import wire_canonical_events


class _FakeTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeConnection:
    def __init__(self, statements: list[str]) -> None:
        self._statements = statements

    async def execute(self, sql: str, *args: Any) -> None:
        self._statements.append(sql)

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction()


class _Acquire:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self._connection

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakePgPool:
    """Pool double for the wiring question only: was the schema ensured?"""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self._connection = _FakeConnection(self.statements)

    def acquire(self) -> _Acquire:
        return _Acquire(self._connection)


async def test_without_pools_the_in_memory_store_is_the_authority() -> None:
    legacy_bus = EventBus()

    publisher = await wire_canonical_events(legacy_bus=legacy_bus)

    assert isinstance(publisher.store, InMemoryEventStore)
    persisted = await publisher.emit(
        EventEnvelope(event_id="wire-memory-1", type="run.started", workspace_id="ws-wire")
    )
    assert persisted.sequence == 1
    [projected] = legacy_bus.get_history()
    assert projected.event_id == "wire-memory-1"
    assert projected.payload[CANONICAL_EVENT_METADATA]["sequence"] == 1


async def test_a_supplied_db_pool_selects_the_sqlite_store_after_its_schema() -> None:
    import aiosqlite

    connection = await aiosqlite.connect(":memory:")
    try:
        publisher = await wire_canonical_events(db_pool=connection)

        assert isinstance(publisher.store, SqliteEventStore)
        persisted = await publisher.emit(
            EventEnvelope(event_id="wire-sqlite-1", type="run.started", workspace_id="ws-wire")
        )
        fetched = await publisher.store.get("wire-sqlite-1")
        assert persisted.sequence == 1
        assert fetched is not None
        assert fetched.sequence == 1
    finally:
        await connection.close()


async def test_a_supplied_pg_pool_selects_the_postgres_store_after_its_schema() -> None:
    pool = _FakePgPool()

    publisher = await wire_canonical_events(pg_pool=pool)

    assert isinstance(publisher.store, PgEventStore)
    assert any("pg_advisory_xact_lock" in sql for sql in pool.statements)
    assert any("CREATE TABLE IF NOT EXISTS canonical_event_log" in sql for sql in pool.statements)


async def test_a_pg_pool_takes_precedence_over_a_sqlite_connection() -> None:
    """Two durable backends supplied at once must not yield two authorities."""

    publisher = await wire_canonical_events(pg_pool=_FakePgPool(), db_pool=object())

    assert isinstance(publisher.store, PgEventStore)


async def test_the_wired_publisher_persists_before_notifying_legacy_consumers() -> None:
    legacy_bus = EventBus()
    publisher = await wire_canonical_events(legacy_bus=legacy_bus)

    assert isinstance(publisher, CanonicalEventPublisher)
    persisted = await publisher.emit(
        EventEnvelope(event_id="wire-composed-1", type="run.started", workspace_id="ws-wire")
    )

    assert await publisher.store.get("wire-composed-1") == persisted
    [projected] = legacy_bus.get_history()
    assert projected.event_id == persisted.event_id
    assert projected.timestamp == persisted.timestamp
