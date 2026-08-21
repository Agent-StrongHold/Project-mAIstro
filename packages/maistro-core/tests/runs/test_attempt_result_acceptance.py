from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import (
    AcceptedNodeOutcome,
    Attempt,
    AttemptExecutionService,
    AttemptResult,
    AttemptStatus,
    InMemoryRunStore,
    RunIntegrityError,
    RunStatus,
)
from maistro.runtime import PythonExecutionRuntime


async def _node_run() -> tuple[InMemoryRunStore, str]:
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("ws-1")
    project = await project_store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Outcome acceptance",
    )
    store = InMemoryRunStore(project_store=project_store)
    graph = Graph(
        workspace_id="ws-1",
        project_id=project.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    return store, node_run.node_run_id


def test_attempt_result_requires_terminal_attempt() -> None:
    attempt = Attempt(node_run_id="nr-1", ordinal=1)

    with pytest.raises(ValueError, match="terminal Attempt"):
        AttemptResult.from_attempt(attempt)


def test_attempt_result_detaches_and_freezes_nested_mutable_payloads() -> None:
    payload = {"items": [{"value": 1}]}
    attempt = Attempt(
        attempt_id="attempt-1",
        node_run_id="nr-1",
        ordinal=1,
        status=AttemptStatus.COMPLETED,
        result=payload,
        finished_at=datetime.now(UTC),
    )

    evidence = AttemptResult.from_attempt(attempt)
    payload["items"][0]["value"] = 2

    assert evidence.result == {"items": [{"value": 1}]}
    with pytest.raises(TypeError, match="immutable"):
        evidence.result["other"] = 3
    with pytest.raises(TypeError, match="immutable"):
        evidence.result["items"].append({"value": 4})


@pytest.mark.asyncio
async def test_completed_attempt_becomes_explicit_accepted_node_outcome() -> None:
    store, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def executor(work_item: Any, _context: Any) -> dict[str, Any]:
        return {"value": work_item}

    terminal = await service.execute(
        node_run_id,
        7,
        None,
        executor=executor,
        executor_id="agent",
    )

    node_run = await store.get_node_run(node_run_id)
    assert node_run is not None
    assert node_run.status is RunStatus.COMPLETED
    assert node_run.result == {"value": 7}
    assert node_run.accepted_outcome is not None
    assert node_run.accepted_outcome.node_run_id == node_run_id
    assert node_run.accepted_outcome.attempt_result.attempt_id == terminal.attempt_id
    assert node_run.accepted_outcome.attempt_result.status is AttemptStatus.COMPLETED
    assert node_run.accepted_outcome.attempt_result.result == terminal.result


@pytest.mark.asyncio
async def test_nan_result_can_be_accepted_without_stranding_node_run() -> None:
    store, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def executor(_work_item: Any, _context: Any) -> float:
        return float("nan")

    await service.execute(node_run_id, None, None, executor=executor)
    node_run = await store.get_node_run(node_run_id)

    assert node_run is not None and node_run.status is RunStatus.COMPLETED
    assert node_run.accepted_outcome is not None
    assert math.isnan(node_run.result)


@pytest.mark.asyncio
async def test_store_rejects_fabricated_accepted_attempt_evidence() -> None:
    store, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def executor(_work_item: Any, _context: Any) -> str:
        return "real"

    terminal = await service.execute(node_run_id, None, None, executor=executor)
    accepted = await store.get_node_run(node_run_id)
    assert accepted is not None and accepted.accepted_outcome is not None

    # Use a fresh logical NodeRun so lifecycle terminality does not mask the
    # storage-integrity assertion under test.
    run = await store.get_run(accepted.run_id)
    assert run is not None
    second = await store.create_node_run(run.run_id, node_id="node-1")
    fabricated = AcceptedNodeOutcome(
        node_run_id=second.node_run_id,
        attempt_result=AttemptResult(
            attempt_id=terminal.attempt_id,
            node_run_id=second.node_run_id,
            ordinal=terminal.ordinal,
            status=AttemptStatus.COMPLETED,
            result="forged",
            finished_at=terminal.finished_at,
        ),
    )

    with pytest.raises(RunIntegrityError):
        await store.transition_node_run(
            second.node_run_id,
            RunStatus.COMPLETED,
            result="forged",
            accepted_outcome=fabricated,
        )


@pytest.mark.asyncio
async def test_retry_history_remains_physical_while_only_success_is_accepted() -> None:
    store, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def fail(_work_item: Any, _context: Any) -> None:
        raise RuntimeError("transient")

    with pytest.raises(RuntimeError, match="transient"):
        await service.execute(node_run_id, None, None, executor=fail)

    after_failure = await store.get_node_run(node_run_id)
    assert after_failure is not None
    assert after_failure.status is RunStatus.WAITING
    assert after_failure.accepted_outcome is None

    async def succeed(_work_item: Any, _context: Any) -> str:
        return "accepted"

    successful = await service.execute(node_run_id, None, None, executor=succeed)
    attempts = await store.list_attempts(node_run_id)
    accepted = await store.get_node_run(node_run_id)

    assert [attempt.status for attempt in attempts] == [
        AttemptStatus.FAILED,
        AttemptStatus.COMPLETED,
    ]
    assert accepted is not None and accepted.accepted_outcome is not None
    assert accepted.accepted_outcome.attempt_result.attempt_id == successful.attempt_id
    assert accepted.accepted_outcome.attempt_result.ordinal == 2
    assert accepted.result == "accepted"
