"""Behavioral parity and canonical evidence for the Builders execution adapter (#734)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from maistro.builders.graph import PipelineGraph, PipelineNode, RunContext
from maistro.builders.graph_executor import (
    CanonicalGraphPipelineExecutor,
    DispatchResult,
    GraphPipelineExecutor,
)
from maistro.builders.pipeline import PipelineRun, PipelineStage, StageStatus
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
)
from maistro.graph.node import IterationBudget
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore

pytestmark = pytest.mark.contract("behavioral")


class ScriptedDispatcher:
    """Deterministic stage dispatcher with concurrency and failure instrumentation."""

    def __init__(
        self,
        outputs: dict[str, str | list[str]] | None = None,
        *,
        fail: set[str] | None = None,
        unsupported: set[str] | None = None,
        delay: float = 0.0,
    ) -> None:
        self._outputs = outputs or {}
        self._fail = fail or set()
        self._unsupported = unsupported or set()
        self._delay = delay
        self.calls: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0

    def supports(self, agent_name: str, node_name: str) -> bool:
        return node_name not in self._unsupported

    async def run(
        self,
        *,
        run_id: str,
        node_name: str,
        agent_name: str,
        prompt: str,
        context: RunContext,
    ) -> DispatchResult:
        self.calls.append(node_name)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            if node_name in self._fail:
                return DispatchResult(ok=False, error=f"{node_name} broke")
            scripted = self._outputs.get(node_name, f"{node_name} output")
            if isinstance(scripted, list):
                index = min(self.calls.count(node_name) - 1, len(scripted) - 1)
                output = scripted[index]
            else:
                output = scripted
            return DispatchResult(ok=True, output=output)
        finally:
            self.in_flight -= 1


def _node(name: str, deps: tuple[str, ...] = (), **kwargs: Any) -> PipelineNode:
    return PipelineNode(
        name=name,
        agent_name=f"agent-{name}",
        prompt_template="do {title}",
        depends_on=deps,
        **kwargs,
    )


def _run(graph: PipelineGraph, *, run_id: str) -> PipelineRun:
    nodes = list(graph)
    run = PipelineRun(
        id=run_id,
        issue_number=734,
        title="Converge Builders",
        repo="Agent-StrongHold/Project-mAIstro",
        stages=[
            PipelineStage(
                name=node.name,
                agent_name=node.agent_name,
                prompt_template=node.prompt_template,
            )
            for node in nodes
        ],
    )
    run.context.update(
        {
            "issue_number": run.issue_number,
            "title": run.title,
            "repo": run.repo,
        }
    )
    return run


@dataclass
class _Owner:
    workspace_id: str
    project_id: str
    run_store: InMemoryRunStore
    durable_store: CanonicalDurableRunStore


async def _owner() -> _Owner:
    workspace_id = "workspace-builders"
    project_store = InMemoryProjectScopeStore()
    await project_store.create_root(workspace_id)
    project = await project_store.root_for_workspace(workspace_id)
    run_store = InMemoryRunStore(project_store=project_store)
    continuation = InMemoryGraphContinuationStore()
    return _Owner(
        workspace_id=workspace_id,
        project_id=project.project_id,
        run_store=run_store,
        durable_store=CanonicalDurableRunStore(run_store, continuation),
    )


async def _canonical(
    graph: PipelineGraph,
    dispatcher: ScriptedDispatcher,
    *,
    budget: IterationBudget | None = None,
) -> tuple[PipelineRun, Any, _Owner]:
    owner = await _owner()
    run = _run(graph, run_id="builders-domain-run")
    executor = CanonicalGraphPipelineExecutor(
        dispatcher,
        run_store=owner.run_store,
        durable_store=owner.durable_store,
        workspace_id=owner.workspace_id,
        project_id=owner.project_id,
        budget=budget,
    )
    record = await executor.execute(graph, run)
    return run, record, owner


@pytest.mark.asyncio
async def test_stage_wave_parity_creates_one_canonical_run_node_runs_and_attempts() -> None:
    graph = PipelineGraph(
        [
            _node("spec"),
            _node("tests", ("spec",)),
            _node("code", ("spec",)),
            _node("review", ("tests", "code")),
        ]
    )
    legacy_dispatcher = ScriptedDispatcher(delay=0.01)
    canonical_dispatcher = ScriptedDispatcher(delay=0.01)
    legacy_run = _run(graph, run_id="legacy")

    await GraphPipelineExecutor(legacy_dispatcher).execute(graph, legacy_run)
    canonical_run, record, owner = await _canonical(graph, canonical_dispatcher)

    assert legacy_run.status == canonical_run.status == "completed"
    assert (
        legacy_dispatcher.calls
        == canonical_dispatcher.calls
        == [
            "spec",
            "tests",
            "code",
            "review",
        ]
    )
    assert legacy_dispatcher.max_in_flight == canonical_dispatcher.max_in_flight == 2
    assert legacy_run.context["review"] == canonical_run.context["review"]

    stored = await owner.run_store.get_run(record.run_id)
    assert stored is not None
    assert stored.status is RunStatus.COMPLETED
    assert stored.provenance["admission_source"] == "builders"
    assert stored.provenance["pipeline_id"] == "builders-domain-run"
    assert canonical_run.canonical_run_id == record.run_id

    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert [item.node_id for item in node_runs] == [
        "builders-stage:spec",
        "builders-stage:tests",
        "builders-stage:code",
        "builders-stage:review",
    ]
    attempts = []
    for node_run in node_runs:
        attempts.extend(await owner.run_store.list_attempts(node_run.node_run_id))
    assert len(attempts) == len(node_runs)
    assert len({attempt.attempt_id for attempt in attempts}) == len(attempts)


@pytest.mark.asyncio
async def test_multiple_root_ready_wave_preserves_concurrency_with_control_frontier() -> None:
    graph = PipelineGraph(
        [
            _node("tests"),
            _node("code"),
            _node("review", ("tests", "code")),
        ]
    )
    legacy_dispatcher = ScriptedDispatcher(delay=0.01)
    canonical_dispatcher = ScriptedDispatcher(delay=0.01)
    legacy_run = _run(graph, run_id="legacy")

    await GraphPipelineExecutor(legacy_dispatcher).execute(graph, legacy_run)
    canonical_run, record, owner = await _canonical(graph, canonical_dispatcher)

    assert legacy_run.status == canonical_run.status == "completed"
    assert legacy_dispatcher.max_in_flight == canonical_dispatcher.max_in_flight == 2
    assert legacy_dispatcher.calls == canonical_dispatcher.calls == ["tests", "code", "review"]

    node_runs = await owner.run_store.list_node_runs(record.run_id)
    stage_runs = [item for item in node_runs if item.node_id.startswith("builders-stage:")]
    assert [item.node_id for item in stage_runs] == [
        "builders-stage:tests",
        "builders-stage:code",
        "builders-stage:review",
    ]
    assert node_runs[0].node_id == "builders-frontier-start"


@pytest.mark.asyncio
async def test_skip_and_unsupported_stage_domain_projection_matches_legacy() -> None:
    graph = PipelineGraph(
        [
            _node("spec", skip_if=lambda ctx: True),
            _node("tests", ("spec",)),
            _node("code", ("tests",)),
        ]
    )
    legacy_dispatcher = ScriptedDispatcher(unsupported={"tests"})
    canonical_dispatcher = ScriptedDispatcher(unsupported={"tests"})
    legacy_run = _run(graph, run_id="legacy")

    await GraphPipelineExecutor(legacy_dispatcher).execute(graph, legacy_run)
    canonical_run, record, owner = await _canonical(graph, canonical_dispatcher)

    assert legacy_run.status == canonical_run.status == "completed"
    assert legacy_run.skipped_stages == canonical_run.skipped_stages == ["spec", "tests"]
    assert legacy_dispatcher.calls == canonical_dispatcher.calls == ["code"]
    assert [stage.status for stage in canonical_run.stages] == [
        StageStatus.SKIPPED,
        StageStatus.SKIPPED,
        StageStatus.COMPLETED,
    ]

    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert node_runs[0].result["skipped"] is True
    assert node_runs[1].result["skipped"] is True


@pytest.mark.asyncio
async def test_gate_revision_is_new_node_run_and_attempt_evidence_with_feedback() -> None:
    outputs = {"review": ["VIOLATION: missing tests", "APPROVED"]}
    graph = PipelineGraph(
        [
            _node("implement"),
            _node(
                "review",
                ("implement",),
                gate=lambda ctx: "approved" in str(ctx.get("review", "")).lower(),
                revise_target="implement",
                max_revisions=2,
            ),
        ]
    )
    legacy_dispatcher = ScriptedDispatcher(outputs=outputs)
    canonical_dispatcher = ScriptedDispatcher(outputs=outputs)
    legacy_run = _run(graph, run_id="legacy")

    await GraphPipelineExecutor(legacy_dispatcher).execute(graph, legacy_run)
    canonical_run, record, owner = await _canonical(graph, canonical_dispatcher)

    expected_calls = ["implement", "review", "implement", "review"]
    assert legacy_dispatcher.calls == canonical_dispatcher.calls == expected_calls
    assert legacy_run.status == canonical_run.status == "completed"
    assert legacy_run.revisions == canonical_run.revisions == {"review": 1}
    assert canonical_run.context["review_feedback"] == "VIOLATION: missing tests"
    assert canonical_run.context["review"] == "APPROVED"

    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert [item.node_id for item in node_runs] == [
        "builders-stage:implement",
        "builders-stage:review",
        "builders-stage:implement",
        "builders-stage:review",
    ]
    assert node_runs[1].result["route"] == "revise"
    assert node_runs[3].result["route"] == "proceed"
    attempts = []
    for node_run in node_runs:
        attempts.extend(await owner.run_store.list_attempts(node_run.node_run_id))
    assert len(attempts) == 4
    assert len({attempt.attempt_id for attempt in attempts}) == 4


@pytest.mark.asyncio
async def test_dispatch_failure_fails_canonical_run_and_never_starts_downstream() -> None:
    graph = PipelineGraph([_node("tests"), _node("code", ("tests",))])
    dispatcher = ScriptedDispatcher(fail={"tests"})

    run, record, owner = await _canonical(graph, dispatcher)

    assert record.run.status is RunStatus.FAILED
    assert run.status == "failed at tests"
    assert run.failed_stage_error == "tests broke"
    assert dispatcher.calls == ["tests"]
    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert len(node_runs) == 1
    assert node_runs[0].status is RunStatus.FAILED
    attempts = await owner.run_store.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_timeout_preserves_legacy_no_on_complete_behavior() -> None:
    hook_outputs: list[str] = []

    async def hook(run: Any, output: str) -> None:
        hook_outputs.append(output)

    graph = PipelineGraph([_node("tests", timeout_seconds=0.001, on_complete=hook)])
    dispatcher = ScriptedDispatcher(delay=0.02)

    run, record, _ = await _canonical(graph, dispatcher)

    assert record.run.status is RunStatus.FAILED
    assert run.status == "failed at tests"
    assert "timed out" in run.failed_stage_error
    assert hook_outputs == []


@pytest.mark.asyncio
async def test_iteration_budget_bounds_revision_loop_before_extra_dispatch() -> None:
    graph = PipelineGraph(
        [
            _node("implement"),
            _node(
                "review",
                ("implement",),
                gate=lambda ctx: False,
                revise_target="implement",
                max_revisions=20,
            ),
        ]
    )
    dispatcher = ScriptedDispatcher(outputs={"review": "VIOLATION"})

    run, record, owner = await _canonical(
        graph,
        dispatcher,
        budget=IterationBudget(max_iterations=3),
    )

    assert record.run.status is RunStatus.FAILED
    assert dispatcher.calls == ["implement", "review", "implement"]
    assert "iteration budget exhausted" in run.failed_stage_error
    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert [item.node_id for item in node_runs] == [
        "builders-stage:implement",
        "builders-stage:review",
        "builders-stage:implement",
        "builders-stage:review",
    ]
    assert node_runs[-1].status is RunStatus.FAILED
