"""Real-PostgreSQL spine crash windows: both authorities durable (R7, #1151).

The crash-window suites that prove the five named seams run against in-memory
authorities, and ``test_cross_store_crash_reconciliation.py``'s PostgreSQL legs
pair a durable continuation store with an ``InMemoryRunStore``. Neither shape
can show what #1151's acceptance actually asks: a Run stranded between two
durable-writer commits has to be re-derived by a *different process*, from
committed rows alone, on connections that share nothing with the walker that
died.

These proofs put both authorities on PostgreSQL -- ``PgRunStore`` for the
Run/NodeRun/Attempt spine, ``PgGraphContinuationStore`` for Graph traversal by
the same canonical ``run_id`` -- and split them across independent pools. The
walker writes on its pool and dies at one exact commit seam (a ``BaseException``
no executor boundary absorbs); recovery runs the production seams on a fresh
pool, the way a restarted process or a peer replica would. Every pre-recovery
assertion is an independent committed read on the recovery pool, not the
walker's objects.

The recovery seams are the shipped ones: the canonical RUNNING sweep
(``CanonicalDurableRunStore.reconcile_persistence``), the due tick
(``resume_due_graph_runs``), and the terminal-Attempt replay through
``AttemptLifecycleReconciler`` over the same bounded ``list_by_status``
enumeration the Container's tick pages. No second engine, no private repair
loop, and no sleeps: the only clock any case advances is the tick's own
``now``, past the terminal-settle quiet period the production policy defines.

Skipped unless ``MAISTRO_TEST_PG_DSN`` names a migrated database.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph import Edge, Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    resume_due_graph_runs,
    run_durable_graph,
)
from maistro.graph.durable_runs.canonical_store import TERMINAL_SETTLE_QUIET_PERIOD
from maistro.graph.durable_runs.continuation import GraphContinuation
from maistro.graph.durable_runs.spine import mirror_node_run
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.projects.pg_scope_store import PgProjectScopeStore
from maistro.runs.concurrency import RunConcurrencyLimits
from maistro.runs.lifecycle import has_live_execution_lease
from maistro.runs.model import (
    TERMINAL_RUN_STATUSES,
    AcceptedNodeOutcome,
    AttemptResult,
    AttemptStatus,
    RunStatus,
)
from maistro.runs.pg_store import PgRunStore
from maistro.runs.reconciliation import AttemptLifecycleReconciler
from maistro.runs.store import run_cursor_key
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.testing.postgres import postgres_dsn

_WORKSPACE = "ws-pg-spine-crash"
#: Room for the bounded-sweep case's RUNNING backlog; not what these cases test.
_BACKLOG_LIMITS = RunConcurrencyLimits(per_workspace=512)
#: How long after the crash the restarted process ticks: past every lease,
#: resume claim and terminal-settle quiet period the spine uses, so the
#: first tick below is the first *eligible* one under the production policy.
_RESTART_DELAY = timedelta(hours=1)


class _ProcessKilled(BaseException):
    """Not an `Exception`, so no executor boundary can absorb the crash."""


class _In(BaseModel):
    pass


class _Out(BaseModel):
    text: str = "done"


class _Step(BaseNode[_In, _Out]):
    kind: ClassVar[str] = "test.pg_spine_crash.step"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        return _Out()


class _Fails(_Step):
    kind: ClassVar[str] = "test.pg_spine_crash.fails"

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        raise ValueError("domain failure")


@dataclass
class _Replica:
    """One process's view of the same durable authorities."""

    run_store: PgRunStore
    continuations: Any

    def durable(self) -> CanonicalDurableRunStore:
        return CanonicalDurableRunStore(self.run_store, self.continuations)


@dataclass
class _Spine:
    walker: _Replica
    recovery: _Replica
    project_id: str

    def graph(self, node_type: str, *, chained: bool = False, name: str = "crash window") -> Graph:
        nodes = [Node(node_id="a", node_type=node_type, policies={"max_attempts": 1})]
        edges: list[Edge] = []
        if chained:
            nodes.append(Node(node_id="b", node_type=node_type, policies={"max_attempts": 1}))
            edges.append(Edge(edge_id="a-b", from_node="a", to_node="b"))
        return Graph(
            workspace_id=_WORKSPACE,
            project_id=self.project_id,
            name=name,
            nodes=nodes,
            edges=edges,
        )


async def _fresh_pool() -> Any:
    """A pool this test process built itself, as a restarted worker would.

    Not the shared `pg_pool` fixture: the whole point is that recovery shares
    no connection, transaction or cached object with the walker.
    """
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.persistence import _register_json_codecs

    dsn = postgres_dsn()
    assert dsn, "caller must skip when no PostgreSQL is configured"
    return await asyncpg.create_pool(dsn, min_size=1, max_size=4, init=_register_json_codecs)


def _replica(pool: Any) -> _Replica:
    from maistro.graph.durable_runs.pg_continuation import PgGraphContinuationStore

    return _Replica(
        PgRunStore(
            pool, project_store=PgProjectScopeStore(pool), concurrency_limits=_BACKLOG_LIMITS
        ),
        PgGraphContinuationStore(pool),
    )


@pytest.fixture
async def spine(pg_pool: Any) -> AsyncIterator[_Spine]:
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root(_WORKSPACE)
    project = await projects.create(
        workspace_id=_WORKSPACE, parent_project_id=root.project_id, name="Spine crash windows"
    )
    recovery_pool = await _fresh_pool()
    try:
        yield _Spine(_replica(pg_pool), _replica(recovery_pool), project.project_id)
    finally:
        await recovery_pool.close()


async def _admit(spine: _Spine, graph: Graph) -> str:
    run = await spine.walker.run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    return run.run_id


async def _die_at_terminal_write(
    spine: _Spine,
    node: BaseNode[Any, Any],
    *,
    mirror_node_runs: bool = False,
) -> str:
    """Walk to the terminal checkpoint and die between its two durable writes.

    ``CanonicalDurableRunStore.update`` persists the continuation first and
    mirrors the spine second. The continuation half (and, with
    ``mirror_node_runs``, the NodeRun mirrors) commit on the walker's pool;
    the canonical Run's own terminal write is lost with the process.
    """
    graph = spine.graph(node.kind)
    run_id = await _admit(spine, graph)
    walker = spine.walker.durable()
    real_update = walker.update

    async def crashing_update(record: DurableRunRecord) -> DurableRunRecord:
        if record.run.status not in TERMINAL_RUN_STATUSES:
            return await real_update(record)
        await spine.walker.continuations.update(GraphContinuation.of(record))
        if mirror_node_runs:
            for node_run in record.node_runs:
                await mirror_node_run(node_run, run_store=spine.walker.run_store)
        raise _ProcessKilled

    walker.update = crashing_update  # type: ignore[method-assign]
    try:
        with pytest.raises(_ProcessKilled):
            await run_durable_graph(
                graph,
                store=walker,
                node_resolver=lambda _node_id, _graph: node,
                run_id=run_id,
                run_store=spine.walker.run_store,
                actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
            )
    finally:
        walker.update = real_update  # type: ignore[method-assign]
    return run_id


async def _reconcile_terminal_attempts(
    replica: _Replica, *, limit: int = 100, moment: datetime
) -> int:
    """One bounded pass of the Container's terminal-Attempt replay, verbatim.

    The same shape `Container._reconcile_unreconciled_terminal_attempts` runs:
    page canonical RUNNING Runs by cursor, and for each NodeRun replay the
    latest COMPLETED Attempt through the production reconciler when no sibling
    Attempt still executes it under a live lease. The decisions are all the
    reconciler's; this only enumerates, the way the scheduled tick does.
    """
    reconciler = AttemptLifecycleReconciler(replica.run_store, source="test.pg_spine_crash_windows")
    changed = 0
    after: tuple[str, str] | None = None
    while changed < limit:
        page = await replica.run_store.list_by_status(
            RunStatus.RUNNING, limit=limit - changed, after=after
        )
        if not page:
            break
        for run in page:
            after = run_cursor_key(run)
            for node_run in await replica.run_store.list_node_runs(run.run_id):
                attempts = await replica.run_store.list_attempts(node_run.node_run_id)
                if has_live_execution_lease(attempts, moment):
                    continue
                completed = next(
                    (
                        attempt
                        for attempt in reversed(attempts)
                        if attempt.status is AttemptStatus.COMPLETED
                    ),
                    None,
                )
                if completed is None:
                    continue
                before_run = await replica.run_store.get_run(node_run.run_id)
                await reconciler.reconcile(completed)
                after_run = await replica.run_store.get_run(node_run.run_id)
                if (
                    before_run is not None
                    and after_run is not None
                    and before_run.status not in TERMINAL_RUN_STATUSES
                    and after_run.status in TERMINAL_RUN_STATUSES
                ):
                    changed += 1
        if len(page) < limit - changed:
            break
    return changed


# ── the continuation-before-mirror window, both halves durable ──────


async def test_a_failed_continuation_settles_its_running_run_on_the_first_tick(
    spine: _Spine,
) -> None:
    """The continuation half of the terminal checkpoint landed; the Run's did not.

    Open NodeRuns remain on the spine, so the residue is ahead of the spine
    and the first recovery tick past the terminal-settle quiet period settles
    it: FAILED with a truthful "the original error was not persisted" cause,
    the open NodeRun cancelled by the spine's own terminal cascade -- not
    passed off as the Run's error.
    """
    run_id = await _die_at_terminal_write(spine, _Fails())

    run = await spine.recovery.run_store.get_run(run_id)
    assert run is not None and run.status is RunStatus.RUNNING
    [node_run] = await spine.recovery.run_store.list_node_runs(run_id)
    assert node_run.status is RunStatus.RUNNING
    continuation = await spine.recovery.continuations.get(run_id)
    assert continuation is not None and continuation.status is RunStatus.FAILED

    moment = datetime.now(UTC) + _RESTART_DELAY
    assert await spine.recovery.durable().reconcile_persistence(now=moment) == 1

    settled = await spine.recovery.run_store.get_run(run_id)
    assert settled is not None and settled.status is RunStatus.FAILED
    assert settled.error is not None
    assert "settled failed before canonical settlement" in settled.error
    [cancelled] = await spine.recovery.run_store.list_node_runs(run_id)
    assert cancelled.status is RunStatus.CANCELLED
    assert await spine.recovery.durable().reconcile_persistence(now=moment) == 0


async def test_a_completed_continuation_settles_once_observed_past_the_quiet_period(
    spine: _Spine,
) -> None:
    """NodeRun mirrors committed too, so only the Run's own write was lost.

    With the spine's NodeRuns already terminal there is nothing ahead of the
    spine, and a replica that has watched nothing must first observe the
    terminal continuation version unchanged for the terminal-settle quiet
    period before it settles -- the same span past which no live walker is
    assumed anywhere in this store. The first tick starts that observation;
    the first tick eligible under the policy settles and re-derives the
    result from the persisted NodeRun evidence.
    """
    run_id = await _die_at_terminal_write(spine, _Step(), mirror_node_runs=True)

    run = await spine.recovery.run_store.get_run(run_id)
    assert run is not None and run.status is RunStatus.RUNNING
    node_runs = await spine.recovery.run_store.list_node_runs(run_id)
    assert node_runs and all(item.status in TERMINAL_RUN_STATUSES for item in node_runs)
    continuation = await spine.recovery.continuations.get(run_id)
    assert continuation is not None and continuation.status is RunStatus.COMPLETED

    patient = spine.recovery.durable()
    far = datetime.now(UTC) + _RESTART_DELAY
    assert await patient.reconcile_persistence(now=far) == 0
    still = await spine.recovery.run_store.get_run(run_id)
    assert still is not None and still.status is RunStatus.RUNNING

    assert await patient.reconcile_persistence(now=far + TERMINAL_SETTLE_QUIET_PERIOD) == 1
    settled = await spine.recovery.run_store.get_run(run_id)
    assert settled is not None and settled.status is RunStatus.COMPLETED
    assert settled.result == {"text": "done"}
    assert await patient.reconcile_persistence(now=far + TERMINAL_SETTLE_QUIET_PERIOD * 2) == 0


# ── the QUEUED-continuation / RUNNING-Run checkpoint-1 window ───────


async def _claimed_but_died(spine: _Spine, *, claim_until: datetime) -> str:
    """Persist the resume claim, step the spine to RUNNING, then die.

    The claim is checkpointed while the continuation still reads QUEUED; the
    canonical RUNNING step commits; the walker never comes back. The due index
    excludes QUEUED continuations, so nothing but reconciliation re-derives
    this Run.
    """
    graph = spine.graph(_Step.kind, name="claim window")
    run_id = await _admit(spine, graph)
    admitted = await spine.walker.run_store.get_run(run_id)
    assert admitted is not None
    await spine.walker.durable().create(
        DurableRunRecord(
            run=admitted,
            graph_state=GraphExecutionState(
                run_id=run_id,
                active_node_ids=("a",),
                metadata={"initial_inputs": {}, "hitl_answers": {}},
            ),
        )
    )
    record = await spine.walker.durable().get(run_id)
    assert record is not None
    claimed = record.model_copy(update={"resume_at": claim_until, "version": record.version + 1})
    await spine.walker.continuations.update(GraphContinuation.of(claimed))
    await spine.walker.run_store.transition_run(run_id, RunStatus.RUNNING)
    return run_id


async def test_an_elapsed_claim_under_a_running_run_is_resumed_by_the_due_tick(
    spine: _Spine,
) -> None:
    run_id = await _claimed_but_died(spine, claim_until=datetime.now(UTC) - timedelta(minutes=1))

    run = await spine.recovery.run_store.get_run(run_id)
    assert run is not None and run.status is RunStatus.RUNNING
    continuation = await spine.recovery.continuations.get(run_id)
    assert continuation is not None and continuation.status is RunStatus.QUEUED

    assert await spine.recovery.durable().reconcile_persistence() == 1
    visible = await spine.recovery.continuations.get(run_id)
    assert visible is not None and visible.status is RunStatus.RUNNING

    resumed = await resume_due_graph_runs(
        store=spine.recovery.durable(),
        run_store=spine.recovery.run_store,
        node_resolver=lambda _node_id, _graph: _Step(),
        now=datetime.now(UTC),
    )
    assert resumed == 1
    finished = await spine.recovery.run_store.get_run(run_id)
    assert finished is not None and finished.status is RunStatus.COMPLETED
    assert finished.result == {"text": "done"}


async def test_a_live_claim_is_left_to_its_walker(spine: _Spine) -> None:
    run_id = await _claimed_but_died(spine, claim_until=datetime.now(UTC) + timedelta(minutes=5))

    assert await spine.recovery.durable().reconcile_persistence() == 0
    assert (
        await resume_due_graph_runs(
            store=spine.recovery.durable(),
            run_store=spine.recovery.run_store,
            node_resolver=lambda _node_id, _graph: _Step(),
            now=datetime.now(UTC),
        )
        == 0
    )
    run = await spine.recovery.run_store.get_run(run_id)
    assert run is not None and run.status is RunStatus.RUNNING
    continuation = await spine.recovery.continuations.get(run_id)
    assert continuation is not None and continuation.status is RunStatus.QUEUED


# ── spine completion windows with no continuation at all ───────────


async def _running_node_run(spine: _Spine) -> tuple[str, str]:
    """A RUNNING Run and NodeRun on the walker's pool, as admission claims them."""
    graph = spine.graph(_Step.kind, name="spine window")
    run_id = await _admit(spine, graph)
    await spine.walker.run_store.transition_run(run_id, RunStatus.RUNNING)
    node_run = await spine.walker.run_store.create_node_run(run_id, node_id="a")
    await spine.walker.run_store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await spine.walker.run_store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    return run_id, node_run.node_run_id


async def test_an_attempt_completion_committed_before_reconciliation_settles(
    spine: _Spine,
) -> None:
    """The success write landed; the process died before reconciliation ran.

    The Attempt is COMPLETED, so no lease is left to lapse, while its NodeRun
    and Run still read RUNNING. A restarted process replays the terminal
    Attempt from the persisted spine and settles both -- no new Attempt, no
    re-execution.
    """
    run_id, node_run_id = await _running_node_run(spine)
    attempt = await spine.walker.run_store.create_attempt(node_run_id)
    await spine.walker.run_store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    await spine.walker.run_store.transition_attempt(
        attempt.attempt_id, AttemptStatus.COMPLETED, result={"text": "done"}
    )

    stranded = await spine.recovery.run_store.get_run(run_id)
    assert stranded is not None and stranded.status is RunStatus.RUNNING
    [spine_node] = await spine.recovery.run_store.list_node_runs(run_id)
    assert spine_node.status is RunStatus.RUNNING

    moment = datetime.now(UTC) + _RESTART_DELAY
    assert await _reconcile_terminal_attempts(spine.recovery, moment=moment) == 1

    settled = await spine.recovery.run_store.get_run(run_id)
    assert settled is not None and settled.status is RunStatus.COMPLETED
    assert settled.result == {"text": "done"}
    [node_run] = await spine.recovery.run_store.list_node_runs(run_id)
    assert node_run.status is RunStatus.COMPLETED
    assert node_run.accepted_outcome is not None
    assert await _reconcile_terminal_attempts(spine.recovery, moment=moment) == 0


async def test_run_settlement_lost_after_the_last_node_run_commits(spine: _Spine) -> None:
    """The NodeRun accepted its outcome; the Run's own settlement write was lost.

    Nothing about the Attempt is unfinished -- the lease sweep would never
    look at it -- yet the Run stays RUNNING forever unless a restarted
    process replays the accepted outcome and settles the Run.
    """
    run_id, node_run_id = await _running_node_run(spine)
    attempt = await spine.walker.run_store.create_attempt(node_run_id)
    await spine.walker.run_store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    attempt = await spine.walker.run_store.transition_attempt(
        attempt.attempt_id, AttemptStatus.COMPLETED, result={"text": "done"}
    )
    outcome = AcceptedNodeOutcome(
        node_run_id=node_run_id,
        attempt_result=AttemptResult.from_attempt(attempt),
        result={"text": "done"},
    )
    await spine.walker.run_store.transition_node_run(
        node_run_id, RunStatus.COMPLETED, result=outcome.result, accepted_outcome=outcome
    )

    stranded = await spine.recovery.run_store.get_run(run_id)
    assert stranded is not None and stranded.status is RunStatus.RUNNING
    [terminal] = await spine.recovery.run_store.list_node_runs(run_id)
    assert terminal.status is RunStatus.COMPLETED

    moment = datetime.now(UTC) + _RESTART_DELAY
    assert await _reconcile_terminal_attempts(spine.recovery, moment=moment) == 1

    settled = await spine.recovery.run_store.get_run(run_id)
    assert settled is not None and settled.status is RunStatus.COMPLETED
    assert settled.result == {"text": "done"}


# ── the frontier whose checkpoint never landed ─────────────────────


async def _die_at_the_next_frontiers_checkpoint(spine: _Spine) -> str:
    """Mint node ``b``'s NodeRun on the spine, then die before its checkpoint.

    The advancement checkpoint for ``a`` cleared ``resume_at``; the process
    dies inside the walk for ``b``, after the canonical NodeRun is minted and
    before the continuation records it. The durable residue reads RUNNING
    with no claim the due index would list and no Attempt holding ``b``.
    """
    graph = spine.graph(_Step.kind, chained=True, name="frontier window")
    run_id = await _admit(spine, graph)
    walker = spine.walker.durable()
    real_update = walker.update

    async def crashing_update(record: DurableRunRecord) -> DurableRunRecord:
        if not any(item.node_id == "b" for item in record.node_runs):
            return await real_update(record)
        raise _ProcessKilled

    walker.update = crashing_update  # type: ignore[method-assign]
    try:
        with pytest.raises(_ProcessKilled):
            await run_durable_graph(
                graph,
                store=walker,
                node_resolver=lambda _node_id, _graph: _Step(),
                run_id=run_id,
                run_store=spine.walker.run_store,
                actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
            )
    finally:
        walker.update = real_update  # type: ignore[method-assign]
    return run_id


async def test_a_frontier_node_run_without_its_checkpoint_is_made_due_and_resumed(
    spine: _Spine,
) -> None:
    """A RUNNING continuation with ``resume_at=None`` is not stranded forever.

    Node ``b``'s NodeRun exists on the spine with no Attempt holding it, so
    the stalled-frontier repair re-derives a due claim from durable facts
    alone, and the due tick walks the frontier to completion. No live walker
    is interfered with: nothing holds ``b``, and the spine has been quiet
    past the period any live walker is assumed to spend between two
    adjacent writes.
    """
    run_id = await _die_at_the_next_frontiers_checkpoint(spine)

    run = await spine.recovery.run_store.get_run(run_id)
    assert run is not None and run.status is RunStatus.RUNNING
    node_runs = await spine.recovery.run_store.list_node_runs(run_id)
    assert {item.node_id: item.status for item in node_runs} == {
        "a": RunStatus.COMPLETED,
        "b": RunStatus.RUNNING,
    }
    continuation = await spine.recovery.continuations.get(run_id)
    assert continuation is not None
    assert continuation.status is RunStatus.RUNNING and continuation.resume_at is None

    moment = datetime.now(UTC) + _RESTART_DELAY
    assert await spine.recovery.durable().reconcile_persistence(now=moment) == 1
    visible = await spine.recovery.continuations.get(run_id)
    assert visible is not None and visible.resume_at is not None

    resumed = await resume_due_graph_runs(
        store=spine.recovery.durable(),
        run_store=spine.recovery.run_store,
        node_resolver=lambda _node_id, _graph: _Step(),
        now=moment,
    )
    assert resumed == 1
    finished = await spine.recovery.run_store.get_run(run_id)
    assert finished is not None and finished.status is RunStatus.COMPLETED
    assert finished.result == {"text": "done"}


# ── bounded, indexed enumeration over the real spine ───────────────


async def test_the_running_sweep_pages_past_a_backlog_within_bounded_calls(
    spine: _Spine,
) -> None:
    """Sixty RUNNING Runs with no continuation sit ahead of the stranded Run.

    Each tick reads one bounded page through `PgRunStore.list_by_status`, the
    `(created_at, run_id)` keyset the unconditional status index carries
    (migration 057); the cursor outlives the call, so three pages of twenty
    reach the stranded Run rather than re-reading a fixed prefix forever.
    """
    filler = spine.graph(_Step.kind, name="not graph work")
    for index in range(60):
        other = await spine.walker.run_store.create_run(
            filler,
            initial_status=RunStatus.QUEUED,
            actor_principal_id=f"filler-principal-{index}",
        )
        await spine.walker.run_store.transition_run(other.run_id, RunStatus.RUNNING)
    run_id = await _die_at_terminal_write(spine, _Fails())

    recovery = spine.recovery.durable()
    moment = datetime.now(UTC) + _RESTART_DELAY
    settled: RunStatus | None = None
    for _ in range(3):
        await recovery.reconcile_persistence(limit=20, now=moment)
        run = await spine.recovery.run_store.get_run(run_id)
        assert run is not None
        settled = run.status
        if settled is RunStatus.FAILED:
            break
    assert settled is RunStatus.FAILED


# ── idempotence and fencing across replicas ────────────────────────


async def test_two_replicas_sweeping_concurrently_converge_on_one_settlement(
    spine: _Spine,
) -> None:
    """Two fresh pools sweep the same residue at the same moment.

    Exactly one settlement may charge the tick: the loser's terminal hop is
    refused by the spine's own lifecycle guard, and both replicas read the
    same converged facts afterwards. The continuation is not rewritten, so
    its version is the fence a second repair would have to beat.
    """
    run_id = await _die_at_terminal_write(spine, _Fails())
    before = await spine.recovery.continuations.get(run_id)
    assert before is not None

    peer_pool = await _fresh_pool()
    try:
        peer = _replica(peer_pool)
        moment = datetime.now(UTC) + _RESTART_DELAY
        changed = await asyncio.gather(
            spine.recovery.durable().reconcile_persistence(now=moment),
            peer.durable().reconcile_persistence(now=moment),
        )

        assert sum(changed) == 1
        for replica in (spine.recovery, peer):
            settled = await replica.run_store.get_run(run_id)
            assert settled is not None and settled.status is RunStatus.FAILED
            continuation = await replica.continuations.get(run_id)
            assert continuation is not None
            assert (continuation.status, continuation.version) == (
                before.status,
                before.version,
            )
            assert await replica.durable().reconcile_persistence(now=moment) == 0
    finally:
        await peer_pool.close()
