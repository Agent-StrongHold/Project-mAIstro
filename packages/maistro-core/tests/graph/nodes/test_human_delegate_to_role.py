"""Tests for the `human.delegate_to_role` node.

The role -> current-holder lookup happens at resume time via an injected
`RoleHolderResolver`, not at graph-build time, so role reassignments mid-run
are picked up correctly.
"""

from __future__ import annotations

from typing import Any

from maistro.graph.nodes import NodeContext, get_node, list_kinds
from maistro.graph.nodes.human_delegate_to_role import HumanDelegateToRoleNode


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


class _StubResolver:
    def __init__(self, holder: str | None) -> None:
        self.holder = holder
        self.calls: list[str] = []

    def resolve(self, role: str) -> str | None:
        self.calls.append(role)
        return self.holder


async def test_first_reach_pauses_with_role_payload() -> None:
    Node = get_node("human.delegate_to_role")
    payload = {"task": "Sign off on release"}
    result = await Node().run(
        {"role": "on_call_pm", "payload": payload, "title": "Release sign-off"},
        _ctx(node_id="delegate-1"),
    )
    assert result.success is True
    assert result.status == "paused"
    assert result.resume_at is not None
    assert result.metadata["paused_reason"] == "awaiting_role_delegate"
    assert result.metadata["role"] == "on_call_pm"
    assert result.metadata["payload"] == payload
    assert result.metadata["title"] == "Release sign-off"


async def test_first_reach_does_not_resolve_role_at_build_time() -> None:
    resolver = _StubResolver("alice")
    Node = HumanDelegateToRoleNode(role_resolver=resolver)
    result = await Node.run({"role": "on_call_pm"}, _ctx(node_id="delegate-1"))
    assert result.status == "paused"
    assert resolver.calls == []  # resolution deferred to resume time


async def test_resume_resolves_holder_via_injected_resolver() -> None:
    resolver = _StubResolver("alice")
    Node = HumanDelegateToRoleNode(role_resolver=resolver)
    ctx = _ctx(node_id="delegate-1")
    ctx.metadata["hitl_answers"] = {"delegate-1": {"verdict": "approved"}}
    result = await Node.run({"role": "on_call_pm"}, ctx)
    assert result.status == "completed"
    assert result.output.verdict == "approved"
    assert result.output.resolved_user_id == "alice"
    assert resolver.calls == ["on_call_pm"]


async def test_resume_with_modified_payload_and_note() -> None:
    resolver = _StubResolver("bob")
    Node = HumanDelegateToRoleNode(role_resolver=resolver)
    ctx = _ctx(node_id="delegate-1")
    ctx.metadata["hitl_answers"] = {
        "delegate-1": {
            "verdict": "modified",
            "modified_payload": {"task": "Sign off, scoped to EU region"},
            "reviewer_note": "Restricted scope",
        }
    }
    result = await Node.run({"role": "on_call_pm"}, ctx)
    assert result.output.verdict == "modified"
    assert result.output.resolved_user_id == "bob"
    assert result.output.modified_payload == {"task": "Sign off, scoped to EU region"}
    assert result.output.reviewer_note == "Restricted scope"


async def test_resume_with_no_resolver_configured_returns_no_holder() -> None:
    Node = HumanDelegateToRoleNode()  # no resolver injected
    ctx = _ctx(node_id="delegate-1")
    ctx.metadata["hitl_answers"] = {"delegate-1": {"verdict": "approved"}}
    result = await Node.run({"role": "on_call_pm"}, ctx)
    assert result.output.verdict == "no_holder"
    assert result.output.resolved_user_id is None


async def test_resume_with_resolver_returning_none_holder() -> None:
    resolver = _StubResolver(None)
    Node = HumanDelegateToRoleNode(role_resolver=resolver)
    ctx = _ctx(node_id="delegate-1")
    ctx.metadata["hitl_answers"] = {"delegate-1": {"verdict": "approved"}}
    result = await Node.run({"role": "missing_role"}, ctx)
    assert result.output.verdict == "no_holder"
    assert result.output.resolved_user_id is None
    assert resolver.calls == ["missing_role"]


async def test_resume_with_timed_out_flag() -> None:
    resolver = _StubResolver("alice")
    Node = HumanDelegateToRoleNode(role_resolver=resolver)
    ctx = _ctx(node_id="delegate-1")
    ctx.metadata["hitl_answers"] = {"delegate-1": {"verdict": "timed_out", "timed_out": True}}
    result = await Node.run({"role": "on_call_pm"}, ctx)
    assert result.output.verdict == "timed_out"
    assert result.output.timed_out is True


def test_kind_is_registered() -> None:
    assert "human.delegate_to_role" in set(list_kinds())
