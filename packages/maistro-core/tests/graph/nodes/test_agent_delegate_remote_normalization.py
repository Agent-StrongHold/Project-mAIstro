"""`agent.delegate_remote` resume-path normalization (M9-D3, #960).

The remote status an answer carries never settles the child on its own word:
`_resume` normalizes it through `maistro.a2a.normalize` against the child
Run's canonical facts. These cases pin the node-side behaviors the pure
normalizer tests cannot: re-parking on progress, deadline expiry into
`timed_out`, synonym/cancellation renames, and late answers against terminal
canonical truth.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.a2a.delegate import A2ADelegator
from maistro.a2a.normalize import PROGRESS_HISTORY_KEY
from maistro.graph import Graph, Node
from maistro.graph.nodes import NodeContext
from maistro.graph.nodes.agent_delegate_remote import AgentDelegateRemoteNode
from maistro.runs import InMemoryRunStore, RunStatus
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

_WORKSPACE = "workspace-1"


async def _spine() -> tuple[InMemoryRunStore, Any]:
    from maistro.projects.scope_store import InMemoryProjectScopeStore

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(_WORKSPACE)
    project = await projects.create(
        workspace_id=_WORKSPACE, parent_project_id=root.project_id, name="Project"
    )
    return InMemoryRunStore(project_store=projects), project


def _graph(project_id: str) -> Graph:
    return Graph(
        workspace_id=_WORKSPACE,
        project_id=project_id,
        name="Delegating pipeline",
        nodes=[Node(node_id="delegate-1", node_type="agent.delegate_remote")],
    )


def _ctx(run_id: str, node_run_id: str, answer: dict[str, Any] | None = None) -> NodeContext:
    metadata: dict[str, Any] = {}
    if answer is not None:
        metadata["hitl_answers"] = {"delegate-1": answer}
    return NodeContext(
        run_id=run_id,
        dag_id="dag-1",
        node_id="delegate-1",
        node_run_id=node_run_id,
        metadata=metadata,
    )


def _delegator() -> A2ADelegator:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["researcher"])
    return delegator


async def _dispatched(
    store: InMemoryRunStore, project: Any, **inputs: Any
) -> tuple[AgentDelegateRemoteNode, NodeContext, str]:
    parent = await store.create_run(
        _graph(project.project_id), actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
    node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)
    inputs.setdefault("from_agent", "planner")
    inputs.setdefault("task", "research X")
    inputs.setdefault("to_agent", "researcher")
    result = await node.run(inputs, _ctx(parent.run_id, node_run.node_run_id))
    assert result.status == "paused"
    return node, _ctx(parent.run_id, node_run.node_run_id), str(result.metadata["run_id"])


def _answer(child_id: str, **fields: Any) -> dict[str, Any]:
    return {"_pause": {"run_id": child_id}, **fields}


async def _one_node_run(store: InMemoryRunStore, child_id: str) -> Any:
    node_runs = await store.list_node_runs(child_id)
    assert len(node_runs) == 1, "normalization must never fork the child's NodeRun"
    return node_runs[0]


# --------------------------------------------------------------------------
# Progress answers re-park instead of settling
# --------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["working", "submitted", "input-required"])
async def test_a_recognized_progress_answer_re_parks_without_settling(raw: str) -> None:
    store, project = await _spine()
    node, ctx, child_id = await _dispatched(store, project)

    result = await node.run(
        {"from_agent": "planner", "task": "research X", "to_agent": "researcher"},
        _ctx(ctx.run_id, ctx.node_run_id, _answer(child_id, status=raw, task_id="t-1")),
    )

    assert result.status == "paused", "progress is not an outcome"
    assert result.metadata["paused_reason"] == "awaiting_remote_delegation"
    child = await store.get_run(child_id)
    assert child is not None and child.status is RunStatus.WAITING
    node_run = await _one_node_run(store, child_id)
    assert len(await store.list_attempts(node_run.node_run_id)) == 1
    assert result.metadata[PROGRESS_HISTORY_KEY][0]["raw_state"] == raw


async def test_progress_rides_the_pause_metadata_across_reconnects() -> None:
    store, project = await _spine()
    node, ctx, child_id = await _dispatched(store, project)
    inputs = {"from_agent": "planner", "task": "research X", "to_agent": "researcher"}

    first = await node.run(
        inputs,
        _ctx(ctx.run_id, ctx.node_run_id, _answer(child_id, status="working", task_id="t-1")),
    )
    stamped = dict(first.metadata)
    stamped.pop("paused_reason", None)
    second = await node.run(
        inputs,
        _ctx(
            ctx.run_id,
            ctx.node_run_id,
            _answer(
                child_id,
                status="working",
                task_id="t-1",
                _pause={"run_id": child_id, "metadata": stamped},
            ),
        ),
    )

    history = second.metadata[PROGRESS_HISTORY_KEY]
    assert [entry["sequence"] for entry in history] == [1, 2]
    assert history[-1]["duplicate"] is True, "a reconnect re-report is flagged, not new progress"
    node_run = await _one_node_run(store, child_id)
    assert len(await store.list_attempts(node_run.node_run_id)) == 1


async def test_progress_cannot_extend_the_delegation_deadline() -> None:
    """The window is the delegation's own timeout from the child's durable
    creation; a progress report re-parks inside it, never re-arms it. The
    resume visit re-runs the node with its persisted durable inputs, so the
    deadline input travels with the delegation."""
    store, project = await _spine()
    node, ctx, child_id = await _dispatched(store, project, timeout_seconds=0)

    result = await node.run(
        {
            "from_agent": "planner",
            "task": "research X",
            "to_agent": "researcher",
            "timeout_seconds": 0,
        },
        _ctx(ctx.run_id, ctx.node_run_id, _answer(child_id, status="working", task_id="t-1")),
    )

    assert result.status == "completed", "the expired window settles, it does not park"
    assert result.output is not None
    assert result.output.status == "timed_out"
    assert result.output.timed_out is True
    assert "working" in (result.output.error or "")
    child = await store.get_run(child_id)
    assert child is not None and child.status is RunStatus.FAILED
    node_run = await _one_node_run(store, child_id)
    attempts = await store.list_attempts(node_run.node_run_id)
    assert len(attempts) == 2
    assert attempts[-1].status.value == "completed"


async def test_progress_after_a_store_less_dispatch_still_re_parks() -> None:
    """Transport-only construction (no Run store) has no child to settle, but
    a progress report must still park rather than terminate the delegation."""
    delegator = _delegator()
    node = AgentDelegateRemoteNode(a2a_delegator=delegator)
    ctx = _ctx("r1", "nr-1")
    ctx.metadata["hitl_answers"] = {"delegate-1": {"status": "working", "task_id": "abc-123"}}
    result = await node.run({"from_agent": "planner", "task": "x"}, ctx)
    assert result.status == "paused"
    assert result.metadata[PROGRESS_HISTORY_KEY][0]["normalized"] == "progress"
    assert result.metadata[PROGRESS_HISTORY_KEY][0]["raw_state"] == "working"


# --------------------------------------------------------------------------
# Terminal answers: renames, refusals, canonical truth
# --------------------------------------------------------------------------


async def test_a_synonym_completion_settles_completed_with_a_result() -> None:
    store, project = await _spine()
    node, ctx, child_id = await _dispatched(store, project)

    result = await node.run(
        {"from_agent": "planner", "task": "research X", "to_agent": "researcher"},
        _ctx(
            ctx.run_id,
            ctx.node_run_id,
            _answer(child_id, status="succeeded", result="done!", task_id="t-1"),
        ),
    )

    assert result.output is not None
    assert result.output.status == "completed"
    assert result.output.result == "done!"
    child = await store.get_run(child_id)
    assert child is not None and child.status is RunStatus.COMPLETED


async def test_a_remote_cancellation_settles_failed_and_says_so() -> None:
    store, project = await _spine()
    node, ctx, child_id = await _dispatched(store, project)

    result = await node.run(
        {"from_agent": "planner", "task": "research X", "to_agent": "researcher"},
        _ctx(ctx.run_id, ctx.node_run_id, _answer(child_id, status="canceled", task_id="t-1")),
    )

    assert result.output is not None
    assert result.output.status == "failed"
    assert "cancelled" in (result.output.error or "")
    child = await store.get_run(child_id)
    assert child is not None and child.status is RunStatus.FAILED


async def test_a_remote_rejection_still_cancels_the_child() -> None:
    store, project = await _spine()
    node, ctx, child_id = await _dispatched(store, project)

    result = await node.run(
        {"from_agent": "planner", "task": "research X", "to_agent": "researcher"},
        _ctx(ctx.run_id, ctx.node_run_id, _answer(child_id, status="rejected", task_id="t-1")),
    )

    assert result.output is not None
    assert result.output.status == "rejected"
    child = await store.get_run(child_id)
    assert child is not None and child.status is RunStatus.CANCELLED


async def test_a_timed_out_answer_reports_its_flag_without_being_told() -> None:
    store, project = await _spine()
    node, ctx, child_id = await _dispatched(store, project)

    result = await node.run(
        {"from_agent": "planner", "task": "research X", "to_agent": "researcher"},
        _ctx(ctx.run_id, ctx.node_run_id, _answer(child_id, status="timed-out", task_id="t-1")),
    )

    assert result.output is not None
    assert result.output.status == "timed_out"
    assert result.output.timed_out is True


async def test_a_late_answer_for_a_completed_child_is_refused_not_settled() -> None:
    """The child completed; a duplicate remote `completed` with a different
    story must neither reopen it nor overwrite its result."""
    store, project = await _spine()
    node, ctx, child_id = await _dispatched(store, project)
    inputs = {"from_agent": "planner", "task": "research X", "to_agent": "researcher"}
    settled = await node.run(
        inputs,
        _ctx(
            ctx.run_id,
            ctx.node_run_id,
            _answer(child_id, status="completed", result="the real answer", task_id="t-1"),
        ),
    )
    assert settled.output is not None and settled.output.status == "completed"

    late = await node.run(
        inputs,
        _ctx(
            ctx.run_id,
            ctx.node_run_id,
            _answer(child_id, status="completed", result="the impostor answer", task_id="t-1"),
        ),
    )

    assert late.status == "completed"
    assert late.output is not None
    assert late.output.status == "failed"
    assert "already 'completed'" in (late.output.error or "")
    child = await store.get_run(child_id)
    assert child is not None
    assert child.status is RunStatus.COMPLETED
    assert child.result == "the real answer"
