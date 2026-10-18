"""Real-PostgreSQL spine crash windows: both authorities durable (R7, #1151).

The crash-window suites that prove the five named seams run against in-memory
authorities, and ``test_cross_store_crash_reconciliation.py``'s PostgreSQL legs
pair a durable continuation store with an ``InMemoryRunStore``. Neither shape
can show what #1151's acceptance actually asks: a Run stranded between two
durable-writer commits has to be re-derived by a *different process*, from
committed rows alone, on connections that share nothing with the interrupted
walker. Independent pools model a restart; these are not OS-process kill tests.

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
(``resume_due_graph_runs``), and the public Container recovery tick
(``Container.recover_abandoned_attempts``), including its terminal-Attempt
replay. No second engine, no private repair loop, and no sleeps: the only clock
any case advances is the tick's own
``now``, past the terminal-settle quiet period the production policy defines.

Skipped unless ``MAISTRO_TEST_PG_DSN`` names a migrated database.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from maistro.container import Container, create_container
from maistro.graph import Edge, Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    resume_due_graph_runs,
    resume_durable_graph,
    run_durable_graph,
)
from maistro.graph.durable_runs.canonical_store import TERMINAL_SETTLE_QUIET_PERIOD
from maistro.graph.durable_runs.continuation import GraphContinuation
from maistro.graph.durable_runs.spine import mirror_node_run
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes import BaseNode, NodeContext, ReplaySemantics
from maistro.projects.pg_scope_store import PgProjectScopeStore
from maistro.runs.concurrency import RunConcurrencyLimits
from maistro.runs.model import (
    TERMINAL_RUN_STATUSES,
    AcceptedNodeOutcome,
    AttemptResult,
    AttemptStatus,
    RunStatus,
)
from maistro.runs.pg_store import PgRunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.testing.postgres import postgres_dsn
from maistro.types.config import AgentConfig

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


@pytest.fixture
async def recovery_container(
    spine: _Spine, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Container]:
    """Run the shipped tick against the independent pool, never a copied sweep.

    Only unrelated Container services use memory; all recovery lifecycle reads
    and writes go through the real PgRunStore. Refuse creation at this replica
    so a passing repair cannot hide re-execution or replacement history.
    """
    container = await create_container(
        AgentConfig(router_api_key="test-key", database_url="memory://")
    )
    container.run_store = spine.recovery.run_store
    for name in ("create_attempt", "create_node_run"):
        monkeypatch.setattr(
            container.run_store, name, AsyncMock(side_effect=AssertionError("new physical work"))
        )
    monkeypatch.setattr(
        container.invocation_store,
        "create",
        AsyncMock(side_effect=AssertionError("new Invocation during recovery")),
    )
    try:
        yield container
    finally:
        await container.aclose()


# ── terminal-spine / stale-continuation window, both halves durable ─


@pytest.mark.parametrize("terminal_status", [RunStatus.COMPLETED, RunStatus.FAILED])
async def test_a_terminal_spine_repairs_its_stale_running_continuation(
    spine: _Spine,
    terminal_status: RunStatus,
) -> None:
    """A restart cannot resume traversal after its canonical Run has settled.

    The walker persisted checkpoint 1, then another canonical lifecycle writer
    terminalized the Run before it could update the continuation projection.
    Recovery runs through an independent PostgreSQL pool and copies only the
    terminal lifecycle status onto that projection.
    """
    graph = spine.graph(_Step.kind, name="terminal-spine projection repair")
    run_id = await _admit(spine, graph)
    run = await spine.walker.run_store.transition_run(run_id, RunStatus.RUNNING)
    await spine.walker.continuations.create(
        GraphContinuation(
            run_id=run_id,
            graph_state=GraphExecutionState(run_id=run_id, active_node_ids=("a",)),
            status=RunStatus.RUNNING,
            project_id=spine.project_id,
            created_at=run.created_at,
        )
    )
    await spine.walker.run_store.transition_run(
        run_id,
        terminal_status,
        error="canonical terminal writer settled the Run",
    )

    canonical = await spine.recovery.run_store.get_run(run_id)
    continuation = await spine.recovery.continuations.get(run_id)
    assert canonical is not None and canonical.status is terminal_status
    assert continuation is not None and continuation.status is RunStatus.RUNNING

    recovery = spine.recovery.durable()
    assert await recovery.reconcile_persistence() == 1
    repaired = await spine.recovery.continuations.get(run_id)
    assert repaired is not None and repaired.status is terminal_status
    assert await recovery.reconcile_persistence() == 0


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
    spine: _Spine, recovery_container: Container
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
    history = await spine.recovery.run_store.list_attempts(node_run_id)
    assert len(history) == 1 and history[0].status is AttemptStatus.COMPLETED

    moment = datetime.now(UTC) + _RESTART_DELAY
    assert await recovery_container.recover_abandoned_attempts(now=moment, limit=1) == 1

    settled = await spine.recovery.run_store.get_run(run_id)
    assert settled is not None and settled.status is RunStatus.COMPLETED
    assert settled.result == {"text": "done"}
    [node_run] = await spine.recovery.run_store.list_node_runs(run_id)
    assert node_run.status is RunStatus.COMPLETED
    assert node_run.accepted_outcome is not None
    assert await spine.recovery.run_store.list_attempts(node_run_id) == history
    assert await recovery_container.recover_abandoned_attempts(now=moment, limit=1) == 0
    assert await spine.recovery.run_store.get_run(run_id) == settled
    assert await spine.recovery.run_store.list_node_runs(run_id) == [node_run]
    assert await spine.recovery.run_store.list_attempts(node_run_id) == history


async def test_run_settlement_lost_after_the_last_node_run_commits(
    spine: _Spine, recovery_container: Container
) -> None:
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
    history = await spine.recovery.run_store.list_attempts(node_run_id)
    assert history == [attempt]

    moment = datetime.now(UTC) + _RESTART_DELAY
    assert await recovery_container.recover_abandoned_attempts(now=moment, limit=1) == 1

    settled = await spine.recovery.run_store.get_run(run_id)
    assert settled is not None and settled.status is RunStatus.COMPLETED
    assert settled.result == {"text": "done"}
    assert await spine.recovery.run_store.list_node_runs(run_id) == [terminal]
    assert await spine.recovery.run_store.list_attempts(node_run_id) == history
    assert await recovery_container.recover_abandoned_attempts(now=moment, limit=1) == 0
    assert await spine.recovery.run_store.get_run(run_id) == settled
    assert await spine.recovery.run_store.list_node_runs(run_id) == [terminal]
    assert await spine.recovery.run_store.list_attempts(node_run_id) == history


# ── successful runtime, failed physical completion write ───────────


@pytest.mark.parametrize("semantics", [ReplaySemantics.PURE, ReplaySemantics.NON_RETRYABLE])
async def test_lost_success_write_preserves_live_ownership_then_parks(
    spine: _Spine,
    recovery_container: Container,
    monkeypatch: pytest.MonkeyPatch,
    semantics: ReplaySemantics,
) -> None:
    """An ordinary store failure must not make a FAILED Run over live work.

    Unlike the committed-success replay above, this output never reaches the
    canonical Attempt. Recovery may reclaim and park, but cannot reconstruct
    success. A fresh resumer then consumes the node's replay contract: pure
    work may execute on a new fence, but non-retryable work records refusal
    without repeating its effect. The lost output is never fabricated.
    """
    graph = spine.graph(_Step.kind, name="successful runtime, lost completion")
    run_id = await _admit(spine, graph)
    step = _Step()
    monkeypatch.setattr(step, "replay_semantics", semantics)
    execute = AsyncMock(wraps=step._execute)
    monkeypatch.setattr(step, "_execute", execute)
    transition = spine.walker.run_store.transition_attempt
    lost_results: list[Any] = []

    async def fail_completion(attempt_id: str, target: AttemptStatus, **kwargs: Any) -> Any:
        if target is AttemptStatus.COMPLETED:
            lost_results.append(kwargs["result"])
            raise OSError("injected completion write failure before commit")
        return await transition(attempt_id, target, **kwargs)

    monkeypatch.setattr(spine.walker.run_store, "transition_attempt", fail_completion)
    record = await run_durable_graph(
        graph,
        store=spine.walker.durable(),
        node_resolver=lambda _node_id, _graph: step,
        run_id=run_id,
        run_store=spine.walker.run_store,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    execute.assert_awaited_once()
    assert len(lost_results) == 1  # No inline retry of the terminal write.
    assert lost_results[0].success
    assert lost_results[0].model_dump(mode="json")["output"] == {"text": "done"}
    assert record.run.status is RunStatus.RUNNING

    # Read committed truth through the independent recovery pool, not the
    # walker's return/projection. No result or accepted success was persisted.
    run = await spine.recovery.run_store.get_run(run_id)
    assert run is not None and run.status is RunStatus.RUNNING and run.error is None
    [node] = await spine.recovery.run_store.list_node_runs(run_id)
    assert node.status is RunStatus.RUNNING and node.accepted_outcome is None
    [attempt] = await spine.recovery.run_store.list_attempts(node.node_run_id)
    assert attempt.status is AttemptStatus.RUNNING and attempt.result is None
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    continuation = await spine.recovery.continuations.get(run_id)
    assert continuation is not None and continuation.status is RunStatus.RUNNING

    # Boundary clocks are derived from persisted ownership, never a sleep or
    # machine-speed threshold. The live tick must be completely read-only.
    assert (
        await recovery_container.recover_abandoned_attempts(
            now=lease.expires_at - timedelta(microseconds=1), limit=1
        )
        == 0
    )
    assert await spine.recovery.run_store.get_run(run_id) == run
    assert await spine.recovery.run_store.list_node_runs(run_id) == [node]
    assert await spine.recovery.run_store.list_attempts(node.node_run_id) == [attempt]

    assert await recovery_container.recover_abandoned_attempts(now=lease.expires_at, limit=1) == 1
    [reclaimed] = await spine.recovery.run_store.list_attempts(node.node_run_id)
    assert reclaimed.status is AttemptStatus.CANCELLED
    assert reclaimed.result is None
    assert reclaimed.execution_lease == lease
    assert (reclaimed.attempt_id, reclaimed.node_run_id, reclaimed.ordinal) == (
        attempt.attempt_id,
        attempt.node_run_id,
        attempt.ordinal,
    )
    parked = await spine.recovery.run_store.get_run(run_id)
    assert parked is not None and parked.status is RunStatus.WAITING
    [parked_node] = await spine.recovery.run_store.list_node_runs(run_id)
    assert parked_node.status is RunStatus.WAITING and parked_node.accepted_outcome is None
    assert parked.result is None and parked_node.result is None
    assert await recovery_container.recover_abandoned_attempts(now=lease.expires_at, limit=1) == 0
    assert await spine.recovery.run_store.get_run(run_id) == parked
    assert await spine.recovery.run_store.list_node_runs(run_id) == [parked_node]
    assert await spine.recovery.run_store.list_attempts(node.node_run_id) == [reclaimed]
    assert await spine.recovery.continuations.get(run_id) == continuation
    execute.assert_awaited_once()

    # Neither the failing writer nor the sweep authorizes another execution.
    # Explicit resume on fresh canonical/continuation owners applies the
    # existing replay contract, with no inherited in-process output.
    peer_pool = await _fresh_pool()
    try:
        peer = _replica(peer_pool)
        resumed = await resume_durable_graph(
            run_id,
            store=peer.durable(),
            run_store=peer.run_store,
            node_resolver=lambda _node_id, _graph: step,
            now=max(lease.expires_at, continuation.resume_at or lease.expires_at),
        )
        history = await spine.recovery.run_store.list_attempts(node.node_run_id)
        assert len(history) == 2
        assert history[0] == reclaimed
        retry = history[1]
        assert retry.ordinal == attempt.ordinal + 1
        assert retry.attempt_id != attempt.attempt_id
        assert retry.execution_lease is not None
        assert retry.execution_lease.fencing_token != lease.fencing_token
        assert retry.status is AttemptStatus.COMPLETED
        expected = RunStatus.COMPLETED if semantics.retryable else RunStatus.FAILED
        assert resumed.run.status is expected
        settled = await spine.recovery.run_store.get_run(run_id)
        assert settled is not None and settled.status is expected
        [settled_node] = await spine.recovery.run_store.list_node_runs(run_id)
        assert settled_node.status is expected
        assert settled_node.accepted_outcome is not None
        assert settled_node.accepted_outcome.attempt_result.attempt_id == retry.attempt_id
        if semantics.retryable:
            assert execute.await_count == 2
            assert retry.result["output"] == {"text": "done"}
            assert settled.result == {"text": "done"}
        else:
            execute.assert_awaited_once()
            assert retry.result["error_code"] == "ReplayRefused"
            assert settled.result is None
            assert (settled.error or "").startswith("ReplayRefused:")
        projected = await spine.recovery.continuations.get(run_id)
        assert projected is not None and projected.status is expected
        assert await recovery_container.recover_abandoned_attempts(now=lease.expires_at) == 0
        assert await spine.recovery.run_store.list_attempts(node.node_run_id) == history
    finally:
        await peer_pool.close()


async def test_committed_success_with_lost_acknowledgement_replays_without_execution(
    spine: _Spine, recovery_container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ordinary error after COMMIT cannot turn persisted success into failure."""
    graph = spine.graph(_Step.kind, name="successful runtime, lost acknowledgement")
    run_id = await _admit(spine, graph)
    step = _Step()
    execute = AsyncMock(wraps=step._execute)
    monkeypatch.setattr(step, "_execute", execute)
    transition = spine.walker.run_store.transition_attempt
    committed = []

    async def lose_acknowledgement(attempt_id: str, target: AttemptStatus, **kwargs: Any) -> Any:
        result = await transition(attempt_id, target, **kwargs)
        if target is AttemptStatus.COMPLETED:
            # The independent reader must see the committed payload before
            # the writer gets an error, not an assumed rollback or success.
            persisted = await spine.recovery.run_store.get_attempt(attempt_id)
            assert persisted is not None
            assert persisted.model_dump(mode="json") == result.model_dump(mode="json")
            committed.append(persisted)
            raise OSError("injected lost completion acknowledgement after commit")
        return result

    monkeypatch.setattr(spine.walker.run_store, "transition_attempt", lose_acknowledgement)
    record = await run_durable_graph(
        graph,
        store=spine.walker.durable(),
        node_resolver=lambda _node_id, _graph: step,
        run_id=run_id,
        run_store=spine.walker.run_store,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        max_steps=1,
    )
    execute.assert_awaited_once()
    assert len(committed) == 1  # No second completion write or physical retry.
    [attempt] = committed
    assert attempt.status is AttemptStatus.COMPLETED
    assert attempt.result["output"] == {"text": "done"}
    assert record.run.status is RunStatus.COMPLETED
    settled = await spine.recovery.run_store.get_run(run_id)
    assert settled is not None and settled.status is RunStatus.COMPLETED
    assert settled.result == {"text": "done"} and settled.error is None
    [node] = await spine.recovery.run_store.list_node_runs(run_id)
    assert node.status is RunStatus.COMPLETED and node.accepted_outcome is not None
    assert node.accepted_outcome.attempt_result.attempt_id == attempt.attempt_id
    assert await spine.recovery.run_store.list_attempts(node.node_run_id) == committed
    continuation = await spine.recovery.continuations.get(run_id)
    assert continuation is not None and continuation.status is RunStatus.COMPLETED
    moment = datetime.now(UTC) + _RESTART_DELAY
    assert await recovery_container.recover_abandoned_attempts(now=moment, limit=1) == 0
    assert await spine.recovery.durable().reconcile_persistence(now=moment) == 0
    assert await spine.recovery.run_store.get_run(run_id) == settled
    assert await spine.recovery.run_store.list_node_runs(run_id) == [node]
    assert await spine.recovery.run_store.list_attempts(node.node_run_id) == committed
    assert await spine.recovery.continuations.get(run_id) == continuation
    execute.assert_awaited_once()


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
