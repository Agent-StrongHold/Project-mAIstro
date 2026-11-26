"""M4-I result-state integration of `agent.delegate_remote`.

The actionable/transitional/terminal taxonomy's flagship actor-gated node:
a paused delegation is ACTIONABLE through the shared pause table, and the
terminal outcomes that hand the next move back to the delegating actor
self-declare ACTIONABLE through the production result-metadata channel.
"""

from __future__ import annotations

from typing import Any

from maistro.a2a.delegate import A2ADelegator
from maistro.graph.nodes import NodeContext
from maistro.graph.nodes.agent_delegate_remote import AgentDelegateRemoteNode
from maistro.graph.verification import RESULT_STATE_METADATA_KEY, ResultState, classify_result_state


def _ctx(**overrides: Any) -> NodeContext:
    base: dict[str, Any] = {
        "run_id": "r1",
        "dag_id": "d1",
        "node_id": "delegate-1",
        "user_id": "u1",
        "project_id": "p1",
    }
    base.update(overrides)
    return NodeContext(**base)


def _resumed_ctx(answer: dict[str, Any]) -> NodeContext:
    ctx = _ctx()
    ctx.metadata["hitl_answers"] = {"delegate-1": answer}
    return ctx


async def test_paused_delegation_is_actionable() -> None:
    """Parking on a remote actor is ACTIONABLE via the shared pause table —
    the taxonomy reads `HUMAN_PAUSE_REASONS`, not a node-private copy."""
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder"])
    node = AgentDelegateRemoteNode(a2a_delegator=delegator)
    result = await node.run(
        {"from_agent": "planner", "task": "implement feature X", "to_agent": "coder"},
        _ctx(),
    )
    assert result.status == "paused"
    assert result.metadata["paused_reason"] == "awaiting_remote_delegation"
    assert classify_result_state(result) is ResultState.ACTIONABLE


async def test_rejected_delegation_self_declares_actionable() -> None:
    node = AgentDelegateRemoteNode()
    result = await node.run(
        {"from_agent": "planner", "task": "x"},
        _resumed_ctx({"status": "rejected", "task_id": "abc", "error": "declined"}),
    )
    assert result.status == "completed"
    assert result.output.status == "rejected"
    assert result.metadata[RESULT_STATE_METADATA_KEY] == ResultState.ACTIONABLE.value
    assert classify_result_state(result) is ResultState.ACTIONABLE


async def test_timed_out_delegation_self_declares_actionable() -> None:
    node = AgentDelegateRemoteNode()
    result = await node.run(
        {"from_agent": "planner", "task": "x"},
        _resumed_ctx({"status": "timed_out", "task_id": "abc", "timed_out": True}),
    )
    assert result.output.status == "timed_out"
    assert classify_result_state(result) is ResultState.ACTIONABLE


async def test_completed_delegation_stays_transitional() -> None:
    """A completed delegation declares nothing: in-graph work follows on the
    delegated result, which is the taxonomy's conservative default."""
    node = AgentDelegateRemoteNode()
    result = await node.run(
        {"from_agent": "planner", "task": "x"},
        _resumed_ctx({"status": "completed", "task_id": "abc", "result": "done"}),
    )
    assert result.output.status == "completed"
    assert RESULT_STATE_METADATA_KEY not in result.metadata
    assert classify_result_state(result) is ResultState.TRANSITIONAL


async def test_failed_delegation_stays_transitional() -> None:
    """A failed delegation ran and its evidence is durable; the graph may
    branch on the status itself, so it is not self-declared actor-owed."""
    node = AgentDelegateRemoteNode()
    result = await node.run(
        {"from_agent": "planner", "task": "x"},
        _resumed_ctx({"status": "failed", "task_id": "abc", "error": "boom"}),
    )
    assert result.output.status == "failed"
    assert RESULT_STATE_METADATA_KEY not in result.metadata
    assert classify_result_state(result) is ResultState.TRANSITIONAL


async def test_dispatch_time_refusal_self_declares_actionable() -> None:
    """A rejection at dispatch (no capable target) is the same actor-owed
    outcome as a resumed rejection — the delegating actor must decide."""
    delegator = A2ADelegator()  # no capabilities registered
    node = AgentDelegateRemoteNode(a2a_delegator=delegator)
    result = await node.run({"from_agent": "planner", "task": "x"}, _ctx())
    assert result.status == "completed"
    assert result.output.status == "rejected"
    assert classify_result_state(result) is ResultState.ACTIONABLE
