"""Durable executor supervision: plan-queue halt-on-mismatch and escalation.

These are the acceptance tests for the M4-I executor integration: declared
post-state expectations halt a Run whose reality contradicts its plan, and
quality shortfalls re-queue at the next ladder rung within the node's visit
budget — through the canonical Goal -> Graph -> Run -> NodeRun -> Attempt
spine, never around it.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import InMemoryDurableRunStore, run_durable_graph
from maistro.graph.nodes import BaseNode, NodeContext, NodeResult
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import RunStatus


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

    def __init__(self, *, quality_by_visit: list[float | None]) -> None:
        self._quality_by_visit = quality_by_visit
        self.visit: int = 0
        self.models_seen: list[str | None] = []

    async def run(self, inputs: BaseModel, ctx: NodeContext) -> NodeResult:
        escalated = ctx.metadata.get("escalated_model")
        self.models_seen.append(str(escalated) if escalated else None)
        quality = (
            self._quality_by_visit[self.visit] if self.visit < len(self._quality_by_visit) else None
        )
        self.visit += 1
        return NodeResult(
            success=True,
            output=_Out(),
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
    admitted = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
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
    assert node.models_seen == [None, "pro"]
    # The shortfall visit keeps its completed NodeRun as evidence; the
    # escalated re-visit is a fresh NodeRun, never a rewritten one.
    assert [node_run.status for node_run in record.node_runs] == [
        RunStatus.COMPLETED,
        RunStatus.COMPLETED,
    ]
    assert record.node_runs[0].node_run_id != record.node_runs[1].node_run_id


async def test_quality_pass_on_first_visit_runs_cheap_only() -> None:
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
    assert node.models_seen == [None]


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
    assert node.models_seen == [None, "pro"]


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
    from maistro.graph.nodes.base import ReplaySemantics

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
