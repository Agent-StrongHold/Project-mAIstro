"""PostgreSQL evidence for canonical Workspace Event ordering (#61)."""

from __future__ import annotations

import asyncio
import os
from typing import Any
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


class _FakeTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeConnection:
    """Connection double answering the canonical_event_log questions asked."""

    def __init__(self, pool: _FakeAsyncpgPool) -> None:
        self._pool = pool

    async def execute(self, sql: str, *args: object) -> None:
        self._pool.statements.append(sql)

    async def fetchrow(self, sql: str, *args: object) -> dict[str, Any] | None:
        self._pool.statements.append(sql)
        if "WHERE event_id = $1" in sql:
            return self._pool.rows.get(str(args[0]))
        return None

    async def fetchval(self, sql: str, *args: object) -> int:
        self._pool.statements.append(sql)
        return self._pool.next_sequence

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction()


class _Acquire:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self._connection

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeAsyncpgPool:
    """Pool double for the guard clauses, so they hold on every laptop run.

    The behavioral evidence against a real PostgreSQL lives above; these legs
    keep the defensive paths — preset sequence, unknown ids, degenerate limits —
    covered where no server exists, not only in the CI job that owns one.
    """

    def __init__(self, rows: dict[str, dict[str, Any]] | None = None) -> None:
        self.statements: list[str] = []
        self.rows: dict[str, dict[str, Any]] = rows or {}
        self.next_sequence = 1
        self._connection = _FakeConnection(self)

    def acquire(self) -> _Acquire:
        return _Acquire(self._connection)

    async def fetchrow(self, sql: str, *args: object) -> dict[str, Any] | None:
        self.statements.append(sql)
        return self.rows.get(str(args[0]))


async def test_ensure_schema_locks_then_creates_the_canonical_table() -> None:
    pool = _FakeAsyncpgPool()

    await PgEventStore(pool).ensure_schema()

    assert any("pg_advisory_xact_lock" in sql for sql in pool.statements)
    assert any("CREATE TABLE IF NOT EXISTS canonical_event_log" in sql for sql in pool.statements)


async def test_append_refuses_an_envelope_that_already_carries_a_sequence() -> None:
    store = PgEventStore(_FakeAsyncpgPool())

    with pytest.raises(ValueError) as exc:
        await store.append(
            EventEnvelope(event_id="preset", type="run.started", workspace_id="ws-a", sequence=7)
        )

    assert "sequence is store-assigned and must be None on append" in str(exc.value)


async def test_get_returns_none_for_an_unknown_event_id() -> None:
    assert await PgEventStore(_FakeAsyncpgPool()).get("no-such-event") is None


async def test_get_round_trips_a_stored_row_with_object_jsonb_columns() -> None:
    row = {
        "event_id": "evt-1",
        "stream_id": "workspace:ws-a",
        "sequence": 3,
        "type": "run.started",
        "timestamp": 1234.5,
        "workspace_id": "ws-a",
        "stream_scope": "",
        "project_id": "proj-1",
        "run_id": "run-1",
        "node_run_id": "node-1",
        "attempt_id": "attempt-1",
        "invocation_id": "inv-1",
        "session_id": "sess-1",
        "correlation_id": "run-1",
        "causation_id": "evt-0",
        "source": "recovery",
        "actor_id": "actor-1",
        # asyncpg configured with a JSONB-to-object codec hands back dicts, not strings.
        "payload": {"disposition": "parked"},
        "provenance": {"legacy_event_category": "system"},
    }
    pool = _FakeAsyncpgPool(rows={"evt-1": row})

    event = await PgEventStore(pool).get("evt-1")

    assert event is not None
    assert event.event_id == "evt-1"
    assert event.sequence == 3
    assert event.timestamp == 1234.5
    assert event.workspace_id == "ws-a"
    assert event.stream_id == "workspace:ws-a"
    assert event.payload == {"disposition": "parked"}
    assert event.provenance == {"legacy_event_category": "system"}


async def test_list_stream_with_a_degenerate_limit_issues_no_query() -> None:
    pool = _FakeAsyncpgPool()

    assert await PgEventStore(pool).list_stream("workspace:ws-a", limit=0) == []
    assert pool.statements == []


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
