from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from maistro.graph import Graph, Node, accepted_outcome_id
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import (
    AcceptedNodeOutcome,
    AttemptExecutionService,
    AttemptResult,
    AttemptStatus,
    InMemoryRunStore,
    RunIntegrityError,
    RunStatus,
)
from maistro.runtime import PythonExecutionRuntime


async def _execution() -> tuple[InMemoryRunStore, str, AttemptExecutionService]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-1")
    project = await projects.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Disposition",
    )
    graph = Graph(
        workspace_id="ws-1",
        project_id=project.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    store = InMemoryRunStore(project_store=projects)
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    return (
        store,
        node_run.node_run_id,
        AttemptExecutionService(
            store=store,
            runtime=PythonExecutionRuntime(),
        ),
    )


@pytest.mark.asyncio
async def test_physical_completion_can_wait_for_domain_acceptance() -> None:
    store, node_run_id, service = await _execution()

    async def executor(_work_item: Any, _context: Any) -> dict[str, str]:
        return {"status": "paused"}

    terminal = await service.execute(
        node_run_id,
        None,
        None,
        executor=executor,
        reconcile_logical=False,
    )

    assert terminal.status is AttemptStatus.COMPLETED
    logical = await store.get_node_run(node_run_id)
    assert logical is not None
    assert logical.status is RunStatus.RUNNING
    assert logical.accepted_outcome is None


@pytest.mark.asyncio
async def test_deferred_completed_result_blocks_redispatch_until_acceptance() -> None:
    _store, node_run_id, service = await _execution()
    calls = 0

    async def executor(_work_item: Any, _context: Any) -> str:
        nonlocal calls
        calls += 1
        return "side-effect"

    await service.execute(
        node_run_id,
        None,
        None,
        executor=executor,
        reconcile_logical=False,
    )
    with pytest.raises(RunIntegrityError, match="awaits domain acceptance"):
        await service.execute(
            node_run_id,
            None,
            None,
            executor=executor,
            reconcile_logical=False,
        )
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "logical_status",
    [RunStatus.PAUSED, RunStatus.WAITING, RunStatus.FAILED],
)
async def test_domain_can_project_completed_physical_result_to_noncompleted_disposition(
    logical_status: RunStatus,
) -> None:
    _store, node_run_id, service = await _execution()

    async def executor(_work_item: Any, _context: Any) -> dict[str, str]:
        return {"physical": logical_status.value}

    terminal = await service.execute(
        node_run_id,
        None,
        None,
        executor=executor,
        reconcile_logical=False,
    )
    logical_error = "logical failure" if logical_status is RunStatus.FAILED else None
    outcome = AcceptedNodeOutcome(
        node_run_id=node_run_id,
        attempt_result=AttemptResult.from_attempt(terminal),
        logical_status=logical_status,
        result=None,
        error=logical_error,
    )
    accepted = await service.accept_outcome(outcome)

    assert accepted.status is logical_status
    assert accepted.accepted_outcome == outcome
    assert accepted.result is None
    assert accepted.accepted_outcome.attempt_result.result == terminal.result


@pytest.mark.asyncio
@pytest.mark.parametrize("logical_status", [RunStatus.PAUSED, RunStatus.WAITING])
async def test_accepted_suspension_is_superseded_when_same_node_run_resumes(
    logical_status: RunStatus,
) -> None:
    store, node_run_id, service = await _execution()

    async def executor(_work_item: Any, _context: Any) -> str:
        return "suspended"

    terminal = await service.execute(
        node_run_id,
        None,
        None,
        executor=executor,
        reconcile_logical=False,
    )
    outcome = AcceptedNodeOutcome(
        node_run_id=node_run_id,
        attempt_result=AttemptResult.from_attempt(terminal),
        logical_status=logical_status,
        result="suspended",
    )
    await service.accept_outcome(outcome)

    queued = await store.transition_node_run(node_run_id, RunStatus.QUEUED)
    assert queued.status is RunStatus.QUEUED
    assert queued.accepted_outcome is None


@pytest.mark.asyncio
async def test_domain_can_project_envelope_to_smaller_logical_result() -> None:
    _store, node_run_id, service = await _execution()

    async def executor(_work_item: Any, _context: Any) -> dict[str, Any]:
        return {"success": True, "output": {"value": 7}, "telemetry": {"tokens": 3}}

    terminal = await service.execute(
        node_run_id,
        None,
        None,
        executor=executor,
        reconcile_logical=False,
    )
    outcome = AcceptedNodeOutcome(
        node_run_id=node_run_id,
        attempt_result=AttemptResult.from_attempt(terminal),
        logical_status=RunStatus.COMPLETED,
        result={"value": 7},
    )
    accepted = await service.accept_outcome(outcome)

    assert accepted.result == {"value": 7}
    assert accepted.accepted_outcome is not None
    assert accepted.accepted_outcome.attempt_result.result != accepted.result


@pytest.mark.asyncio
async def test_default_execution_still_accepts_simple_completed_result() -> None:
    store, node_run_id, service = await _execution()

    async def executor(_work_item: Any, _context: Any) -> str:
        return "ok"

    terminal = await service.execute(node_run_id, None, None, executor=executor)
    accepted = await store.get_node_run(node_run_id)

    assert terminal.status is AttemptStatus.COMPLETED
    assert accepted is not None and accepted.status is RunStatus.COMPLETED
    assert accepted.accepted_outcome is not None
    assert accepted.accepted_outcome.logical_status is RunStatus.COMPLETED
    assert accepted.accepted_outcome.result == "ok"


def test_default_completed_projection_preserves_v1_accepted_outcome_hash() -> None:
    physical = AttemptResult(
        attempt_id="attempt-1",
        node_run_id="node-run-1",
        ordinal=1,
        status=AttemptStatus.COMPLETED,
        result={"value": 7},
        finished_at=datetime(2026, 8, 16, 10, 0, tzinfo=UTC),
    )
    outcome = AcceptedNodeOutcome(
        node_run_id="node-run-1",
        attempt_result=physical,
        logical_status=RunStatus.COMPLETED,
        result={"value": 7},
    )
    legacy_payload = {
        "node_run_id": "node-run-1",
        "attempt_result": physical.model_dump(mode="json"),
    }
    expected = hashlib.sha256(
        json.dumps(
            legacy_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    assert accepted_outcome_id(outcome) == expected


def test_nondefault_projection_uses_stable_json_safe_v2_hash() -> None:
    physical = AttemptResult(
        attempt_id="attempt-1",
        node_run_id="node-run-1",
        ordinal=1,
        status=AttemptStatus.COMPLETED,
        result={"physical": "ok"},
        finished_at=datetime(2026, 8, 16, 10, 0, tzinfo=UTC),
    )
    first = AcceptedNodeOutcome(
        node_run_id="node-run-1",
        attempt_result=physical,
        logical_status=RunStatus.WAITING,
        result={"observed_at": datetime(2026, 8, 16, 10, 1, tzinfo=UTC)},
    )
    second = AcceptedNodeOutcome.model_validate(first.model_dump(mode="json"))

    assert accepted_outcome_id(first) == accepted_outcome_id(second)
