"""One suite over the in-memory and SQLite BacklogItem history stores (#101).

The in-memory store is the reference; running the same bodies against the
SQLite store is what makes "the durable journal behaves like the reference" a
comparison rather than a hope. Both are paired with a real Project scope
store, because the SQLite journal writes inside that store's transaction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.workspaces.backlog_history import (
    BacklogEventAlreadyExists,
    BacklogHistoryEvent,
    BacklogHistoryEventKind,
    BacklogHistoryStore,
    GoalLink,
    RunReference,
)


class _MemoryBackend:
    def __init__(self) -> None:
        from maistro.workspaces.backlog_history.store import InMemoryBacklogHistoryStore

        self.projects = InMemoryProjectScopeStore()
        self._store = InMemoryBacklogHistoryStore()

    async def store(self) -> BacklogHistoryStore:
        return self._store

    async def reopen(self) -> BacklogHistoryStore:
        return self._store

    async def close(self) -> None:
        return None


class _SqliteBackend:
    def __init__(self, tmp_path: object) -> None:
        self._path = tmp_path / "backlog-history.db"  # type: ignore[operator]
        self._connections: list[object] = []
        self.projects = None

    async def store(self) -> BacklogHistoryStore:
        import aiosqlite

        from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
        from maistro.workspaces.backlog_history.sqlite_store import SqliteBacklogHistoryStore

        conn = await aiosqlite.connect(self._path)
        self._connections.append(conn)
        self.projects = SqliteProjectScopeStore(conn)
        await self.projects.ensure_schema()
        store = SqliteBacklogHistoryStore(conn, project_store=self.projects)
        await store.ensure_schema()
        return store

    async def reopen(self) -> BacklogHistoryStore:
        for conn in self._connections:
            await conn.close()
        self._connections.clear()
        return await self.store()

    async def close(self) -> None:
        for conn in self._connections:
            await conn.close()


@pytest.fixture(params=["memory", "sqlite"])
async def backend(request: pytest.FixtureRequest, tmp_path: object) -> AsyncIterator[object]:
    made = _MemoryBackend() if request.param == "memory" else _SqliteBackend(tmp_path)
    try:
        yield made
    finally:
        await made.close()  # type: ignore[attr-defined]


def _event(item_id: str, kind: BacklogHistoryEventKind, **fields: object) -> BacklogHistoryEvent:
    return BacklogHistoryEvent(
        workspace_id="ws-a",
        project_id="p-1",
        item_id=item_id,
        kind=kind,
        **fields,  # type: ignore[arg-type]
    )


async def test_append_assigns_a_per_item_sequence(backend) -> None:
    store = await backend.store()
    first = await store.append(_event("item-1", BacklogHistoryEventKind.ITEM_RECORDED))
    second = await store.append(
        _event(
            "item-1",
            BacklogHistoryEventKind.STATUS_MOVED,
            from_status="proposed",
            to_status="accepted",
        )
    )
    other = await store.append(_event("item-2", BacklogHistoryEventKind.ITEM_RECORDED))

    assert (first.sequence, second.sequence, other.sequence) == (1, 2, 1)


async def test_history_for_item_is_ordered_and_scoped(backend) -> None:
    store = await backend.store()
    await store.append(_event("item-1", BacklogHistoryEventKind.ITEM_RECORDED))
    await store.append(_event("item-2", BacklogHistoryEventKind.ITEM_RECORDED))
    moved = await store.append(
        _event(
            "item-1",
            BacklogHistoryEventKind.STATUS_MOVED,
            from_status="proposed",
            to_status="accepted",
        )
    )

    history = await store.history_for_item("ws-a", "item-1")
    assert [event.sequence for event in history] == [1, 2]
    assert history[-1].event_id == moved.event_id

    only_moves = await store.history_for_item(
        "ws-a", "item-1", kind=BacklogHistoryEventKind.STATUS_MOVED
    )
    assert [event.event_id for event in only_moves] == [moved.event_id]
    assert await store.history_for_item("ws-b", "item-1") == []


async def test_history_for_workspace_filters_by_project_item_and_kind(backend) -> None:
    store = await backend.store()
    other_project = _event("item-1", BacklogHistoryEventKind.ITEM_RECORDED)
    await store.append(other_project.model_copy(update={"project_id": "p-2"}))
    await store.append(_event("item-1", BacklogHistoryEventKind.ITEM_RECORDED))
    await store.append(_event("item-2", BacklogHistoryEventKind.ITEM_RECORDED))

    listed = await store.history_for_workspace("ws-a", project_id="p-1")
    assert [event.item_id for event in listed] == ["item-1", "item-2"]
    assert all(event.project_id == "p-1" for event in listed)

    listed = await store.history_for_workspace("ws-a", project_id="p-1", item_id="item-2")
    assert [event.item_id for event in listed] == ["item-2"]

    await store.append(
        _event(
            "item-2",
            BacklogHistoryEventKind.REOPENED,
            reason="acceptance was not met",
        )
    )
    reopened = await store.history_for_workspace("ws-a", kind=BacklogHistoryEventKind.REOPENED)
    assert len(reopened) == 1
    assert reopened[0].reason == "acceptance was not met"


async def test_history_for_workspace_orders_per_item_by_sequence(backend) -> None:
    """Both backends answer the Workspace read per item, by that item's
    sequence — appending item-2's story first does not reorder the replay."""
    store = await backend.store()
    await store.append(_event("item-2", BacklogHistoryEventKind.ITEM_RECORDED))
    await store.append(_event("item-1", BacklogHistoryEventKind.ITEM_RECORDED))
    await store.append(
        _event(
            "item-1",
            BacklogHistoryEventKind.STATUS_MOVED,
            from_status="proposed",
            to_status="accepted",
        )
    )

    listed = await store.history_for_workspace("ws-a")
    assert [(event.item_id, event.sequence) for event in listed] == [
        ("item-1", 1),
        ("item-1", 2),
        ("item-2", 1),
    ]


async def test_duplicate_event_id_is_refused(backend) -> None:
    store = await backend.store()
    event = await store.append(_event("item-1", BacklogHistoryEventKind.ITEM_RECORDED))
    with pytest.raises(BacklogEventAlreadyExists):
        await store.append(event)


async def test_callers_get_copies_of_recorded_events(backend) -> None:
    store = await backend.store()
    event = await store.append(_event("item-1", BacklogHistoryEventKind.ITEM_RECORDED))
    tampered = event.model_copy(update={"summary": "rewritten"})
    history = await store.history_for_item("ws-a", "item-1")
    assert history[0].summary == ""
    assert tampered.summary == "rewritten"
    assert await store.history_for_item("ws-a", "item-1") != [tampered]


async def test_payload_round_trip_keeps_every_reference(backend) -> None:
    store = await backend.store()
    recorded = await store.append(
        _event(
            "item-1",
            BacklogHistoryEventKind.RUN_EVIDENCE_RECORDED,
            goal_link=GoalLink(goal_id="g-9", goal_revision=7),
            run_refs=(RunReference(run_id="run-1", node_run_id="nr-2", attempt_id="a-3"),),
            evaluation_refs=("eval-run-1",),
            reason="the first Run failed its acceptance check",
            actor_agent_id="agent-7",
        )
    )
    history = await backend.reopen() if isinstance(backend, _SqliteBackend) else store
    history = await history.history_for_item("ws-a", "item-1")
    assert len(history) == 1
    restored = history[0]
    assert restored == recorded
    assert restored.goal_link == GoalLink(goal_id="g-9", goal_revision=7)
    assert restored.run_refs == (
        RunReference(run_id="run-1", node_run_id="nr-2", attempt_id="a-3"),
    )
    assert restored.evaluation_refs == ("eval-run-1",)
    assert restored.actor_agent_id == "agent-7"
    assert restored.sequence == 1


async def test_history_survives_a_restart(backend) -> None:
    store = await backend.store()
    await store.append(_event("item-1", BacklogHistoryEventKind.ITEM_RECORDED))
    await store.append(
        _event(
            "item-1",
            BacklogHistoryEventKind.CLOSURE_RECORDED,
            evidence_refs=("spec:SPEC-001#AC-2", "artifact:report-1"),
        )
    )

    reopened_store = await backend.reopen()
    history = await reopened_store.history_for_item("ws-a", "item-1")
    assert [event.kind for event in history] == [
        BacklogHistoryEventKind.ITEM_RECORDED,
        BacklogHistoryEventKind.CLOSURE_RECORDED,
    ]
    # The sequence continues after a restart; a journal that restarted its
    # numbering would make item histories ambiguous.
    next_event = await reopened_store.append(
        _event("item-1", BacklogHistoryEventKind.REOPENED, reason="regression found")
    )
    assert next_event.sequence == 3
