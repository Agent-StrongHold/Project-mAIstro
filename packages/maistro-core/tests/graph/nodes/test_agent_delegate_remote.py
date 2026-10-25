"""Tests for the `agent.delegate_remote` node.

Verifies the pause/resume contract matches the HITL nodes' shape, for both
delegation paths: in-process (via `A2ADelegator`) and cross-instance (via
`GuestPeerManager`).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from maistro.a2a.delegate import A2ADelegator
from maistro.a2a.guest_peers import DelegationResult, GuestPeerManager
from maistro.graph.nodes import NodeContext, get_node, list_kinds
from maistro.graph.nodes.agent_delegate_remote import (
    AgentDelegateRemoteNode,
    DelegationNotConfiguredError,
)


def _ctx(**overrides: Any) -> NodeContext:
    base = {
        "run_id": "r1",
        "dag_id": "d1",
        "node_id": "n1",
        "user_id": "u1",
        "project_id": "p1",
    }
    base.update(overrides)
    return NodeContext(**base)


def test_kind_is_registered() -> None:
    assert "agent.delegate_remote" in set(list_kinds())


# --- in-process delegation (A2ADelegator) ---------------------------------


async def test_in_process_first_reach_pauses_with_task_id() -> None:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder"])
    node = AgentDelegateRemoteNode(a2a_delegator=delegator)
    result = await node.run(
        {"from_agent": "planner", "task": "implement feature X", "to_agent": "coder"},
        _ctx(node_id="delegate-1"),
    )
    assert result.success is True
    assert result.status == "paused"
    assert result.resume_at is not None
    assert result.metadata["paused_reason"] == "awaiting_remote_delegation"
    assert result.metadata["mode"] == "in_process"
    assert result.metadata["to_agent"] == "coder"
    assert result.metadata["task_id"]
    # the delegator actually recorded the task
    assert delegator.get_task_status(result.metadata["task_id"]) is not None


async def test_in_process_no_delegator_configured_is_a_refusal_not_a_result() -> None:
    """A wiring fault is not the target agent declining (#147).

    This used to return `status="failed"` with "no a2a_delegator configured",
    which is the same shape a real refusal takes — so a Graph branching on
    failure could not tell "this instance is misconfigured" from "the agent
    said no", and nothing surfaced it. `build_node_resolver` constructed this
    node with `a2a_delegator=None` in the only resolver production uses, so
    that was every delegation.
    """
    node = AgentDelegateRemoteNode()  # no a2a_delegator injected

    result = await node.run({"from_agent": "planner", "task": "x"}, _ctx(node_id="delegate-1"))

    # The distinction is in the NodeResult, not the output: the *node* failed,
    # rather than completing with an output that says the delegation failed.
    assert result.success is False
    assert result.status == "failed"
    assert result.error_code == DelegationNotConfiguredError.__name__
    assert result.output is None, "a misconfiguration produces no delegation result"


async def test_in_process_delegation_rejected_returns_without_pausing() -> None:
    delegator = A2ADelegator()  # no capabilities registered for "planner"
    node = AgentDelegateRemoteNode(a2a_delegator=delegator)
    result = await node.run({"from_agent": "planner", "task": "x"}, _ctx(node_id="delegate-1"))
    assert result.status == "completed"
    assert result.output.status == "rejected"
    assert "no delegation capabilities" in (result.output.error or "")


async def test_in_process_resume_with_completed_result() -> None:
    delegator = A2ADelegator()
    node = AgentDelegateRemoteNode(a2a_delegator=delegator)
    ctx = _ctx(node_id="delegate-1")
    ctx.metadata["hitl_answers"] = {
        "delegate-1": {"status": "completed", "task_id": "abc-123", "result": "done"}
    }
    result = await node.run({"from_agent": "planner", "task": "x"}, ctx)
    assert result.status == "completed"
    assert result.output.status == "completed"
    assert result.output.task_id == "abc-123"
    assert result.output.result == "done"
    assert result.output.timed_out is False


async def test_in_process_resume_with_failed_result() -> None:
    delegator = A2ADelegator()
    node = AgentDelegateRemoteNode(a2a_delegator=delegator)
    ctx = _ctx(node_id="delegate-1")
    ctx.metadata["hitl_answers"] = {
        "delegate-1": {"status": "failed", "task_id": "abc-123", "error": "boom"}
    }
    result = await node.run({"from_agent": "planner", "task": "x"}, ctx)
    assert result.output.status == "failed"
    assert result.output.error == "boom"


async def test_in_process_resume_with_timed_out_flag() -> None:
    delegator = A2ADelegator()
    node = AgentDelegateRemoteNode(a2a_delegator=delegator)
    ctx = _ctx(node_id="delegate-1")
    ctx.metadata["hitl_answers"] = {
        "delegate-1": {"status": "timed_out", "task_id": "abc-123", "timed_out": True}
    }
    result = await node.run({"from_agent": "planner", "task": "x"}, ctx)
    assert result.output.status == "timed_out"
    assert result.output.timed_out is True


# --- cross-instance delegation (GuestPeerManager) -------------------------


async def test_cross_instance_first_reach_pauses_with_task_id() -> None:
    guest_peers = GuestPeerManager()
    guest_peers.delegate = AsyncMock(  # type: ignore[method-assign]
        return_value=DelegationResult(task_id="remote-1", peer_name="hub", status="submitted")
    )
    node = AgentDelegateRemoteNode(guest_peers=guest_peers)
    result = await node.run(
        {"from_agent": "planner", "task": "x", "peer_name": "hub"},
        _ctx(node_id="delegate-2"),
    )
    assert result.status == "paused"
    assert result.metadata["paused_reason"] == "awaiting_remote_delegation"
    assert result.metadata["mode"] == "guest_peer"
    assert result.metadata["peer_name"] == "hub"
    assert result.metadata["task_id"] == "remote-1"
    guest_peers.delegate.assert_called_once_with(
        "hub", "planner", [{"role": "user", "content": "x"}]
    )


async def test_cross_instance_no_guest_peers_configured_is_a_refusal_not_a_result() -> None:
    """Same distinction on the cross-instance path (#147)."""
    node = AgentDelegateRemoteNode()  # no guest_peers injected

    result = await node.run(
        {"from_agent": "planner", "task": "x", "peer_name": "peer-a"},
        _ctx(node_id="delegate-1"),
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error_code == DelegationNotConfiguredError.__name__


async def test_cross_instance_peer_rejected_returns_without_pausing() -> None:
    guest_peers = GuestPeerManager()  # "hub" never registered
    node = AgentDelegateRemoteNode(guest_peers=guest_peers)
    result = await node.run(
        {"from_agent": "planner", "task": "x", "peer_name": "hub"}, _ctx(node_id="delegate-2")
    )
    assert result.status == "completed"
    assert result.output.status == "rejected"
    assert result.output.error == "peer not found"


async def test_cross_instance_peer_delegation_failed_returns_without_pausing() -> None:
    guest_peers = GuestPeerManager()
    guest_peers.delegate = AsyncMock(  # type: ignore[method-assign]
        return_value=DelegationResult(
            task_id="", peer_name="hub", status="failed", error="connection refused"
        )
    )
    node = AgentDelegateRemoteNode(guest_peers=guest_peers)
    result = await node.run(
        {"from_agent": "planner", "task": "x", "peer_name": "hub"}, _ctx(node_id="delegate-2")
    )
    assert result.output.status == "failed"
    assert result.output.error == "connection refused"


async def test_cross_instance_resume_with_completed_result() -> None:
    guest_peers = GuestPeerManager()
    node = AgentDelegateRemoteNode(guest_peers=guest_peers)
    ctx = _ctx(node_id="delegate-2")
    ctx.metadata["hitl_answers"] = {
        "delegate-2": {"status": "completed", "task_id": "remote-1", "result": "ok"}
    }
    result = await node.run({"from_agent": "planner", "task": "x", "peer_name": "hub"}, ctx)
    assert result.output.status == "completed"
    assert result.output.task_id == "remote-1"
    assert result.output.result == "ok"


def test_via_registry_default_constructible() -> None:
    Node = get_node("agent.delegate_remote")
    instance = Node()
    assert isinstance(instance, AgentDelegateRemoteNode)
