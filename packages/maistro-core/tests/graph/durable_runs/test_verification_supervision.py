"""Durable executor supervision: plan-queue halt-on-mismatch and escalation.

These are the acceptance tests for the M4-I executor integration: declared
post-state expectations halt a Run whose reality contradicts its plan, and
quality shortfalls re-queue at the next ladder rung within the node's visit
budget — through the canonical Goal -> Graph -> Run -> NodeRun -> Attempt
spine, never around it.
"""

from __future__ import annotations

import math
from typing import ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph import Edge, Graph, Node
from maistro.graph.durable_runs import InMemoryDurableRunStore, run_durable_graph
from maistro.graph.nodes import BaseNode, NodeContext, NodeResult
from maistro.graph.nodes.base import PAUSE_AWAITING_HUMAN_REVIEW, ReplaySemantics
from maistro.graph.verification.escalation import ESCALATION_STATE_METADATA_KEY
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import RunStatus
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


class _In(BaseModel):
    pass


class _Out(BaseModel):
    status: str = "done"
    summary: str = "shipped"


class _ReportingNode(BaseNode[_In, _Out]):
    """Records each visit's context and reports a configurable quality.

    ``run`` is overridden (not ``_execute``) because the quality metadata is
    the node's own report about its output — exactly what a quality-judging
    node would attach — and the test node writes that envelope itself.
    """

    kind: ClassVar[str] = "test.verification_reporting"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    def __init__(
        self,
        *,
        quality_by_visit: list[float | None],
        status_by_visit: list[str] | None = None,
    ) -> None:
        self._quality_by_visit = quality_by_visit
        self._status_by_visit = status_by_visit
        self.visit: int = 0
        self.models_seen: list[str | None] = []

    async def run(self, inputs: BaseModel, ctx: NodeContext) -> NodeResult:
        rung = ctx.metadata.get("escalated_model") or ctx.metadata.get("escalation_ladder_start")
        self.models_seen.append(str(rung) if rung else None)
        quality = (
            self._quality_by_visit[self.visit] if self.visit < len(self._quality_by_visit) else None
        )
        status = (
            self._status_by_visit[self.visit]
            if self._status_by_visit is not None and self.visit < len(self._status_by_visit)
            else "done"
        )
        self.visit += 1
        return NodeResult(
            success=True,
            output=_Out(status=status),
            latency_ms=1,
            status="completed",
            metadata={"quality": quality} if quality is not None else {},
        )


async def _run(
    node: _ReportingNode,
    *,
    policies: dict[str, object],
    workspace: str,
):
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace,
        parent_project_id=root.project_id,
        name=workspace,
    )
    run_store = InMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id=workspace,
        project_id=project.project_id,
        name=workspace,
        nodes=[Node(node_id="step", node_type=node.kind, policies=dict(policies))],
    )
    admitted = await run_store.create_run(
        graph,
        initial_status=RunStatus.QUEUED,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    record = await run_durable_graph(
        graph,
        store=InMemoryDurableRunStore(),
        node_resolver=lambda _node_id, _graph: node,
        run_id=admitted.run_id,
        run_store=run_store,
    )
    return record, run_store


async def test_matching_expectation_completes() -> None:
    node = _ReportingNode(quality_by_visit=[None])
    record, _ = await _run(
        node,
        policies={
            "expect_post_state": {
                "expected_output": {"status": "done"},
                "expect_result_state": "transitional",
            }
        },
        workspace="ws-verify-happy",
    )
    assert record.status is RunStatus.COMPLETED
    assert node.visit == 1


class _AlwaysFails(BaseNode[_In, _Out]):
    kind: ClassVar[str] = "test.verification_failing"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    def __init__(self) -> None:
        self.calls = 0

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        del inputs, ctx
        self.calls += 1
        raise ValueError("domain failure")


async def _run_mixed_frontier(
    *, quality: _ReportingNode, flaky: _AlwaysFails, gate: _ReportingNode, workspace: str
):
    """gate fans out to a retryable-failure branch and a quality-ladder branch."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace,
        parent_project_id=root.project_id,
        name=workspace,
    )
    run_store = InMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id=workspace,
        project_id=project.project_id,
        name=workspace,
        nodes=[
            Node(node_id="gate", node_type=gate.kind),
            Node(
                node_id="flaky",
                node_type=flaky.kind,
                policies={"max_attempts": 2, "continue_on_failure": True},
            ),
            Node(
                node_id="quality",
                node_type=quality.kind,
                policies={
                    "max_attempts": 2,
                    "escalation_ladder": {"models": ["flash", "pro"], "quality_floor": 0.7},
                },
            ),
        ],
        edges=[
            Edge(
                edge_id="gate-flaky",
                from_node="gate",
                to_node="flaky",
                metadata={"parallel": True},
            ),
            Edge(
                edge_id="gate-quality",
                from_node="gate",
                to_node="quality",
                metadata={"parallel": True},
            ),
        ],
        metadata={"entry_node": "gate"},
    )
    admitted = await run_store.create_run(
        graph,
        initial_status=RunStatus.QUEUED,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    record = await run_durable_graph(
        graph,
        store=InMemoryDurableRunStore(),
        node_resolver=lambda node_id, _graph: {
            "gate": gate,
            "flaky": flaky,
            "quality": quality,
        }[node_id],
        run_id=admitted.run_id,
        run_store=run_store,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    return record, run_store


async def test_mixed_frontier_supervises_completed_siblings() -> None:
    """A retryable failure in one branch must not waive supervision for a
    completed sibling: on the mixed-result frontier the sub-floor visit is
    still withheld and re-queued at the next ladder rung instead of routing
    past the quality contract alongside the failure's retry."""
    gate = _ReportingNode(quality_by_visit=[None])
    quality = _ReportingNode(quality_by_visit=[0.2, 0.9])
    flaky = _AlwaysFails()
    record, _ = await _run_mixed_frontier(
        gate=gate, quality=quality, flaky=flaky, workspace="ws-verify-mixed"
    )
    assert record.status is RunStatus.COMPLETED
    # The sibling's sub-floor visit was NOT accepted as final on the mixed
    # frontier: it re-queued at the next rung exactly as it would have on a
    # clean frontier, then passed on its second visit.
    assert quality.visit == 2
    assert quality.models_seen == ["flash", "pro"]
    # The failing branch retried through its own budget; the exhausted failure
    # stayed soft via continue_on_failure.
    assert flaky.calls == 2
    assert gate.visit == 1


@pytest.mark.contract("boundary")
async def test_output_mismatch_halts_with_plan_mismatch() -> None:
    node = _ReportingNode(quality_by_visit=[None])
    record, _ = await _run(
        node,
        policies={
            "expect_post_state": {
                "expected_output": {"status": "deployed"},
                "description": "planner predicted deployment",
            }
        },
        workspace="ws-verify-mismatch",
    )
    assert record.status is RunStatus.FAILED
    assert record.run.error is not None
    assert record.run.error.startswith("PlanPostStateMismatch:")
    assert "output_mismatch" in record.run.error
    assert "planner predicted deployment" in record.run.error
    # The physical evidence stays completed; the halt is logical, not a rewrite.
    accepted = record.node_runs[-1].accepted_outcome
    assert accepted is not None
    assert accepted.attempt_result.status.value == "completed"


async def test_result_state_mismatch_halts() -> None:
    node = _ReportingNode(quality_by_visit=[None])
    record, _ = await _run(
        node,
        policies={
            "expect_post_state": {"expect_result_state": "terminal"},
        },
        workspace="ws-verify-state",
    )
    assert record.status is RunStatus.FAILED
    assert record.run.error is not None
    assert "result_state" in record.run.error
    assert "terminal" in record.run.error


async def test_unsupervised_graph_unaffected() -> None:
    node = _ReportingNode(quality_by_visit=[None])
    record, _ = await _run(node, policies={}, workspace="ws-verify-plain")
    assert record.status is RunStatus.COMPLETED


async def test_quality_shortfall_escalates_to_next_rung() -> None:
    node = _ReportingNode(quality_by_visit=[0.2, 0.9])
    record, _ = await _run(
        node,
        policies={
            "max_attempts": 2,
            "escalation_ladder": {"models": ["flash", "pro"], "quality_floor": 0.7},
        },
        workspace="ws-verify-escalate",
    )
    assert record.status is RunStatus.COMPLETED
    assert node.visit == 2
    assert node.models_seen == ["flash", "pro"]
    # The shortfall visit keeps its completed NodeRun as evidence; the
    # escalated re-visit is a fresh NodeRun, never a rewritten one.
    assert [node_run.status for node_run in record.node_runs] == [
        RunStatus.COMPLETED,
        RunStatus.COMPLETED,
    ]
    assert record.node_runs[0].node_run_id != record.node_runs[1].node_run_id
    # The accepted revisit clears the escalation rung from graph state so a
    # later revisit of the node starts fresh at the cheap/default model.
    assert ESCALATION_STATE_METADATA_KEY not in record.graph_state.metadata


async def test_quality_pass_on_first_visit_runs_cheap_only() -> None:
    """The first visit runs the ladder's cheapest rung, not an ambient default.

    The executor seeds ``escalated_model`` with ``models[0]`` for the initial
    visit of a ladder-declaring node, so a node whose configured default
    model differs from the cheapest rung still starts cheap-first — the
    fold's "no supervision state yet = cheapest rung ran" premise holds by
    construction.
    """
    node = _ReportingNode(quality_by_visit=[0.9])
    record, _ = await _run(
        node,
        policies={
            "max_attempts": 2,
            "escalation_ladder": {"models": ["flash", "pro"], "quality_floor": 0.7},
        },
        workspace="ws-verify-cheap-ok",
    )
    assert record.status is RunStatus.COMPLETED
    assert node.visit == 1
    assert node.models_seen == ["flash"]


async def test_exhausted_ladder_accepts_shortfall_without_looping() -> None:
    node = _ReportingNode(quality_by_visit=[0.2, 0.3])
    record, _ = await _run(
        node,
        policies={
            "max_attempts": 2,
            "escalation_ladder": {"models": ["flash", "pro"], "quality_floor": 0.7},
        },
        workspace="ws-verify-exhausted",
    )
    assert record.status is RunStatus.COMPLETED
    assert node.visit == 2
    assert node.models_seen == ["flash", "pro"]
    # Exhausting the ladder accepts the shortfall as final and must clear the
    # stale rung from persisted graph state, not just the local mapping.
    assert ESCALATION_STATE_METADATA_KEY not in record.graph_state.metadata


async def test_escalation_never_exceeds_visit_budget() -> None:
    node = _ReportingNode(quality_by_visit=[0.2, 0.3, 0.4])
    record, _ = await _run(
        node,
        policies={
            # Budget 2: after the second visit, supervision may not re-queue.
            "max_attempts": 2,
            "escalation_ladder": {
                "models": ["flash", "pro", "ultra"],
                "quality_floor": 0.7,
            },
        },
        workspace="ws-verify-budget",
    )
    assert record.status is RunStatus.COMPLETED
    assert node.visit == 2


async def test_non_retryable_nodes_do_not_escalate() -> None:
    class _Sticky(_ReportingNode):
        replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.NON_RETRYABLE

    node = _Sticky(quality_by_visit=[0.2])
    record, _ = await _run(
        node,
        policies={
            "max_attempts": 3,
            "escalation_ladder": {"models": ["flash", "pro"], "quality_floor": 0.7},
        },
        workspace="ws-verify-sticky",
    )
    assert record.status is RunStatus.COMPLETED
    assert node.visit == 1


class _SelfReportingNode(BaseNode[_In, _Out]):
    """Reports quality through the production self-report channel.

    Unlike ``_ReportingNode`` (which hand-builds its NodeResult envelope),
    this node writes ``NodeContext.result_metadata`` in ``_execute`` and lets
    ``BaseNode.run`` merge it — exactly the path a shipped node like
    ``llm.summarize`` takes, so the escalation gate is exercised end to end
    through the production channel rather than a test-only envelope.
    """

    kind: ClassVar[str] = "test.verification_self_report"
    kind_category: ClassVar = "sync.llm"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out
    # Same contract as the shipped model node: retryable under an effect key
    # so supervision may spend another visit when the graph declares a budget.
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.EFFECT_KEY

    def logical_effect_key(self, inputs: _In, ctx: NodeContext) -> str | None:
        # Same fail-closed contract as the shipped llm.summarize node: the
        # rung-scoped key makes a supervision re-visit a *new* keyed effect.
        rung = ctx.metadata.get("escalated_model") or ctx.metadata.get("escalation_ladder_start")
        return "test.verification_self_report:{}".format(str(rung).strip() if rung else "first")

    def __init__(self, *, quality_by_visit: list[float | None]) -> None:
        self._quality_by_visit = quality_by_visit
        self.visit: int = 0
        self.models_seen: list[str | None] = []

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        rung = ctx.metadata.get("escalated_model") or ctx.metadata.get("escalation_ladder_start")
        self.models_seen.append(str(rung) if rung else None)
        quality = (
            self._quality_by_visit[self.visit] if self.visit < len(self._quality_by_visit) else None
        )
        self.visit += 1
        if quality is not None:
            ctx.result_metadata["quality"] = quality
        return _Out()


@pytest.mark.contract("behavioral")
async def test_production_self_report_channel_drives_escalation() -> None:
    """A node self-reporting through ``NodeContext.result_metadata`` — the
    channel shipped nodes use — is withheld and re-queued at the next rung
    by the executor's supervision, without any test-built NodeResult."""
    node = _SelfReportingNode(quality_by_visit=[0.2, 0.9])
    record, _ = await _run(
        node,
        policies={
            "max_attempts": 2,
            "escalation_ladder": {"models": ["flash", "pro"], "quality_floor": 0.7},
        },
        workspace="ws-verify-channel",
    )
    assert record.status is RunStatus.COMPLETED
    assert node.visit == 2
    assert node.models_seen == ["flash", "pro"]
    # Both visits are distinct completed NodeRuns; the shortfall visit was
    # withheld from advancement, never rewritten.
    assert [node_run.status for node_run in record.node_runs] == [
        RunStatus.COMPLETED,
        RunStatus.COMPLETED,
    ]
    assert record.node_runs[0].node_run_id != record.node_runs[1].node_run_id


async def test_escalation_defers_post_state_until_the_accepted_visit() -> None:
    """A withheld cheap visit is not judged as the final world.

    Review-finding regression: enforcing the plan before escalation failed a
    Run whose cheap visit missed both the quality floor and the predicted
    output, even though the ladder's stronger rung would have satisfied the
    plan. Escalation runs first; only the visit accepted for advancement is
    supervised against the post-state.
    """
    node = _ReportingNode(
        quality_by_visit=[0.2, 0.9],
        status_by_visit=["draft", "done"],
    )
    record, _ = await _run(
        node,
        policies={
            "max_attempts": 2,
            "escalation_ladder": {"models": ["flash", "pro"], "quality_floor": 0.7},
            "expect_post_state": {"expected_output": {"status": "done"}},
        },
        workspace="ws-verify-escalate-before-plan",
    )
    assert record.status is RunStatus.COMPLETED
    assert node.visit == 2
    assert node.models_seen == ["flash", "pro"]


async def test_post_state_is_still_enforced_on_the_accepted_visit() -> None:
    """Escalation defers the plan check; it does not waive it. After the
    ladder produces an accepted visit, a contradicted post-state still halts."""
    node = _ReportingNode(
        quality_by_visit=[0.2, 0.9],
        status_by_visit=["draft", "draft"],
    )
    record, _ = await _run(
        node,
        policies={
            "max_attempts": 2,
            "escalation_ladder": {"models": ["flash", "pro"], "quality_floor": 0.7},
            "expect_post_state": {"expected_output": {"status": "done"}},
        },
        workspace="ws-verify-escalated-still-mismatched",
    )
    assert record.status is RunStatus.FAILED
    assert record.run.error is not None
    assert record.run.error.startswith("PlanPostStateMismatch:")
    assert node.visit == 2


async def test_non_finite_quality_is_a_finite_shortfall_not_a_crash() -> None:
    """A malformed quality report cannot poison durable graph state.

    ``NaN`` fails the floor comparison but used to be copied into the
    escalation metadata, where JSON construction rejected it after the fold
    had already decided to re-queue. Supervision treats it as the lowest
    score, so the visit escalates (or accepts the shortfall when the ladder
    is exhausted) and every persisted number stays finite.
    """
    node = _ReportingNode(quality_by_visit=[math.nan, 0.9])
    record, _ = await _run(
        node,
        policies={
            "max_attempts": 2,
            "escalation_ladder": {"models": ["flash", "pro"], "quality_floor": 0.7},
        },
        workspace="ws-verify-nonfinite-quality",
    )
    assert record.status is RunStatus.COMPLETED
    assert node.visit == 2
    assert node.models_seen == ["flash", "pro"]


class _PausingNode(BaseNode[_In, _Out]):
    """A successful human-gated pause: the taxonomy calls it ACTIONABLE."""

    kind: ClassVar[str] = "test.verification_pausing"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    async def run(self, inputs: BaseModel, ctx: NodeContext) -> NodeResult:
        del inputs, ctx
        return NodeResult(
            success=True,
            output=_Out(),
            latency_ms=1,
            status="paused",
            metadata={"paused_reason": PAUSE_AWAITING_HUMAN_REVIEW},
        )


async def test_paused_actionable_visit_matches_an_actionable_expectation() -> None:
    """A human pause is supervised where it happens, so a plan that predicts
    ACTIONABLE is verified against the pause rather than only after a resume
    changes the result the actor was answering."""
    node = _PausingNode()
    record, _ = await _run(
        node,
        policies={"expect_post_state": {"expect_result_state": "actionable"}},
        workspace="ws-verify-pause-matches",
    )
    assert record.status is RunStatus.PAUSED


async def test_paused_visit_that_contradicts_the_predicted_state_halts() -> None:
    """Result-state supervision on a pause is real: predicting TERMINAL while
    the node parks on a person is a contradiction, not a deferral."""
    node = _PausingNode()
    record, _ = await _run(
        node,
        policies={"expect_post_state": {"expect_result_state": "terminal"}},
        workspace="ws-verify-pause-mismatch",
    )
    assert record.status is RunStatus.FAILED
    assert record.run.error is not None
    assert record.run.error.startswith("PlanPostStateMismatch:")
    assert "result_state" in record.run.error


class _ByNodeReportingNode(BaseNode[_In, _Out]):
    """Reports a per-node output status so a multi-node plan can be mismatched
    on its second node after the first matched."""

    kind: ClassVar[str] = "test.verification_by_node"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    def __init__(self, outputs: dict[str, str]) -> None:
        self._outputs = outputs

    async def run(self, inputs: BaseModel, ctx: NodeContext) -> NodeResult:
        del inputs
        return NodeResult(
            success=True,
            output=_Out(status=self._outputs[ctx.node_id]),
            latency_ms=1,
            status="completed",
        )


async def _run_two_node_plan(*, workspace: str) -> tuple[object, _ByNodeReportingNode]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace,
        parent_project_id=root.project_id,
        name=workspace,
    )
    run_store = InMemoryRunStore(project_store=projects)
    policy = {"expect_post_state": {"expected_output": {"status": "done"}}}
    node = _ByNodeReportingNode({"first": "done", "second": "draft"})
    graph = Graph(
        workspace_id=workspace,
        project_id=project.project_id,
        name=workspace,
        nodes=[
            Node(node_id="first", node_type=node.kind, policies=policy),
            Node(node_id="second", node_type=node.kind, policies=policy),
        ],
        edges=[Edge(edge_id="first-second", from_node="first", to_node="second")],
        metadata={"entry_node": "first"},
    )
    admitted = await run_store.create_run(
        graph,
        initial_status=RunStatus.QUEUED,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    record = await run_durable_graph(
        graph,
        store=InMemoryDurableRunStore(),
        node_resolver=lambda _node_id, _graph: node,
        run_id=admitted.run_id,
        run_store=run_store,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    return record, node


async def test_plan_progress_spans_frontier_folds() -> None:
    """A mismatch on a later node does not report an already-matched earlier
    node as still awaited. Plan consumption is derived from durable completed
    NodeRuns, not from the current fold's slice."""
    record, _ = await _run_two_node_plan(workspace="ws-verify-plan-progress")
    assert record.run.status is RunStatus.FAILED
    assert record.run.error is not None
    assert record.run.error.startswith("PlanPostStateMismatch:")
    assert "node 'second'" in record.run.error
    assert "still awaiting: first" not in record.run.error
