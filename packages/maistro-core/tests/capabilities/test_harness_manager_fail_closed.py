"""Degraded-path admission for HarnessSessionManager (#846).

Every live harness effect must resolve authorization at Invocation time and
fail closed when a policy/security dependency is unavailable. These tests
construct the real manager and drive the shipped degraded branches: no
policy, revoked/mismatched Bindings, provider swaps and health loss after
start, and provider-contract violations. A provider call in any of these
tests would be an allow-all bypass.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from maistro.agents.spec.agent_spec import AgentRole, AgentSpec
from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import InMemoryBindingStore
from maistro.capabilities.bootstrap import default_capability_registry
from maistro.capabilities.effect_context import binding_scope_policy, new_effect_context
from maistro.capabilities.harness_manager import HarnessSessionManager
from maistro.capabilities.invocation import EffectNotApplied
from maistro.capabilities.slots.harness_runner import SLOT_NAME
from maistro.capabilities.types import ProviderHealth, Unavailable
from maistro.policy import SequencePolicyEngine
from maistro.policy.types import Decision, PolicyVerdict
from maistro.security._types import WardenVerdict


def _spec() -> AgentSpec:
    return AgentSpec(role=AgentRole.CODER, task_id="t", subtask_id="s", description="d")


class _StubWarden:
    async def scan(self, content: str, boundary: str) -> WardenVerdict:
        return WardenVerdict(clean=True)


class _FakeHarness:
    """Minimal healthy HarnessRunner; ``send`` echoes canned actions."""

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

    async def healthcheck(self) -> ProviderHealth:
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


_DEFAULT_POLICY = SequencePolicyEngine([])


def _registry_with(harness: _FakeHarness):
    reg = default_capability_registry(entry_points=[])
    reg.register(harness)
    reg.activate(SLOT_NAME, harness.name)
    return reg


class _RenamedHarness(_FakeHarness):
    """A second harness provider under a different name (for swap tests)."""

    @property
    def name(self) -> str:
        return "fake2"


def _wired_manager(
    harness: _FakeHarness,
    *,
    policy: SequencePolicyEngine | None = _DEFAULT_POLICY,
    gate_factory: Any = None,
    binding_store: InMemoryBindingStore | None = None,
    provider_pin: str = "fake",
    registry: Any = None,
) -> tuple[HarnessSessionManager, Any]:
    effects = new_effect_context(policy_evaluator=binding_scope_policy)
    binding = Binding(
        binding_id=f"binding-harness-fc-{id(harness)}",
        workspace_id="default",
        project_id="default",
        capability=SLOT_NAME,
        provider_name=provider_pin,
    )
    store = binding_store if binding_store is not None else effects.bindings
    store.register(binding)
    mgr = HarnessSessionManager(
        registry if registry is not None else _registry_with(harness),
        warden=_StubWarden(),
        policy=policy,
        gate_factory=gate_factory,
        invocation_service=effects.invocations,
        invocation_binding=binding,
        binding_store=store,
    )
    return mgr, effects


async def _allow(_binding: Binding, _request: Any, _context: Any) -> PolicyVerdict:
    return PolicyVerdict(Decision.ALLOW, reason="within scope", rule="test")


# --- gate selection -------------------------------------------------------


class _RecordingDenyGate:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def allow(self, action: dict[str, Any]) -> bool:
        self.seen.append(str(action))
        return False


async def test_gate_factory_is_used_for_admission_when_supplied() -> None:
    harness = _FakeHarness(actions=[{"tool": "write"}])
    gate = _RecordingDenyGate()
    mgr, _effects = _wired_manager(harness, policy=None, gate_factory=lambda sid: gate)

    sid = await mgr.start(_spec(), workdir="/w")
    assert isinstance(sid, str)
    response = await mgr.send(sid, [{"role": "user", "content": "hi"}])

    assert not isinstance(response, Unavailable)
    assert response["actions"] == []  # factory gate denied every action
    assert gate.seen  # the factory gate, not a default allow-all, decided
    assert harness.sent == [[{"role": "user", "content": "hi"}]]


def test_missing_policy_and_factory_degrades_to_none_gate_marker() -> None:
    harness = _FakeHarness()
    mgr, _effects = _wired_manager(harness, policy=None)
    # SafeHarnessRunner turns this None into a DenyAllGate; the manager itself
    # must not manufacture an allow-all default.
    assert mgr._gate("any-session") is None


async def test_safe_for_session_refuses_unknown_session() -> None:
    harness = _FakeHarness()
    mgr, _effects = _wired_manager(harness)
    result = await mgr._safe_for_session("no-such-session")
    assert isinstance(result, Unavailable)
    assert "unknown harness session" in result.reason


# --- read-only admission when policy is absent -----------------------------


async def test_send_without_policy_or_factory_is_read_only() -> None:
    harness = _FakeHarness()
    mgr, _effects = _wired_manager(harness, policy=None)

    result = await mgr.send("whatever", [{"role": "user", "content": "hi"}])

    assert isinstance(result, Unavailable)
    assert "read-only" in result.reason
    assert harness.sent == []


async def test_stream_without_policy_or_factory_is_unavailable() -> None:
    harness = _FakeHarness()
    mgr, _effects = _wired_manager(harness, policy=None)

    events = await mgr.stream_events("whatever")

    assert isinstance(events, Unavailable)
    assert "read-only" in events.reason


async def test_stop_without_policy_or_factory_is_unavailable() -> None:
    harness = _FakeHarness()
    mgr, _effects = _wired_manager(harness, policy=None)

    result = await mgr.stop("whatever")

    assert isinstance(result, Unavailable)
    assert "read-only" in result.reason
    assert harness.stopped == []


async def test_send_invocation_without_policy_is_read_only() -> None:
    harness = _FakeHarness()
    mgr, _effects = _wired_manager(harness, policy=None)

    result = await mgr.send_invocation(
        "whatever",
        [{"role": "user", "content": "hi"}],
        binding=mgr._invocation_binding,
        run_id="run",
        node_run_id="node",
        attempt_id="attempt",
        effect_key="effect",
        invocation_service=mgr._invocation_service,
    )

    assert isinstance(result, Unavailable)
    assert "read-only" in result.reason
    assert harness.sent == []


# --- live Binding / provider state re-checked at Invocation time -----------


async def test_start_with_revoked_binding_denies_inside_invocation() -> None:
    harness = _FakeHarness()
    bindings = InMemoryBindingStore()
    mgr, _effects = _wired_manager(harness, binding_store=bindings)
    await bindings.revoke(mgr._invocation_binding.binding_id)

    result = await mgr.start(_spec(), workdir="/w")

    assert isinstance(result, Unavailable)
    assert harness.started == []


async def test_provider_swap_mid_session_denies_without_provider_call() -> None:
    harness = _FakeHarness()
    registry = _registry_with(harness)
    effects = new_effect_context(policy_evaluator=binding_scope_policy)
    binding = Binding(
        binding_id="binding-harness-swap",
        workspace_id="default",
        project_id="default",
        capability=SLOT_NAME,
        provider_name="fake",
    )
    effects.bindings.register(binding)
    mgr = HarnessSessionManager(
        registry,
        warden=_StubWarden(),
        policy=SequencePolicyEngine([]),
        invocation_service=effects.invocations,
        invocation_binding=binding,
        binding_store=effects.bindings,
    )
    sid = await mgr.start(_spec(), workdir="/w")
    assert isinstance(sid, str)

    registry.register(_RenamedHarness())
    registry.activate(SLOT_NAME, "fake2")

    result = await mgr.send(sid, [{"role": "user", "content": "hi"}])

    assert isinstance(result, Unavailable)
    assert "no longer active" in result.reason
    assert harness.sent == []
    assert registry.provider(SLOT_NAME, "fake2").sent == []  # type: ignore[union-attr]


async def test_binding_provider_pin_mismatch_denies_at_invocation_time() -> None:
    """The manager re-checks a Binding's provider pin at its own admission seam."""

    harness = _FakeHarness()
    mgr, _effects = _wired_manager(harness)  # boot: pinned to the active provider
    sid = await mgr.start(_spec(), workdir="/w")
    assert isinstance(sid, str)

    repinned = mgr._invocation_binding.model_copy(update={"provider_name": "someone-else"})
    result = await mgr._resolve_invocation_provider(sid, repinned)

    assert isinstance(result, Unavailable)
    assert "pins provider" in result.reason
    assert harness.sent == []


async def test_start_with_pinned_unknown_provider_refuses_fail_closed() -> None:
    """A Binding pinning a provider that never matches refuses without effects."""

    harness = _FakeHarness()
    mgr, _effects = _wired_manager(harness, provider_pin="someone-else")

    with pytest.raises(ValueError):  # hard refusal — never a silent allow-all
        await mgr.start(_spec(), workdir="/w")
    assert harness.started == []


async def test_unhealthy_provider_denies_at_invocation_time() -> None:
    harness = _FakeHarness()
    mgr, _effects = _wired_manager(harness)
    sid = await mgr.start(_spec(), workdir="/w")
    assert isinstance(sid, str)
    harness._healthy = False

    result = await mgr.send(sid, [{"role": "user", "content": "hi"}])

    assert isinstance(result, Unavailable)
    assert harness.sent == []


async def test_stop_after_revocation_denies_without_provider_call() -> None:
    harness = _FakeHarness()
    bindings = InMemoryBindingStore()
    mgr, _effects = _wired_manager(harness, binding_store=bindings)
    sid = await mgr.start(_spec(), workdir="/w")
    assert isinstance(sid, str)
    await bindings.revoke(mgr._invocation_binding.binding_id)

    result = await mgr.stop(sid)

    assert isinstance(result, Unavailable)
    assert harness.stopped == []


async def test_stop_unknown_session_is_unavailable() -> None:
    harness = _FakeHarness()
    mgr, _effects = _wired_manager(harness)
    assert isinstance(await mgr.stop("missing"), Unavailable)
    assert harness.stopped == []


# --- Binding-constraint admission on the cached session --------------------


async def test_send_invocation_rejects_foreign_capability_binding() -> None:
    harness = _FakeHarness()
    mgr, _effects = _wired_manager(harness)
    sid = await mgr.start(_spec(), workdir="/w")
    assert isinstance(sid, str)

    foreign = Binding(
        binding_id="binding-foreign",
        workspace_id="default",
        project_id="default",
        capability="other_capability",
    )
    result = await mgr.send_invocation(
        sid,
        [{"role": "user", "content": "hi"}],
        binding=foreign,
        run_id="run",
        node_run_id="node",
        attempt_id="attempt",
        effect_key="effect",
        invocation_service=mgr._invocation_service,
    )

    assert isinstance(result, Unavailable)
    assert "must be 'harness_runner'" in result.reason
    assert harness.sent == []


async def test_send_invocation_rejects_binding_config_on_cached_session() -> None:
    harness = _FakeHarness()
    mgr, _effects = _wired_manager(harness)
    sid = await mgr.start(_spec(), workdir="/w")
    assert isinstance(sid, str)

    configured = Binding(
        binding_id="binding-configured",
        workspace_id="default",
        project_id="default",
        capability=SLOT_NAME,
        config={"scope": "escape"},
    )
    result = await mgr.send_invocation(
        sid,
        [{"role": "user", "content": "hi"}],
        binding=configured,
        run_id="run",
        node_run_id="node",
        attempt_id="attempt",
        effect_key="effect",
        invocation_service=mgr._invocation_service,
    )

    assert isinstance(result, Unavailable)
    assert "binding-scoped session creation is required" in result.reason
    assert harness.sent == []


# --- provider-contract violations degrade safely ----------------------------


class _NoneSessionHarness(_FakeHarness):
    async def start_session(self, agent_spec: AgentSpec, *, workdir: str) -> str:
        self.started.append(workdir)
        return None  # type: ignore[return-value] — contract violation on purpose


async def test_start_session_contract_violation_degrades_to_unavailable() -> None:
    harness = _NoneSessionHarness()
    mgr, _effects = _wired_manager(harness)

    result = await mgr.start(_spec(), workdir="/w")

    assert isinstance(result, Unavailable)
    assert "returned no session" in result.reason
    assert mgr._sessions == {}


class _EffectLossHarness(_FakeHarness):
    async def send(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        raise EffectNotApplied("provider lost the effect") from RuntimeError("transport")


async def test_non_warden_effect_failure_propagates_to_caller() -> None:
    harness = _EffectLossHarness()
    mgr, _effects = _wired_manager(harness)
    sid = await mgr.start(_spec(), workdir="/w")
    assert isinstance(sid, str)

    with pytest.raises(EffectNotApplied):
        await mgr.send(sid, [{"role": "user", "content": "hi"}])
    # The loss surfaced as an error, never as a silently "successful" turn.
    assert harness.sent == []


class _BadShapeHarness(_FakeHarness):
    async def send(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        return "not-a-mapping"  # type: ignore[return-value] — contract violation


async def test_non_mapping_provider_response_is_refused_before_caller() -> None:
    """A shape-violating provider response never reaches the caller as success."""

    harness = _BadShapeHarness()
    mgr, _effects = _wired_manager(harness)
    sid = await mgr.start(_spec(), workdir="/w")
    assert isinstance(sid, str)

    with pytest.raises(AttributeError):  # SafeHarnessRunner refuses the malformed envelope
        await mgr.send(sid, [{"role": "user", "content": "hi"}])
