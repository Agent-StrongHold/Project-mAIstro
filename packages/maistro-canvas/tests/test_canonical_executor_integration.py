"""End-to-end Canvas package proof for canonical generation execution (#735)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro_canvas.canvas.canonical_execution import (
    CanvasCanonicalExecution,
    canonical_run_id,
    correlate_run,
)
from maistro_canvas.canvas.executor import CanvasExecutor
from maistro_canvas.canvas.runner import CanvasJobRunner
from maistro_canvas.protocols import ImageData
from maistro_canvas.types import (
    CanvasRecord,
    GenerationJobRecord,
    JobAction,
    JobStatus,
    LayerRecord,
)

pytestmark = pytest.mark.asyncio


class _CanvasStore:
    def __init__(self) -> None:
        self.canvas = CanvasRecord(id="canvas-1", name="Canvas", width=64, height=64)
        self.layer = LayerRecord(
            id="layer-1",
            canvas_id=self.canvas.id,
            name="Background",
            layer_type="background",
        )
        self.jobs: dict[str, GenerationJobRecord] = {}
        self.fail_create = False
        self.reaped: list[GenerationJobRecord] = []

    async def get_canvas(self, canvas_id: str) -> CanvasRecord | None:
        return self.canvas if canvas_id == self.canvas.id else None

    async def get_layer(self, layer_id: str) -> LayerRecord | None:
        return self.layer if layer_id == self.layer.id else None

    async def active_job_for_layer(self, layer_id: str) -> GenerationJobRecord | None:
        return next(
            (
                job
                for job in self.jobs.values()
                if job.layer_id == layer_id and job.status in {JobStatus.PENDING, JobStatus.RUNNING}
            ),
            None,
        )

    async def create_job(self, job: GenerationJobRecord) -> GenerationJobRecord:
        if self.fail_create:
            raise RuntimeError("receipt store unavailable")
        self.jobs[job.id] = job
        return job

    async def get_job(self, job_id: str) -> GenerationJobRecord | None:
        return self.jobs.get(job_id)

    async def update_job(self, job: GenerationJobRecord) -> GenerationJobRecord:
        self.jobs[job.id] = job
        return job

    async def claim_next_pending(
        self,
        worker_id: str,
        lease_seconds: int,
    ) -> GenerationJobRecord | None:
        job = next((item for item in self.jobs.values() if item.status == JobStatus.PENDING), None)
        if job is None:
            return None
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.leased_by = worker_id
        job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        return job

    async def reap_expired_leases(self) -> list[GenerationJobRecord]:
        return list(self.reaped)


class _ImageClient:
    async def generate(self, **_kwargs: object) -> list[ImageData]:
        return [ImageData(width=64, height=64, url="image://generated")]

    async def refine(self, **_kwargs: object) -> ImageData:
        return ImageData(width=64, height=64, url="image://refined")


class _Registry:
    def is_registered(self, model_id: str) -> bool:
        return model_id == "draft-model"

    def get_default_draft(self) -> str:
        return "draft-model"


class _Warden:
    async def scan_prompt(self, _prompt: str) -> str:
        return "ALLOW"


class _CanonicalStub:
    def __init__(self) -> None:
        self.cancelled: list[str] = []
        self.failed: list[tuple[str, str]] = []

    async def admit(self, **_kwargs: object) -> str:
        return "run-stub"

    async def cancel(self, run_id: str) -> None:
        self.cancelled.append(run_id)

    async def fail(self, run_id: str, error: str) -> None:
        self.failed.append((run_id, error))

    async def execute_stage(
        self,
        _run_id: str,
        _stage: str,
        operation: Any,
    ) -> Any:
        return await operation()


class _FailingRunnerExecutor:
    canonical_enabled = True

    def __init__(self, *, with_terminal_hook: bool = True) -> None:
        self.with_terminal_hook = with_terminal_hook
        self.failures: list[str] = []

    async def _execute_claimed(self, _job: GenerationJobRecord) -> None:
        raise RuntimeError("provider 503")

    async def fail_job_execution(self, _job: GenerationJobRecord, exc: Exception) -> str:
        if not self.with_terminal_hook:
            raise AssertionError("terminal hook should not be called")
        self.failures.append(str(exc))
        return "Generation failed: provider service temporarily unavailable."


async def test_generation_request_and_runner_are_visible_on_canonical_spine() -> None:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-1")
    runs = InMemoryRunStore(project_store=projects)
    canonical = CanvasCanonicalExecution(
        runs,
        workspace_id="workspace-1",
        project_id=root.project_id,
    )
    store = _CanvasStore()
    executor = CanvasExecutor(
        store=store,  # type: ignore[arg-type]
        image_client=_ImageClient(),  # type: ignore[arg-type]
        model_registry=_Registry(),
        warden=_Warden(),
        canonical_execution=canonical,
    )

    job = await executor.start_job(
        canvas_id="canvas-1",
        layer_id="layer-1",
        action=JobAction.GENERATE,
        prompt="a safe landscape",
        actor_principal_id="user-1",
    )
    run_id = canonical_run_id(job.params)
    assert run_id is not None
    admitted = await runs.get_run(run_id)
    assert admitted is not None
    assert admitted.status is RunStatus.QUEUED
    assert admitted.actor_principal_id == "user-1"

    runner = CanvasJobRunner(store=store, executor=executor)
    assert await runner.tick_once() is True

    receipt = await store.get_job(job.id)
    assert receipt is not None
    assert receipt.status == JobStatus.DONE
    assert receipt.result_paths == ["image://generated"]
    assert receipt.attempts == 1

    node_runs = await runs.list_node_runs(run_id)
    assert len(node_runs) == 1
    assert node_runs[0].node_id == f"canvas:{job.id}:generate"
    assert node_runs[0].status is RunStatus.COMPLETED
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert [attempt.status for attempt in attempts] == [AttemptStatus.COMPLETED]
    completed = await runs.get_run(run_id)
    assert completed is not None
    assert completed.status is RunStatus.COMPLETED


async def test_receipt_persistence_failure_compensates_admitted_run() -> None:
    store = _CanvasStore()
    store.fail_create = True
    canonical = _CanonicalStub()
    executor = CanvasExecutor(
        store=store,  # type: ignore[arg-type]
        image_client=_ImageClient(),  # type: ignore[arg-type]
        model_registry=_Registry(),
        warden=_Warden(),
        canonical_execution=canonical,  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="receipt store unavailable"):
        await executor.start_job(
            canvas_id="canvas-1",
            layer_id="layer-1",
            action=JobAction.GENERATE,
            prompt="safe",
        )

    assert canonical.cancelled == ["run-stub"]


async def test_claimed_job_rejects_missing_or_unbound_canonical_correlation() -> None:
    store = _CanvasStore()
    canonical = _CanonicalStub()
    configured = CanvasExecutor(
        store=store,  # type: ignore[arg-type]
        image_client=_ImageClient(),  # type: ignore[arg-type]
        model_registry=_Registry(),
        warden=_Warden(),
        canonical_execution=canonical,  # type: ignore[arg-type]
    )
    missing = GenerationJobRecord(
        id="job-missing-run",
        layer_id="layer-1",
        canvas_id="canvas-1",
        model_id="draft-model",
    )
    with pytest.raises(RuntimeError, match="no Run correlation"):
        await configured._execute_claimed(missing)
    with pytest.raises(RuntimeError, match="no Run correlation"):
        await configured._execute_stage(missing, "generate", lambda: _async_value([]))

    unbound = CanvasExecutor(
        store=store,  # type: ignore[arg-type]
        image_client=_ImageClient(),  # type: ignore[arg-type]
        model_registry=_Registry(),
        warden=_Warden(),
    )
    correlated = GenerationJobRecord(
        id="job-unbound",
        layer_id="layer-1",
        canvas_id="canvas-1",
        model_id="draft-model",
    )
    correlate_run(correlated.params, "run-orphan")
    with pytest.raises(RuntimeError, match="no adapter is bound"):
        await unbound._execute_claimed(correlated)
    with pytest.raises(RuntimeError, match="no adapter is bound"):
        await unbound._execute_stage(correlated, "generate", lambda: _async_value([]))
    with pytest.raises(RuntimeError, match="no adapter is bound"):
        await unbound.fail_job_execution(correlated, RuntimeError("503"))
    store.jobs[correlated.id] = correlated
    with pytest.raises(RuntimeError, match="no adapter is bound"):
        await unbound.cancel_job(correlated.id)


async def test_runner_refuses_real_executor_without_canonical_binding_before_claim() -> None:
    store = _CanvasStore()
    job = GenerationJobRecord(
        id="job-no-binding",
        layer_id="layer-1",
        canvas_id="canvas-1",
        model_id="draft-model",
    )
    store.jobs[job.id] = job
    executor = CanvasExecutor(
        store=store,  # type: ignore[arg-type]
        image_client=_ImageClient(),  # type: ignore[arg-type]
        model_registry=_Registry(),
        warden=_Warden(),
    )
    runner = CanvasJobRunner(store=store, executor=executor)

    with pytest.raises(RuntimeError, match="requires canonical execution binding"):
        await runner.tick_once()

    assert job.attempts == 0
    assert job.status == JobStatus.PENDING


async def test_runner_requeues_then_terminalizes_at_retry_budget() -> None:
    store = _CanvasStore()
    job = GenerationJobRecord(
        id="job-retry-budget",
        layer_id="layer-1",
        canvas_id="canvas-1",
        model_id="draft-model",
        max_attempts=2,
    )
    store.jobs[job.id] = job
    executor = _FailingRunnerExecutor()
    runner = CanvasJobRunner(store=store, executor=executor)  # type: ignore[arg-type]

    assert await runner.tick_once() is True
    assert job.status == JobStatus.PENDING
    assert job.attempts == 1
    assert job.leased_by is None
    assert job.lease_expires_at is None

    assert await runner.tick_once() is True
    assert job.status == JobStatus.FAILED
    assert job.attempts == 2
    assert job.error_message == "Generation failed: provider service temporarily unavailable."
    assert job.completed_at is not None
    assert job.leased_by is None
    assert job.lease_expires_at is None
    assert executor.failures == ["provider 503"]


async def test_runner_idle_and_reap_terminal_failure_paths() -> None:
    store = _CanvasStore()
    executor = _FailingRunnerExecutor()
    runner = CanvasJobRunner(store=store, executor=executor)  # type: ignore[arg-type]

    assert await runner.tick_once() is False

    failed = GenerationJobRecord(
        id="job-reaped",
        layer_id="layer-1",
        canvas_id="canvas-1",
        status=JobStatus.FAILED,
        model_id="draft-model",
        error_message="canvas worker lease expired",
    )
    store.reaped = [failed]
    assert await runner.reap_once() == [failed]
    assert failed.error_message == "Generation failed: provider service temporarily unavailable."
    assert executor.failures == ["canvas worker lease expired"]


async def _async_value(value: list[str]) -> list[str]:
    return value
