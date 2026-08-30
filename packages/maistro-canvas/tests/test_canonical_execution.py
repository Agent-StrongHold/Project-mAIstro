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


async def _seed_active_attempt(
    runs: InMemoryRunStore,
    run_id: str,
    node_id: str,
):
    await runs.transition_run(run_id, RunStatus.RUNNING)
    node_run = await runs.create_node_run(run_id, node_id=node_id)
    await runs.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await runs.create_attempt(node_run.node_run_id, executor_id="dead-canvas-worker")
    assert attempt.execution_lease is not None
    await runs.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    return node_run, attempt


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
        ("canvas:job-1:generate", "canvas.generate"),
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

    result = await adapter.execute_stage(
        run_id,
        "generate",
        lambda: _result(["image://one"]),
    )

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


async def test_reclaimed_worker_attempt_is_fenced_before_retry() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-reclaim",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )
    node_run, abandoned = await _seed_active_attempt(
        runs,
        run_id,
        "canvas:job-reclaim:generate",
    )
    calls = 0

    async def operation() -> list[str]:
        nonlocal calls
        calls += 1
        return ["image://replacement"]

    result = await adapter.execute_stage(run_id, "generate", operation)

    assert result == ["image://replacement"]
    assert calls == 1
    attempts = await runs.list_attempts(node_run.node_run_id)
    assert [attempt.status for attempt in attempts] == [
        AttemptStatus.CANCELLED,
        AttemptStatus.COMPLETED,
    ]
    assert attempts[0].attempt_id == abandoned.attempt_id
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED


async def test_requested_cancel_fences_active_attempt_and_cancels_logical_identity() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-cancel",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )
    node_run, active = await _seed_active_attempt(
        runs,
        run_id,
        "canvas:job-cancel:generate",
    )

    await adapter.cancel(run_id)

    attempt = await runs.get_attempt(active.attempt_id)
    assert attempt is not None
    assert attempt.status is AttemptStatus.CANCELLED
    settled_node = await runs.get_node_run(node_run.node_run_id)
    assert settled_node is not None
    assert settled_node.status is RunStatus.CANCELLED
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.CANCELLED


async def test_cancel_after_failed_attempt_terminalizes_parked_node() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-cancel-parked",
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
    assert node_runs[0].status is RunStatus.WAITING
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert [attempt.status for attempt in attempts] == [AttemptStatus.FAILED]

    await adapter.cancel(run_id)

    settled_node = await runs.get_node_run(node_runs[0].node_run_id)
    assert settled_node is not None
    assert settled_node.status is RunStatus.CANCELLED
    attempts_after = await runs.list_attempts(node_runs[0].node_run_id)
    assert [attempt.status for attempt in attempts_after] == [AttemptStatus.FAILED]
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.CANCELLED


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


async def test_empty_reference_hero_short_circuits_without_fabricating_stages() -> None:
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-empty-ref",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="reference",
        actor_principal_id="user-1",
    )
    calls = 0

    async def no_hero() -> list[str]:
        nonlocal calls
        calls += 1
        return []

    first = await adapter.execute_stage(run_id, "reference.hero", no_hero)
    second = await adapter.execute_stage(run_id, "reference.hero", no_hero)

    assert first == second == []
    assert calls == 1
    node_runs = await runs.list_node_runs(run_id)
    assert [node_run.node_id for node_run in node_runs] == ["canvas:job-empty-ref:reference.hero"]
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert [attempt.status for attempt in attempts] == [AttemptStatus.COMPLETED]
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED
    assert run.result == []


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


async def test_terminal_canvas_failure_settles_stranded_physical_attempt_first() -> None:
    """Final worker lease loss cannot leave a RUNNING Attempt under a FAILED Run."""
    adapter, runs, _project_id = await _adapter()
    run_id = await adapter.admit(
        job_id="job-worker-loss",
        canvas_id="canvas-1",
        layer_id="layer-1",
        action="generate",
        actor_principal_id="user-1",
    )
    node_run, attempt = await _seed_active_attempt(
        runs,
        run_id,
        "canvas:job-worker-loss:generate",
    )

    await adapter.fail(run_id, "Generation failed: worker lease expired.")

    settled_attempt = await runs.get_attempt(attempt.attempt_id)
    assert settled_attempt is not None
    assert settled_attempt.status is AttemptStatus.CANCELLED
    settled_node = await runs.get_node_run(node_run.node_run_id)
    assert settled_node is not None
    assert settled_node.status is RunStatus.FAILED
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.FAILED
    assert run.error == "Generation failed: worker lease expired."


async def _result(value: list[str]) -> list[str]:
    return value
