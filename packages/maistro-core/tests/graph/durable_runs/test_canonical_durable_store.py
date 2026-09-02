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
from maistro.graph.durable_runs.continuation import (
    GraphContinuation,
    GraphContinuationStore,
)
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


async def _reconcile_spine() -> tuple[
    CanonicalDurableRunStore,
    InMemoryRunStore,
    InMemoryGraphContinuationStore,
    str,
    str,
]:
    run_store, workspace_id, project_id = await _spine()
    continuations = InMemoryGraphContinuationStore()
    return (
        CanonicalDurableRunStore(run_store, continuations),
        run_store,
        continuations,
        workspace_id,
        project_id,
    )


async def _continued_run(
    run_store: InMemoryRunStore,
    continuations: InMemoryGraphContinuationStore,
    graph: Graph,
    *,
    continuation_status: RunStatus,
    run_status: RunStatus | None = None,
) -> str:
    """Admit a Run, drive it to `run_status`, and persist a continuation."""
    run = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    if run_status is not None and run_status is not RunStatus.QUEUED:
        await run_store.transition_run(run.run_id, RunStatus.RUNNING)
        if run_status is not RunStatus.RUNNING:
            await run_store.transition_run(run.run_id, run_status)
    await continuations.create(
        GraphContinuation(
            run_id=run.run_id,
            graph_state=GraphExecutionState(run_id=run.run_id, active_node_ids=("step",)),
            status=continuation_status,
            project_id=graph.project_id,
            created_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    return run.run_id


@pytest.mark.ac("ADR-082826-d9f5/AC-4")
async def test_reconcile_purges_a_continuation_whose_run_left_the_spine() -> None:
    """A continuation whose Run was purged is evidence of nothing -- keeping it
    would let a later Run with the same id inherit stale traversal state."""
    store, _run_store, continuations, _workspace_id, _project_id = await _reconcile_spine()
    await continuations.create(
        GraphContinuation(
            run_id="purged-before-checkpointing",
            graph_state=GraphExecutionState(run_id="purged-before-checkpointing"),
            status=RunStatus.WAITING,
        )
    )

    assert await store.reconcile_persistence() == 1
    assert await continuations.get("purged-before-checkpointing") is None
    assert await store.reconcile_persistence() == 0


async def test_reconcile_stays_bounded_when_the_budget_runs_out_mid_scan() -> None:
    """The repair is budgeted so one tick cannot lock the table behind a
    decade of crash residue: a second orphan simply waits for the next tick."""
    store, _run_store, continuations, _workspace_id, _project_id = await _reconcile_spine()
    for run_id in ("orphan-one", "orphan-two"):
        await continuations.create(
            GraphContinuation(
                run_id=run_id,
                graph_state=GraphExecutionState(run_id=run_id),
                status=RunStatus.WAITING,
            )
        )

    assert await store.reconcile_persistence(limit=1) == 1
    survivors = [
        run_id
        for run_id in ("orphan-one", "orphan-two")
        if await continuations.get(run_id) is not None
    ]
    assert len(survivors) == 1
    assert await store.reconcile_persistence(limit=1) == 1
    assert await store.reconcile_persistence(limit=1) == 0


@pytest.mark.ac("ADR-082826-d9f5/AC-4")
async def test_reconcile_steps_a_running_run_back_to_its_waiting_continuation() -> None:
    """A Run left RUNNING by a crashed worker, whose continuation persisted the
    wait, must be stepped back rather than resumed blind -- the continuation is
    the half that knows what the Run is waiting for."""
    store, run_store, _continuations, workspace_id, project_id = await _reconcile_spine()
    graph = _graph(workspace_id, project_id, _Step.kind)
    run_id = await _continued_run(
        run_store,
        _continuations,
        graph,
        continuation_status=RunStatus.WAITING,
        run_status=RunStatus.RUNNING,
    )

    assert await store.reconcile_persistence() == 1
    stepped = await run_store.get_run(run_id)
    assert stepped is not None and stepped.status is RunStatus.WAITING


@pytest.mark.ac("ADR-082826-d9f5/AC-4")
async def test_reconcile_leaves_a_consistent_persistence_pair_alone() -> None:
    store, run_store, _continuations, workspace_id, project_id = await _reconcile_spine()
    graph = _graph(workspace_id, project_id, _Step.kind)
    run_id = await _continued_run(
        run_store,
        _continuations,
        graph,
        continuation_status=RunStatus.QUEUED,
    )

    assert await store.reconcile_persistence() == 0
    untouched = await run_store.get_run(run_id)
    assert untouched is not None and untouched.status is RunStatus.QUEUED


async def test_reconcile_with_a_non_positive_limit_repairs_nothing() -> None:
    store, _run_store, continuations, _workspace_id, _project_id = await _reconcile_spine()
    await continuations.create(
        GraphContinuation(
            run_id="orphan-under-a-zero-budget",
            graph_state=GraphExecutionState(run_id="orphan-under-a-zero-budget"),
            status=RunStatus.WAITING,
        )
    )

    assert await store.reconcile_persistence(limit=0) == 0
    assert await continuations.get("orphan-under-a-zero-budget") is not None


@pytest.mark.ac("ADR-082826-d9f5/AC-4")
async def test_list_due_returns_only_visible_runs_whose_wait_has_elapsed() -> None:
    """The wakeup tick reads through this projection, so the deadline has to
    survive the split: only recovery-visible Runs with an elapsed `resume_at`
    are handed back, in deadline order."""
    store, run_store, _continuations, workspace_id, project_id = await _reconcile_spine()
    graph = _graph(workspace_id, project_id, _Step.kind)
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    waiting = await _continued_run(
        run_store, _continuations, graph, continuation_status=RunStatus.WAITING
    )
    paused = await _continued_run(
        run_store, _continuations, graph, continuation_status=RunStatus.PAUSED
    )
    future = await _continued_run(
        run_store, _continuations, graph, continuation_status=RunStatus.WAITING
    )
    rows = {
        waiting: now - timedelta(seconds=2),
        paused: now - timedelta(seconds=1),
        future: now + timedelta(seconds=1),
    }
    for run_id, resume_at in rows.items():
        continuation = await _continuations.get(run_id)
        assert continuation is not None
        await _continuations.update(
            continuation.model_copy(update={"resume_at": resume_at, "version": 2})
        )
    for run_id in (waiting, paused):
        await run_store.transition_run(run_id, RunStatus.RUNNING)
        await run_store.transition_run(run_id, RunStatus.WAITING)
    await run_store.transition_run(paused, RunStatus.PAUSED)

    due = await store.list_due(now=now, limit=10)
    assert [record.run_id for record in due] == [waiting, paused]
    assert all(record.resume_at is not None and record.resume_at <= now for record in due)
