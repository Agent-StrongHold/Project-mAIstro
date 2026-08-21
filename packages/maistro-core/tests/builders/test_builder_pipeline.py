"""Tests for the default builder pipeline and the BuildersRuntime dispatcher."""

from __future__ import annotations

import pytest

from maistro.builders.contracts import RunRequest, RunResult, RunStatus, WorkerName
from maistro.builders.graph import PipelineGraph, RunContext
from maistro.builders.pipeline import (
    BUILDER_PIPELINE,
    BuilderPipeline,
    RuntimeDispatcher,
    StageStatus,
)
from maistro.builders.runtime import BuildersRuntime


class ScriptedDispatcher:
    """Pipeline dispatcher returning scripted outputs keyed by node name."""

    def __init__(self, outputs: dict[str, str]) -> None:
        self._outputs = outputs
        self.prompts: dict[str, list[str]] = {}

    def supports(self, agent_name: str, node_name: str) -> bool:
        return node_name in self._outputs

    async def run(
        self,
        *,
        run_id: str,
        node_name: str,
        agent_name: str,
        prompt: str,
        context: RunContext,
    ) -> object:
        from maistro.builders.graph_executor import DispatchResult

        self.prompts.setdefault(node_name, []).append(prompt)
        return DispatchResult(ok=True, output=self._outputs[node_name])


def test_default_pipeline_is_a_valid_dag() -> None:
    graph = PipelineGraph(BUILDER_PIPELINE)

    assert graph.validate() == []
    assert [n.name for n in graph] == ["decompose", "scaffold", "implement", "review", "cleanup"]


def test_default_pipeline_review_gates_back_to_implement() -> None:
    review = next(n for n in BUILDER_PIPELINE if n.name == "review")

    assert review.gate is not None
    assert review.revise_target == "implement"
    assert review.gate_exhausted == "continue"


@pytest.mark.asyncio
async def test_atomic_issue_skips_decompose_and_clean_review_skips_cleanup() -> None:
    dispatcher = ScriptedDispatcher(
        {
            "decompose": "sub-issues",
            "scaffold": "scaffolded",
            "implement": "PR created, tests pass",
            "review": "APPROVED — no violations",
            "cleanup": "fixed",
        }
    )
    pipeline = BuilderPipeline(dispatcher)

    run = await pipeline.execute(
        issue_number=7, title="Add cache", repo="acme/widget", skip_decompose=True
    )

    assert run.status == "completed"
    assert "decompose" in run.skipped_stages
    assert "cleanup" in run.skipped_stages
    stages = {s.name: s.status for s in run.stages}
    assert stages["decompose"] is StageStatus.SKIPPED
    assert stages["implement"] is StageStatus.COMPLETED
    assert stages["review"] is StageStatus.COMPLETED
    assert stages["cleanup"] is StageStatus.SKIPPED


@pytest.mark.asyncio
async def test_clean_implement_output_skips_review_and_runs_cleanup_decision() -> None:
    dispatcher = ScriptedDispatcher(
        {
            "scaffold": "scaffolded",
            "implement": "all checks pass",
            "review": "should not run",
            "cleanup": "final sweep",
        }
    )
    pipeline = BuilderPipeline(dispatcher)

    run = await pipeline.execute(
        issue_number=8, title="Fix bug", repo="acme/widget", skip_decompose=True
    )

    assert run.status == "completed"
    assert "review" in run.skipped_stages
    assert "review" not in dispatcher.prompts


@pytest.mark.asyncio
async def test_prompt_templates_interpolate_run_context() -> None:
    dispatcher = ScriptedDispatcher(
        {
            "scaffold": "scaffolded files",
            "implement": "PR ready, approved",
        }
    )
    pipeline = BuilderPipeline(dispatcher)

    await pipeline.execute(
        issue_number=42, title="Add caching", repo="acme/widget", skip_decompose=True
    )

    implement_prompt = dispatcher.prompts["implement"][0]
    assert "issue #42: Add caching" in implement_prompt
    assert "acme/widget" in implement_prompt
    assert "scaffolded files" in implement_prompt


@pytest.mark.asyncio
async def test_run_is_recorded_and_serializable() -> None:
    dispatcher = ScriptedDispatcher({"scaffold": "ok", "implement": "approved"})
    pipeline = BuilderPipeline(dispatcher)

    run = await pipeline.execute(
        issue_number=9, title="Thing", repo="acme/widget", skip_decompose=True
    )

    assert pipeline.get_run(run.id) is run
    payload = pipeline.list_runs()
    assert payload[0]["id"] == "pipeline-9"
    assert payload[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_runtime_dispatcher_maps_agents_to_workers() -> None:
    runtime = BuildersRuntime()
    seen: list[RunRequest] = []

    async def handler(req: RunRequest) -> RunResult:
        seen.append(req)
        return RunResult(
            run_id=req.run_id,
            worker=req.worker,
            stage=req.stage,
            status=RunStatus.PASSED,
            summary="mason did it",
        )

    runtime.register(WorkerName.MASON, "implement", handler)
    dispatcher = RuntimeDispatcher(runtime)

    assert dispatcher.supports("mason", "implement")
    assert not dispatcher.supports("mason", "review")
    assert not dispatcher.supports("unknown-agent", "implement")

    result = await dispatcher.run(
        run_id="pipeline-1",
        node_name="implement",
        agent_name="mason",
        prompt="build it",
        context={"repo": "acme/widget", "issue_number": 5},
    )

    assert result.ok
    assert result.output == "mason did it"
    assert seen[0].worker is WorkerName.MASON
    assert seen[0].stage == "implement"
    assert seen[0].run_id == "pipeline-1-implement"
    assert seen[0].context["prompt"] == "build it"


@pytest.mark.asyncio
async def test_runtime_dispatcher_surfaces_failure() -> None:
    runtime = BuildersRuntime()

    async def handler(req: RunRequest) -> RunResult:
        return RunResult(
            run_id=req.run_id,
            worker=req.worker,
            stage=req.stage,
            status=RunStatus.FAILED,
            summary="exploded",
        )

    runtime.register(WorkerName.AUDITOR, "review", handler)
    dispatcher = RuntimeDispatcher(runtime)

    result = await dispatcher.run(
        run_id="pipeline-2",
        node_name="review",
        agent_name="auditor",
        prompt="check it",
        context={},
    )

    assert not result.ok
    assert result.error == "exploded"
