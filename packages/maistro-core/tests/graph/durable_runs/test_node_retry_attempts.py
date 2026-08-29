"""A retried node is its next visit, not a second Attempt (#548).

Nothing retried a failed node before this: a failed node failed the Run. The
executor now spends the node's own budget, which is what lets
`MasterOrchestrator`'s private `_execute_item` retry loop become a projection
rather than a competing lifecycle.

Retry is a **new NodeRun**, deliberately. `AttemptExecutionService` refuses to
redispatch a completed Attempt, and that guard is right: completion means the
physical work ran, side effects and all. A node that ran and did not succeed
is a *logical* failure, so asking for it again is asking for another visit —
and the traversal already mints a NodeRun per visit for cycles.

Transport failures never reach this decision. A 429 or a 5xx is the call not
landing rather than the work failing, and `maistro.resilience.classifier`
already treats `{429, 500, 502, 503, 504}` as transient beneath the Attempt,
where repeating is safe because nothing was accomplished yet.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import InMemoryDurableRunStore, run_durable_graph
from maistro.graph.nodes import BaseNode, NodeContext, pause_until
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import AttemptStatus, RunStatus


class _In(BaseModel):
    pass


class _Out(BaseModel):
    text: str = "done"


class _FlakyStep(BaseNode[_In, _Out]):
    """Fails a fixed number of times, then succeeds."""

    kind: ClassVar[str] = "test.node_retry.flaky"
    kind_category: ClassVar = "sync.transform"
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


class _AskStep(BaseNode[_In, _Out]):
    kind: ClassVar[str] = "test.node_retry.ask"
    kind_category: ClassVar = "hitl"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    def __init__(self) -> None:
        self.calls = 0

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        self.calls += 1
        pause_until("awaiting_human_answer", metadata={"question": "Continue?"})
        return _Out(text="UNREACHABLE")


async def _spine() -> tuple[InMemoryRunStore, str, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-retry")
    project = await projects.create(
        workspace_id="ws-retry", parent_project_id=root.project_id, name="Retry"
    )
    return InMemoryRunStore(project_store=projects), "ws-retry", project.project_id


def _graph(
    workspace_id: str,
    project_id: str,
    node_type: str,
    *,
    policies: dict[str, Any] | None = None,
) -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="one step",
        nodes=[Node(node_id="step", node_type=node_type, policies=policies or {})],
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


async def test_a_node_that_fails_then_succeeds_gets_a_second_visit() -> None:
    """One NodeRun per visit, one Attempt under each. The Run's history says
    the node was tried three times and what happened each time."""
    run_store, workspace_id, project_id = await _spine()
    node = _FlakyStep(failures=2)
    graph = _graph(workspace_id, project_id, _FlakyStep.kind, policies={"max_attempts": 3})

    record = await _run(graph, node, run_store)

    assert record.status is RunStatus.COMPLETED
    assert node.calls == 3
    node_runs = await run_store.list_node_runs(record.run_id)
    assert [item.ordinal for item in node_runs] == [1, 2, 3]
    assert [item.node_id for item in node_runs] == ["step", "step", "step"]
    assert [item.status for item in node_runs] == [
        RunStatus.FAILED,
        RunStatus.FAILED,
        RunStatus.COMPLETED,
    ]
    for node_run in node_runs:
        attempts = await run_store.list_attempts(node_run.node_run_id)
        assert [item.status for item in attempts] == [AttemptStatus.COMPLETED], (
            "each visit is one physically complete try; only the logical outcome differed"
        )


async def test_the_budget_bounds_the_tries_and_the_run_still_fails() -> None:
    """A budget is a bound, not a promise. Work that never succeeds must still
    reach a terminal Run rather than retrying forever."""
    run_store, workspace_id, project_id = await _spine()
    node = _FlakyStep(failures=99)
    graph = _graph(workspace_id, project_id, _FlakyStep.kind, policies={"max_attempts": 2})

    record = await _run(graph, node, run_store)

    assert record.status is RunStatus.FAILED
    assert node.calls == 2
    node_runs = await run_store.list_node_runs(record.run_id)
    assert [item.status for item in node_runs] == [RunStatus.FAILED, RunStatus.FAILED]


async def test_without_a_policy_a_node_gets_exactly_one_try() -> None:
    """Today's behaviour, unchanged: a graph that says nothing about retries
    gets none."""
    run_store, workspace_id, project_id = await _spine()
    node = _FlakyStep(failures=1)
    graph = _graph(workspace_id, project_id, _FlakyStep.kind)

    record = await _run(graph, node, run_store)

    assert record.status is RunStatus.FAILED
    assert node.calls == 1


async def test_a_pause_is_not_a_failure_to_retry() -> None:
    """Repeating a paused node would ask the same question again while the
    first one is still outstanding."""
    run_store, workspace_id, project_id = await _spine()
    node = _AskStep()
    graph = _graph(workspace_id, project_id, _AskStep.kind, policies={"max_attempts": 3})

    record = await _run(graph, node, run_store)

    assert record.status is RunStatus.PAUSED
    assert node.calls == 1


@pytest.mark.parametrize("declared", [0, -1, "many", None, 99])
async def test_an_unusable_budget_is_one_try_not_zero(declared: Any) -> None:
    """Refusing to run the node at all is a stranger reading of "retries" than
    declining to repeat it, and a typo in a policy must not silently skip work.
    A budget above the ceiling is capped rather than honoured."""
    run_store, workspace_id, project_id = await _spine()
    node = _FlakyStep(failures=0)
    graph = _graph(workspace_id, project_id, _FlakyStep.kind, policies={"max_attempts": declared})

    record = await _run(graph, node, run_store)

    assert record.status is RunStatus.COMPLETED
    assert node.calls == 1
