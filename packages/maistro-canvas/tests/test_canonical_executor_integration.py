"""End-to-end Canvas package proof for canonical generation execution (#735)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro_canvas.canvas.canonical_execution import (
    CanvasCanonicalExecution,
    canonical_run_id,
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
