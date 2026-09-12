from __future__ import annotations

from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.runs import AcceptedNodeOutcome, AttemptResult, AttemptStatus, RunStatus
from maistro.runs.lifecycle import InvalidLifecycleTransition
from maistro.runs.model import NodeRun
from maistro.runs.store import RunStore


async def _running_node(spine: Any) -> tuple[RunStore, NodeRun]:
    store, workspace_id, project_id = spine
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="Accepted outcome invariant",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    node_run = await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    node_run = await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    return store, node_run


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [None, {"answer": 42}])
async def test_direct_success_without_accepted_outcome_is_rejected_on_every_backend(
    spine: Any, result: object
) -> None:
    store, node_run = await _running_node(spine)

    with pytest.raises(InvalidLifecycleTransition, match="AcceptedNodeOutcome"):
        await store.transition_node_run(
            node_run.node_run_id,
            RunStatus.COMPLETED,
            result=result,
        )

    persisted = await store.get_node_run(node_run.node_run_id)
    assert persisted is not None
    assert persisted.status is RunStatus.RUNNING
    assert persisted.accepted_outcome is None


@pytest.mark.asyncio
async def test_no_output_success_is_explicit_accepted_outcome_on_every_backend(spine: Any) -> None:
    store, node_run = await _running_node(spine)
    attempt = await store.create_attempt(node_run.node_run_id)
    attempt = await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    attempt = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.COMPLETED,
        result=None,
    )
    accepted = AcceptedNodeOutcome(
        node_run_id=node_run.node_run_id,
        attempt_result=AttemptResult.from_attempt(attempt),
        logical_status=RunStatus.COMPLETED,
        result=None,
    )

    completed = await store.transition_node_run(
        node_run.node_run_id,
        RunStatus.COMPLETED,
        result=None,
        accepted_outcome=accepted,
    )

    assert completed.status is RunStatus.COMPLETED
    assert completed.result is None
    assert completed.accepted_outcome == accepted


@pytest.mark.asyncio
async def test_runtime_no_output_success_has_real_accepted_attempt(spine: Any) -> None:
    from maistro.runs.execution import AttemptExecutionService
    from maistro.runtime import PythonExecutionRuntime

    store, node_run = await _running_node(spine)
    calls: list[str] = []

    async def execute(_work: Any, _context: Any) -> None:
        calls.append("executed")

    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    terminal = await service.execute(node_run.node_run_id, None, None, executor=execute)
    persisted = await store.get_node_run(node_run.node_run_id)
    assert calls == ["executed"]
    assert terminal.status is AttemptStatus.COMPLETED
    assert persisted is not None and persisted.status is RunStatus.COMPLETED
    assert persisted.result is None
    assert persisted.accepted_outcome is not None
    assert persisted.accepted_outcome.attempt_result == AttemptResult.from_attempt(terminal)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT])
async def test_unsuccessful_terminal_states_do_not_require_success_evidence(
    spine: Any, target: RunStatus
) -> None:
    store, node_run = await _running_node(spine)
    terminal = await store.transition_node_run(node_run.node_run_id, target, error="not successful")
    assert terminal.status is target
    assert terminal.accepted_outcome is None
    assert terminal.finished_at is not None
    assert terminal.error == "not successful"
