"""The four parked canonical x terminal continuation rows, characterized (#1151).

These are constructed split-state inputs, not proof that a production walker
can reach all four ``WAITING/PAUSED x COMPLETED/FAILED`` rows. The accepted
ADR-082826-08f0 disposition table requires preserving a pending retry/answer
decision; this characterization does not satisfy the parent's still-blocked
terminal-disagreement repair criterion.

Each row is enumerated and evaluated by the production reconciliation sweep,
keeps its pending decision and full canonical history, and does not block a
second, repairable Run. PostgreSQL uses both durable authorities and an
independent recovery pool, so a process-local canonical spine cannot supply the
evidence. This is persistence-boundary proof, not process-death injection.
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
    if request.param == "postgres":
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        import asyncpg

        from maistro.graph.durable_runs.pg_continuation import PgGraphContinuationStore
        from maistro.persistence import _register_json_codecs
        from maistro.projects.pg_scope_store import PgProjectScopeStore
        from maistro.runs.pg_store import PgRunStore
        from maistro.testing.postgres import postgres_dsn

        projects = PgProjectScopeStore(pg_pool)
        root = await projects.create_root(_WORKSPACE)
        project = await projects.create(
            workspace_id=_WORKSPACE, parent_project_id=root.project_id, name="Parked rows"
        )
        runs = PgRunStore(pg_pool, project_store=projects, concurrency_limits=_BACKLOG_LIMITS)
        continuations = PgGraphContinuationStore(pg_pool)
        recovery_pool = await asyncpg.create_pool(
            postgres_dsn(), min_size=1, max_size=4, init=_register_json_codecs
        )
        try:
            recovery_runs = PgRunStore(
                recovery_pool,
                project_store=PgProjectScopeStore(recovery_pool),
                concurrency_limits=_BACKLOG_LIMITS,
            )
            yield _Spine(
                runs,
                continuations,
                CanonicalDurableRunStore(recovery_runs, PgGraphContinuationStore(recovery_pool)),
                project.project_id,
            )
        finally:
            await recovery_pool.close()
        return
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
    memory_continuations = InMemoryGraphContinuationStore()
    run_store = InMemoryRunStore(project_store=projects, concurrency_limits=_BACKLOG_LIMITS)
    yield _Spine(
        run_store,
        memory_continuations,
        CanonicalDurableRunStore(run_store, memory_continuations),
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
) -> int:
    """Construct the split-state input without claiming walker reachability."""
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
    # On PostgreSQL this read crosses an independent pool and resolves both
    # authorities. A memory-only Run paired with a PG continuation cannot pass.
    before = await spine.store.get(run_id)
    assert before is not None
    assert _NOW < _TIMER_RESUME_AT < _HITL_DEADLINE

    assert await spine.store.reconcile_persistence(now=_NOW) == 0

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

    # Preserve the complete identity, accepted result, ordinal and lease/fence
    # history, not only the status projection. Both observations use recovery's
    # pool on PostgreSQL, independent of the pool that constructed the residue.
    assert await spine.store.get(run_id) == before
    assert await spine.store.reconcile_persistence(now=_NOW) == 0
    assert await spine.store.get(run_id) == before


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

    assert await spine.store.reconcile_persistence(now=_NOW) == 1

    repaired = await spine.continuations.get(repairable.run_id)
    assert repaired is not None and repaired.status is RunStatus.COMPLETED
    for (parked_status, terminal_status), run_id in parked.items():
        run = await spine.run_store.get_run(run_id)
        assert run is not None and run.status is parked_status, (
            f"{parked_status.value} x {terminal_status.value} was not preserved"
        )
        continuation = await spine.continuations.get(run_id)
        assert continuation is not None and continuation.status is terminal_status

    assert await spine.store.reconcile_persistence(now=_NOW) == 0
