"""Tests for HarnessSessionManager — the harness_runner glue layer (SPEC-208)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from maistro.agents.spec.agent_spec import AgentRole, AgentSpec
from maistro.capabilities.binding import Binding
from maistro.capabilities.bootstrap import default_capability_registry
from maistro.capabilities.governed_invocation import GovernedInvocationExecutionService
from maistro.capabilities.harness_manager import HarnessSessionManager
from maistro.capabilities.invocation import InMemoryInvocationStore, InvocationExecutionService
from maistro.capabilities.slots.harness_runner import SLOT_NAME, HarnessInputBlocked
from maistro.capabilities.types import Unavailable
from maistro.events.envelope import InMemoryEventStore
from maistro.policy import AfterCountRule, SequencePolicyEngine
from maistro.policy.types import Decision, PolicyVerdict
from maistro.security._types import WardenVerdict


def _spec() -> AgentSpec:
    return AgentSpec(role=AgentRole.CODER, task_id="t", subtask_id="s", description="d")


class _StubWarden:
    def __init__(self, block_on: str | None = None) -> None:
        self.block_on = block_on

    async def scan(self, content: str, boundary: str) -> WardenVerdict:
        if self.block_on is not None and self.block_on in content:
            return WardenVerdict(clean=False, blocked=True, flags=("injection",))
        return WardenVerdict(clean=True)


class _FakeHarness:
    """A minimal healthy HarnessRunner whose send() echoes canned actions."""

    def __init__(
        self, *, healthy: bool = True, actions: list[dict[str, Any]] | None = None
    ) -> None:
        self._healthy = healthy
        self._actions = actions or []
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.sent: list[list[dict[str, Any]]] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def slot(self) -> str:
        return SLOT_NAME

    @property
    def trust_tier(self) -> str:
        return "t2"

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self):
        from maistro.capabilities.types import ProviderHealth

        return ProviderHealth(healthy=self._healthy)

    async def start_session(self, agent_spec: AgentSpec, *, workdir: str) -> str:
        sid = f"sess-{len(self.started)}"
        self.started.append(workdir)
        return sid

    async def send(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        self.sent.append(messages)
        return {"role": "assistant", "content": "ok", "actions": list(self._actions)}

    async def stream(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "token", "text": "x"}

    async def stop(self, session_id: str) -> None:
        self.stopped.append(session_id)


def _registry_with(harness: _FakeHarness):
    reg = default_capability_registry(entry_points=[])
    reg.register(harness)
    reg.activate(SLOT_NAME, "fake")
    return reg


async def test_start_returns_unavailable_when_no_provider():
    reg = default_capability_registry(entry_points=[])
    mgr = HarnessSessionManager(reg, warden=_StubWarden())
    result = await mgr.start(_spec(), workdir="/w")
    assert isinstance(result, Unavailable) and result.slot == SLOT_NAME


async def test_start_returns_unavailable_when_unhealthy():
    reg = _registry_with(_FakeHarness(healthy=False))
    mgr = HarnessSessionManager(reg, warden=_StubWarden())
    assert isinstance(await mgr.start(_spec(), workdir="/w"), Unavailable)


async def test_full_session_lifecycle_with_safety():
    harness = _FakeHarness()
    mgr = HarnessSessionManager(_registry_with(harness), warden=_StubWarden(block_on="EVIL"))

    sid = await mgr.start(_spec(), workdir="/w")
    assert isinstance(sid, str)
    assert mgr.active_sessions() == [sid]
    assert harness.started == ["/w"]

    resp = await mgr.send(sid, [{"role": "user", "content": "hello"}])
    assert not isinstance(resp, Unavailable) and resp["content"] == "ok"

    with pytest.raises(HarnessInputBlocked):
        await mgr.send(sid, [{"role": "user", "content": "do EVIL"}])

    events = [e async for e in mgr.stream(sid)]
    assert events and events[0]["type"] == "token"

    await mgr.stop(sid)
    assert harness.stopped == [sid] and mgr.active_sessions() == []


async def test_send_and_stream_unknown_session():
    mgr = HarnessSessionManager(_registry_with(_FakeHarness()), warden=_StubWarden())
    assert isinstance(await mgr.send("nope", []), Unavailable)
    assert [e async for e in mgr.stream("nope")] == []


async def test_policy_engine_gates_actions_per_session():
    harness = _FakeHarness(actions=[{"tool": "rm"}, {"tool": "ls"}])
    policy = SequencePolicyEngine([AfterCountRule("rm", threshold=0)])
    mgr = HarnessSessionManager(_registry_with(harness), warden=_StubWarden(), policy=policy)

    sid = await mgr.start(_spec(), workdir="/w")
    assert isinstance(sid, str)
    resp = await mgr.send(sid, [{"role": "user", "content": "clean"}])
    assert not isinstance(resp, Unavailable)
    tools = [a["tool"] for a in resp["actions"]]
    assert tools == ["ls"]


async def test_send_invocation_preserves_safety_and_canonical_correlation():
    harness = _FakeHarness()
    mgr = HarnessSessionManager(_registry_with(harness), warden=_StubWarden(block_on="EVIL"))
    sid = await mgr.start(_spec(), workdir="/w")
    assert isinstance(sid, str)

    event_store = InMemoryEventStore()

    async def allow(_binding: Binding, _request: Any, _context: Any) -> PolicyVerdict:
        return PolicyVerdict(Decision.ALLOW, reason="within scope", rule="harness-turn")

    governed = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=event_store,
        policy_evaluator=allow,
    )
    binding = Binding(
        binding_id="binding-harness",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability=SLOT_NAME,
        provider_name="fake",
        policy_refs=("harness-turn",),
    )

    response = await mgr.send_invocation(
        sid,
        [{"role": "user", "content": "hello"}],
        binding=binding,
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        effect_key="harness:turn:1",
        invocation_service=governed,
    )

    assert not isinstance(response, Unavailable)
    assert response["content"] == "ok"
    assert harness.sent == [[{"role": "user", "content": "hello"}]]
    events = await event_store.list_stream("workspace:ws-1")
    assert [event.type for event in events] == [
        "capability.invocation.policy_decision",
        "capability.invocation.completed",
    ]
    assert events[1].run_id == "run-1"
    assert events[1].node_run_id == "node-run-1"
    assert events[1].attempt_id == "attempt-1"
    assert events[1].invocation_id


async def test_cached_invocation_does_not_reemit_previously_gated_actions():
    harness = _FakeHarness(actions=[{"tool": "write", "path": "result.txt"}])
    mgr = HarnessSessionManager(_registry_with(harness), warden=_StubWarden())
    sid = await mgr.start(_spec(), workdir="/w")
    assert isinstance(sid, str)

    async def allow(_binding: Binding, _request: Any, _context: Any) -> PolicyVerdict:
        return PolicyVerdict(Decision.ALLOW, reason="within scope", rule="harness-turn")

    governed = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=InMemoryEventStore(),
        policy_evaluator=allow,
    )
    binding = Binding(
        binding_id="binding-harness-replay",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability=SLOT_NAME,
        provider_name="fake",
        policy_refs=("harness-turn",),
    )
    messages = [{"role": "user", "content": "write the result"}]

    first = await mgr.send_invocation(
        sid,
        messages,
        binding=binding,
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        effect_key="harness:turn:replay",
        invocation_service=governed,
    )
    replay = await mgr.send_invocation(
        sid,
        messages,
        binding=binding,
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-2",
        effect_key="harness:turn:replay",
        invocation_service=governed,
    )

    assert not isinstance(first, Unavailable)
    assert not isinstance(replay, Unavailable)
    assert first["actions"] == [{"tool": "write", "path": "result.txt"}]
    assert replay["content"] == "ok"
    assert replay["actions"] == []
    assert harness.sent == [messages]
