"""Acceptance regressions for canonical admitted-Run claim recovery (#544)."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import ClassVar

from pydantic import BaseModel

from maistro.container import Container, create_container
from maistro.graph import Graph, Node
from maistro.graph.nodes import BaseNode, NodeContext, register_node
from maistro.runs.consumer_claim import ConsumerClaimLost, ConsumerClaimStore
from maistro.runs.consumption import SCHEDULE_EXECUTOR_ID
from maistro.runs.model import Attempt, AttemptStatus, RunStatus
from maistro.runs.sources import ADMISSION_SOURCE, SCHEDULE_SOURCE
from maistro.types.config import AgentConfig


class _In(BaseModel):
    value: str = "ok"


class _Out(BaseModel):
    value: str


class _EligibleNode(BaseNode[_In, _Out]):
    kind: ClassVar[str] = "test.consumer.claim-recovery"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out
    calls: ClassVar[int] = 0

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        del ctx
        type(self).calls += 1
        return _Out(value=inputs.value)


with contextlib.suppress(ValueError):
    register_node(_EligibleNode)


async def _container() -> Container:
    return await create_container(AgentConfig(router_api_key="test-key"))


async def _admit(
    container: Container,
    *,
    workspace: str,
    source: str = SCHEDULE_SOURCE,
    nodes: int = 1,
) -> str:
    root = await container.project_scope_store.create_root(workspace)
    graph = Graph(
        workspace_id=workspace,
        project_id=root.project_id,
        name="consumer claim recovery",
        nodes=[Node(node_id=f"n{i}", node_type=_EligibleNode.kind) for i in range(nodes)],
    )
    run = await container.run_store.create_run(
        graph,
        provenance={ADMISSION_SOURCE: source},
        initial_status=RunStatus.QUEUED,
    )
    return run.run_id


async def test_ineligible_head_rows_do_not_starve_eligible_work_behind_limit() -> None:
    """`limit` bounds executions, not how many oldest QUEUED rows may be inspected.

    This is the #544 regression: the old consumer asks the store for exactly
    `limit` oldest QUEUED rows and filters eligibility afterwards. Once those
    rows are permanently ineligible, every tick sees the same prefix forever.
    """
    _EligibleNode.calls = 0
    container = await _container()
    limit = 3

    foreign = [
        await _admit(container, workspace=f"foreign-{index}", source="task_queue")
        for index in range(limit)
    ]
    eligible = await _admit(container, workspace="eligible")

    executed = await container.execute_admitted_runs(limit=limit)

    assert executed == 1
    assert _EligibleNode.calls == 1
    eligible_run = await container.run_store.get_run(eligible)
    assert eligible_run is not None and eligible_run.status is RunStatus.COMPLETED
    for run_id in foreign:
        run = await container.run_store.get_run(run_id)
        assert run is not None and run.status is RunStatus.QUEUED


async def test_multinode_head_rows_do_not_starve_eligible_work() -> None:
    """Rows waiting for durable Graph traversal cannot starve schedules."""
    _EligibleNode.calls = 0
    container = await _container()
    limit = 2

    waiting = [
        await _admit(container, workspace=f"multi-{index}", nodes=2) for index in range(limit)
    ]
    eligible = await _admit(container, workspace="eligible-after-multi")

    assert await container.execute_admitted_runs(limit=limit) == 1
    assert _EligibleNode.calls == 1
    run = await container.run_store.get_run(eligible)
    assert run is not None and run.status is RunStatus.COMPLETED
    for run_id in waiting:
        parked = await container.run_store.get_run(run_id)
        assert parked is not None and parked.status is RunStatus.QUEUED


async def _claim(container: Container, run_id: str, *, ttl: timedelta) -> Attempt:
    run = await container.run_store.get_run(run_id)
    assert run is not None
    store = container.run_store
    assert isinstance(store, ConsumerClaimStore)
    node_id = run.graph.materialize().nodes[0].node_id
    claim = await store.claim_consumer_run(
        run_id,
        node_id=node_id,
        runtime_id="test-runtime",
        executor_id=SCHEDULE_EXECUTOR_ID,
        lease_ttl=ttl,
    )
    return claim.attempt


async def test_claim_is_run_node_and_leased_attempt_together() -> None:
    container = await _container()
    run_id = await _admit(container, workspace="leased-claim")
    attempt = await _claim(container, run_id, ttl=timedelta(seconds=30))
    run = await container.run_store.get_run(run_id)
    node_runs = await container.run_store.list_node_runs(run_id)
    assert run is not None and run.status is RunStatus.RUNNING
    assert len(node_runs) == 1 and node_runs[0].status is RunStatus.RUNNING
    assert attempt.status is AttemptStatus.RUNNING
    persisted = await container.run_store.get_attempt(attempt.attempt_id)
    assert persisted is not None and persisted.status is AttemptStatus.RUNNING
    assert attempt.execution_lease is not None


async def test_hard_death_after_claim_recovers_through_ordinary_tick() -> None:
    container = await _container()
    run_id = await _admit(container, workspace="claim-death")
    attempt = await _claim(container, run_id, ttl=timedelta(seconds=5))
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    assert (
        await container.recover_abandoned_attempts(now=lease.expires_at + timedelta(microseconds=1))
        == 1
    )
    settled = await container.run_store.get_attempt(attempt.attempt_id)
    node_run = await container.run_store.get_node_run(attempt.node_run_id)
    run = await container.run_store.get_run(run_id)
    assert settled is not None and settled.status is AttemptStatus.CANCELLED
    assert node_run is not None and node_run.status is RunStatus.WAITING
    assert run is not None and run.status is RunStatus.WAITING


async def test_concurrent_claims_have_one_physical_winner() -> None:
    container = await _container()
    run_id = await _admit(container, workspace="claim-race")
    results = await asyncio.gather(
        _claim(container, run_id, ttl=timedelta(seconds=30)),
        _claim(container, run_id, ttl=timedelta(seconds=30)),
        return_exceptions=True,
    )
    assert sum(isinstance(item, Attempt) for item in results) == 1
    assert sum(isinstance(item, ConsumerClaimLost) for item in results) == 1
    node_runs = await container.run_store.list_node_runs(run_id)
    assert len(node_runs) == 1
    attempts = await container.run_store.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1


async def test_normal_tick_completes_the_exact_claimed_attempt() -> None:
    _EligibleNode.calls = 0
    container = await _container()
    run_id = await _admit(container, workspace="exact-claimed-attempt")
    assert await container.execute_admitted_runs(limit=1) == 1
    (node_run,) = await container.run_store.list_node_runs(run_id)
    attempts = await container.run_store.list_attempts(node_run.node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.COMPLETED
    assert attempts[0].execution_lease is not None
    run = await container.run_store.get_run(run_id)
    assert run is not None and run.status is RunStatus.COMPLETED
    assert _EligibleNode.calls == 1


async def test_hard_crash_during_runtime_leaves_recoverable_running_attempt() -> None:
    """A process-level failure after runtime starts leaves leased physical evidence."""
    from maistro.runs.execution import AttemptExecutionService
    from maistro.runtime import PythonExecutionRuntime

    class _HardCrash(BaseException):
        pass

    container = await _container()
    run_id = await _admit(container, workspace="runtime-hard-crash")
    attempt = await _claim(container, run_id, ttl=timedelta(seconds=5))
    service = AttemptExecutionService(
        store=container.run_store,
        runtime=PythonExecutionRuntime(),
        lease_ttl=timedelta(seconds=5),
    )

    async def _crash(_work_item: object, _context: object) -> object:
        raise _HardCrash()

    try:
        await service.execute_claimed(attempt, None, None, executor=_crash)
    except _HardCrash:
        pass
    else:  # pragma: no cover - the executor above always raises
        raise AssertionError("hard crash did not escape execution")

    persisted = await container.run_store.get_attempt(attempt.attempt_id)
    assert persisted is not None and persisted.status is AttemptStatus.RUNNING
    lease = persisted.execution_lease
    assert lease is not None and lease.expires_at is not None
    assert (
        await container.recover_abandoned_attempts(now=lease.expires_at + timedelta(microseconds=1))
        == 1
    )
    recovered = await container.run_store.get_attempt(attempt.attempt_id)
    node_run = await container.run_store.get_node_run(attempt.node_run_id)
    run = await container.run_store.get_run(run_id)
    assert recovered is not None and recovered.status is AttemptStatus.CANCELLED
    assert node_run is not None and node_run.status is RunStatus.WAITING
    assert run is not None and run.status is RunStatus.WAITING


async def test_sqlite_claim_is_atomic_running_evidence_and_uses_ordinary_recovery() -> None:
    """The durable SQLite implementation has the same claim/recovery invariant."""
    import aiosqlite

    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs.consumer_claim import ClaimingSqliteRunStore
    from maistro.runs.reconciliation import AttemptLifecycleReconciler

    workspace = "sqlite-consumer-claim"
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace,
        parent_project_id=root.project_id,
        name="claim",
    )
    conn = await aiosqlite.connect(":memory:")
    store = ClaimingSqliteRunStore(conn, project_store=projects)
    await store.ensure_schema()
    try:
        graph = Graph(
            workspace_id=workspace,
            project_id=project.project_id,
            name="sqlite claim",
            nodes=[Node(node_id="n0", node_type=_EligibleNode.kind)],
        )
        run = await store.create_run(
            graph,
            provenance={ADMISSION_SOURCE: SCHEDULE_SOURCE},
            initial_status=RunStatus.QUEUED,
        )
        claim = await store.claim_consumer_run(
            run.run_id,
            node_id="n0",
            runtime_id="sqlite-test",
            executor_id=SCHEDULE_EXECUTOR_ID,
            lease_ttl=timedelta(seconds=5),
        )
        persisted_run = await store.get_run(run.run_id)
        persisted_node = await store.get_node_run(claim.node_run.node_run_id)
        persisted_attempt = await store.get_attempt(claim.attempt.attempt_id)
        assert persisted_run is not None and persisted_run.status is RunStatus.RUNNING
        assert persisted_node is not None and persisted_node.status is RunStatus.RUNNING
        assert persisted_attempt is not None and persisted_attempt.status is AttemptStatus.RUNNING
        lease = persisted_attempt.execution_lease
        assert lease is not None and lease.expires_at is not None

        try:
            await store.claim_consumer_run(
                run.run_id,
                node_id="n0",
                runtime_id="sqlite-test",
                executor_id=SCHEDULE_EXECUTOR_ID,
                lease_ttl=timedelta(seconds=5),
            )
        except ConsumerClaimLost:
            pass
        else:  # pragma: no cover - the first transaction owns the Run
            raise AssertionError("a second SQLite consumer claim unexpectedly succeeded")
        assert len(await store.list_node_runs(run.run_id)) == 1
        assert len(await store.list_attempts(claim.node_run.node_run_id)) == 1

        reclaimed = await store.reclaim_expired_attempts(
            now=lease.expires_at + timedelta(microseconds=1)
        )
        assert len(reclaimed) == 1
        await AttemptLifecycleReconciler(store).reconcile(reclaimed[0])
        recovered_run = await store.get_run(run.run_id)
        recovered_node = await store.get_node_run(claim.node_run.node_run_id)
        assert recovered_run is not None and recovered_run.status is RunStatus.WAITING
        assert recovered_node is not None and recovered_node.status is RunStatus.WAITING
    finally:
        await conn.close()


async def test_postgres_claim_is_atomic_running_evidence(pg_pool: object) -> None:
    if pg_pool is None:
        import pytest

        pytest.skip("MAISTRO_TEST_PG_DSN is not set")

    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.consumer_claim import ClaimingPgRunStore

    workspace = "postgres-consumer-claim"
    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace,
        parent_project_id=root.project_id,
        name="claim",
    )
    store = ClaimingPgRunStore(pg_pool, project_store=projects)
    graph = Graph(
        workspace_id=workspace,
        project_id=project.project_id,
        name="postgres claim",
        nodes=[Node(node_id="n0", node_type=_EligibleNode.kind)],
    )
    run = await store.create_run(
        graph,
        provenance={ADMISSION_SOURCE: SCHEDULE_SOURCE},
        initial_status=RunStatus.QUEUED,
    )
    claim = await store.claim_consumer_run(
        run.run_id,
        node_id="n0",
        runtime_id="postgres-test",
        executor_id=SCHEDULE_EXECUTOR_ID,
        lease_ttl=timedelta(seconds=5),
    )

    persisted_run = await store.get_run(run.run_id)
    persisted_node = await store.get_node_run(claim.node_run.node_run_id)
    persisted_attempt = await store.get_attempt(claim.attempt.attempt_id)
    assert persisted_run is not None and persisted_run.status is RunStatus.RUNNING
    assert persisted_node is not None and persisted_node.status is RunStatus.RUNNING
    assert persisted_attempt is not None and persisted_attempt.status is AttemptStatus.RUNNING
    assert persisted_attempt.execution_lease is not None
