from __future__ import annotations

import pytest

from maistro.graph import Graph, Node
from maistro.graph.durable_runs.execution_store import DurableRunExecutionStore
from maistro.graph.durable_runs.stores import InMemoryDurableRunStore
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.runs import AttemptExecutionService, AttemptStatus, RunStatus
from maistro.runs.lifecycle import transition_node_run, transition_run
from maistro.runs.model import GraphSnapshot, NodeRun, Run
from maistro.runtime import PythonExecutionRuntime


async def _durable_running_node() -> tuple[InMemoryDurableRunStore, DurableRunRecord, str]:
    graph = Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Attempt boundary",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = Run(
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
    )
    run = transition_run(run, RunStatus.QUEUED)
    run = transition_run(run, RunStatus.RUNNING)
    node_run = NodeRun(run_id=run.run_id, node_id="node-1", ordinal=1)
    node_run = transition_node_run(node_run, RunStatus.QUEUED)
    node_run = transition_node_run(node_run, RunStatus.RUNNING)
    record = DurableRunRecord(
        run=run,
        graph_state=GraphExecutionState(run_id=run.run_id, active_node_ids=("node-1",)),
        node_runs=(node_run,),
        version=1,
    )
    store = InMemoryDurableRunStore()
    await store.create(record)
    return store, record, node_run.node_run_id


@pytest.mark.asyncio
async def test_attempt_service_persists_physical_try_in_same_durable_record() -> None:
    store, record, node_run_id = await _durable_running_node()
    execution_store = DurableRunExecutionStore(store, run_id=record.run_id)
    service = AttemptExecutionService(
        store=execution_store,
        runtime=PythonExecutionRuntime(),
    )

    async def executor(work_item: object, context: object) -> dict[str, object]:
        return {"work": work_item, "context": context}

    attempt = await service.execute(
        node_run_id,
        {"input": 1},
        {"node": "node-1"},
        executor=executor,
        executor_id="graph.node",
        reconcile_logical=False,
    )

    persisted = await store.get(record.run_id)
    assert persisted is not None
    assert len(persisted.attempts) == 1
    assert persisted.attempts[0].attempt_id == attempt.attempt_id
    assert persisted.attempts[0].status is AttemptStatus.COMPLETED
    assert persisted.attempts[0].result == {
        "work": {"input": 1},
        "context": {"node": "node-1"},
    }
    assert persisted.node_runs[0].status is RunStatus.RUNNING


@pytest.mark.asyncio
async def test_attempt_service_can_reconcile_durable_logical_state_when_requested() -> None:
    store, record, node_run_id = await _durable_running_node()
    execution_store = DurableRunExecutionStore(store, run_id=record.run_id)
    service = AttemptExecutionService(
        store=execution_store,
        runtime=PythonExecutionRuntime(),
    )

    async def executor(_work_item: object, _context: object) -> str:
        return "ok"

    attempt = await service.execute(
        node_run_id,
        None,
        None,
        executor=executor,
    )

    persisted = await store.get(record.run_id)
    assert persisted is not None
    assert attempt.status is AttemptStatus.COMPLETED
    assert persisted.attempts[-1].status is AttemptStatus.COMPLETED
    assert persisted.node_runs[0].status is RunStatus.COMPLETED
    assert persisted.node_runs[0].result == "ok"


@pytest.mark.asyncio
async def test_retry_reuses_logical_node_run_and_appends_second_attempt() -> None:
    store, record, node_run_id = await _durable_running_node()
    execution_store = DurableRunExecutionStore(store, run_id=record.run_id)
    service = AttemptExecutionService(
        store=execution_store,
        runtime=PythonExecutionRuntime(),
    )

    async def fail(_work_item: object, _context: object) -> str:
        raise RuntimeError("first physical try failed")

    with pytest.raises(RuntimeError, match="first physical try failed"):
        await service.execute(node_run_id, None, None, executor=fail)

    after_failure = await store.get(record.run_id)
    assert after_failure is not None
    assert after_failure.node_runs[0].node_run_id == node_run_id
    assert after_failure.node_runs[0].status is RunStatus.WAITING
    assert after_failure.run.status is RunStatus.WAITING
    assert len(after_failure.attempts) == 1
    assert after_failure.attempts[0].ordinal == 1
    assert after_failure.attempts[0].status is AttemptStatus.FAILED

    async def recover(_work_item: object, _context: object) -> str:
        return "recovered"

    second = await service.execute(
        node_run_id,
        None,
        None,
        executor=recover,
        resume_checkpoint_id="checkpoint-1",
    )

    persisted = await store.get(record.run_id)
    assert persisted is not None
    assert len(persisted.node_runs) == 1
    assert persisted.node_runs[0].node_run_id == node_run_id
    assert persisted.node_runs[0].status is RunStatus.COMPLETED
    assert [attempt.ordinal for attempt in persisted.attempts] == [1, 2]
    assert persisted.attempts[1].attempt_id == second.attempt_id
    assert persisted.attempts[1].resume_checkpoint_id == "checkpoint-1"
    assert persisted.attempts[1].status is AttemptStatus.COMPLETED
    assert persisted.attempts[1].result == "recovered"


# ── lease renewal and reclamation on the fourth store (#232) ───────────
#
# `DurableRunExecutionStore` is a RunStore-shaped view over one durable Run,
# and it needs these for the same reason the other three do: a durable Graph
# node is executed by a process that can die exactly like a task worker, and
# `AttemptExecutionService` renews through whatever store it was handed.


@pytest.mark.asyncio
async def test_a_durable_lease_is_renewed_and_keeps_its_token() -> None:
    from datetime import timedelta

    store, record, node_run_id = await _durable_running_node()
    execution_store = DurableRunExecutionStore(store, run_id=record.run_id)
    attempt = await execution_store.create_attempt(
        node_run_id, lease_holder="graph-worker", lease_ttl=timedelta(seconds=30)
    )
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None

    renewed = await execution_store.renew_lease(
        attempt.attempt_id,
        fencing_token=lease.fencing_token,
        ttl=timedelta(seconds=60),
        at=lease.expires_at - timedelta(seconds=5),
    )

    assert renewed.execution_lease is not None
    assert renewed.execution_lease.expires_at > lease.expires_at
    assert renewed.execution_lease.fencing_token == lease.fencing_token
    persisted = await execution_store.get_attempt(attempt.attempt_id)
    assert persisted is not None
    assert persisted.execution_lease is not None
    assert persisted.execution_lease.expires_at == renewed.execution_lease.expires_at


@pytest.mark.asyncio
async def test_a_durable_lease_that_lapses_is_reclaimed() -> None:
    from datetime import timedelta

    store, record, node_run_id = await _durable_running_node()
    execution_store = DurableRunExecutionStore(store, run_id=record.run_id)
    attempt = await execution_store.create_attempt(
        node_run_id, lease_holder="graph-worker", lease_ttl=timedelta(seconds=30)
    )
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    await execution_store.transition_attempt(
        attempt.attempt_id, AttemptStatus.RUNNING, fencing_token=lease.fencing_token
    )

    assert await execution_store.reclaim_expired_attempts(now=lease.expires_at) != []
    settled = await execution_store.get_attempt(attempt.attempt_id)
    assert settled is not None
    assert settled.status is AttemptStatus.CANCELLED
    assert "graph-worker" in (settled.error or "")


@pytest.mark.asyncio
async def test_a_live_durable_lease_is_left_alone_and_reclaim_is_idempotent() -> None:
    from datetime import timedelta

    store, record, node_run_id = await _durable_running_node()
    execution_store = DurableRunExecutionStore(store, run_id=record.run_id)
    attempt = await execution_store.create_attempt(
        node_run_id, lease_holder="graph-worker", lease_ttl=timedelta(seconds=30)
    )
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None

    assert (
        await execution_store.reclaim_expired_attempts(now=lease.expires_at - timedelta(seconds=1))
        == []
    )

    first = await execution_store.reclaim_expired_attempts(
        now=lease.expires_at + timedelta(seconds=1)
    )
    second = await execution_store.reclaim_expired_attempts(
        now=lease.expires_at + timedelta(hours=1)
    )

    assert len(first) == 1
    assert second == []


@pytest.mark.asyncio
async def test_a_durable_attempt_without_a_ttl_is_never_reclaimed() -> None:
    from datetime import UTC, datetime, timedelta

    store, record, node_run_id = await _durable_running_node()
    execution_store = DurableRunExecutionStore(store, run_id=record.run_id)
    attempt = await execution_store.create_attempt(node_run_id, lease_holder="graph-worker")

    assert attempt.execution_lease is not None
    assert attempt.execution_lease.expires_at is None
    assert (
        await execution_store.reclaim_expired_attempts(now=datetime.now(UTC) + timedelta(days=365))
        == []
    )


@pytest.mark.asyncio
async def test_renewing_an_unknown_durable_attempt_is_refused() -> None:
    from datetime import timedelta

    from maistro.runs.store import AttemptNotFound

    store, record, _node_run_id = await _durable_running_node()
    execution_store = DurableRunExecutionStore(store, run_id=record.run_id)

    with pytest.raises(AttemptNotFound):
        await execution_store.renew_lease(
            "no-such-attempt", fencing_token="t", ttl=timedelta(seconds=30)
        )
