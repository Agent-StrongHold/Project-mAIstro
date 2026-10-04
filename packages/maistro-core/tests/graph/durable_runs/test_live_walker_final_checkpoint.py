"""A live walker's final checkpoint must not be claimed by recovery (#1861).

`CanonicalDurableRunStore.reconcile_persistence` re-queues a RUNNING
continuation whose record shows active NodeRuns with no live Attempt. A walker
that has committed its final empty-frontier checkpoint but not yet written its
terminal Run checkpoint sits in a state with *no* active NodeRun at all — the
predicate used to fall through `True` for that state, so one recovery tick
bumped the continuation version under the live walker and its final checkpoint
died on `version regression` (#1715 removed the empty-frontier guard while
refactoring the lease helper). These tests drive a real canonical walker into
exactly that barrier, hold it there while a second canonical-store instance
over the same authorities runs one recovery tick, and then release the walker.

An empty frontier is also what a walker that *died* in the same window leaves
behind, and the dead one must still be recovered — so the companion case kills
the walker at the barrier and proves recovery resumes it once the spine has
been quiet past the terminal-settle period. That is the oracle a bare
`if not active_node_runs: return False` would silently break.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
    resume_due_graph_runs,
    run_durable_graph,
)
from maistro.graph.durable_runs.continuation import GraphContinuationStore
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import AttemptStatus, InMemoryRunStore, RunStatus
from maistro.runs.model import TERMINAL_RUN_STATUSES
from maistro.runs.store import RunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.testing.postgres import postgres_dsn

pytestmark = [pytest.mark.contract("behavioral")]

_WORKSPACE = "ws-live-walker-final-checkpoint"
#: How far past the crash the restarted recovery process ticks: past the
#: terminal-settle quiet period the spine uses to assume no live walker
#: (the same posture as the crash-window suite's restart delay).
_RESTART_DELAY = timedelta(hours=1)


class _In(BaseModel):
    pass


class _Out(BaseModel):
    text: str = "done"


class _CountedStep(BaseNode[_In, _Out]):
    """The one physical node whose execution every case counts."""

    kind: ClassVar[str] = "test.live_walker_final_checkpoint.step"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out
    executions: ClassVar[int] = 0

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        type(self).executions += 1
        return _Out()


class _WalkKilled(BaseException):
    """Not an `Exception`, so no executor boundary can absorb the crash."""


def _at_final_frontier(record: Any) -> bool:
    """Whether `record` is the final empty-frontier continuation commit.

    The walk's last frontier checkpoint: every NodeRun terminal, no active
    node left, and the Run not yet terminalized (that write is the final
    checkpoint `_finish_walk` performs next).
    """
    return (
        record.run.status is RunStatus.RUNNING
        and not record.graph_state.active_node_ids
        and bool(record.node_runs)
        and all(item.status in TERMINAL_RUN_STATUSES for item in record.node_runs)
    )


class _BarrierStore(CanonicalDurableRunStore):
    """A walker suspended after the final empty-frontier continuation commits.

    `super().update` has fully returned — continuation and canonical mirror
    both committed — when the walk is parked, so recovery sees exactly the
    state a real walker presents between the two final writes.
    """

    def __init__(self, run_store: RunStore, continuations: GraphContinuationStore) -> None:
        super().__init__(run_store, continuations)
        self.at_barrier = asyncio.Event()
        self.release = asyncio.Event()
        self.barrier_hits = 0

    async def update(self, record: Any) -> Any:
        final_frontier = _at_final_frontier(record)
        stored = await super().update(record)
        if final_frontier and not self.at_barrier.is_set():
            self.barrier_hits += 1
            self.at_barrier.set()
            await self.release.wait()
        return stored


class _CrashAtBarrierStore(CanonicalDurableRunStore):
    """A walker whose process dies after committing the same final frontier."""

    def __init__(self, run_store: RunStore, continuations: GraphContinuationStore) -> None:
        super().__init__(run_store, continuations)
        self.crashed = asyncio.Event()

    async def update(self, record: Any) -> Any:
        final_frontier = _at_final_frontier(record)
        stored = await super().update(record)
        if final_frontier and not self.crashed.is_set():
            self.crashed.set()
            raise _WalkKilled
        return stored


@dataclass
class _Spine:
    """Walker and recovery stores over one set of authorities.

    The PostgreSQL legs hand the recovery instance its own pool, so the
    recovery tick reads what the walker wrote through an independent
    connection rather than shared in-process state.
    """

    walker_run_store: RunStore
    walker_continuations: GraphContinuationStore
    recovery_run_store: RunStore
    recovery_continuations: GraphContinuationStore
    project_id: str


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def spine(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[_Spine]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(_WORKSPACE)
    project = await projects.create(
        workspace_id=_WORKSPACE, parent_project_id=root.project_id, name="Live walker"
    )
    if request.param == "postgres":
        dsn = postgres_dsn()
        if not dsn:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        asyncpg = pytest.importorskip("asyncpg")
        from maistro.graph.durable_runs.pg_continuation import PgGraphContinuationStore
        from maistro.persistence import _register_json_codecs
        from maistro.projects.pg_scope_store import PgProjectScopeStore
        from maistro.runs.pg_store import PgRunStore

        walker_pool = await asyncpg.create_pool(
            dsn, min_size=1, max_size=2, init=_register_json_codecs
        )
        recovery_pool = await asyncpg.create_pool(
            dsn, min_size=1, max_size=2, init=_register_json_codecs
        )
        pg_projects = PgProjectScopeStore(walker_pool)
        try:
            async with walker_pool.acquire() as conn:
                await conn.execute(
                    "TRUNCATE canonical_attempts, canonical_node_runs, canonical_runs, "
                    "canonical_project_resources, canonical_project_memberships, "
                    "canonical_projects, graph_continuations RESTART IDENTITY CASCADE"
                )
            pg_root = await pg_projects.create_root(_WORKSPACE)
            pg_project = await pg_projects.create(
                workspace_id=_WORKSPACE,
                parent_project_id=pg_root.project_id,
                name="Live walker",
            )
            yield _Spine(
                PgRunStore(walker_pool, project_store=pg_projects),
                PgGraphContinuationStore(walker_pool),
                PgRunStore(recovery_pool, project_store=PgProjectScopeStore(recovery_pool)),
                PgGraphContinuationStore(recovery_pool),
                pg_project.project_id,
            )
        finally:
            await walker_pool.close()
            await recovery_pool.close()
        return
    if request.param == "sqlite":
        import aiosqlite

        from maistro.graph.durable_runs import SqliteGraphContinuationStore
        from maistro.runs.sqlite_store import SqliteRunStore

        async with aiosqlite.connect(tmp_path / "spine.db") as conn:
            sqlite_runs = SqliteRunStore(conn, project_store=projects)
            await sqlite_runs.ensure_schema()
            sqlite_continuations = SqliteGraphContinuationStore(conn)
            await sqlite_continuations.ensure_schema()
            yield _Spine(
                sqlite_runs,
                sqlite_continuations,
                sqlite_runs,
                sqlite_continuations,
                project.project_id,
            )
        return
    continuations = InMemoryGraphContinuationStore()
    run_store = InMemoryRunStore(project_store=projects)
    yield _Spine(run_store, continuations, run_store, continuations, project.project_id)


def _graph(spine: _Spine) -> Graph:
    return Graph(
        workspace_id=_WORKSPACE,
        project_id=spine.project_id,
        name="final checkpoint",
        nodes=[Node(node_id="step", node_type=_CountedStep.kind, policies={"max_attempts": 1})],
    )


async def _admit(spine: _Spine, graph: Graph) -> str:
    run = await spine.walker_run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    return run.run_id


async def _physical_evidence(spine: _Spine, run_id: str) -> tuple[Any, ...]:
    node_runs = await spine.recovery_run_store.list_node_runs(run_id)
    attempts = await spine.recovery_run_store.list_attempts(node_runs[0].node_run_id)
    return node_runs, attempts


async def test_live_walker_final_checkpoint_is_not_claimed_by_recovery(spine: _Spine) -> None:
    """One recovery tick at the barrier leaves the live walker's version alone.

    The walker is parked after its final empty-frontier continuation committed.
    Recovery must leave the continuation byte-identical, so the released
    walker's terminal checkpoint lands on the original version lineage and the
    original caller returns COMPLETED with one Attempt, one accepted outcome
    and one counted execution.
    """
    _CountedStep.executions = 0
    graph = _graph(spine)
    run_id = await _admit(spine, graph)
    walker = _BarrierStore(spine.walker_run_store, spine.walker_continuations)
    recovery = CanonicalDurableRunStore(spine.recovery_run_store, spine.recovery_continuations)

    walk = asyncio.create_task(
        run_durable_graph(
            graph,
            store=walker,
            node_resolver=lambda _node_id, _graph: _CountedStep(),
            run_id=run_id,
            run_store=spine.walker_run_store,
        )
    )
    await asyncio.wait_for(walker.at_barrier.wait(), timeout=10)
    assert walker.barrier_hits == 1

    at_barrier = await spine.walker_continuations.get(run_id)
    assert at_barrier is not None
    assert at_barrier.status is RunStatus.RUNNING
    assert at_barrier.resume_at is None
    canonical = await spine.recovery_run_store.get_run(run_id)
    assert canonical is not None and canonical.status is RunStatus.RUNNING
    node_runs = await spine.recovery_run_store.list_node_runs(run_id)
    assert len(node_runs) == 1
    assert all(item.status in TERMINAL_RUN_STATUSES for item in node_runs)

    assert await recovery.reconcile_persistence(now=datetime.now(UTC)) == 0
    assert await spine.walker_continuations.get(run_id) == at_barrier

    walker.release.set()
    record = await asyncio.wait_for(walk, timeout=10)
    assert record.status is RunStatus.COMPLETED
    assert _CountedStep.executions == 1

    node_runs, attempts = await _physical_evidence(spine, run_id)
    assert len(node_runs) == 1 and node_runs[0].accepted_outcome is not None
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.COMPLETED
    assert attempts[0].ordinal == 1
    assert attempts[0].result is not None

    final = await spine.walker_continuations.get(run_id)
    assert final is not None
    assert final.status is RunStatus.COMPLETED
    assert final.version == at_barrier.version + 1
    assert final.resume_at is None

    moment = datetime.now(UTC)
    assert await recovery.reconcile_persistence(now=moment) == 0
    assert await spine.walker_continuations.get(run_id) == final
    settled = await spine.recovery_run_store.get_run(run_id)
    assert settled is not None and settled.status is RunStatus.COMPLETED


async def test_crashed_empty_frontier_walker_is_still_recovered_after_quiet_period(
    spine: _Spine,
) -> None:
    """The genuinely dead frontier this repair must keep recovering.

    A walker that died after committing the same final empty-frontier
    checkpoint leaves spine state indistinguishable from the live walker
    above — the quiet period is what says no live walker remains. Recovery
    claims it after one restarted tick past that period and the original
    physical work settles exactly once.
    """
    _CountedStep.executions = 0
    graph = _graph(spine)
    run_id = await _admit(spine, graph)
    walker = _CrashAtBarrierStore(spine.walker_run_store, spine.walker_continuations)

    with pytest.raises(_WalkKilled):
        await run_durable_graph(
            graph,
            store=walker,
            node_resolver=lambda _node_id, _graph: _CountedStep(),
            run_id=run_id,
            run_store=spine.walker_run_store,
        )
    assert walker.crashed.is_set()
    assert _CountedStep.executions == 1

    residue = await spine.walker_continuations.get(run_id)
    assert residue is not None
    assert residue.status is RunStatus.RUNNING and residue.resume_at is None

    moment = datetime.now(UTC) + _RESTART_DELAY
    recovery = CanonicalDurableRunStore(spine.recovery_run_store, spine.recovery_continuations)
    assert (
        await resume_due_graph_runs(
            store=recovery,
            run_store=spine.recovery_run_store,
            node_resolver_factory=lambda _run: lambda _node_id, _graph: _CountedStep(),
            now=moment,
        )
        == 1
    )

    run = await spine.recovery_run_store.get_run(run_id)
    assert run is not None and run.status is RunStatus.COMPLETED
    assert _CountedStep.executions == 1
    node_runs, attempts = await _physical_evidence(spine, run_id)
    assert len(node_runs) == 1 and node_runs[0].accepted_outcome is not None
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.COMPLETED
    assert attempts[0].ordinal == 1
    final = await spine.walker_continuations.get(run_id)
    assert final is not None and final.status is RunStatus.COMPLETED
    assert final.resume_at is None
