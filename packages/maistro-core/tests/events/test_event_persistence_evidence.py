"""Durability evidence for the canonical Workspace event sequence authority."""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from maistro.events.envelope import EventEnvelope, SqliteEventStore


async def _open_store(path: Path) -> tuple[aiosqlite.Connection, SqliteEventStore]:
    connection = await aiosqlite.connect(path)
    store = SqliteEventStore(connection)
    await store.ensure_schema()
    return connection, store


async def test_workspace_sequence_survives_store_restart(tmp_path: Path) -> None:
    """A new store/connection must continue the persisted Workspace sequence."""
    database = tmp_path / "events.db"

    first_connection, first_store = await _open_store(database)
    try:
        first = await first_store.append(
            EventEnvelope(
                type="run.started",
                workspace_id="workspace-1",
                run_id="run-1",
                event_id="event-before-restart",
            )
        )
        assert first.sequence == 1
    finally:
        await first_connection.close()

    restarted_connection, restarted_store = await _open_store(database)
    try:
        second = await restarted_store.append(
            EventEnvelope(
                type="run.started",
                workspace_id="workspace-1",
                run_id="run-2",
                event_id="event-after-restart",
            )
        )
        history = await restarted_store.list_stream("workspace:workspace-1")

        assert second.sequence == 2
        assert [event.sequence for event in history] == [1, 2]
        assert [event.event_id for event in history] == [
            "event-before-restart",
            "event-after-restart",
        ]
    finally:
        await restarted_connection.close()


async def test_workspace_sequence_serializes_across_store_connections(tmp_path: Path) -> None:
    """Independent store instances must share the database sequence authority."""
    database = tmp_path / "events.db"
    connection_a, store_a = await _open_store(database)
    connection_b, store_b = await _open_store(database)

    try:
        events = [
            EventEnvelope(
                type="node.progress",
                workspace_id="workspace-1",
                run_id=f"run-{index % 3}",
                event_id=f"event-{index}",
            )
            for index in range(12)
        ]
        persisted = await asyncio.gather(
            *(
                (store_a if index % 2 == 0 else store_b).append(event)
                for index, event in enumerate(events)
            )
        )
        history = await store_a.list_stream("workspace:workspace-1", limit=100)

        sequences = [event.sequence for event in persisted]
        assert all(sequence is not None for sequence in sequences)
        assert sorted(sequence for sequence in sequences if sequence is not None) == list(
            range(1, 13)
        )
        assert [event.sequence for event in history] == list(range(1, 13))
        assert {event.event_id for event in history} == {event.event_id for event in events}
    finally:
        await connection_a.close()
        await connection_b.close()
