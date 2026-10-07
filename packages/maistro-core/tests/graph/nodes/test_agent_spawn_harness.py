"""Tests for governed `agent.spawn_harness` execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.capabilities.approval_store import InMemoryApprovalStore, approval_request_digest
from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    binding_scope_policy,
    new_in_memory_effect_context,
)
from maistro.capabilities.invocation import Invocation, InvocationStatus, ReconciliationDisposition
from maistro.graph.harness import (
    HarnessAdapter,
    HarnessHandle,
    HarnessKind,
    HarnessRequest,
    HarnessResult,
)
from maistro.graph.nodes import NodeContext, get_node, list_kinds
from maistro.graph.nodes.agent_spawn_harness import AgentSpawnHarnessNode
from maistro.graph.nodes.base import replay_effect_key
from maistro.policy.types import Decision, PolicyVerdict


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


def _legacy_resolver(adapter: FakeHarnessAdapter) -> Any:
    """Resolve the same provider the node would, for the pre-#1319 dispatch."""

    from maistro.graph.nodes.agent_spawn_harness import _HarnessDispatchProvider

    async def resolve(_binding: Any) -> Any:
        return _HarnessDispatchProvider(name="claude_code", adapter=adapter)

    return resolve


def _legacy_executor(adapter: FakeHarnessAdapter) -> Any:
    """Dispatch through the adapter exactly as the node's executor does."""

    async def execute(provider: Any, request: Any) -> Any:
        payload = dict(request)
        handle = await provider.adapter.dispatch(
            HarnessRequest(
                harness_type=str(payload["harness_type"]),
                task=str(payload["task"]),
                context={},
                timeout_seconds=3600,
            )
        )
        return {"handle_id": handle.handle_id, "harness_type": handle.harness_type}

    return execute


async def _effects_with_binding(
    *,
    binding_id: str = "b1",
    workspace_id: str = "ws1",
    project_id: str = "p1",
    node_id: str = "h-node-1",
    provider_name: str = "claude_code",
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


def test_kind_registered() -> None:
    assert "agent.spawn_harness" in set(list_kinds())


def test_protocol_satisfied() -> None:
    adapter = FakeHarnessAdapter()
    assert isinstance(adapter, HarnessAdapter)


async def test_missing_binding_fails_closed_without_dispatch() -> None:
    adapter = FakeHarnessAdapter()
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
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
    effect_key = replay_effect_key(
        _ctx(),
        "agent.spawn_harness.dispatch",
        {
            "harness_type": "claude_code",
            "task": "implement feature Y",
            "context": {},
            "timeout_seconds": 3600,
        },
    )
    history = await effects.invocation_store.list_effect(
        run_id="r1",
        node_run_id="nr1",
        binding_id="b1",
        effect_key=effect_key,
        effect_scope=effect_key,
    )
    assert len(history) == 1
    invocation = history[0]
    assert invocation.status is InvocationStatus.COMPLETED
    assert invocation.run_id == "r1"
    assert invocation.effect_scope == effect_key
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

    first = await node.run(inputs, _ctx(node_run_id="nr1", attempt_id="a1"))
    second = await node.run(inputs, _ctx(node_run_id="nr2", attempt_id="a2"))

    assert first.status == second.status == "paused"
    assert first.metadata["invocation_id"] == second.metadata["invocation_id"]
    assert len(adapter.dispatched) == 1
    effect_key = replay_effect_key(
        _ctx(),
        "agent.spawn_harness.dispatch",
        {"harness_type": "claude_code", "task": "once", "context": {}, "timeout_seconds": 3600},
    )
    history = await effects.invocation_store.list_effect(
        run_id="r1",
        node_run_id="nr2",
        binding_id="b1",
        effect_key=effect_key,
        effect_scope=effect_key,
    )
    assert len(history) == 1
    assert history[0].attempt_id == "a1"
    assert history[0].node_run_id == "nr1"


async def test_a_dispatch_recorded_under_the_pre_1319_key_is_not_repeated() -> None:
    """An upgrade mid-flight must not dispatch the same harness task twice.

    #1319 changed this node's effect key from
    `agent.spawn_harness.dispatch:<harness type>` to one carrying the Run, the
    graph node and a request digest. A deployment that upgraded after the
    adapter dispatched but before the node persisted its pause would compute
    the new key, find nothing under it, and send the external harness a second
    task it is already working on (Codex, #1362).
    """

    adapter = FakeHarnessAdapter()
    effects = await _effects_with_binding()
    node = AgentSpawnHarnessNode(adapters={"claude_code": adapter}, effect_context=effects)
    inputs = {"harness_type": "claude_code", "task": "once", "binding_id": "b1"}
    binding = await effects.bindings.get("b1")
    assert binding is not None

    # The pre-upgrade dispatch: recorded under the old key, on this Run.
    # Its logical scope is the old key itself -- the pre-#1319 code bound
    # ``effect_scope`` to the effect key it dispatched under, which is what
    # makes the row readable Run-wide after the upgrade.
    legacy_key = "agent.spawn_harness.dispatch:claude_code"
    legacy = await effects.invocations.invoke(
        binding=binding,
        run_id="r1",
        node_run_id="nr-old",
        attempt_id="a-old",
        effect_key=legacy_key,
        effect_scope=legacy_key,
        request=dict(inputs),
        resolver=_legacy_resolver(adapter),
        executor=_legacy_executor(adapter),
    )
    assert len(adapter.dispatched) == 1

    # The post-upgrade visit computes the new key and finds nothing there.
    result = await node.run(inputs, _ctx(node_run_id="nr-new", attempt_id="a-new"))

    assert result.status == "paused"
    # No second task reached the harness, and the pause carries the handle the
    # harness actually issued rather than a newly minted one.
    assert len(adapter.dispatched) == 1
    assert result.metadata["invocation_id"] == legacy.invocation_id


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


# --- Dispatch-guard failures (#55): fail closed on corrupt provider results -


@dataclass
class _StubRecord:
    """Minimal invocation-shaped record a stubbed service can return."""

    result: object
    invocation_id: str = "stub-invocation"


class _ForeignProviderInvoker:
    """Cross the Invocation seam with a provider of the wrong concrete type."""

    async def invoke(self, *, executor: Any, request: Any, **_kwargs: Any) -> Any:
        await executor(object(), request)
        raise AssertionError("executor must have refused the foreign provider")


class _NonDictResultInvoker:
    """Complete an Invocation whose persisted result is not a dispatch dict."""

    async def invoke(self, **_kwargs: Any) -> Any:
        return _StubRecord(result="opaque provider blob")


def _effects_with_stub(
    effects: CapabilityEffectContext, stub_invocations: Any
) -> CapabilityEffectContext:
    return CapabilityEffectContext(
        bindings=effects.bindings,
        invocations=stub_invocations,
        invocation_store=effects.invocation_store,
        event_store=effects.event_store,
    )


async def test_foreign_provider_type_is_refused_before_dispatch() -> None:
    adapter = FakeHarnessAdapter()
    effects = await _effects_with_binding()
    node = AgentSpawnHarnessNode(
        adapters={"claude_code": adapter},
        effect_context=_effects_with_stub(effects, _ForeignProviderInvoker()),
    )
    result = await node.run(
        {"harness_type": "claude_code", "task": "do something", "binding_id": "b1"},
        _ctx(),
    )
    assert result.success is False
    assert result.error_code == "TypeError"
    assert "non-harness provider" in (result.error_message or "")
    assert adapter.dispatched == []


async def test_non_dict_invocation_result_is_refused() -> None:
    adapter = FakeHarnessAdapter()
    effects = await _effects_with_binding()
    node = AgentSpawnHarnessNode(
        adapters={"claude_code": adapter},
        effect_context=_effects_with_stub(effects, _NonDictResultInvoker()),
    )
    result = await node.run(
        {"harness_type": "claude_code", "task": "do something", "binding_id": "b1"},
        _ctx(),
    )
    assert result.success is False
    assert result.error_code == "RuntimeError"
    assert "did not persist a dispatch result" in (result.error_message or "")


class _EmptyHandleAdapter(FakeHarnessAdapter):
    """Provider bug: a dispatch handle without identity fields."""

    async def dispatch(self, request: HarnessRequest) -> HarnessHandle:
        await super().dispatch(request)
        return HarnessHandle(handle_id="", harness_type=request.harness_type)


async def test_provider_returning_an_invalid_handle_fails_the_node() -> None:
    adapter = _EmptyHandleAdapter()
    effects = await _effects_with_binding()
    node = AgentSpawnHarnessNode(
        adapters={"claude_code": adapter},
        effect_context=effects,
    )
    result = await node.run(
        {"harness_type": "claude_code", "task": "do something", "binding_id": "b1"},
        _ctx(),
    )
    assert result.success is False
    assert result.error_code == "RuntimeError"
    assert "invalid dispatch handle" in (result.error_message or "")
    assert len(adapter.dispatched) == 1


async def test_distinct_requests_do_not_replay_one_another() -> None:
    """Two different tasks are two effects, not a replay of one (#1362)."""
    adapter = FakeHarnessAdapter()
    effects = await _effects_with_binding()
    node = AgentSpawnHarnessNode(
        adapters={"claude_code": adapter},
        effect_context=effects,
    )

    first = await node.run(
        {"harness_type": "claude_code", "task": "task one", "binding_id": "b1"},
        _ctx(),
    )
    second = await node.run(
        {"harness_type": "claude_code", "task": "task two", "binding_id": "b1"},
        _ctx(attempt_id="a2"),
    )

    assert first.status == second.status == "paused"
    assert len(adapter.dispatched) == 2
    assert first.metadata["invocation_id"] != second.metadata["invocation_id"]


# #1192 residual: real governed observations, rather than answer-shaped success.
class _ObservedAdapter(FakeHarnessAdapter):
    def __init__(self, results: list[Any]) -> None:
        super().__init__()
        self.results = list(results)
        self.polled: list[HarnessHandle] = []

    async def poll(self, handle: HarnessHandle) -> HarnessResult | None:
        self.polled.append(handle)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _resume_ctx(result: Any, **overrides: Any) -> NodeContext:
    return _ctx(metadata={"resumed_pause": dict(result.metadata)}, **overrides)


_INPUT = {"harness_type": "claude_code", "task": "once", "binding_id": "b1"}


async def test_dispatch_checkpoints_zero_before_poll_and_arms_fixed_deadline() -> None:
    from datetime import timedelta

    adapter = _ObservedAdapter([None])
    effects = await _effects_with_binding()
    node = AgentSpawnHarnessNode(adapters={"claude_code": adapter}, effect_context=effects)
    first = await node.run(_INPUT, _ctx())
    assert first.status == "paused"
    assert first.resume_at is not None
    assert first.metadata["harness_wait_version"] == 1
    assert first.metadata["observation_index"] == 0
    invocation = await effects.invocation_store.get(first.metadata["dispatch_invocation_id"])
    assert invocation is not None and invocation.started_at is not None
    assert (
        first.metadata["deadline_at"]
        == (invocation.started_at + timedelta(seconds=3600)).isoformat()
    )
    assert adapter.polled == []


async def test_pending_observation_replay_advances_once_without_duplicate_read() -> None:
    adapter = _ObservedAdapter([None])
    effects = await _effects_with_binding()
    node = AgentSpawnHarnessNode(adapters={"claude_code": adapter}, effect_context=effects)
    first = await node.run(_INPUT, _ctx())
    second = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    replay = await node.run(_INPUT, _resume_ctx(first, node_run_id="nr-new", attempt_id="a3"))
    assert second.status == replay.status == "paused"
    assert second.metadata["observation_index"] == replay.metadata["observation_index"] == 1
    assert second.metadata["deadline_at"] == first.metadata["deadline_at"]
    assert len(adapter.dispatched) == len(adapter.polled) == 1


async def test_approval_shaped_answer_is_never_an_empty_completed_harness() -> None:
    node = AgentSpawnHarnessNode()
    result = await node.run(
        {"harness_type": "claude_code", "task": "x"},
        _ctx(metadata={"hitl_answers": {"h-node-1": {"approved": True}}}),
    )
    assert result.status == "failed"
    assert result.output is None


async def test_terminal_failed_poll_is_a_completed_observation_domain_failure() -> None:
    adapter = _ObservedAdapter(
        [HarnessResult(handle_id="fake-h1", success=False, output="partial", error="remote failed")]
    )
    effects = await _effects_with_binding()
    node = AgentSpawnHarnessNode(adapters={"claude_code": adapter}, effect_context=effects)
    first = await node.run(_INPUT, _ctx())
    terminal = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    assert terminal.status == "completed"
    assert terminal.success is True
    assert terminal.output.status == "failed"
    assert terminal.output.error == "remote failed"
    assert terminal.output.output == "partial"
    assert len(adapter.dispatched) == len(adapter.polled) == 1


async def test_deadline_is_local_failure_and_never_another_poll(monkeypatch: Any) -> None:
    from datetime import datetime

    from maistro.graph.nodes import agent_spawn_harness as module

    adapter = _ObservedAdapter([None])
    effects = await _effects_with_binding()
    node = AgentSpawnHarnessNode(adapters={"claude_code": adapter}, effect_context=effects)
    first = await node.run(_INPUT, _ctx())
    deadline = datetime.fromisoformat(first.metadata["deadline_at"])
    monkeypatch.setattr(module, "now_utc", lambda: deadline, raising=False)
    expired = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    assert expired.status == "failed"
    assert expired.error_code == "HarnessWaitTimedOut"
    assert expired.metadata["remote_outcome"] == "unknown"
    assert adapter.polled == []


async def _parked(results: list[Any]) -> tuple[Any, Any, Any, Any]:
    adapter = _ObservedAdapter(results)
    effects = await _effects_with_binding()
    node = AgentSpawnHarnessNode(adapters={"claude_code": adapter}, effect_context=effects)
    first = await node.run(_INPUT, _ctx())
    assert first.status == "paused"
    return adapter, effects, node, first


async def _poll_history(effects: Any, first: Any, ordinal: int = 0) -> list[Invocation]:
    return await effects.invocation_store.list_effect(
        run_id="r1",
        node_run_id=None,
        binding_id="b1",
        effect_key=f"agent.spawn_harness.poll:{first.metadata['dispatch_invocation_id']}:{ordinal}",
    )


async def _record_poll(
    effects: Any,
    first: Any,
    *,
    status: InvocationStatus,
    result: Any = None,
    request_changes: dict[str, Any] | None = None,
    finished_at: datetime | None = None,
) -> Invocation:
    original = await effects.invocation_store.get(first.metadata["dispatch_invocation_id"])
    assert original is not None
    request = {
        key: first.metadata[key]
        for key in (
            "dispatch_invocation_id",
            "binding_id",
            "provider_name",
            "handle_id",
            "harness_type",
            "observation_index",
        )
    }
    request["operation"] = "poll"
    request.update(request_changes or {})
    terminal = status in {
        InvocationStatus.COMPLETED,
        InvocationStatus.FAILED,
        InvocationStatus.UNKNOWN,
    }
    finished = finished_at or datetime.now(UTC)
    # Seed internally coherent canonical rows, including synthetic future
    # deadline boundaries. Individual corruption tests override finished_at.
    if finished_at is None and isinstance(result, dict):
        observed = result.get("observed_at")
        if isinstance(observed, str):
            try:
                parsed = datetime.fromisoformat(observed)
            except ValueError:
                pass
            else:
                if parsed.utcoffset() is not None:
                    finished = max(finished, parsed)
    invocation = Invocation(
        binding=original.binding,
        run_id="r1",
        node_run_id="nr-old",
        attempt_id="a-old",
        effect_key=f"agent.spawn_harness.poll:{original.invocation_id}:0",
        effect_scope=f"agent.spawn_harness.poll:{original.invocation_id}:0",
        request=request,
        status=status,
        result=result,
        started_at=original.started_at,
        finished_at=finished if terminal else None,
    )
    return await effects.invocation_store.create(invocation)


def _terminal_observation(observed_at: datetime, **result: Any) -> dict[str, Any]:
    return {
        "state": "terminal",
        "observed_at": observed_at.isoformat(),
        "result": {
            "handle_id": "fake-h1",
            "success": True,
            "output": "done",
            "error": None,
            "metadata": {},
            **result,
        },
    }


@pytest.mark.parametrize("timeout", [0, -1])
async def test_nonpositive_timeout_refuses_before_dispatch(timeout: int) -> None:
    adapter = _ObservedAdapter([])
    effects = await _effects_with_binding()
    node = AgentSpawnHarnessNode(adapters={"claude_code": adapter}, effect_context=effects)
    result = await node.run({**_INPUT, "timeout_seconds": timeout}, _ctx())
    assert result.status == "failed"
    assert adapter.dispatched == adapter.polled == []


async def test_completed_dispatch_without_checkpoint_replays_original_deadline(
    monkeypatch: Any,
) -> None:
    from maistro.graph.nodes import agent_spawn_harness as module

    adapter, _effects, node, first = await _parked([])
    deadline = datetime.fromisoformat(first.metadata["deadline_at"])
    monkeypatch.setattr(module, "now_utc", lambda: deadline + timedelta(days=1))
    replay = await node.run(_INPUT, _ctx(node_run_id="new", attempt_id="a2"))
    assert replay.status == "paused"
    assert replay.metadata["observation_index"] == 0
    assert replay.metadata["deadline_at"] == first.metadata["deadline_at"]
    assert replay.resume_at == deadline
    assert len(adapter.dispatched) == 1 and adapter.polled == []


@pytest.mark.parametrize(
    "status", [InvocationStatus.CREATED, InvocationStatus.RUNNING, InvocationStatus.UNKNOWN]
)
async def test_unresolved_observation_reparks_same_ordinal_without_physical_replay(
    status: InvocationStatus,
    monkeypatch: Any,
) -> None:
    from maistro.graph.nodes import agent_spawn_harness as module

    adapter, effects, node, first = await _parked([])
    recorded = await _record_poll(effects, first, status=status)
    result = await node.run(_INPUT, _resume_ctx(first, node_run_id="nr2", attempt_id="a2"))
    assert result.status == "paused" and result.metadata["observation_index"] == 0
    assert result.metadata["deadline_at"] == first.metadata["deadline_at"]
    assert adapter.polled == []
    assert (await effects.invocation_store.get(recorded.invocation_id)).status is status
    monkeypatch.setattr(
        module, "now_utc", lambda: datetime.fromisoformat(first.metadata["deadline_at"])
    )
    expired = await node.run(_INPUT, _resume_ctx(result, attempt_id="a3"))
    assert expired.error_code == "HarnessWaitTimedOut"
    assert (await effects.invocation_store.get(recorded.invocation_id)).status is status
    assert adapter.polled == []


async def test_provider_exception_is_unknown_and_does_not_advance_or_retry() -> None:
    adapter, effects, node, first = await _parked([RuntimeError("lost response")])
    uncertain = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    assert uncertain.status == "paused" and uncertain.metadata["observation_index"] == 0
    replay = await node.run(_INPUT, _resume_ctx(uncertain, node_run_id="nr2", attempt_id="a3"))
    assert replay.status == "paused" and replay.metadata["observation_index"] == 0
    history = await _poll_history(effects, first)
    assert len(history) == len(adapter.polled) == 1
    assert history[0].status is InvocationStatus.UNKNOWN
    assert "lost response" in history[0].error


async def test_external_cancellation_propagates_and_preserves_unknown_observation() -> None:
    adapter, effects, node, first = await _parked([asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    history = await _poll_history(effects, first)
    assert len(history) == len(adapter.polled) == 1
    assert history[0].status is InvocationStatus.UNKNOWN


@pytest.mark.parametrize("offset", [-1, 0, 1])
async def test_observation_deadline_boundary_is_based_on_recorded_time(
    offset: int,
    monkeypatch: Any,
) -> None:
    from maistro.graph.nodes import agent_spawn_harness as module

    adapter, effects, node, first = await _parked([])
    deadline = datetime.fromisoformat(first.metadata["deadline_at"])
    await _record_poll(
        effects,
        first,
        status=InvocationStatus.COMPLETED,
        result=_terminal_observation(deadline + timedelta(microseconds=offset)),
    )
    monkeypatch.setattr(module, "now_utc", lambda: deadline + timedelta(days=1))
    replay = await node.run(_INPUT, _resume_ctx(first, node_run_id="nr2", attempt_id="a2"))
    if offset < 0:
        assert replay.status == "completed" and replay.output.output == "done"
    else:
        assert replay.status == "failed" and replay.error_code == "HarnessWaitTimedOut"
    assert adapter.polled == []


@pytest.mark.parametrize(
    "changes",
    [
        {"observed_at": None},
        {"observed_at": "2026-01-01T00:00:00"},
        {"observed_at": "2000-01-01T00:00:00+00:00"},
        {"state": "complete"},
        {"result": {"handle_id": "fake-h1", "success": True}},
    ],
)
async def test_malformed_completed_observation_is_not_terminal_success(
    changes: dict[str, Any],
) -> None:
    adapter, effects, node, first = await _parked([])
    observation = {**_terminal_observation(datetime.now(UTC)), **changes}
    await _record_poll(effects, first, status=InvocationStatus.COMPLETED, result=observation)
    result = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    assert result.status == "failed" and result.output is None
    assert adapter.polled == []


@pytest.mark.parametrize(
    "result",
    [
        HarnessResult(handle_id="foreign", success=True, output="wrong"),
        HarnessResult(handle_id="fake-h1", success="yes", output="wrong"),
        HarnessResult(
            handle_id="fake-h1", success=True, output="wrong", metadata={"nan": float("nan")}
        ),
        {"handle_id": "fake-h1", "success": True},
    ],
)
async def test_invalid_provider_terminal_evidence_remains_unknown(result: Any) -> None:
    adapter, effects, node, first = await _parked([result])
    result = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    assert result.status == "paused" and result.metadata["observation_index"] == 0
    assert result.output is None
    history = await _poll_history(effects, first)
    assert len(history) == len(adapter.polled) == 1
    assert history[0].status is InvocationStatus.UNKNOWN


@pytest.mark.parametrize(
    "changes",
    [
        {"harness_wait_version": True},
        {"harness_wait_version": 2},
        {"observation_index": -1},
        {"observation_index": True},
        {"observation_index": "0"},
        {"handle_id": "foreign"},
        {"harness_type": "foreign"},
        {"provider_name": "other"},
        {"binding_id": "other"},
        {"dispatch_invocation_id": "absent"},
        {"deadline_at": "2999-01-01T00:00:00+00:00"},
    ],
)
async def test_tampered_continuation_refuses_without_poll(changes: dict[str, Any]) -> None:
    adapter, _effects, node, first = await _parked([])
    ctx = _resume_ctx(first, attempt_id="a2")
    ctx.metadata["resumed_pause"].update(changes)
    result = await node.run(_INPUT, ctx)
    assert result.status == "failed" and result.output is None
    assert adapter.polled == [] and len(adapter.dispatched) == 1


@pytest.mark.parametrize(
    "missing", ["harness_wait_version", "observation_index", "deadline_at", "provider_name"]
)
async def test_incomplete_continuation_does_not_restart_at_zero(missing: str) -> None:
    adapter, _effects, node, first = await _parked([])
    ctx = _resume_ctx(first, attempt_id="a2")
    del ctx.metadata["resumed_pause"][missing]
    result = await node.run(_INPUT, ctx)
    assert result.status == "failed"
    assert adapter.polled == [] and len(adapter.dispatched) == 1


async def test_completed_poll_with_mutated_request_refuses_before_output() -> None:
    adapter, effects, node, first = await _parked([])
    await _record_poll(
        effects,
        first,
        status=InvocationStatus.COMPLETED,
        result=_terminal_observation(datetime.now(UTC)),
        request_changes={"handle_id": "foreign"},
    )
    result = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    assert result.status == "failed" and result.output is None
    assert adapter.polled == []


@pytest.mark.parametrize("change", ["revoked", "provider"])
async def test_poll_revalidates_binding_and_never_substitutes_provider(change: str) -> None:
    adapter, effects, node, first = await _parked([])
    if change == "revoked":
        await effects.bindings.revoke("b1")
    else:
        changed = await _effects_with_binding(provider_name="other")
        node._effects = replace(effects, bindings=changed.bindings)
    result = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    assert result.status == "failed"
    assert adapter.polled == []
    assert await _poll_history(effects, first) == []


async def _approval_node(*, dispatch_approval: bool = False) -> tuple[Any, Any, Any, Any]:
    approvals = InMemoryApprovalStore()

    async def policy(_binding: Any, request: Any, context: Any) -> PolicyVerdict:
        needs_approval = dispatch_approval or request.get("operation") == "poll"
        decision = (
            Decision.REQUIRE_APPROVAL if needs_approval and not context.approved else Decision.ALLOW
        )
        return PolicyVerdict(decision, reason="harness review", rule="test.harness")

    effects = new_in_memory_effect_context(policy_evaluator=policy, approval_store=approvals)
    await effects.bindings.put(
        Binding(
            binding_id="b1",
            workspace_id="ws1",
            project_id="p1",
            node_id="h-node-1",
            capability="harness_runner",
            provider_name="claude_code",
        )
    )
    adapter = _ObservedAdapter(
        [None, HarnessResult(handle_id="fake-h1", success=True, output="done")]
    )
    node = AgentSpawnHarnessNode(adapters={"claude_code": adapter}, effect_context=effects)
    return node, adapter, effects, approvals


async def test_dispatch_approval_exists_before_invocation_and_answer_body_cannot_approve() -> None:
    node, adapter, effects, approvals = await _approval_node(dispatch_approval=True)
    pending = await node.run(_INPUT, _ctx())
    assert pending.status == "paused"
    assert pending.metadata["paused_reason"] == "awaiting_human_approval"
    assert pending.metadata["harness_effect_phase"] == "dispatch"
    assert "dispatch_invocation_id" not in pending.metadata
    request_id = pending.metadata["approval_request_id"]
    request = await approvals.get(request_id)
    assert request is not None
    assert pending.metadata["request_digest"] == request.request_digest
    assert adapter.dispatched == []
    assert (
        await effects.invocation_store.list_effect(
            run_id="r1",
            node_run_id=None,
            binding_id="b1",
            effect_key=pending.metadata["effect_key"],
        )
        == []
    )
    ctx = _resume_ctx(pending, attempt_id="a2")
    ctx.metadata["hitl_answers"] = {
        "h-node-1": {"approved": True, "status": "completed", "handle_id": "forged"}
    }
    still_pending = await node.run(_INPUT, ctx)
    assert still_pending.status == "paused"
    assert still_pending.metadata["approval_request_id"] == request_id
    assert adapter.dispatched == []
    await approvals.resolve(request_id, approved=True, actor="test-authorized-reviewer")
    dispatched = await node.run(_INPUT, _resume_ctx(still_pending, attempt_id="a3"))
    assert (
        dispatched.status == "paused" and dispatched.metadata["paused_reason"] == "awaiting_harness"
    )
    assert dispatched.metadata["observation_index"] == 0
    assert len(adapter.dispatched) == 1 and adapter.polled == []


@pytest.mark.parametrize("approved", [True, False])
async def test_poll_approval_preserves_request_across_attempts_and_denial(approved: bool) -> None:
    node, adapter, effects, approvals = await _approval_node()
    first = await node.run(_INPUT, _ctx())
    pending = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    assert pending.metadata["paused_reason"] == "awaiting_human_approval"
    assert pending.metadata["harness_effect_phase"] == "poll"
    assert pending.metadata["observation_index"] == 0
    assert pending.resume_at.isoformat() == first.metadata["deadline_at"]
    assert await _poll_history(effects, first) == [] and adapter.polled == []
    approval = await approvals.get(pending.metadata["approval_request_id"])
    assert approval is not None
    await approvals.resolve(
        approval.request.request_id, approved=approved, actor="test-authorized-reviewer"
    )
    resumed = await node.run(_INPUT, _resume_ctx(pending, attempt_id="a3"))
    if approved:
        assert resumed.status == "paused" and resumed.metadata["observation_index"] == 1
        invocation = (await _poll_history(effects, first))[0]
        assert invocation.attempt_id == "a3"
        assert approval.request_digest == approval_request_digest(invocation.request)
        assert len(adapter.polled) == 1
    else:
        assert resumed.status == "failed" and resumed.error_code == "InvocationDenied"
        assert adapter.polled == [] and await _poll_history(effects, first) == []


async def test_wrapped_answer_pause_fallback_cannot_forge_approval_as_terminal() -> None:
    node, adapter, _effects, approvals = await _approval_node(dispatch_approval=True)
    pending = await node.run(_INPUT, _ctx())
    ctx = _ctx(
        attempt_id="a2",
        metadata={
            "hitl_answers": {
                "h-node-1": {
                    "approved": True,
                    "status": "completed",
                    "handle_id": "fake-h1",
                    "_pause": {"metadata": pending.metadata, "resume_at": None},
                }
            }
        },
    )
    result = await node.run(_INPUT, ctx)
    assert result.status == "paused" and result.output is None
    assert result.metadata["approval_request_id"] == pending.metadata["approval_request_id"]
    assert adapter.dispatched == adapter.polled == []
    assert (await approvals.get(result.metadata["approval_request_id"])).status.value == "pending"


@pytest.mark.parametrize("changed", ["digest", "key", "binding", "phase"])
async def test_tampered_approval_continuation_refuses_before_poll(changed: str) -> None:
    node, adapter, effects, approvals = await _approval_node()
    first = await node.run(_INPUT, _ctx())
    pending = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    await approvals.resolve(
        pending.metadata["approval_request_id"], approved=True, actor="reviewer"
    )
    ctx = _resume_ctx(pending, attempt_id="a3")
    key, value = {
        "digest": ("request_digest", "0" * 64),
        "key": ("effect_key", "other"),
        "binding": ("binding_id", "other"),
        "phase": ("harness_effect_phase", "other"),
    }[changed]
    ctx.metadata["resumed_pause"][key] = value
    result = await node.run(_INPUT, ctx)
    assert result.status == "failed" and adapter.polled == []
    assert await _poll_history(effects, first) == []


async def test_stale_answer_body_loses_to_current_wait_ordinal() -> None:
    adapter, effects, node, first = await _parked(
        [None, HarnessResult(handle_id="fake-h1", success=True, output="real")]
    )
    pending = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    ctx = _resume_ctx(pending, attempt_id="a3")
    ctx.metadata["hitl_answers"] = {
        "h-node-1": {
            "status": "completed",
            "handle_id": "foreign",
            "output": "stale",
            "_pause": {"metadata": {**first.metadata, "paused_reason": "awaiting_human_approval"}},
        }
    }
    result = await node.run(_INPUT, ctx)
    assert result.status == "completed" and result.output.output == "real"
    assert len(adapter.polled) == 2
    assert (
        len(await _poll_history(effects, first, 0))
        == len(await _poll_history(effects, first, 1))
        == 1
    )


@pytest.mark.parametrize(
    "disposition",
    [
        ReconciliationDisposition.APPLIED,
        ReconciliationDisposition.NOT_APPLIED,
        ReconciliationDisposition.INDETERMINATE,
    ],
)
async def test_observation_reconciliation_keeps_the_same_logical_ordinal(disposition: Any) -> None:
    adapter, effects, node, first = await _parked(
        [HarnessResult(handle_id="fake-h1", success=True, output="retry")]
    )
    uncertain = await _record_poll(effects, first, status=InvocationStatus.UNKNOWN)
    await effects.invocations.reconcile(
        uncertain.invocation_id,
        disposition=disposition,
        source="test-provider",
        actor="test-operator",
        reason="verified provider evidence",
        evidence={"probe": "receipt"},
        workspace_id="ws1",
        project_id="p1",
        result=_terminal_observation(datetime.now(UTC), output="reconciled")
        if disposition is ReconciliationDisposition.APPLIED
        else None,
    )
    result = await node.run(_INPUT, _resume_ctx(first, node_run_id="nr2", attempt_id="a2"))
    history = await _poll_history(effects, first)
    if disposition is ReconciliationDisposition.APPLIED:
        assert result.output.output == "reconciled" and adapter.polled == [] and len(history) == 1
    elif disposition is ReconciliationDisposition.NOT_APPLIED:
        assert result.output.output == "retry" and len(adapter.polled) == 1 and len(history) == 2
        assert history[0].effect_key == history[1].effect_key
    else:
        assert result.status == "paused" and result.metadata["observation_index"] == 0
        assert adapter.polled == [] and len(history) == 1


async def test_ambiguous_legacy_dispatch_is_not_retried_under_new_key() -> None:
    adapter = _ObservedAdapter([])
    effects = await _effects_with_binding()
    binding = await effects.bindings.get("b1")

    async def uncertain_dispatch(_provider: Any, _request: Any) -> Any:
        raise RuntimeError("dispatch receipt lost")

    with pytest.raises(RuntimeError, match="receipt lost"):
        await effects.invocations.invoke(
            binding=binding,
            run_id="r1",
            node_run_id="nr-old",
            attempt_id="a-old",
            effect_key="agent.spawn_harness.dispatch:claude_code",
            request=dict(_INPUT),
            resolver=_legacy_resolver(adapter),
            executor=uncertain_dispatch,
            effect_scope="agent.spawn_harness.dispatch:claude_code",
        )
    node = AgentSpawnHarnessNode(adapters={"claude_code": adapter}, effect_context=effects)
    result = await node.run(_INPUT, _ctx())
    assert result.status == "failed" and result.error_code == "UnsafeEffectRetry"
    assert adapter.dispatched == adapter.polled == []


async def test_each_physical_poll_is_bounded_by_remaining_fixed_wait(monkeypatch: Any) -> None:
    from maistro.graph.nodes import agent_spawn_harness as module

    _adapter, effects, node, first = await _parked([None])
    deadline = datetime.fromisoformat(first.metadata["deadline_at"])
    before = datetime.now(UTC)
    original_timeout = asyncio.timeout
    limits: list[float] = []

    def bounded(delay: float) -> Any:
        limits.append(delay)
        return original_timeout(delay)

    monkeypatch.setattr(module.asyncio, "timeout", bounded)
    result = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    assert result.status == "paused" and result.metadata["observation_index"] == 1
    assert len(limits) == 1 and 0 < limits[0] <= (deadline - before).total_seconds()
    invocation = (await _poll_history(effects, first))[0]
    assert "timeout_seconds" not in invocation.request and "resume_at" not in invocation.request
    assert "attempt_id" not in invocation.request and "deadline_at" not in invocation.request


async def test_poll_timeout_preserves_unknown_instead_of_not_applied(monkeypatch: Any) -> None:
    from maistro.graph.nodes import agent_spawn_harness as module

    _adapter, effects, node, first = await _parked([])
    original_timeout = asyncio.timeout
    started = asyncio.Event()

    async def blocked(_handle: HarnessHandle) -> None:
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(_adapter, "poll", blocked)
    # Force cancellation on the first suspension, independent of machine speed.
    monkeypatch.setattr(module.asyncio, "timeout", lambda _remaining: original_timeout(0))
    result = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    assert started.is_set()
    assert result.status == "paused" and result.metadata["observation_index"] == 0
    history = await _poll_history(effects, first)
    assert len(history) == 1 and history[0].status is InvocationStatus.UNKNOWN
    assert history[0].reconciliation_history == ()


async def test_policy_elapsed_deadline_starts_no_physical_observation(monkeypatch: Any) -> None:
    from maistro.graph.nodes import agent_spawn_harness as module

    adapter, effects, node, first = await _parked([])
    current = datetime.now(UTC)
    deadline = datetime.fromisoformat(first.metadata["deadline_at"])

    async def policy(_binding: Any, _request: Any, _context: Any) -> PolicyVerdict:
        nonlocal current
        current = deadline
        return PolicyVerdict(Decision.ALLOW, reason="late allowed", rule="test")

    monkeypatch.setattr(module, "now_utc", lambda: current)
    node._effects = replace(effects, invocations=effects.invocations.with_policy_evaluator(policy))
    result = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    assert result.error_code == "HarnessWaitTimedOut"
    assert adapter.polled == []
    assert (await _poll_history(effects, first))[0].status is InvocationStatus.UNKNOWN


async def test_revocation_during_policy_evaluation_blocks_physical_poll() -> None:
    adapter, effects, node, first = await _parked([])

    async def policy(_binding: Any, _request: Any, _context: Any) -> PolicyVerdict:
        await effects.bindings.revoke("b1")
        return PolicyVerdict(Decision.ALLOW, reason="stale allowed", rule="test")

    node._effects = replace(effects, invocations=effects.invocations.with_policy_evaluator(policy))
    result = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    assert result.status == "failed" and result.error_code == "BindingNotFound"
    assert adapter.polled == [] and await _poll_history(effects, first) == []


async def test_current_policy_denial_wins_over_prior_durable_approval() -> None:
    node, adapter, effects, approvals = await _approval_node()
    first = await node.run(_INPUT, _ctx())
    pending = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    await approvals.resolve(
        pending.metadata["approval_request_id"], approved=True, actor="reviewer"
    )

    async def denied(_binding: Any, _request: Any, _context: Any) -> PolicyVerdict:
        return PolicyVerdict(Decision.DENY, reason="policy changed", rule="test")

    node._effects = replace(effects, invocations=effects.invocations.with_policy_evaluator(denied))
    result = await node.run(_INPUT, _resume_ctx(pending, attempt_id="a3"))
    assert result.error_code == "InvocationDenied" and result.output is None
    assert adapter.polled == [] and await _poll_history(effects, first) == []


async def test_dispatch_approval_cannot_be_used_for_changed_request() -> None:
    node, adapter, _effects, approvals = await _approval_node(dispatch_approval=True)
    pending = await node.run(_INPUT, _ctx())
    await approvals.resolve(
        pending.metadata["approval_request_id"], approved=True, actor="reviewer"
    )
    result = await node.run({**_INPUT, "task": "different"}, _resume_ctx(pending, attempt_id="a2"))
    assert result.status == "failed" and result.output is None
    assert adapter.dispatched == adapter.polled == []


@pytest.mark.parametrize(
    "evidence",
    [None, {"metadata": None}, {"metadata": {"paused_reason": "awaiting_human_approval"}}],
)
async def test_malformed_stamped_approval_fails_closed(evidence: Any) -> None:
    result = await AgentSpawnHarnessNode().run(
        {"harness_type": "claude_code", "task": "x"},
        _ctx(
            metadata={
                "hitl_answers": {
                    "h-node-1": {
                        "status": "completed",
                        "handle_id": "fake-h1",
                        "_pause": evidence,
                    }
                }
            }
        ),
    )
    assert result.status == "failed" and result.output is None


async def test_current_corrupt_pause_cannot_fall_back_to_terminal_answer() -> None:
    result = await AgentSpawnHarnessNode().run(
        {"harness_type": "claude_code", "task": "x"},
        _ctx(
            metadata={
                "resumed_pause": None,
                "hitl_answers": {
                    "h-node-1": {
                        "status": "completed",
                        "handle_id": "fake-h1",
                    }
                },
            }
        ),
    )
    assert result.status == "failed" and result.output is None


async def test_reconciled_applied_without_original_observation_time_refuses() -> None:
    adapter, effects, node, first = await _parked([])
    uncertain = await _record_poll(effects, first, status=InvocationStatus.UNKNOWN)
    observation = _terminal_observation(datetime.now(UTC))
    del observation["observed_at"]
    await effects.invocations.reconcile(
        uncertain.invocation_id,
        disposition=ReconciliationDisposition.APPLIED,
        source="provider",
        actor="operator",
        reason="remote work done, timing unavailable",
        evidence={"handle": "fake-h1"},
        result=observation,
        workspace_id="ws1",
        project_id="p1",
    )
    result = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    assert result.status == "failed" and result.output is None and adapter.polled == []
    assert (await _poll_history(effects, first))[0].status is InvocationStatus.COMPLETED


async def test_normal_observation_time_is_bounded_by_its_invocation() -> None:
    adapter, effects, node, first = await _parked(
        [HarnessResult(handle_id="fake-h1", success=True, output="done")]
    )
    result = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    assert result.status == "completed" and len(adapter.polled) == 1
    invocation = (await _poll_history(effects, first))[0]
    observed = datetime.fromisoformat(invocation.result["observed_at"])
    assert invocation.started_at <= observed <= invocation.finished_at


@pytest.mark.parametrize("reconciled", [False, True])
async def test_observation_after_canonical_completion_cannot_be_timely_evidence(
    reconciled: bool,
) -> None:
    adapter, effects, node, first = await _parked([])
    future = datetime.now(UTC) + timedelta(minutes=1)
    if reconciled:
        uncertain = await _record_poll(effects, first, status=InvocationStatus.UNKNOWN)
        await effects.invocations.reconcile(
            uncertain.invocation_id,
            disposition=ReconciliationDisposition.APPLIED,
            source="provider",
            actor="operator",
            reason="reported done",
            evidence={"receipt": "fake-h1"},
            result=_terminal_observation(future),
            workspace_id="ws1",
            project_id="p1",
        )
    else:
        await _record_poll(
            effects,
            first,
            status=InvocationStatus.COMPLETED,
            result=_terminal_observation(future),
            finished_at=datetime.now(UTC),
        )
    result = await node.run(_INPUT, _resume_ctx(first, attempt_id="a2"))
    assert result.status == "failed" and result.output is None
    assert "follows its canonical completion" in result.error_message
    assert adapter.polled == []


@pytest.mark.parametrize("same_node_run", [False, True])
async def test_legacy_wildcard_binding_requires_exact_node_run_provenance(
    same_node_run: bool,
) -> None:
    adapter = _ObservedAdapter([])
    effects = await _effects_with_binding(node_id="")
    binding = await effects.bindings.get("b1")
    legacy = await effects.invocations.invoke(
        binding=binding,
        run_id="r1",
        node_run_id="nr-original",
        attempt_id="a-original",
        effect_key="agent.spawn_harness.dispatch:claude_code",
        request=dict(_INPUT),
        resolver=_legacy_resolver(adapter),
        executor=_legacy_executor(adapter),
        effect_scope="agent.spawn_harness.dispatch:claude_code",
    )
    node = AgentSpawnHarnessNode(adapters={"claude_code": adapter}, effect_context=effects)
    ctx = _ctx(node_run_id="nr-original" if same_node_run else "nr-sibling", attempt_id="a2")
    result = await node.run(_INPUT, ctx)
    if same_node_run:
        assert result.status == "paused"
        assert result.metadata["dispatch_invocation_id"] == legacy.invocation_id
    else:
        assert result.status == "failed" and result.error_code == "UnsafeEffectRetry"
        assert result.output is None
    assert len(adapter.dispatched) == 1 and adapter.polled == []


async def test_present_empty_pause_cannot_fall_back_to_uncorrelated_legacy_answer() -> None:
    result = await AgentSpawnHarnessNode().run(
        {"harness_type": "claude_code", "task": "x"},
        _ctx(
            metadata={
                "resumed_pause": {},
                "hitl_answers": {
                    "h-node-1": {
                        "status": "completed",
                        "handle_id": "fake-h1",
                        "output": "untrusted fallback",
                    }
                },
            }
        ),
    )
    assert result.status == "failed" and result.output is None
    assert result.error_code == "ValueError"


# Compatibility is node-local re-entry; this does not claim old timeless
# WAITING records have acquired a production recovery/backfill mechanism.
def _legacy_pause(first: Any) -> dict[str, Any]:
    return {
        "paused_reason": "awaiting_harness",
        "handle_id": first.metadata["handle_id"],
        "harness_type": first.metadata["harness_type"],
        "binding_id": first.metadata["binding_id"],
        "invocation_id": first.metadata["dispatch_invocation_id"],
        "timeout_seconds": 3600,
    }


async def test_legacy_canonical_pause_reentry_checkpoints_zero_without_new_effect(
    monkeypatch: Any,
) -> None:
    from maistro.graph.nodes import agent_spawn_harness as module

    adapter, effects, node, first = await _parked([])
    deadline = datetime.fromisoformat(first.metadata["deadline_at"])
    monkeypatch.setattr(module, "now_utc", lambda: deadline - timedelta(seconds=3))
    upgraded = await node.run(
        _INPUT,
        _ctx(attempt_id="a2", metadata={"resumed_pause": _legacy_pause(first)}),
    )
    assert upgraded.status == "paused"
    assert upgraded.metadata["harness_wait_version"] == 1
    assert upgraded.metadata["observation_index"] == 0
    assert upgraded.metadata["dispatch_invocation_id"] == first.metadata["dispatch_invocation_id"]
    assert upgraded.metadata["deadline_at"] == first.metadata["deadline_at"]
    assert upgraded.resume_at == deadline
    assert len(adapter.dispatched) == 1 and adapter.polled == []
    assert await _poll_history(effects, first) == []


@pytest.mark.parametrize("status", ["completed", "failed", "timed_out"])
@pytest.mark.parametrize("transport", ["current_pause", "answered_wrapper"])
async def test_typed_legacy_answer_matches_its_canonical_dispatch_without_provider_read(
    status: str,
    transport: str,
) -> None:
    adapter, effects, node, first = await _parked([])
    answer = {
        "status": status,
        "handle_id": "fake-h1",
        "output": "legacy terminal evidence",
        "error": "remote failure" if status != "completed" else None,
        "metadata": {"receipt": "legacy"},
    }
    metadata: dict[str, Any] = {"hitl_answers": {"h-node-1": answer}}
    if transport == "current_pause":
        metadata["resumed_pause"] = _legacy_pause(first)
    else:
        answer["_pause"] = {"metadata": _legacy_pause(first), "resume_at": None}
    result = await node.run(_INPUT, _ctx(attempt_id="a2", metadata=metadata))
    assert result.status == "completed" and result.success is True
    assert result.output.status == status
    assert result.output.handle_id == "fake-h1"
    assert result.output.output == "legacy terminal evidence"
    assert result.output.error == answer["error"]
    assert result.output.metadata == {"receipt": "legacy"}
    assert len(adapter.dispatched) == 1 and adapter.polled == []
    assert await _poll_history(effects, first) == []


@pytest.mark.parametrize(
    "receipt",
    [
        "missing",
        "foreign_run",
        "foreign_node",
        "foreign_capability",
        "missing_started_at",
        "missing_request",
    ],
)
async def test_legacy_pause_refuses_missing_foreign_or_incomplete_canonical_receipt(
    receipt: str,
) -> None:
    adapter, effects, node, first = await _parked([])
    pause = _legacy_pause(first)
    pause["invocation_id"] = "other-receipt"
    if receipt != "missing":
        original = await effects.invocation_store.get(first.metadata["dispatch_invocation_id"])
        assert original is not None
        changes: dict[str, Any] = {
            "invocation_id": "other-receipt",
            "effect_key": "agent.spawn_harness.dispatch:claude_code",
        }
        if receipt == "foreign_run":
            changes["run_id"] = "other-run"
        elif receipt == "foreign_node":
            changes["binding"] = original.binding.model_copy(update={"node_id": "other-node"})
        elif receipt == "foreign_capability":
            changes["binding"] = original.binding.model_copy(
                update={"capability": "other-capability"}
            )
        elif receipt == "missing_started_at":
            changes["started_at"] = None
        else:
            changes["request"] = None
        await effects.invocation_store.create(original.model_copy(update=changes))
    result = await node.run(_INPUT, _ctx(attempt_id="a2", metadata={"resumed_pause": pause}))
    assert result.status == "failed" and result.output is None
    assert result.error_code == "ValueError"
    expected = {
        "missing": "no canonical dispatch receipt",
        "foreign_run": "belongs to another execution",
        "foreign_node": "belongs to another execution",
        "foreign_capability": "another capability",
        "missing_started_at": "missing original timing/request evidence",
        "missing_request": "missing original timing/request evidence",
    }
    assert expected[receipt] in result.error_message
    assert len(adapter.dispatched) == 1 and adapter.polled == []
    assert await _poll_history(effects, first) == []


@pytest.mark.parametrize("source", ["pause_handle", "pause_type", "answer_handle"])
async def test_legacy_pause_and_answer_must_match_the_canonical_handle(source: str) -> None:
    adapter, effects, node, first = await _parked([])
    pause = _legacy_pause(first)
    metadata: dict[str, Any] = {"resumed_pause": pause}
    if source == "pause_handle":
        pause["handle_id"] = "foreign-handle"
    elif source == "pause_type":
        pause["harness_type"] = "foreign-type"
    else:
        metadata["hitl_answers"] = {
            "h-node-1": {"status": "completed", "handle_id": "foreign-handle"}
        }
    result = await node.run(_INPUT, _ctx(attempt_id="a2", metadata=metadata))
    assert result.status == "failed" and result.output is None
    assert result.error_code == "ValueError"
    assert (
        "answer has a foreign handle"
        if source == "answer_handle"
        else "differs from canonical dispatch receipt"
    ) in result.error_message
    assert len(adapter.dispatched) == 1 and adapter.polled == []
    assert await _poll_history(effects, first) == []
