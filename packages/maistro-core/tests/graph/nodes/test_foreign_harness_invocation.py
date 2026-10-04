"""Foreign harnesses as governed graph nodes (issue #1613, M1-D).

Proves the M1-D acceptance at the real seams:

- OpenClaw and Pi providers construct and dispatch *through the shipped
  Invocation path* — Binding -> GovernedInvocationExecutionService ->
  InvocationExecutionService -> provider — via the
  ``HarnessRunnerDispatchAdapter`` bridge and ``agent.spawn_harness``.
- The Invocation row records the harness id, the session/workspace hint
  (adapter dispatch detail), and the result payload.
- Failure inside the bounded turn terminalizes the node as a failure — no
  orphan harness session survives as canonical success.
- A Graph with one native node and one foreign-harness node executes under
  one parent Run (durable walk).
"""

from __future__ import annotations

import contextlib
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.capabilities import OpenClawHarnessRunner, PiHarnessRunner
from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    binding_scope_policy,
    new_in_memory_effect_context,
)
from maistro.capabilities.invocation import InvocationStatus
from maistro.graph.durable_runs import InMemoryDurableRunStore, RunStatus
from maistro.graph.harness import (
    HarnessAdapter,
    HarnessRequest,
    HarnessRunnerDispatchAdapter,
)
from maistro.graph.nodes import BaseNode, NodeContext, get_node, register_node
from maistro.graph.nodes.agent_spawn_harness import AgentSpawnHarnessNode

from .._canonical_helpers import run_legacy_dag_fixture as run_durable_dag

# --- shared fixtures ----------------------------------------------------------


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


class _FakeSandbox:
    def __init__(self, result: tuple[int, str]) -> None:
        self.result = result
        self.commands: list[str] = []

    async def exec(self, command: str, timeout: int = 60) -> tuple[int, str]:
        self.commands.append(command)
        return self.result


def _sandbox_factory(sandbox: _FakeSandbox):
    async def make(workdir: str) -> _FakeSandbox:
        return sandbox

    return make


class _ScriptedRunner:
    """Session-protocol double that fails mid-turn, on demand.

    Models the far side dying inside the bounded turn: the session started,
    the turn raises, and stop must still run (the no-orphan-session guarantee).
    """

    def __init__(self, *, fail_send: bool = False) -> None:
        self.name = "scripted"
        self.slot = "harness_runner"
        self.trust_tier = "t2"
        self.stopped: list[str] = []
        self.fail_send = fail_send

    def requires(self) -> tuple[str, ...]:
        return ("scripted",)

    async def healthcheck(self) -> None:
        return None

    async def start_session(self, spec: Any, *, workdir: str) -> str:
        return "scripted-session-1"

    async def send(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if self.fail_send:
            raise TimeoutError("harness turn exceeded its bound")
        return {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "task done"},
                    "finish_reason": "stop",
                }
            ],
            "exit_code": 0,
            "actions": [],
        }

    async def stop(self, session_id: str) -> None:
        self.stopped.append(session_id)

    async def stream(self, session_id: str):
        yield {"type": "status", "detail": "idle"}


async def _effects_with_binding(
    *,
    binding_id: str = "b1",
    workspace_id: str = "ws1",
    project_id: str = "p1",
    node_id: str = "h-node-1",
    provider_name: str,
) -> CapabilityEffectContext:
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
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


# --- the bridge itself ----------------------------------------------------------


class TestHarnessRunnerDispatchAdapter:
    async def test_one_bounded_turn_returns_handle_with_dispatch_provenance(self) -> None:
        runner = _ScriptedRunner()
        adapter = HarnessRunnerDispatchAdapter(runner)
        handle = await adapter.dispatch(
            HarnessRequest(
                harness_type="scripted",
                task="do the thing",
                metadata={"workdir": "/repos/proj"},
            )
        )
        assert handle.harness_type == "scripted"
        # the harness id and workspace hint ride the handle detail
        assert handle.detail["session_id"] == "scripted-session-1"
        assert handle.detail["workdir"] == "/repos/proj"
        assert handle.detail["provider"] == "scripted"
        # one bounded turn: the session is already stopped, no orphan process
        assert runner.stopped == ["scripted-session-1"]

    async def test_poll_replays_the_completed_turn_without_redispatch(self) -> None:
        adapter = HarnessRunnerDispatchAdapter(_ScriptedRunner())
        handle = await adapter.dispatch(
            HarnessRequest(harness_type="scripted", task="t", context={"k": "v"})
        )
        first = await adapter.poll(handle)
        second = await adapter.poll(handle)
        assert first is not None and second is not None
        assert first.success is True
        assert first.output == "task done"
        assert first.metadata["session_id"] == "scripted-session-1"
        assert first.metadata["workdir"]  # provider default workdir applied
        assert second == first

    async def test_failed_turn_still_stops_the_session_and_raises(self) -> None:
        runner = _ScriptedRunner(fail_send=True)
        adapter = HarnessRunnerDispatchAdapter(runner)
        try:
            await adapter.dispatch(HarnessRequest(harness_type="scripted", task="t"))
        except TimeoutError:
            pass
        else:
            raise AssertionError("dispatch must surface the harness failure")
        # the bounded-turn finally stopped the session — no orphan harness
        assert runner.stopped == ["scripted-session-1"]

    def test_satisfies_the_graph_adapter_protocol(self) -> None:
        adapter: HarnessAdapter = HarnessRunnerDispatchAdapter(_ScriptedRunner())
        assert isinstance(adapter, HarnessAdapter)


# --- both harnesses construct through the shipped Invocation path ---------------


class TestProvidersThroughInvocationPath:
    async def test_openclaw_and_pi_dispatch_through_governed_invocation(self) -> None:
        openclaw_sandbox = _FakeSandbox((0, "gateway task complete"))
        pi_sandbox = _FakeSandbox((0, "patched tests"))
        openclaw = OpenClawHarnessRunner(sandbox_factory=_sandbox_factory(openclaw_sandbox))
        pi = PiHarnessRunner(sandbox_factory=_sandbox_factory(pi_sandbox))

        effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
        for provider, binding_id in (("openclaw", "b-openclaw"), ("pi", "b-pi")):
            await effects.bindings.put(
                Binding(
                    binding_id=binding_id,
                    workspace_id="ws1",
                    project_id="p1",
                    node_id="h-node-1",
                    capability=AgentSpawnHarnessNode.capability,
                    provider_name=provider,
                )
            )
        node = AgentSpawnHarnessNode(
            adapters={
                "openclaw": HarnessRunnerDispatchAdapter(openclaw),
                "pi": HarnessRunnerDispatchAdapter(pi),
            },
            effect_context=effects,
        )

        first = await node.run(
            {
                "harness_type": "openclaw",
                "task": "one outbound gateway task",
                "workdir": "/repos/app",
                "binding_id": "b-openclaw",
            },
            _ctx(),
        )
        assert first.status == "paused"
        second = await node.run(
            {
                "harness_type": "pi",
                "task": "one print-mode coding turn",
                "workdir": "/repos/app",
                "binding_id": "b-pi",
            },
            _ctx(),
        )
        assert second.status == "paused"

        # each provider ran its real near-side turn inside its sandbox
        assert openclaw_sandbox.commands[0].startswith("openclaw agent --message")
        assert pi_sandbox.commands[0].startswith("pi -p")

        openclaw_history = await effects.invocation_store.list_effect(
            run_id="r1",
            node_run_id="nr1",
            binding_id="b-openclaw",
            effect_key=str(first.metadata["replay_effect_key"]),
        )
        pi_history = await effects.invocation_store.list_effect(
            run_id="r1",
            node_run_id="nr1",
            binding_id="b-pi",
            effect_key=str(second.metadata["replay_effect_key"]),
        )
        assert len(openclaw_history) == len(pi_history) == 1
        for invocation in (*openclaw_history, *pi_history):
            assert invocation.status is InvocationStatus.COMPLETED
            assert invocation.run_id == "r1"
            assert invocation.node_run_id == "nr1"
            assert invocation.attempt_id == "a1"
            assert invocation.binding.provider_name in {"openclaw", "pi"}

        # the Invocation rows record harness id, session/workspace hint, and
        # the turn's result payload — not an opaque handle
        oc_row = openclaw_history[0]
        assert oc_row.request["harness_type"] == "openclaw"
        assert oc_row.request["workdir"] == "/repos/app"
        assert oc_row.result["harness_type"] == "openclaw"
        assert oc_row.result["session_id"]
        assert oc_row.result["workdir"] == "/repos/app"
        assert oc_row.result["provider"] == "openclaw"
        pi_row = pi_history[0]
        assert pi_row.request["harness_type"] == "pi"
        assert pi_row.result["provider"] == "pi"
        assert pi_row.result["session_id"]

    async def test_failed_harness_turn_fails_the_node_without_success_record(self) -> None:
        runner = _ScriptedRunner(fail_send=True)
        effects = await _effects_with_binding(provider_name="scripted")
        node = AgentSpawnHarnessNode(
            adapters={"scripted": HarnessRunnerDispatchAdapter(runner)},
            effect_context=effects,
        )
        result = await node.run(
            {"harness_type": "scripted", "task": "will fail", "binding_id": "b1"},
            _ctx(),
        )
        # the Attempt terminalizes as a failure, not a degraded success
        assert result.success is False
        assert result.status == "failed"
        assert "TimeoutError" in (result.error_code or "")
        # and no orphan harness session outlives the attempt
        assert runner.stopped == ["scripted-session-1"]

    async def test_node_accepts_a_raw_session_provider_and_wraps_it(self) -> None:
        """Adding a harness is a Provider + Binding (#1613): the node wraps a
        HarnessRunner provider itself — no hand-rolled adapter required."""
        runner = _ScriptedRunner()
        effects = await _effects_with_binding(provider_name="scripted")
        node = AgentSpawnHarnessNode(
            adapters={"scripted": runner},  # type: ignore[dict-item]
            effect_context=effects,
        )
        result = await node.run(
            {"harness_type": "scripted", "task": "one bounded turn", "binding_id": "b1"},
            _ctx(),
        )
        assert result.status == "paused"
        assert runner.stopped == ["scripted-session-1"]
        history = await effects.invocation_store.list_effect(
            run_id="r1",
            node_run_id="nr1",
            binding_id="b1",
            effect_key=str(result.metadata["replay_effect_key"]),
        )
        assert len(history) == 1
        invocation = history[0]
        assert invocation.status is InvocationStatus.COMPLETED
        # the row records harness id, session/workspace hint, and result payload
        assert invocation.result["provider"] == "scripted"
        assert invocation.result["session_id"] == "scripted-session-1"
        assert invocation.result["workdir"]
        assert invocation.result["output"] == "task done"

    async def test_node_rejects_a_non_harness_provider_shape(self) -> None:
        with pytest.raises(TypeError, match="HarnessAdapter or a HarnessRunner"):
            AgentSpawnHarnessNode(adapters={"junk": object()})  # type: ignore[dict-item]

    async def test_resume_prefers_the_provider_poll_evidence(self) -> None:
        runner = _ScriptedRunner()
        effects = await _effects_with_binding(provider_name="scripted")
        node = AgentSpawnHarnessNode(
            adapters={"scripted": runner},
            effect_context=effects,
        )
        inputs = {"harness_type": "scripted", "task": "x", "binding_id": "b1"}
        dispatched = await node.run(inputs, _ctx())
        assert dispatched.status == "paused"
        handle_id = str(dispatched.metadata["handle_id"])

        ctx = _ctx()
        ctx.metadata["hitl_answers"] = {
            "h-node-1": {
                "status": "completed",
                "handle_id": handle_id,
                "output": "stale transported answer",
            }
        }
        result = await node.run(inputs, ctx)
        # the adapter's own poll evidence won over the transported answer
        assert result.output.output == "task done"
        assert result.output.metadata["session_id"] == "scripted-session-1"

    async def test_resume_falls_back_to_the_answer_without_an_adapter(self) -> None:
        node = AgentSpawnHarnessNode()
        ctx = _ctx()
        ctx.metadata["hitl_answers"] = {
            "h-node-1": {
                "status": "completed",
                "handle_id": "h1",
                "output": "recorded answer",
            }
        }
        result = await node.run({"harness_type": "claude_code", "task": "x"}, ctx)
        assert result.output.output == "recorded answer"


# --- one parent Run over one native node + one foreign-harness node -------------


class _NativeUpperIn(BaseModel):
    text: str


class _NativeUpperOut(BaseModel):
    text: str


class _NativeUppercaseNode(BaseNode):
    """A plain native transform node, the 'native' half of the mixed graph."""

    kind: ClassVar[str] = "test.m1d_native_upper"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _NativeUpperIn
    output_schema: ClassVar[type[BaseModel]] = _NativeUpperOut

    async def _execute(self, inputs: _NativeUpperIn, ctx: NodeContext) -> _NativeUpperOut:
        return _NativeUpperOut(text=inputs.text.upper())


with contextlib.suppress(ValueError):
    register_node(_NativeUppercaseNode)


def _mixed_graph() -> dict[str, Any]:
    return {
        "id": "mixed-run-graph",
        "name": "native + foreign harness",
        "nodes": [
            {"id": "native", "kind": "test.m1d_native_upper", "inputs": {"text": "ship"}},
            {
                "id": "foreign",
                "kind": "agent.spawn_harness",
                "inputs": {
                    "harness_type": "openclaw",
                    "task": "one gateway task",
                    "binding_id": "b1",
                },
            },
        ],
        "edges": [{"from_node": "native", "to_node": "foreign"}],
        "entry_node": "native",
    }


def _kind_of(dag: dict[str, Any], node_id: str) -> str:
    for node in dag["nodes"]:
        if node["id"] == node_id:
            return str(node["kind"])
    raise KeyError(node_id)


async def test_native_and_foreign_harness_nodes_share_one_parent_run() -> None:
    store = InMemoryDurableRunStore()
    sandbox = _FakeSandbox((0, "gateway task complete"))
    openclaw = OpenClawHarnessRunner(sandbox_factory=_sandbox_factory(sandbox))
    effects = await _effects_with_binding(
        workspace_id="test-workspace",
        project_id="test-project",
        node_id="foreign",
        provider_name="openclaw",
    )
    harness_node = AgentSpawnHarnessNode(
        adapters={"openclaw": HarnessRunnerDispatchAdapter(openclaw)},
        effect_context=effects,
    )

    def resolver(node_id: str, dag: dict[str, Any]):
        if node_id == "foreign":
            return harness_node
        return get_node(_kind_of(dag, node_id))()

    result = await run_durable_dag(
        _mixed_graph(),
        store=store,
        node_resolver=resolver,
        inputs={},
        user_id="alice",
    )

    # the walk parks at the harness node — a system-owned pause waits in
    # WAITING (the awaiting_harness waker is the #1192 gap) — but both node
    # runs exist under ONE canonical parent Run
    assert result.status == RunStatus.WAITING
    by_id = {nr.node_id: nr for nr in result.node_runs}
    assert set(by_id) == {"native", "foreign"}
    assert by_id["native"].status is RunStatus.COMPLETED
    assert by_id["native"].result == {"text": "SHIP"}
    assert by_id["foreign"].status is RunStatus.WAITING
    # one parent Run identity for the native and the foreign node alike
    assert by_id["native"].run_id == by_id["foreign"].run_id == result.run_id
    # the foreign node's Attempt is real Attempt machinery: the durable record
    # carries it, linked to the foreign NodeRun under that same parent Run
    foreign_attempts = [a for a in result.attempts if a.node_run_id == by_id["foreign"].node_run_id]
    assert foreign_attempts
    native_attempts = [a for a in result.attempts if a.node_run_id == by_id["native"].node_run_id]
    assert native_attempts

    # the pause record carries the dispatch provenance a harness waker (#1192)
    # needs: handle id and the governed Invocation id
    pause_meta = result.graph_state.metadata["pauses"]["foreign"]["metadata"]
    assert pause_meta["handle_id"]
    invocation = await effects.invocation_store.get(str(pause_meta["invocation_id"]))
    assert invocation is not None
    assert invocation.status is InvocationStatus.COMPLETED
    assert invocation.run_id == result.run_id
    assert invocation.node_run_id == by_id["foreign"].node_run_id
    assert invocation.attempt_id == foreign_attempts[0].attempt_id
    assert invocation.binding.provider_name == "openclaw"
    # the outbound task really went through the provider boundary
    assert sandbox.commands and sandbox.commands[0].startswith("openclaw agent --message")
