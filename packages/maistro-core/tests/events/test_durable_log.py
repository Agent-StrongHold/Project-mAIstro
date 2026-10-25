"""Tests for the durable append-only event log (SPEC-070226-b234)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.events.bus import Event, EventCategory
from maistro.events.durable_log import (
    EventLogStore,
    InMemoryEventLog,
    SqliteEventLog,
    append_from_bus_event,
)


@pytest.fixture(params=["memory", "sqlite"])
async def log(request: pytest.FixtureRequest) -> AsyncIterator[EventLogStore]:
    if request.param == "memory":
        yield InMemoryEventLog()
    else:
        conn = await aiosqlite.connect(":memory:")
        store = SqliteEventLog(conn)
        await store.ensure_schema()
        yield store
        await conn.close()


class TestAppend:
    @pytest.mark.ac("SPEC-070226-b234/AC-1")
    async def test_append_assigns_monotonic_ids(self, log: EventLogStore) -> None:
        e1 = await log.append("agent.created", payload={"a": 1})
        e2 = await log.append("agent.deleted")
        assert e2.id > e1.id

    @pytest.mark.ac("SPEC-070226-b234/AC-1")
    async def test_append_persists_fields(self, log: EventLogStore) -> None:
        e = await log.append(
            "task.completed",
            entity_type="task",
            entity_id="t-1",
            payload={"result": "ok"},
            source="core",
        )
        got = await log.get(e.id)
        assert got is not None
        assert got.event_type == "task.completed"
        assert got.entity_type == "task"
        assert got.entity_id == "t-1"
        assert got.payload == {"result": "ok"}
        assert got.source == "core"
        assert got.created_at == pytest.approx(time.time(), abs=5)

    async def test_get_missing_returns_none(self, log: EventLogStore) -> None:
        assert await log.get(999) is None

    @pytest.mark.ac("SPEC-070226-b234/AC-1")
    async def test_no_lost_events(self, log: EventLogStore) -> None:
        for i in range(50):
            await log.append(f"e.{i}")
        events = await log.query(limit=100)
        assert len(events) == 50


class TestQuery:
    async def test_filter_by_type(self, log: EventLogStore) -> None:
        await log.append("agent.created")
        await log.append("task.created")
        await log.append("agent.created")
        events = await log.query(event_type="agent.created")
        assert len(events) == 2
        assert all(e.event_type == "agent.created" for e in events)

    async def test_pagination_after_id(self, log: EventLogStore) -> None:
        ids = [(await log.append("e.x")).id for _ in range(10)]
        page1 = await log.query(limit=4)
        assert [e.id for e in page1] == ids[:4]
        page2 = await log.query(after_id=page1[-1].id, limit=4)
        assert [e.id for e in page2] == ids[4:8]
        page3 = await log.query(after_id=page2[-1].id, limit=4)
        assert [e.id for e in page3] == ids[8:]

    async def test_time_window(self, log: EventLogStore) -> None:
        e = await log.append("e.time")
        assert await log.query(since=e.created_at - 1) != []
        assert await log.query(since=e.created_at + 100) == []
        assert await log.query(until=e.created_at - 100) == []

    @pytest.mark.ac("SPEC-070226-b234/AC-1")
    async def test_ascending_order(self, log: EventLogStore) -> None:
        for _ in range(5):
            await log.append("e.o")
        events = await log.query()
        assert [e.id for e in events] == sorted(e.id for e in events)


def test_append_from_bus_event() -> None:
    ev = Event(
        category=EventCategory.AGENT,
        event_type="agent.delegated",
        source="conductor",
        payload={"k": "v"},
        correlation_id="c1",
    )
    kwargs = append_from_bus_event(ev)
    assert kwargs == {
        "event_type": "agent.delegated",
        "entity_type": "agent",
        "entity_id": "c1",
        "payload": {"k": "v"},
        "source": "conductor",
    }
