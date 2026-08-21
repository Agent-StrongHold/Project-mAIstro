"""Characterization tests for behavior Stream 7 must preserve during convergence.

These tests intentionally exercise the current Builders orchestration/runtime seam
without depending on canonical Run/NodeRun/Attempt APIs.  They are migration
contracts: the implementation may move onto the canonical execution spine, but
these externally useful behaviors must survive.
"""

from __future__ import annotations

import pytest

from maistro.builders.contracts import ArtifactRef, RunRequest, RunResult, RunStatus, WorkerName
from maistro.builders.orchestrator import BuildersOrchestrator
from maistro.builders.runtime import BuildersRuntime


def _create_stage_run(
    orchestrator: BuildersOrchestrator,
    *,
    run_id: str = "builders-run-1",
    stage: str = "issue_analyzed",
    worker: WorkerName = WorkerName.FRANK,
) -> None:
    orchestrator.create_run(
        run_id=run_id,
        repo="acme/widget",
        issue_number=42,
        branch="feat/widget",
        workspace_ref="workspace-1",
        initial_stage=stage,
        initial_worker=worker,
    )


@pytest.mark.asyncio
async def test_runtime_result_artifact_crosses_stage_boundary_and_worker_handoff() -> None:
    """A produced artifact remains available to the next stage/worker."""
    orchestrator = BuildersOrchestrator()
    runtime = BuildersRuntime()
    _create_stage_run(orchestrator)

    artifact = ArtifactRef(
        artifact_id="artifact-spec-1",
        type="acceptance_spec",
        path="runs/builders-run-1/acceptance.json",
        producer="frank",
        content_type="application/vnd.maistro.acceptance+json",
        version="7",
        metadata={"schema": "acceptance-v2", "reviewed": True},
    )

    async def analyze(request: RunRequest) -> RunResult:
        assert request.run_id == "builders-run-1"
        assert request.stage == "issue_analyzed"
        assert request.worker is WorkerName.FRANK
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary="analysis complete",
            artifacts=[artifact],
        )

    runtime.register(WorkerName.FRANK, "issue_analyzed", analyze)

    result = await runtime.execute(orchestrator.build_request("builders-run-1"))
    orchestrator.apply_result(result, next_stage="acceptance_defined")
    orchestrator.advance_stage(
        "builders-run-1",
        "tests_written",
        next_worker=WorkerName.MASON,
    )

    next_request = orchestrator.build_request("builders-run-1")
    assert next_request.run_id == "builders-run-1"
    assert next_request.worker is WorkerName.MASON
    assert next_request.stage == "tests_written"
    assert next_request.artifacts == [artifact]
    assert next_request.context["runtime_version"] == "v1"


@pytest.mark.asyncio
async def test_failed_runtime_result_terminalizes_builders_flow_without_advancing() -> None:
    """A failed stage cannot be accidentally advanced by a requested next stage."""
    orchestrator = BuildersOrchestrator()
    runtime = BuildersRuntime()
    _create_stage_run(orchestrator, stage="implementation_started", worker=WorkerName.MASON)

    async def implement(request: RunRequest) -> RunResult:
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.FAILED,
            summary="tests failed",
        )

    runtime.register(WorkerName.MASON, "implementation_started", implement)

    result = await runtime.execute(orchestrator.build_request("builders-run-1"))
    run = orchestrator.apply_result(result, next_stage="implementation_ready")

    assert run.run_id == "builders-run-1"
    assert run.status is RunStatus.FAILED
    assert run.current_stage == "failed"
    assert run.events[-1].event == "runtime_failed"
    assert run.events[-1].message == "tests failed"


def test_retry_preserves_logical_run_identity_and_stage_context() -> None:
    """Builders retry is currently same-run/same-stage behavior, not a new run."""
    orchestrator = BuildersOrchestrator()
    _create_stage_run(orchestrator, stage="implementation_started", worker=WorkerName.MASON)

    before = orchestrator.build_request("builders-run-1")
    run = orchestrator.schedule_retry("builders-run-1", reason="transient provider failure")
    after = orchestrator.build_request("builders-run-1")

    assert run.run_id == "builders-run-1"
    assert run.current_stage == "implementation_started"
    assert run.current_worker is WorkerName.MASON
    assert run.retries == {"implementation_started": 1}
    assert before.run_id == after.run_id == "builders-run-1"
    assert before.stage == after.stage == "implementation_started"
    assert after.context["runtime_version"] == before.context["runtime_version"] == "v1"
    assert run.events[-1].event == "retry_scheduled"


def test_revision_path_preserves_run_and_can_return_from_review_to_implementation() -> None:
    """Builders' review/revision loop is domain behavior, not lifecycle noise."""
    orchestrator = BuildersOrchestrator()
    _create_stage_run(orchestrator, stage="implementation_ready", worker=WorkerName.AUDITOR)

    run = orchestrator.advance_stage(
        "builders-run-1",
        "implementation_started",
        next_worker=WorkerName.MASON,
    )

    assert run.run_id == "builders-run-1"
    assert run.status is RunStatus.RUNNING
    assert run.current_stage == "implementation_started"
    assert run.current_worker is WorkerName.MASON
    assert run.events[-1].event == "stage_advanced"
