"""The durable revisit gate reads the node's replay contract (#1194).

A failed visit is a new NodeRun, bounded by ``max_attempts`` only when the
kind says another visit is safe. ``pure`` and ``idempotent`` may spend the
budget. ``effect_keyed`` may only when the effect key does not name
``node_run_id``. ``non_retryable`` stops after a lease reclaim or a recovered
cancel, even when the budget has tries left.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import InMemoryDurableRunStore, run_durable_graph
from maistro.graph.durable_runs import executor as traversal
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes import BaseNode, NodeContext, NodeResult, register_node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.lifecycle import RECOVERED_CANCEL_ERROR, reclaimed_attempt_error
from maistro.runs.model import Attempt, AttemptStatus, NodeRun, RunStatus


class _In(BaseModel):
    pass


class _Out(BaseModel):
    text: str = "done"


class _Counting(BaseNode[_In, _Out]):
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    def __init__(self, failures: int) -> None:
        self.remaining = failures
        self.calls = 0

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise ValueError("transient failure")
        return _Out()


class _PureStep(_Counting):
    kind: ClassVar[str] = "test.replay.pure"
    replay: ClassVar = "pure"


class _StableEffect(_Counting):
    kind: ClassVar[str] = "test.replay.effect_stable"
    replay: ClassVar = "effect_keyed"
    effect_key: ClassVar[tuple[str, ...]] = ("run_id", "node_id")


class _VisitEffect(_Counting):
    kind: ClassVar[str] = "test.replay.effect_visit"
    replay: ClassVar = "effect_keyed"
    effect_key: ClassVar[tuple[str, ...]] = ("run_id", "node_run_id", "node_id")


class _NonRetryable(_Counting):
    kind: ClassVar[str] = "test.replay.non_retryable"
    replay: ClassVar = "non_retryable"


register_node(_PureStep)
register_node(_StableEffect)
register_node(_VisitEffect)
register_node(_NonRetryable)


async def _spine() -> tuple[InMemoryRunStore, str, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-replay")
    project = await projects.create(
        workspace_id="ws-replay", parent_project_id=root.project_id, name="Replay"
    )
    return InMemoryRunStore(project_store=projects), "ws-replay", project.project_id


def _graph(workspace_id: str, project_id: str, node_type: str, *, max_attempts: int) -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="one step",
        nodes=[Node(node_id="step", node_type=node_type, policies={"max_attempts": max_attempts})],
    )


async def _run(graph: Graph, node: BaseNode[Any, Any], run_store: InMemoryRunStore) -> Any:
    admitted = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    return await run_durable_graph(
        graph,
        store=InMemoryDurableRunStore(),
        node_resolver=lambda node_id, _graph: node,
        run_id=admitted.run_id,
        run_store=run_store,
    )


async def test_a_pure_node_may_spend_its_visit_budget() -> None:
    run_store, workspace_id, project_id = await _spine()
    node = _PureStep(failures=2)
    record = await _run(
        _graph(workspace_id, project_id, _PureStep.kind, max_attempts=3), node, run_store
    )
    assert record.status is RunStatus.COMPLETED
    assert node.calls == 3


async def test_a_stable_effect_key_may_visit_again() -> None:
    run_store, workspace_id, project_id = await _spine()
    node = _StableEffect(failures=2)
    record = await _run(
        _graph(workspace_id, project_id, _StableEffect.kind, max_attempts=3), node, run_store
    )
    assert record.status is RunStatus.COMPLETED
    assert node.calls == 3


async def test_an_effect_key_that_names_the_visit_is_not_retried() -> None:
    run_store, workspace_id, project_id = await _spine()
    node = _VisitEffect(failures=5)
    record = await _run(
        _graph(workspace_id, project_id, _VisitEffect.kind, max_attempts=3), node, run_store
    )
    assert record.status is RunStatus.FAILED
    assert node.calls == 1


async def test_the_failure_fold_hands_attempts_to_the_replay_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both folds decide through ``first_exhausted_failure``. The attempts have
    to arrive with that call, or a reclaimed lease is invisible to the contract.
    """
    seen: dict[str, Any] = {}
    original = traversal._may_revisit_after

    def spy(
        prior_state: GraphExecutionState,
        item: traversal._FrontierItem,
        *,
        attempts: tuple[Attempt, ...] = (),
        node_runs: tuple[NodeRun, ...] = (),
    ) -> bool:
        seen["attempts"] = attempts
        seen["node_runs"] = node_runs
        return original(prior_state, item, attempts=attempts, node_runs=node_runs)

    monkeypatch.setattr(traversal, "_may_revisit_after", spy)
    run_store, workspace_id, project_id = await _spine()
    node = _PureStep(failures=1)
    record = await _run(
        _graph(workspace_id, project_id, _PureStep.kind, max_attempts=1), node, run_store
    )
    assert record.status is RunStatus.FAILED
    assert seen["attempts"], "the fold decided a retry without the Attempt history"
    assert any(
        attempt.node_run_id in {item.node_run_id for item in seen["node_runs"]}
        for attempt in seen["attempts"]
    )


def _failure_item(kind: str, node_run: NodeRun) -> traversal._FrontierItem:
    spec = Node(node_id="step", node_type=kind, policies={"max_attempts": 3})
    return traversal._FrontierItem(
        node_id="step",
        spec=spec,
        node_run=node_run,
        ctx=NodeContext(
            run_id="run-1",
            dag_id="dag-1",
            node_id="step",
            node_run_id=node_run.node_run_id,
        ),
        result=NodeResult(
            success=False,
            status="failed",
            error_code="ValueError",
            error_message="nope",
        ),
    )


def _state() -> GraphExecutionState:
    return GraphExecutionState(run_id="run-1", visit_counts={"step": 1})


def _cancelled(node_run: NodeRun, error: str) -> Attempt:
    return Attempt(
        node_run_id=node_run.node_run_id,
        ordinal=1,
        status=AttemptStatus.CANCELLED,
        finished_at=datetime.now(UTC),
        error=error,
    )


@pytest.mark.parametrize(
    "error",
    [reclaimed_attempt_error("worker-1"), RECOVERED_CANCEL_ERROR],
)
def test_non_retryable_does_not_revisit_after_an_ambiguous_effect(error: str) -> None:
    node_run = NodeRun(run_id="run-1", node_id="step", ordinal=1)
    item = _failure_item(_NonRetryable.kind, node_run)
    exhausted = traversal.first_exhausted_failure(
        _state(),
        (item,),
        attempts=(_cancelled(node_run, error),),
        node_runs=(node_run,),
    )
    assert exhausted is item


def test_non_retryable_may_still_spend_a_budget_when_nothing_ambiguous_happened() -> None:
    node_run = NodeRun(run_id="run-1", node_id="step", ordinal=1)
    item = _failure_item(_NonRetryable.kind, node_run)
    assert (
        traversal.first_exhausted_failure(
            _state(),
            (item,),
            attempts=(),
            node_runs=(node_run,),
        )
        is None
    )


def test_a_pure_node_may_revisit_even_after_a_reclaimed_lease() -> None:
    node_run = NodeRun(run_id="run-1", node_id="step", ordinal=1)
    item = _failure_item(_PureStep.kind, node_run)
    assert (
        traversal.first_exhausted_failure(
            _state(),
            (item,),
            attempts=(_cancelled(node_run, reclaimed_attempt_error("worker-1")),),
            node_runs=(node_run,),
        )
        is None
    )
