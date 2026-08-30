"""Behavioral proof for Canvas canonical Run/NodeRun/Attempt execution (#735)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from maistro.graph.durable_runs import CanonicalDurableRunStore, InMemoryGraphContinuationStore
from maistro.graph.nodes import NodeResult
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro_canvas.canvas.canonical_execution import (
    CanvasCanonicalExecution,
    canonical_run_id,
    public_job_params,
)
from maistro_canvas.types import GenerationJobRecord, JobAction, JobStatus

pytestmark = pytest.mark.asyncio


class _FailOnceExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def _execute_claimed(self, job: GenerationJobRecord) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError(
                "503 service unavailable at https://image.internal with token=do-not-expose"
            )
        job.result_paths = ["artifacts/canvas-7/layer-3/final.png"]


class _AlwaysFailExecutor:
    async def _execute_claimed(self, job: GenerationJobRecord) -> None:
        raise RuntimeError("401 provider-key=do-not-expose")


async def _adapter() -> tuple[CanvasCanonicalExecution, Any, str]:
    project_store = InMemoryProjectScopeStore()
    project = await project_store.create_root("workspace-canvas")
    run_store = InMemoryRunStore(project_store=project_store)
    durable = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
    adapter = CanvasCanonicalExecution(
        run_store=run_store,
        durable_store=durable,
        workspace_id="workspace-canvas",
        project_id=project.project_id,
        actor_principal_id="canvas-user",
    )
    return adapter, run_store, project.project_id


def _job(*, max_attempts: int = 3) -> GenerationJobRecord:
    return GenerationJobRecord(
        id="job-17",
        layer_id="layer-3",
        canvas_id="canvas-7",
        action=JobAction.REFINE,
        status=JobStatus.PENDING,
        model_id="proof-model",
        prompt="keep the pose; improve lighting",
        params={"count": 1, "seed": 421, "strength": 0.35},
        max_attempts=max_attempts,
    )


async def test_provider_failure_then_retry_leaves_both_attempts_inspectable() -> None:
    adapter, run_store, _ = await _adapter()
    job = _job(max_attempts=3)
    executor = _FailOnceExecutor()

    admitted_id = await adapter.admit(job)
    assert canonical_run_id(job) == admitted_id
    admitted = await run_store.get_run(admitted_id)
    assert admitted is not None
    assert admitted.status is RunStatus.QUEUED
    assert public_job_params(job) == {"count": 1, "seed": 421, "strength": 0.35}

    record = await adapter.execute(job, executor=executor)  # type: ignore[arg-type]

    assert executor.calls == 2
    assert record.run.status is RunStatus.COMPLETED
    assert job.status == JobStatus.DONE
    assert job.attempts == 2
    assert job.result_paths == ["artifacts/canvas-7/layer-3/final.png"]
    assert job.error_message is None

    node_runs = await run_store.list_node_runs(admitted_id)
    assert [item.status for item in node_runs] == [RunStatus.FAILED, RunStatus.COMPLETED]

    attempts = []
    for node_run in node_runs:
        physical = await run_store.list_attempts(node_run.node_run_id)
        assert len(physical) == 1
        attempts.extend(physical)

    assert len(attempts) == 2
    assert len({attempt.attempt_id for attempt in attempts}) == 2

    first_result = NodeResult.model_validate(attempts[0].result)
    second_result = NodeResult.model_validate(attempts[1].result)
    assert first_result.success is False
    assert first_result.error_message == (
        "Generation failed: provider service temporarily unavailable."
    )
    assert "do-not-expose" not in (first_result.error_message or "")
    assert second_result.success is True
    assert second_result.output == {
        "result_paths": ["artifacts/canvas-7/layer-3/final.png"]
    }


async def test_terminal_provider_failure_projects_safe_canvas_receipt() -> None:
    adapter, run_store, _ = await _adapter()
    job = _job(max_attempts=1)
    executor = _AlwaysFailExecutor()

    run_id = await adapter.admit(job)
    record = await adapter.execute(job, executor=executor)  # type: ignore[arg-type]

    assert record.run.status is RunStatus.FAILED
    assert job.status == JobStatus.FAILED
    assert job.attempts == 1
    assert job.error_message == "Generation failed: provider authentication error."
    assert "do-not-expose" not in (job.error_message or "")

    node_runs = await run_store.list_node_runs(run_id)
    assert len(node_runs) == 1
    assert node_runs[0].status is RunStatus.FAILED
    attempts = await run_store.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1
    physical = NodeResult.model_validate(attempts[0].result)
    assert physical.success is False
    assert physical.error_message == "Generation failed: provider authentication error."
