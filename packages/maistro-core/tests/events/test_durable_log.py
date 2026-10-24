"""Tests for the durable append-only event log (SPEC-070226-b234)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from maistro.events.bus import Event, EventCategory
from maistro.events.durable_log import (
    EventLogStore,
    InMemoryEventLog,
    SqliteEventLog,
    append_from_bus_event,
)


class _FailingDeleteConnection:
    """aiosqlite wrapper whose execute() raises exactly on the purge DELETE.

    Every other statement (BEGIN IMMEDIATE, commits, rollbacks, the health
    probe's SELECTs) is delegated to the real connection, so the test drives
    one precise failure: the DELETE itself blowing up mid-transaction.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def execute(self, sql: str, *args: Any) -> Any:
        if "DELETE FROM event_log" in sql:
            raise RuntimeError("disk I/O error")
        return await self._conn.execute(sql, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


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

    async def test_sqlite_purge_is_bounded_and_honors_legal_hold(self, log: EventLogStore) -> None:
        if not isinstance(log, SqliteEventLog):
            pytest.skip("purge is a durable-store operation")
        await log.append("old.held", entity_id="held")
        await log.append("old.free", entity_id="free")
        removed = await log.purge_expired(
            before=time.time() + 1, limit=1, legal_hold_entity_ids=("held",)
        )
        assert removed == 1
        assert len(await log.query(limit=10)) == 1

    async def test_a_sqlite_purge_publishes_the_delivery_log_stored_volume(self) -> None:
        """The sweep contract's stored-volume clause for the delivery log:
        the purge counters are rates, so a delivery log nobody bounds looks
        exactly as healthy as one at steady state — the level is the signal
        the bound is actually being driven (#325)."""
        from maistro.observability import metrics as retention_health
        from maistro.observability.metrics import (
            retention_oldest_record_timestamp,
            retention_table_rows,
        )

        retention_health._LAST_PROBE.clear()

        def _series(metric: Any) -> list[float]:
            return [
                float(s["value"])
                for s in metric.collect()
                if s.get("labels", {}) == {"table": "event_log", "backend": "sqlite"}
            ]

        conn = await aiosqlite.connect(":memory:")
        try:
            store = SqliteEventLog(conn)
            await store.ensure_schema()
            old = time.time() - 10_000
            await store.append("old.event")
            # The append API stamps `time.time()`; backdate the first row so
            # the purge has an expired batch and the probe has a distinct
            # oldest survivor.
            await conn.execute("UPDATE event_log SET created_at = ?", (old,))
            await conn.commit()
            await store.append("fresh.event")

            assert await store.purge_expired(before=time.time() - 1) == 1

            assert _series(retention_table_rows) == [1.0]
            assert _series(retention_oldest_record_timestamp) == [pytest.approx(time.time(), abs=5)]

            # Draining the log removes the oldest-record series rather than
            # leaving the last value to stand in for history that is gone.
            retention_health._LAST_PROBE.clear()
            await store.purge_expired(before=time.time() + 1)
            assert _series(retention_table_rows) == [0.0]
            assert _series(retention_oldest_record_timestamp) == []
        finally:
            await conn.close()

    async def test_sqlite_purge_rejects_a_nonpositive_limit(self) -> None:
        """The bounded batch is bounded: a caller asking for a purge that
        deletes "no more than zero" rows has a broken sweep loop, and the
        guard must say so before touching the table."""
        conn = await aiosqlite.connect(":memory:")
        try:
            store = SqliteEventLog(conn)
            await store.ensure_schema()
            await store.append("old.event")
            with pytest.raises(ValueError, match="limit must be positive"):
                await store.purge_expired(before=time.time() + 1, limit=0)
            # The refusal deletes nothing and the log is intact.
            assert len(await store.query(limit=10)) == 1
        finally:
            await conn.close()

    async def test_a_failed_sqlite_purge_commits_nothing_and_leaves_the_store_usable(
        self,
    ) -> None:
        """A purge that blows up mid-transaction must raise, leave every row
        in place, and roll back — the connection is not left inside the
        aborted BEGIN IMMEDIATE, so the next statement on the store works.
        This is the no-partial-delete half of the #325 purge contract."""
        conn = await aiosqlite.connect(":memory:")
        try:
            store = SqliteEventLog(conn)
            await store.ensure_schema()
            await store.append("old.event")
            await store.append("other.event")

            failing = _FailingDeleteConnection(conn)
            with pytest.raises(RuntimeError, match="disk I/O error"):
                await SqliteEventLog(failing).purge_expired(  # type: ignore[arg-type]
                    before=time.time() + 1
                )

            # Nothing was deleted, and the rolled-back connection still
            # serves queries (a missing rollback would surface here as
            # "cannot start a transaction within a transaction").
            assert len(await store.query(limit=10)) == 2
            assert await store.append("after.failure") is not None
        finally:
            await conn.close()

    async def test_a_second_purge_inside_the_probe_interval_costs_no_probe(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The stored-volume probe is the amortized cost of the sweep: two
        purges inside one probe interval sample the table once (#325)."""
        import maistro.events.durable_log as durable_log_module
        from maistro.observability import metrics as retention_health

        retention_health._LAST_PROBE.clear()
        samples: list[str] = []
        real_sample = durable_log_module.sqlite_table_sample

        async def counting_sample(conn: Any, table: str, *args: Any, **kwargs: Any) -> Any:
            samples.append(table)
            return await real_sample(conn, table, *args, **kwargs)

        monkeypatch.setattr(durable_log_module, "sqlite_table_sample", counting_sample)

        conn = await aiosqlite.connect(":memory:")
        try:
            store = SqliteEventLog(conn)
            await store.ensure_schema()
            await store.append("e.1")
            assert await store.purge_expired(before=time.time() + 1) == 1
            assert samples == ["event_log"]

            # Inside the interval: the purge still runs, the probe does not.
            await store.append("e.2")
            assert await store.purge_expired(before=time.time() + 1) == 1
            assert samples == ["event_log"]
        finally:
            await conn.close()


class TestReplayCursor:
    async def test_acknowledgement_is_monotonic(self, log: EventLogStore) -> None:
        assert await log.get_replay_cursor("reactor") == 0
        assert await log.acknowledge_replay("reactor", 4) == 4
        assert await log.acknowledge_replay("reactor", 2) == 4
        assert await log.get_replay_cursor("reactor") == 4

    async def test_negative_acknowledgement_is_rejected(self, log: EventLogStore) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            await log.acknowledge_replay("reactor", -1)


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


async def test_sqlite_replay_cursor_survives_restart(tmp_path: Path) -> None:
    database = tmp_path / "event-log.db"
    first_connection = await aiosqlite.connect(database)
    first = SqliteEventLog(first_connection)
    await first.ensure_schema()
    event = await first.append("agent.created")
    assert await first.acknowledge_replay("reactor", event.id) == event.id
    await first_connection.close()

    restarted_connection = await aiosqlite.connect(database)
    restarted = SqliteEventLog(restarted_connection)
    await restarted.ensure_schema()
    try:
        assert await restarted.get_replay_cursor("reactor") == event.id
    finally:
        await restarted_connection.close()


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
