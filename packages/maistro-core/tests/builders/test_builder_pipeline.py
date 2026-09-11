"""Tests for the default builder pipeline and the BuildersRuntime dispatcher."""

from __future__ import annotations

import pytest

from maistro.builders.contracts import RunRequest, RunResult, RunStatus, WorkerName
from maistro.builders.graph import PipelineGraph, PipelineNode, RunContext
from maistro.builders.pipeline import (
    BUILDER_PIPELINE,
    BuilderPipeline,
    RuntimeDispatcher,
    StageStatus,
)
from maistro.builders.runtime import BuildersRuntime
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
)
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus as CanonicalRunStatus
from maistro.runs.store import InMemoryRunStore


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
async def test_builder_pipeline_records_canonical_run_and_stage_attempts() -> None:
    project_store = InMemoryProjectScopeStore()
    workspace_id = "builders-pipeline-test"
    await project_store.create_root(workspace_id)
    project = await project_store.root_for_workspace(workspace_id)
    run_store = InMemoryRunStore(project_store=project_store)
    durable_store = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
    dispatcher = ScriptedDispatcher({"spec": "spec ready"})
    pipeline = BuilderPipeline(
        dispatcher,
        nodes=[
            PipelineNode(name="spec", agent_name="planner", prompt_template="{title}"),
            PipelineNode(
                name="optional-review",
                agent_name="auditor",
                prompt_template="review",
                depends_on=("spec",),
                skip_if=lambda _ctx: True,
            ),
        ],
        run_store=run_store,
        durable_store=durable_store,
        workspace_id=workspace_id,
        project_id=project.project_id,
    )

    run = await pipeline.execute(issue_number=734, title="Builders", repo="acme/widget")

    assert run.status == "completed"
    assert run.canonical_run_id is not None
    stored = await run_store.get_run(run.canonical_run_id)
    assert stored is not None
    assert stored.status is CanonicalRunStatus.COMPLETED
    node_runs = await run_store.list_node_runs(run.canonical_run_id)
    assert [node_run.node_id for node_run in node_runs] == [
        "builders-stage:spec",
        "builders-stage:optional-review",
    ]
    attempts = [
        attempt
        for node_run in node_runs
        for attempt in await run_store.list_attempts(node_run.node_run_id)
    ]
    assert len(attempts) == 2
    assert run.skipped_stages == ["optional-review"]


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
