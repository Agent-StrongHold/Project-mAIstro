"""Tests for governed `agent.spawn_harness` execution."""

from __future__ import annotations

from typing import Any

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    new_in_memory_effect_context,
)
from maistro.capabilities.invocation import InvocationStatus
from maistro.graph.harness import (
    HarnessAdapter,
    HarnessHandle,
    HarnessKind,
    HarnessRequest,
    HarnessResult,
)
from maistro.graph.nodes import NodeContext, get_node, list_kinds
from maistro.graph.nodes.agent_spawn_harness import AgentSpawnHarnessNode


def _ctx(**overrides: Any) -> NodeContext:
    base = {
        "run_id": "r1",
        "dag_id": "d1",
        "node_id": "h-node-1",
        "node_run_id": "nr1",
        "attempt_id": "a1",
        "user_id": "u1",
        "workspace_id": "ws1",
        "project_id": "p1",
    }
    base.update(overrides)
    return NodeContext(**base)


class FakeHarnessAdapter:
    """Minimal in-memory provider adapter."""

    def __init__(self, fail: bool = False) -> None:
        self._fail = fail
        self.dispatched: list[HarnessRequest] = []

    async def dispatch(self, request: HarnessRequest) -> HarnessHandle:
        self.dispatched.append(request)
        return HarnessHandle(handle_id="fake-h1", harness_type=request.harness_type)

    async def poll(self, handle: HarnessHandle) -> HarnessResult | None:
        return HarnessResult(
            handle_id=handle.handle_id,
            success=not self._fail,
            output="harness output" if not self._fail else "",
            error="harness failed" if self._fail else None,
        )

    async def cancel(self, handle: HarnessHandle) -> None:
        pass


async def _effects_with_binding(
    *,
    binding_id: str = "b1",
    workspace_id: str = "ws1",
    project_id: str = "p1",
    node_id: str = "h-node-1",
    provider_name: str = "claude_code",
) -> CapabilityEffectContext:
    effects = new_in_memory_effect_context()
    await effects.bindings.put(
        Binding(
            binding_id=binding_id,
            workspace_id=workspace_id,
            project_id=project_id,
            node_id=node_id,
            capability=AgentSpawnHarnessNode.capability,
            provider_name=provider_name,
        )
    )
    return effects


def test_kind_registered() -> None:
    assert "agent.spawn_harness" in set(list_kinds())


def test_protocol_satisfied() -> None:
    adapter = FakeHarnessAdapter()
    assert isinstance(adapter, HarnessAdapter)


async def test_missing_binding_fails_closed_without_dispatch() -> None:
    adapter = FakeHarnessAdapter()
    effects = new_in_memory_effect_context()
    node = AgentSpawnHarnessNode(
        adapters={"claude_code": adapter},
        effect_context=effects,
    )
    result = await node.run(
        {"harness_type": "claude_code", "task": "do something"},
        _ctx(),
    )
    assert result.success is False
    assert result.status == "failed"
    assert result.error_code == "BindingNotFound"
    assert adapter.dispatched == []


async def test_binding_scope_mismatch_fails_before_provider() -> None:
    adapter = FakeHarnessAdapter()
    effects = await _effects_with_binding(workspace_id="other-ws")
    node = AgentSpawnHarnessNode(
        adapters={"claude_code": adapter},
        effect_context=effects,
    )
    result = await node.run(
        {"harness_type": "claude_code", "task": "do something", "binding_id": "b1"},
        _ctx(),
    )
    assert result.success is False
    assert result.error_code == "BindingScopeDenied"
    assert adapter.dispatched == []


async def test_missing_provider_fails_closed_without_invocation_record() -> None:
    effects = await _effects_with_binding(provider_name="")
    node = AgentSpawnHarnessNode(effect_context=effects)
    result = await node.run(
        {"harness_type": "claude_code", "task": "do something", "binding_id": "b1"},
        _ctx(),
    )
    assert result.success is False
    assert result.error_code == "CapabilityUnavailable"
    history = await effects.invocation_store.list_effect(
        run_id="r1",
        node_run_id="nr1",
        binding_id="b1",
        effect_key="agent.spawn_harness.dispatch:claude_code",
    )
    assert history == []


async def test_dispatch_pauses_after_completed_correlated_invocation() -> None:
    adapter = FakeHarnessAdapter()
    effects = await _effects_with_binding()
    node = AgentSpawnHarnessNode(
        adapters={"claude_code": adapter},
        effect_context=effects,
    )
    result = await node.run(
        {
            "harness_type": "claude_code",
            "task": "implement feature Y",
            "binding_id": "b1",
        },
        _ctx(),
    )
    assert result.status == "paused"
    assert result.success is True
    assert result.metadata["paused_reason"] == "awaiting_harness"
    assert result.metadata["binding_id"] == "b1"
    assert result.metadata["handle_id"] == "fake-h1"
    assert len(adapter.dispatched) == 1

    history = await effects.invocation_store.list_effect(
        run_id="r1",
        node_run_id="nr1",
        binding_id="b1",
        effect_key="agent.spawn_harness.dispatch:claude_code",
    )
    assert len(history) == 1
    invocation = history[0]
    assert invocation.status is InvocationStatus.COMPLETED
    assert invocation.run_id == "r1"
    assert invocation.node_run_id == "nr1"
    assert invocation.attempt_id == "a1"
    assert invocation.binding.binding_id == "b1"
    assert invocation.binding.provider_name == "claude_code"
    assert result.metadata["invocation_id"] == invocation.invocation_id


async def test_completed_effect_replay_does_not_dispatch_twice() -> None:
    adapter = FakeHarnessAdapter()
    effects = await _effects_with_binding()
    node = AgentSpawnHarnessNode(
        adapters={"claude_code": adapter},
        effect_context=effects,
    )
    inputs = {"harness_type": "claude_code", "task": "once", "binding_id": "b1"}

    first = await node.run(inputs, _ctx(attempt_id="a1"))
    second = await node.run(inputs, _ctx(attempt_id="a2"))

    assert first.status == second.status == "paused"
    assert first.metadata["invocation_id"] == second.metadata["invocation_id"]
    assert len(adapter.dispatched) == 1
    history = await effects.invocation_store.list_effect(
        run_id="r1",
        node_run_id="nr1",
        binding_id="b1",
        effect_key="agent.spawn_harness.dispatch:claude_code",
    )
    assert len(history) == 1
    assert history[0].attempt_id == "a1"


async def test_dispatch_passes_domain_context_to_provider_adapter() -> None:
    adapter = FakeHarnessAdapter()
    effects = await _effects_with_binding(provider_name="conductor")
    node = AgentSpawnHarnessNode(
        adapters={"conductor": adapter},
        effect_context=effects,
    )
    await node.run(
        {
            "harness_type": "conductor",
            "task": "analyze repo",
            "context": {"repo": "maistro-engine", "branch": "main"},
            "binding_id": "b1",
        },
        _ctx(),
    )
    assert adapter.dispatched[0].context == {"repo": "maistro-engine", "branch": "main"}


async def test_pinned_binding_cannot_select_another_provider() -> None:
    cc = FakeHarnessAdapter()
    cond = FakeHarnessAdapter()
    effects = await _effects_with_binding(provider_name="claude_code")
    node = AgentSpawnHarnessNode(
        adapters={"claude_code": cc, "conductor": cond},
        effect_context=effects,
    )
    result = await node.run(
        {"harness_type": "conductor", "task": "plan sprint", "binding_id": "b1"},
        _ctx(),
    )
    assert result.success is False
    assert result.error_code == "CapabilityUnavailable"
    assert cc.dispatched == []
    assert cond.dispatched == []


async def test_resume_completed_needs_no_new_effect_authority() -> None:
    node = AgentSpawnHarnessNode()
    ctx = _ctx()
    ctx.metadata["hitl_answers"] = {
        "h-node-1": {
            "status": "completed",
            "handle_id": "fake-h1",
            "output": "analysis complete",
            "metadata": {"tokens": 512},
        }
    }
    result = await node.run({"harness_type": "claude_code", "task": "x"}, ctx)
    assert result.status == "completed"
    assert result.output.status == "completed"
    assert result.output.handle_id == "fake-h1"
    assert result.output.output == "analysis complete"
    assert result.output.metadata == {"tokens": 512}


async def test_resume_failed_and_timed_out_remain_domain_results() -> None:
    node = AgentSpawnHarnessNode()
    failed_ctx = _ctx()
    failed_ctx.metadata["hitl_answers"] = {
        "h-node-1": {"status": "failed", "handle_id": "fake-h1", "error": "timeout"}
    }
    failed = await node.run({"harness_type": "claude_code", "task": "x"}, failed_ctx)
    assert failed.output.status == "failed"
    assert failed.output.error == "timeout"

    timed_ctx = _ctx()
    timed_ctx.metadata["hitl_answers"] = {
        "h-node-1": {"status": "timed_out", "handle_id": "fake-h1", "output": ""}
    }
    timed = await node.run({"harness_type": "claude_code", "task": "x"}, timed_ctx)
    assert timed.output.status == "timed_out"


def test_via_registry_default_constructible_and_fail_closed() -> None:
    NodeCls = get_node("agent.spawn_harness")
    instance = NodeCls()
    assert isinstance(instance, AgentSpawnHarnessNode)


def test_harness_kind_enum_values() -> None:
    assert HarnessKind.CLAUDE_CODE == "claude_code"
    assert HarnessKind.CONDUCTOR == "conductor"
    assert HarnessKind.IN_PROCESS == "in_process"
