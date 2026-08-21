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
