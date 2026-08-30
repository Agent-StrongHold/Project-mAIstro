"""Behavioral proof that Canvas physical work uses canonical execution (#735)."""

from __future__ import annotations

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro_canvas.canvas.canonical_execution import CanvasCanonicalExecution

pytestmark = pytest.mark.asyncio


async def _adapter() -> tuple[CanvasCanonicalExecution, InMemoryRunStore, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-1")
    runs = InMemoryRunStore(project_store=projects)
    return (
        CanvasCanonicalExecution(
            runs,
            workspace_id="workspace-1",
            project_id=root.project_id,
        ),
        runs,
        root.project_id,
    )


async def test_admission_creates_one_scoped_run_with_stage_graph() -> None:
    adapter, runs, project_id = await _adapter()

    run_id = await adapter.admit(
        job_id="job-1",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )

    run = await runs.get_run(run_id)
    assert run is not None
    assert run.workspace_id == "workspace-1"
    assert run.project_id == project_id
    assert run.actor_principal_id == "user-1"
    assert run.status is RunStatus.QUEUED
    graph = run.graph.materialize()
    assert [(node.node_id, node.node_type) for node in graph.nodes] == [
        ("canvas:job-1:generate", "canvas.generate")
    ]


async def test_successful_stage_is_one_completed_node_run_and_attempt() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-1",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )

    result = await adapter.execute_stage(run_id, "generate", lambda: _result(["image://one"]))

    assert result == ["image://one"]
    node_runs = await runs.list_node_runs(run_id)
    assert len(node_runs) == 1
    assert node_runs[0].status is RunStatus.COMPLETED
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.COMPLETED
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED


async def test_failed_stage_retry_keeps_both_attempts_under_same_node_run() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-retry",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )

    async def fail() -> list[str]:
        raise RuntimeError("provider 503")

    with pytest.raises(RuntimeError, match="provider 503"):
        await adapter.execute_stage(run_id, "generate", fail)

    node_runs = await runs.list_node_runs(run_id)
    assert len(node_runs) == 1
    first_attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert [attempt.status for attempt in first_attempts] == [AttemptStatus.FAILED]

    result = await adapter.execute_stage(
        run_id,
        "generate",
        lambda: _result(["image://retry-success"]),
    )

    assert result == ["image://retry-success"]
    node_runs_after = await runs.list_node_runs(run_id)
    assert [node_run.node_run_id for node_run in node_runs_after] == [node_runs[0].node_run_id]
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert [attempt.status for attempt in attempts] == [
        AttemptStatus.FAILED,
        AttemptStatus.COMPLETED,
    ]
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED


async def test_reference_operation_has_four_distinct_canonical_stages() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-ref",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="reference",
        actor_principal_id="user-1",
    )

    for stage in (
        "reference.hero",
        "reference.side",
        "reference.back",
        "reference.three-quarter",
    ):
        await adapter.execute_stage(run_id, stage, lambda stage=stage: _result([stage]))

    node_runs = await runs.list_node_runs(run_id)
    assert {node_run.node_id for node_run in node_runs} == {
        "canvas:job-ref:reference.hero",
        "canvas:job-ref:reference.side",
        "canvas:job-ref:reference.back",
        "canvas:job-ref:reference.three-quarter",
    }
    for node_run in node_runs:
        attempts = await runs.list_attempts(node_run.node_run_id)
        assert len(attempts) == 1
        assert attempts[0].status is AttemptStatus.COMPLETED
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED


async def test_completed_stage_reuses_attempt_evidence_without_reexecuting_provider() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-cache",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )
    calls = 0

    async def operation() -> list[str]:
        nonlocal calls
        calls += 1
        return ["image://stable"]

    first = await adapter.execute_stage(run_id, "generate", operation)
    second = await adapter.execute_stage(run_id, "generate", operation)

    assert first == second == ["image://stable"]
    assert calls == 1
    node_runs = await runs.list_node_runs(run_id)
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1


async def _result(value: list[str]) -> list[str]:
    return value
