"""`DurableRunStore` over the canonical spine, not beside it (#44).

The interface survives the convergence; the second system of record does not.
A record written here is split — Run, NodeRuns and Attempts go back to the
`RunStore` that already holds their identities, and the Graph continuation is
persisted beside them — and a record read back is assembled from both halves.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import aiosqlite
import pytest
from pydantic import BaseModel

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
    SqliteGraphContinuationStore,
    resume_durable_graph,
    run_durable_graph,
)
from maistro.graph.durable_runs.continuation import GraphContinuation, GraphContinuationStore
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes import BaseNode, NodeContext, pause_until
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import RunStatus
from maistro.runs.store import RunIntegrityError


class _StepIn(BaseModel):
    pass


class _StepOut(BaseModel):
    text: str = "done"


class _Step(BaseNode[_StepIn, _StepOut]):
    kind: ClassVar[str] = "test.canonical_store.step"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _StepIn
    output_schema: ClassVar[type[BaseModel]] = _StepOut

    async def _execute(self, inputs: _StepIn, ctx: NodeContext) -> _StepOut:
        return _StepOut()


class _Ask(BaseNode[_StepIn, _StepOut]):
    kind: ClassVar[str] = "test.canonical_store.ask"
    kind_category: ClassVar = "hitl"
    input_schema: ClassVar[type[BaseModel]] = _StepIn
    output_schema: ClassVar[type[BaseModel]] = _StepOut

    async def _execute(self, inputs: _StepIn, ctx: NodeContext) -> _StepOut:
        answered = ((ctx.metadata or {}).get("hitl_answers") or {}).get(ctx.node_id)
        if answered is not None:
            return _StepOut(text=str(answered.get("answer") or ""))
        pause_until("awaiting_human_answer", metadata={"question": "Continue?"})
        return _StepOut(text="UNREACHABLE")


async def _spine() -> tuple[InMemoryRunStore, str, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-canonical-store")
    project = await projects.create(
        workspace_id="ws-canonical-store", parent_project_id=root.project_id, name="Graphs"
    )
    return InMemoryRunStore(project_store=projects), "ws-canonical-store", project.project_id


def _graph(workspace_id: str, project_id: str, node_type: str, name: str = "one step") -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name=name,
        nodes=[Node(node_id="step", node_type=node_type)],
    )


def _resolve(node: BaseNode[Any, Any]) -> Any:
    return lambda node_id, graph: node


async def _admit(run_store: InMemoryRunStore, graph: Graph) -> str:
    """Admit the Run, the way a producer does, then hand traversal its id."""
    run = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    return run.run_id


@pytest.mark.ac("ADR-082826-d9f5/AC-4")
async def test_a_run_executed_through_this_store_is_assembled_from_the_spine() -> None:
    run_store, workspace_id, project_id = await _spine()
    store = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())

    graph = _graph(workspace_id, project_id, _Step.kind)
    record = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolve(_Step()),
        run_id=await _admit(run_store, graph),
        run_store=run_store,
    )

    assert record.status is RunStatus.COMPLETED
    reread = await store.get(record.run_id)
    assert reread is not None
    assert reread.run.run_id == record.run_id
    assert [item.node_run_id for item in reread.node_runs] == [
        item.node_run_id for item in record.node_runs
    ]
    assert [item.attempt_id for item in reread.attempts] == [
        item.attempt_id for item in record.attempts
    ]
    assert reread.graph_state.run_id == record.run_id


@pytest.mark.ac("ADR-082826-d9f5/AC-4")
async def test_the_spine_is_the_only_copy_of_the_execution_history() -> None:
    """Deleting the continuation leaves the Run intact, because the Run was
    never stored here — the point of the convergence."""
    run_store, workspace_id, project_id = await _spine()
    continuations = InMemoryGraphContinuationStore()
    store = CanonicalDurableRunStore(run_store, continuations)

    graph = _graph(workspace_id, project_id, _Step.kind)
    record = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolve(_Step()),
        run_id=await _admit(run_store, graph),
        run_store=run_store,
    )

    canonical = await run_store.get_run(record.run_id)
    assert canonical is not None and canonical.status is RunStatus.COMPLETED
    node_runs = await run_store.list_node_runs(record.run_id)
    assert [item.status for item in node_runs] == [RunStatus.COMPLETED]
    assert await run_store.list_attempts(node_runs[0].node_run_id)


@pytest.mark.ac("ADR-082826-d9f5/AC-4")
async def test_a_run_the_spine_never_saw_is_refused_rather_than_minted() -> None:
    """An adapter would have created a second Run here. That is the duplicate
    identity this store exists to remove, so it says no instead."""
    run_store, workspace_id, project_id = await _spine()
    store = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())

    with pytest.raises(RunIntegrityError, match="canonical spine"):
        await run_durable_graph(
            _graph(workspace_id, project_id, _Step.kind),
            store=store,
            node_resolver=_resolve(_Step()),
        )
    assert await run_store.list_by_status(RunStatus.RUNNING, limit=10) == []


async def _pause_answer_resume(
    continuations: GraphContinuationStore,
) -> None:
    run_store, workspace_id, project_id = await _spine()
    store = CanonicalDurableRunStore(run_store, continuations)
    graph = _graph(workspace_id, project_id, _Ask.kind, name="ask once")

    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolve(_Ask()),
        run_id=await _admit(run_store, graph),
        run_store=run_store,
    )
    assert paused.status is RunStatus.PAUSED
    assert [item.run_id for item in await store.list_by_status(RunStatus.PAUSED)] == [paused.run_id]

    answered = await store.submit_hitl_answer(paused.run_id, "step", {"answer": "yes"})
    assert answered.status is RunStatus.QUEUED
    assert answered.hitl_answers["step"]["answer"] == "yes"

    resumed = await resume_durable_graph(
        paused.run_id,
        store=store,
        node_resolver=_resolve(_Ask()),
        run_store=run_store,
    )
    assert resumed.status is RunStatus.COMPLETED
    settled = await run_store.get_run(paused.run_id)
    assert settled is not None and settled.status is RunStatus.COMPLETED
    assert [item.run_id for item in await store.list_for_project(project_id)] == [paused.run_id]


@pytest.mark.ac("ADR-082826-d9f5/AC-5")
async def test_a_paused_run_is_answered_and_resumed_through_the_projection() -> None:
    await _pause_answer_resume(InMemoryGraphContinuationStore())


@pytest.mark.ac("ADR-082826-d9f5/AC-5")
async def test_the_same_holds_when_the_continuation_outlives_the_process(
    tmp_path: Path,
) -> None:
    """The continuation is the half that has to survive a restart; the spine
    already had its own durable stores."""
    async with aiosqlite.connect(tmp_path / "continuations.db") as conn:
        store = SqliteGraphContinuationStore(conn)
        await store.ensure_schema()
        await _pause_answer_resume(store)


@pytest.mark.ac("ADR-082826-d9f5/AC-4")
async def test_an_unknown_run_is_absent_rather_than_an_empty_record() -> None:
    run_store, _workspace_id, _project_id = await _spine()
    store = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())

    assert await store.get("no-such-run") is None
    with pytest.raises(KeyError):
        await store.submit_hitl_answer("no-such-run", "step", {"answer": "x"})


async def _listing_parity(store: GraphContinuationStore) -> None:
    """Both listings, over both continuation backends, agree on the same rows.

    The project filter is the half that has no other caller yet: `list_for_project`
    reaches it, but a status listing scoped to one project is what the HITL door
    asks for once more than one project shares a store. Exercised here so the
    SQLite spelling of it is a query that has run, not a query that parses.
    """
    for index, (run_id, project_id, status) in enumerate(
        [
            ("run-a", "proj-1", RunStatus.PAUSED),
            ("run-b", "proj-2", RunStatus.PAUSED),
            ("run-c", "proj-1", RunStatus.RUNNING),
        ]
    ):
        await store.create(
            GraphContinuation(
                run_id=run_id,
                graph_state=GraphExecutionState(run_id=run_id),
                status=status,
                project_id=project_id,
                created_at=datetime(2026, 8, 29, tzinfo=UTC) + timedelta(minutes=index),
            )
        )

    assert await store.list_run_ids_by_status(RunStatus.PAUSED) == ["run-a", "run-b"]
    assert await store.list_run_ids_by_status(RunStatus.PAUSED, project_id="proj-2") == ["run-b"]
    assert await store.list_run_ids_by_status(RunStatus.PAUSED, limit=1) == ["run-a"]
    assert await store.list_run_ids_for_project("proj-1") == ["run-c", "run-a"]
    assert await store.list_run_ids_for_project("proj-1", limit=1) == ["run-c"]


async def test_the_continuation_listings_agree_in_memory() -> None:
    await _listing_parity(InMemoryGraphContinuationStore())


async def test_the_continuation_listings_agree_on_sqlite(tmp_path: Path) -> None:
    async with aiosqlite.connect(tmp_path / "listings.db") as conn:
        store = SqliteGraphContinuationStore(conn)
        await store.ensure_schema()
        await _listing_parity(store)
