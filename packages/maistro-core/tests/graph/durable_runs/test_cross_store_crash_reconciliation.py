"""A crash between the continuation write and the canonical mirror (#1151).

`CanonicalDurableRunStore.update` writes the Graph continuation first and then
mirrors its lifecycle onto the spine. A process that dies in between leaves the
continuation terminal (or, at the resume claim, QUEUED) while the canonical Run
still reads RUNNING -- a Run nothing else will ever settle or resume, because
the due index only sees continuations whose own status is recoverable. These
drive the real executor into each window and assert the reconcile the due and
queued ticks already run repairs it from durable facts alone.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
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
    resume_due_graph_runs,
    run_durable_graph,
)
from maistro.graph.durable_runs.continuation import GraphContinuation, GraphContinuationStore
from maistro.graph.durable_runs.spine import mirror_node_run
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.lifecycle import transition_run
from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus
from maistro.runs.store import RunStore

pytestmark = [pytest.mark.contract("behavioral")]

_WORKSPACE = "ws-cross-store-crash"
_UNPERSISTED = "original error not persisted"


class _In(BaseModel):
    pass


class _Out(BaseModel):
    text: str = "done"


class _Step(BaseNode[_In, _Out]):
    kind: ClassVar[str] = "test.cross_store_crash.step"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        return _Out()


class _Fails(_Step):
    kind: ClassVar[str] = "test.cross_store_crash.fails"

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        raise ValueError("domain failure")


class _InjectedCrash(BaseException):
    """Not an `Exception`, so no executor boundary can absorb the crash."""


@dataclass
class _Spine:
    run_store: RunStore
    continuations: GraphContinuationStore
    store: CanonicalDurableRunStore
    project_id: str


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def spine(
    request: pytest.FixtureRequest, tmp_path: Path, pg_pool: Any
) -> AsyncIterator[_Spine]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(_WORKSPACE)
    project = await projects.create(
        workspace_id=_WORKSPACE, parent_project_id=root.project_id, name="Crash windows"
    )
    if request.param == "sqlite":
        from maistro.runs.sqlite_store import SqliteRunStore

        async with aiosqlite.connect(tmp_path / "spine.db") as conn:
            sqlite_runs = SqliteRunStore(conn, project_store=projects)
            await sqlite_runs.ensure_schema()
            sqlite_continuations = SqliteGraphContinuationStore(conn)
            await sqlite_continuations.ensure_schema()
            yield _Spine(
                sqlite_runs,
                sqlite_continuations,
                CanonicalDurableRunStore(sqlite_runs, sqlite_continuations),
                project.project_id,
            )
        return
    continuations: GraphContinuationStore
    if request.param == "memory":
        continuations = InMemoryGraphContinuationStore()
    else:
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        from maistro.graph.durable_runs.pg_continuation import PgGraphContinuationStore

        continuations = PgGraphContinuationStore(pg_pool)
    run_store = InMemoryRunStore(project_store=projects)
    yield _Spine(
        run_store,
        continuations,
        CanonicalDurableRunStore(run_store, continuations),
        project.project_id,
    )


def _graph(spine: _Spine, node: BaseNode[Any, Any], name: str = "crash window") -> Graph:
    return Graph(
        workspace_id=_WORKSPACE,
        project_id=spine.project_id,
        name=name,
        nodes=[Node(node_id="step", node_type=node.kind, policies={"max_attempts": 1})],
    )


_Rewrite = Callable[[DurableRunRecord], Awaitable[DurableRunRecord]]


async def _crash_at_terminal_write(
    spine: _Spine,
    node: BaseNode[Any, Any],
    *,
    rewrite: _Rewrite | None = None,
    mirror_node_runs: bool = False,
) -> str:
    """Run a graph to its terminal checkpoint and die after the continuation write.

    ``mirror_node_runs`` places the crash one step later, between the NodeRun
    mirror and the Run mirror -- the two halves of `mirror_lifecycle`.
    """
    graph = _graph(spine, node)
    admitted = await spine.run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    real_update = spine.store.update

    async def crashing_update(record: DurableRunRecord) -> DurableRunRecord:
        if record.run.status not in TERMINAL_RUN_STATUSES:
            return await real_update(record)
        written = record if rewrite is None else await rewrite(record)
        await spine.continuations.update(GraphContinuation.of(written))
        if mirror_node_runs:
            for node_run in written.node_runs:
                await mirror_node_run(node_run, run_store=spine.run_store)
        raise _InjectedCrash

    spine.store.update = crashing_update  # type: ignore[method-assign]
    try:
        with pytest.raises(_InjectedCrash):
            await run_durable_graph(
                graph,
                store=spine.store,
                node_resolver=lambda node_id, current: node,
                run_id=admitted.run_id,
                run_store=spine.run_store,
            )
    finally:
        spine.store.update = real_update  # type: ignore[method-assign]
    stranded = await spine.run_store.get_run(admitted.run_id)
    assert stranded is not None and stranded.status is RunStatus.RUNNING
    return admitted.run_id


async def _assert_settled(spine: _Spine, run_id: str, status: RunStatus) -> DurableRunRecord:
    assert await spine.store.reconcile_persistence() == 1
    record = await spine.store.get(run_id)
    assert record is not None
    assert record.run.status is status
    assert record.node_runs
    assert all(item.status in TERMINAL_RUN_STATUSES for item in record.node_runs)
    assert await spine.store.reconcile_persistence() == 0
    return record


async def test_a_completed_continuation_settles_its_running_run_with_the_node_result(
    spine: _Spine,
) -> None:
    run_id = await _crash_at_terminal_write(spine, _Step())

    record = await _assert_settled(spine, run_id, RunStatus.COMPLETED)

    assert record.run.result == {"text": "done"}
    assert record.run.error is None
    assert [item.status for item in record.node_runs] == [RunStatus.COMPLETED]


async def test_a_failed_continuation_whose_error_was_lost_settles_with_a_truthful_error(
    spine: _Spine,
) -> None:
    """The crash beat every mirror: the node's error lived only in the lost write."""
    run_id = await _crash_at_terminal_write(spine, _Fails())

    record = await _assert_settled(spine, run_id, RunStatus.FAILED)

    assert record.run.error is not None
    assert "settled failed before canonical settlement" in record.run.error
    assert _UNPERSISTED in record.run.error
    [node_run] = record.node_runs
    assert node_run.status is RunStatus.CANCELLED


async def test_a_failed_continuation_carries_the_mirrored_node_error_onto_the_run(
    spine: _Spine,
) -> None:
    run_id = await _crash_at_terminal_write(spine, _Fails(), mirror_node_runs=True)

    record = await _assert_settled(spine, run_id, RunStatus.FAILED)

    assert record.run.error == "ValueError: domain failure"
    assert [item.status for item in record.node_runs] == [RunStatus.FAILED]


async def test_a_cancelled_continuation_without_hitl_evidence_settles_its_running_run(
    spine: _Spine,
) -> None:
    async def cancelled(record: DurableRunRecord) -> DurableRunRecord:
        running = await spine.run_store.get_run(record.run_id)
        assert running is not None
        return record.model_copy(update={"run": transition_run(running, RunStatus.CANCELLED)})

    run_id = await _crash_at_terminal_write(spine, _Step(), rewrite=cancelled)

    record = await _assert_settled(spine, run_id, RunStatus.CANCELLED)

    assert record.run.error is not None
    assert "settled cancelled before canonical settlement" in record.run.error


async def test_a_lost_race_to_the_same_repair_is_already_repaired(spine: _Spine) -> None:
    """Another replica mirrored first: this tick's terminal hop is refused."""
    run_id = await _crash_at_terminal_write(spine, _Step())
    real_transition = spine.run_store.transition_run

    async def racing_transition(run_id: str, target: RunStatus, **kwargs: Any) -> Any:
        await real_transition(run_id, target, **kwargs)
        return await real_transition(run_id, target, **kwargs)

    spine.run_store.transition_run = racing_transition  # type: ignore[method-assign]
    try:
        assert await spine.store.reconcile_persistence() == 0
    finally:
        spine.run_store.transition_run = real_transition  # type: ignore[method-assign]
    settled = await spine.run_store.get_run(run_id)
    assert settled is not None and settled.status is RunStatus.COMPLETED


async def _claimed_but_not_running(spine: _Spine, *, claim_until: datetime) -> str:
    """The resume claim persisted QUEUED; the spine then stepped to RUNNING and died."""
    graph = _graph(spine, _Step(), name="claim window")
    admitted = await spine.run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    await spine.store.create(
        DurableRunRecord(
            run=admitted,
            graph_state=GraphExecutionState(
                run_id=admitted.run_id,
                active_node_ids=("step",),
                metadata={"initial_inputs": {}, "hitl_answers": {}},
            ),
        )
    )
    record = await spine.store.get(admitted.run_id)
    assert record is not None
    claimed = record.model_copy(update={"resume_at": claim_until, "version": record.version + 1})
    await spine.continuations.update(GraphContinuation.of(claimed))
    await spine.run_store.transition_run(admitted.run_id, RunStatus.RUNNING)
    return admitted.run_id


async def test_a_queued_continuation_under_a_running_run_is_resumed_once_its_claim_elapses(
    spine: _Spine,
) -> None:
    now = datetime.now(UTC)
    run_id = await _claimed_but_not_running(spine, claim_until=now - timedelta(minutes=1))

    assert await spine.store.reconcile_persistence() == 1
    continuation = await spine.continuations.get(run_id)
    assert continuation is not None
    assert continuation.status is RunStatus.RUNNING
    assert continuation.resume_at == now - timedelta(minutes=1)
    assert await spine.store.reconcile_persistence() == 0

    resumed = await resume_due_graph_runs(
        store=spine.store,
        run_store=spine.run_store,
        node_resolver=lambda node_id, graph: _Step(),
        now=datetime.now(UTC),
    )

    assert resumed == 1
    finished = await spine.run_store.get_run(run_id)
    assert finished is not None and finished.status is RunStatus.COMPLETED


async def test_the_due_tick_alone_recovers_a_queued_continuation_under_a_running_run(
    spine: _Spine,
) -> None:
    """The production tick reconciles before it scans, so nothing else is needed."""
    run_id = await _claimed_but_not_running(
        spine, claim_until=datetime.now(UTC) - timedelta(minutes=1)
    )

    resumed = await resume_due_graph_runs(
        store=spine.store,
        run_store=spine.run_store,
        node_resolver=lambda node_id, graph: _Step(),
        now=datetime.now(UTC),
    )

    assert resumed == 1
    finished = await spine.run_store.get_run(run_id)
    assert finished is not None and finished.status is RunStatus.COMPLETED


async def test_a_live_claim_on_a_queued_continuation_is_left_to_its_walker(
    spine: _Spine,
) -> None:
    run_id = await _claimed_but_not_running(
        spine, claim_until=datetime.now(UTC) + timedelta(minutes=5)
    )
    before = await spine.continuations.get(run_id)
    assert before is not None

    assert await spine.store.reconcile_persistence() == 0

    after = await spine.continuations.get(run_id)
    assert after is not None
    assert (after.status, after.version) == (RunStatus.QUEUED, before.version)
    running = await spine.run_store.get_run(run_id)
    assert running is not None and running.status is RunStatus.RUNNING


async def test_a_stranded_run_behind_many_running_runs_is_reached_within_bounded_calls(
    spine: _Spine,
) -> None:
    """Neither scan may re-read one fixed prefix forever.

    150 RUNNING Runs with no continuation sit ahead of the stranded Run on the
    spine, and 150 consistent QUEUED continuations fill the continuation-status
    buckets the per-status loop reads first. Only a cursor that advances across
    calls reaches the stranded Run.
    """
    filler = _graph(spine, _Step(), name="not graph work")
    for _ in range(150):
        other = await spine.run_store.create_run(filler, initial_status=RunStatus.QUEUED)
        await spine.run_store.transition_run(other.run_id, RunStatus.RUNNING)
    for _ in range(150):
        queued = await spine.run_store.create_run(filler, initial_status=RunStatus.QUEUED)
        await spine.continuations.create(
            GraphContinuation(
                run_id=queued.run_id,
                graph_state=GraphExecutionState(run_id=queued.run_id, active_node_ids=("step",)),
                status=RunStatus.QUEUED,
                project_id=spine.project_id,
                created_at=queued.created_at,
            )
        )
    run_id = await _crash_at_terminal_write(spine, _Step())

    for _ in range(3):
        await spine.store.reconcile_persistence(limit=100)
        settled = await spine.run_store.get_run(run_id)
        assert settled is not None
        if settled.status is RunStatus.COMPLETED:
            break
    assert settled.status is RunStatus.COMPLETED
