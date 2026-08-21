"""Tests for `agent.spawn_harness` node."""

from __future__ import annotations

from typing import Any

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
    base = {"run_id": "r1", "dag_id": "d1", "node_id": "n1", "user_id": "u1"}
    base.update(overrides)
    return NodeContext(**base)


class FakeHarnessAdapter:
    """Minimal in-memory adapter — dispatch succeeds, poll returns immediately."""

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


def test_kind_registered() -> None:
    assert "agent.spawn_harness" in set(list_kinds())


def test_protocol_satisfied() -> None:
    adapter = FakeHarnessAdapter()
    assert isinstance(adapter, HarnessAdapter)


async def test_no_adapter_returns_failed_without_pausing() -> None:
    node = AgentSpawnHarnessNode()  # no adapters wired
    result = await node.run({"harness_type": "claude_code", "task": "do something"}, _ctx())
    assert result.status == "completed"
    assert result.output.status == "failed"
    assert "claude_code" in (result.output.error or "")


async def test_dispatch_pauses_run() -> None:
    adapter = FakeHarnessAdapter()
    node = AgentSpawnHarnessNode(adapters={"claude_code": adapter})
    result = await node.run(
        {"harness_type": "claude_code", "task": "implement feature Y"}, _ctx(node_id="h-node-1")
    )
    assert result.status == "paused"
    assert result.success is True
    assert result.metadata["paused_reason"] == "awaiting_harness"
    assert result.metadata["harness_type"] == "claude_code"
    assert result.metadata["handle_id"] == "fake-h1"
    assert len(adapter.dispatched) == 1
    assert adapter.dispatched[0].task == "implement feature Y"


async def test_dispatch_passes_context_to_adapter() -> None:
    adapter = FakeHarnessAdapter()
    node = AgentSpawnHarnessNode(adapters={"conductor": adapter})
    await node.run(
        {
            "harness_type": "conductor",
            "task": "analyze repo",
            "context": {"repo": "maistro-engine", "branch": "main"},
        },
        _ctx(),
    )
    assert adapter.dispatched[0].context == {"repo": "maistro-engine", "branch": "main"}


async def test_resume_completed() -> None:
    node = AgentSpawnHarnessNode()
    ctx = _ctx(node_id="h-node-1")
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
    assert result.output.error is None


async def test_resume_failed() -> None:
    node = AgentSpawnHarnessNode()
    ctx = _ctx(node_id="h-node-1")
    ctx.metadata["hitl_answers"] = {
        "h-node-1": {"status": "failed", "handle_id": "fake-h1", "error": "timeout"}
    }
    result = await node.run({"harness_type": "claude_code", "task": "x"}, ctx)
    assert result.output.status == "failed"
    assert result.output.error == "timeout"


async def test_resume_timed_out() -> None:
    node = AgentSpawnHarnessNode()
    ctx = _ctx(node_id="h-node-1")
    ctx.metadata["hitl_answers"] = {
        "h-node-1": {"status": "timed_out", "handle_id": "fake-h1", "output": ""}
    }
    result = await node.run({"harness_type": "claude_code", "task": "x"}, ctx)
    assert result.output.status == "timed_out"


async def test_multiple_adapters_routes_by_type() -> None:
    cc = FakeHarnessAdapter()
    cond = FakeHarnessAdapter()
    node = AgentSpawnHarnessNode(adapters={"claude_code": cc, "conductor": cond})

    await node.run({"harness_type": "conductor", "task": "plan sprint"}, _ctx())
    assert len(cc.dispatched) == 0
    assert len(cond.dispatched) == 1


async def test_unknown_harness_type_lists_available() -> None:
    node = AgentSpawnHarnessNode(adapters={"claude_code": FakeHarnessAdapter()})
    result = await node.run({"harness_type": "langchain", "task": "x"}, _ctx())
    assert result.output.status == "failed"
    assert "langchain" in (result.output.error or "")
    assert "claude_code" in (result.output.error or "")


def test_via_registry_default_constructible() -> None:
    NodeCls = get_node("agent.spawn_harness")
    instance = NodeCls()
    assert isinstance(instance, AgentSpawnHarnessNode)


def test_harness_kind_enum_values() -> None:
    assert HarnessKind.CLAUDE_CODE == "claude_code"
    assert HarnessKind.CONDUCTOR == "conductor"
    assert HarnessKind.IN_PROCESS == "in_process"
