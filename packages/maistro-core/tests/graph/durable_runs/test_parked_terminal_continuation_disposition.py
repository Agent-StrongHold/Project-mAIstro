"""The four parked canonical x terminal continuation rows, characterized (#1151).

A crash between a resumed walker's terminal continuation write and every spine
write behind it can leave a canonical Run still parked at WAITING or PAUSED
while its continuation already reads COMPLETED or FAILED -- the four reachable
``WAITING/PAUSED x COMPLETED/FAILED`` rows of the parked-conflict table. The
accepted disposition table keeps them preserved: a parked Run awaits its
existing retry/answer decision, terminal history is not rewritten, and no
lifecycle edge is invented to settle one over the other. Repair of these rows
is DESIGN_BLOCKED for exactly that reason -- a disposition that settled a
WAITING Run COMPLETED would bypass the pending decision, and inverting the
intentional zero-repair behavior of
``test_a_waiting_run_under_a_completed_continuation_does_not_abort_the_tick``
would contradict the accepted table, not extend it.

What this parent-held artifact delivers is the characterization the acceptance
criterion asks for: each row is reachable (built as the crash residue it is),
each is enumerated and evaluated by the bounded sweep (a visitation spy on the
per-Run repair, not merely an absent count), each keeps its pending decision
evidence (an unelapsed wait timer, a durable HITL pause entry) and its
completed NodeRun evidence intact, none aborts or poisons the tick, and a
genuinely repairable Run -- the stale RUNNING continuation under a terminal
canonical Run that ``_reconcile_terminal_spine`` owns -- is still settled in
the same sweep, proving the parked rows isolate rather than block.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
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
)
from maistro.graph.durable_runs.continuation import (
    GraphContinuation,
    GraphContinuationStore,
)
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes import BaseNode
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.concurrency import RunConcurrencyLimits
from maistro.runs.model import AcceptedNodeOutcome, AttemptResult, AttemptStatus, RunStatus
from maistro.runs.store import RunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

pytestmark = [pytest.mark.contract("behavioral")]

_WORKSPACE = "ws-parked-terminal-disposition"
_NOW = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
_TIMER_RESUME_AT = _NOW + timedelta(seconds=30)
_HITL_DEADLINE = _NOW + timedelta(seconds=60)
_HITL_PAUSE_METADATA = {
    "pauses": {"step": {"kind": "hitl", "resume_at": _HITL_DEADLINE.isoformat()}}
}

#: Room beside the parked rows; the governed root-Run ceiling (#1182) is not
#: what these cases exercise.
_BACKLOG_LIMITS = RunConcurrencyLimits(per_workspace=512)

_PARKED_STATUSES = (RunStatus.WAITING, RunStatus.PAUSED)
_TERMINAL_CONTINUATION_STATUSES = (RunStatus.COMPLETED, RunStatus.FAILED)


class _In(BaseModel):
    pass


class _Out(BaseModel):
    text: str = "done"


class _Step(BaseNode[_In, _Out]):
    kind: ClassVar[str] = "test.parked_terminal_disposition.step"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out


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
        workspace_id=_WORKSPACE, parent_project_id=root.project_id, name="Parked rows"
    )
    if request.param == "sqlite":
        from maistro.runs.sqlite_store import SqliteRunStore

        async with aiosqlite.connect(tmp_path / "spine.db") as conn:
            sqlite_runs = SqliteRunStore(
                conn, project_store=projects, concurrency_limits=_BACKLOG_LIMITS
            )
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
    run_store = InMemoryRunStore(project_store=projects, concurrency_limits=_BACKLOG_LIMITS)
    yield _Spine(
        run_store,
        continuations,
        CanonicalDurableRunStore(run_store, continuations),
        project.project_id,
    )


def _graph(spine: _Spine) -> Graph:
    return Graph(
        workspace_id=_WORKSPACE,
        project_id=spine.project_id,
        name="parked under a terminal continuation",
        nodes=[Node(node_id="step", node_type=_Step.kind)],
    )


async def _completed_node_run(spine: _Spine, run_id: str) -> str:
    """The NodeRun evidence a parked Run's finished work left on the spine."""
    node_run = await spine.run_store.create_node_run(run_id, node_id="step")
    await spine.run_store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await spine.run_store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await spine.run_store.create_attempt(node_run.node_run_id)
    await spine.run_store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    completed = await spine.run_store.transition_attempt(
        attempt.attempt_id, AttemptStatus.COMPLETED, result={"text": "done"}
    )
    await spine.run_store.transition_node_run(
        node_run.node_run_id,
        RunStatus.COMPLETED,
        result={"text": "done"},
        accepted_outcome=AcceptedNodeOutcome(
            node_run_id=node_run.node_run_id,
            attempt_result=AttemptResult.from_attempt(completed),
        ),
    )
    return node_run.node_run_id


async def _parked_run(
    spine: _Spine,
    *,
    parked_status: RunStatus,
) -> str:
    """Admit, work, and park a Run the way a walker leaves it, on both halves."""
    graph = _graph(spine)
    run = await spine.run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    await _completed_node_run(spine, run.run_id)
    await spine.run_store.transition_run(run.run_id, RunStatus.RUNNING)
    if parked_status is RunStatus.WAITING:
        # A machine pause with a pending wakeup timer: the unelapsed deadline
        # is the pending decision this row must keep.
        resume_at: datetime | None = _TIMER_RESUME_AT
        metadata: dict[str, Any] = {}
    else:
        # A durable human pause on the active frontier: the pause entry (and
        # its lookup projections) are the pending decision this row must keep.
        resume_at = None
        metadata = dict(_HITL_PAUSE_METADATA)
    await spine.continuations.create(
        GraphContinuation(
            run_id=run.run_id,
            graph_state=GraphExecutionState(
                run_id=run.run_id,
                active_node_ids=("step",),
                metadata=metadata,
            ),
            status=parked_status,
            resume_at=resume_at,
            hitl_deadline_at=_HITL_DEADLINE if parked_status is RunStatus.PAUSED else None,
            has_hitl_pause=parked_status is RunStatus.PAUSED,
            project_id=spine.project_id,
            created_at=run.created_at,
        )
    )
    await spine.run_store.transition_run(run.run_id, parked_status)
    return run.run_id


async def _terminal_continuation_first(
    spine: _Spine,
    run_id: str,
    *,
    terminal_status: RunStatus,
) -> None:
    """Rewrite the continuation terminal and lose every spine write behind it.

    This is the crash window itself: the resumed walker persisted its terminal
    traversal and died before the spine learned anything, so the canonical Run
    keeps its parked status under a continuation that already reads terminal.
    """
    continuation = await spine.continuations.get(run_id)
    assert continuation is not None
    rewritten = await spine.continuations.update(
        continuation.model_copy(
            update={"status": terminal_status, "version": continuation.version + 1}
        )
    )
    return rewritten.version


async def _spy_repairs(spine: _Spine, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every Run the sweep actually evaluates this tick."""
    visited: list[str] = []
    real = spine.store._reconcile_run

    async def spy(run_id: str, moment: datetime) -> bool:
        visited.append(run_id)
        return await real(run_id, moment)

    monkeypatch.setattr(spine.store, "_reconcile_run", spy)
    return visited


@pytest.mark.parametrize("terminal_status", _TERMINAL_CONTINUATION_STATUSES)
@pytest.mark.parametrize("parked_status", _PARKED_STATUSES)
async def test_a_parked_run_under_a_terminal_continuation_keeps_its_pending_disposition(
    spine: _Spine,
    monkeypatch: pytest.MonkeyPatch,
    parked_status: RunStatus,
    terminal_status: RunStatus,
) -> None:
    run_id = await _parked_run(spine, parked_status=parked_status)
    terminal_version = await _terminal_continuation_first(
        spine, run_id, terminal_status=terminal_status
    )
    visited = await _spy_repairs(spine, monkeypatch)

    assert await spine.store.reconcile_persistence() == 0

    # Enumerated and evaluated, not merely invisible: the bounded sweep reaches
    # the row through the canonical parked scan and the terminal continuation
    # buckets, walks its branch chain, and finds no authorized repair.
    assert visited == [run_id]

    run = await spine.run_store.get_run(run_id)
    assert run is not None and run.status is parked_status
    continuation = await spine.continuations.get(run_id)
    assert continuation is not None
    # Terminal history is not rewritten and the parked projection is not consumed.
    assert continuation.status is terminal_status
    assert continuation.version == terminal_version
    assert continuation.run_id == run_id
    # The pending decision survives untouched for its owner.
    if parked_status is RunStatus.WAITING:
        assert continuation.resume_at == _TIMER_RESUME_AT
    else:
        assert continuation.resume_at is None
        assert continuation.has_hitl_pause is True
        assert continuation.hitl_deadline_at == _HITL_DEADLINE
        assert (
            continuation.graph_state.metadata.get("pauses", {}).get("step", {}).get("kind")
            == "hitl"
        )
    # The completed NodeRun evidence a replay or answer decision would read.
    node_runs = await spine.run_store.list_node_runs(run_id)
    assert [node_run.status for node_run in node_runs] == [RunStatus.COMPLETED]
    assert node_runs[0].result == {"text": "done"}

    # Idempotent: the next tick re-derives the same zero.
    assert await spine.store.reconcile_persistence() == 0


async def test_a_repairable_run_is_settled_alongside_the_parked_rows_in_one_tick(
    spine: _Spine,
) -> None:
    """Isolation control: the parked rows neither block nor poison the sweep.

    The repairable Run is the reverse disagreement the disposition table does
    authorize repairing -- a stale RUNNING continuation under a canonically
    terminal COMPLETED Run. It is settled in the same bounded sweep that walks
    all four parked rows and refuses each of them.
    """
    parked: dict[tuple[RunStatus, RunStatus], str] = {}
    for parked_status in _PARKED_STATUSES:
        for terminal_status in _TERMINAL_CONTINUATION_STATUSES:
            run_id = await _parked_run(spine, parked_status=parked_status)
            await _terminal_continuation_first(spine, run_id, terminal_status=terminal_status)
            parked[(parked_status, terminal_status)] = run_id

    graph = _graph(spine)
    repairable = await spine.run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    await spine.run_store.transition_run(repairable.run_id, RunStatus.RUNNING)
    await spine.run_store.transition_run(repairable.run_id, RunStatus.COMPLETED)
    await spine.continuations.create(
        GraphContinuation(
            run_id=repairable.run_id,
            graph_state=GraphExecutionState(run_id=repairable.run_id),
            status=RunStatus.RUNNING,
            project_id=spine.project_id,
            created_at=repairable.created_at,
        )
    )

    assert await spine.store.reconcile_persistence() == 1

    repaired = await spine.continuations.get(repairable.run_id)
    assert repaired is not None and repaired.status is RunStatus.COMPLETED
    for (parked_status, terminal_status), run_id in parked.items():
        run = await spine.run_store.get_run(run_id)
        assert run is not None and run.status is parked_status, (
            f"{parked_status.value} x {terminal_status.value} was not preserved"
        )
        continuation = await spine.continuations.get(run_id)
        assert continuation is not None and continuation.status is terminal_status

    assert await spine.store.reconcile_persistence() == 0
