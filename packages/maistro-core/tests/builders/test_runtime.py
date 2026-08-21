"""Behavioral tests for the stateless BuildersRuntime stage dispatcher."""

from __future__ import annotations

import pytest

from maistro.builders.contracts import RunRequest, RunResult, RunStatus, WorkerName
from maistro.builders.runtime import BuildersRuntime


def _request(worker: WorkerName = WorkerName.FRANK, stage: str = "issue_analyzed") -> RunRequest:
    return RunRequest(
        run_id="run-1",
        worker=worker,
        stage=stage,
        repo="acme/widget",
        issue_number=1,
        branch="b",
        workspace_ref="w",
    )


@pytest.mark.asyncio
async def test_execute_dispatches_to_registered_handler() -> None:
    runtime = BuildersRuntime()

    async def handler(req: RunRequest) -> RunResult:
        return RunResult(
            run_id=req.run_id,
            worker=req.worker,
            stage=req.stage,
            status=RunStatus.PASSED,
            summary="handled",
        )

    runtime.register(WorkerName.FRANK, "issue_analyzed", handler)
    result = await runtime.execute(_request())

    assert result.status is RunStatus.PASSED
    assert result.summary == "handled"
    assert result.run_id == "run-1"


@pytest.mark.asyncio
async def test_execute_unknown_role_stage_returns_failed_not_raises() -> None:
    runtime = BuildersRuntime()
    result = await runtime.execute(_request(stage="nonexistent"))
    assert result.status is RunStatus.FAILED
    assert "Unsupported role/stage" in result.summary
    assert "frank/nonexistent" in result.summary


@pytest.mark.asyncio
async def test_execute_routes_by_worker_and_stage() -> None:
    runtime = BuildersRuntime()

    async def frank_handler(req: RunRequest) -> RunResult:
        return RunResult(
            run_id=req.run_id,
            worker=req.worker,
            stage=req.stage,
            status=RunStatus.PASSED,
            summary="frank",
        )

    async def mason_handler(req: RunRequest) -> RunResult:
        return RunResult(
            run_id=req.run_id,
            worker=req.worker,
            stage=req.stage,
            status=RunStatus.PASSED,
            summary="mason",
        )

    runtime.register(WorkerName.FRANK, "implementation_started", frank_handler)
    runtime.register(WorkerName.MASON, "implementation_started", mason_handler)

    frank_result = await runtime.execute(_request(WorkerName.FRANK, "implementation_started"))
    mason_result = await runtime.execute(_request(WorkerName.MASON, "implementation_started"))
    assert frank_result.summary == "frank"
    assert mason_result.summary == "mason"


def test_supports_reflects_registration() -> None:
    runtime = BuildersRuntime()

    async def handler(req: RunRequest) -> RunResult:  # pragma: no cover - not called
        raise AssertionError

    assert runtime.supports(WorkerName.AUDITOR, "tests_written") is False
    runtime.register(WorkerName.AUDITOR, "tests_written", handler)
    assert runtime.supports(WorkerName.AUDITOR, "tests_written") is True
    # Distinct worker for the same stage is not registered.
    assert runtime.supports(WorkerName.FRANK, "tests_written") is False


def test_prompt_register_and_load() -> None:
    runtime = BuildersRuntime()
    runtime.register_prompt(WorkerName.FRANK, "issue_analyzed", "v1", "do the thing")
    assert runtime.load_prompt(WorkerName.FRANK, "issue_analyzed", "v1") == "do the thing"


def test_load_prompt_missing_raises_keyerror() -> None:
    runtime = BuildersRuntime()
    with pytest.raises(KeyError):
        runtime.load_prompt(WorkerName.FRANK, "issue_analyzed", "v1")


def test_allowed_tools_defaults_empty_and_reflects_registration() -> None:
    runtime = BuildersRuntime()
    assert runtime.allowed_tools(WorkerName.MASON, "implementation_started") == ()
    runtime.register_tools(WorkerName.MASON, "implementation_started", ("git", "pytest"))
    assert runtime.allowed_tools(WorkerName.MASON, "implementation_started") == (
        "git",
        "pytest",
    )
