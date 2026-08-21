"""harness_runner slot: SlotSpec, protocol conformance, SAFE_NOOP resolution (SPEC-208)."""

from __future__ import annotations

from typing import Any

from maistro.capabilities.bootstrap import default_capability_registry
from maistro.capabilities.protocols import HarnessRunner
from maistro.capabilities.providers.harness_stub import StubHarnessRunner
from maistro.capabilities.registry import CapabilityRegistry
from maistro.capabilities.slots.harness import (
    HARNESS_RUNNER_SLOT,
    GuardedHarnessRunner,
    resolve_harness_runner,
)
from maistro.capabilities.types import FallbackPolicy, SlotSpec, Unavailable
from maistro.types.agent import AgentIdentity


def _allow_all(payload: dict[str, Any]) -> bool:
    return True


def _registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.define(SlotSpec(name=HARNESS_RUNNER_SLOT, fallback_policy=FallbackPolicy.SAFE_NOOP))
    return reg


async def _resolve(reg: CapabilityRegistry) -> GuardedHarnessRunner | Unavailable:
    return await resolve_harness_runner(reg, scan_message=_allow_all, allow_action=_allow_all)


def test_slot_defined_in_default_registry_with_safe_noop() -> None:
    reg = default_capability_registry(entry_points=())
    assert HARNESS_RUNNER_SLOT in reg.slots()


def test_stub_provider_conforms_to_harness_runner_protocol() -> None:
    assert isinstance(StubHarnessRunner(), HarnessRunner)


async def test_absent_provider_degrades_to_unavailable() -> None:
    result = await _resolve(_registry())
    assert isinstance(result, Unavailable)
    assert result.slot == HARNESS_RUNNER_SLOT


async def test_undefined_slot_degrades_to_unavailable_not_keyerror() -> None:
    result = await _resolve(CapabilityRegistry())
    assert isinstance(result, Unavailable)


async def test_disabled_slot_degrades_to_unavailable() -> None:
    reg = _registry()
    reg.register(StubHarnessRunner())
    reg.activate(HARNESS_RUNNER_SLOT, "stub")
    reg.set_enabled(HARNESS_RUNNER_SLOT, False)
    assert isinstance(await _resolve(reg), Unavailable)


async def test_unhealthy_provider_degrades_to_unavailable() -> None:
    reg = _registry()
    reg.register(StubHarnessRunner(healthy=False))
    reg.activate(HARNESS_RUNNER_SLOT, "stub")
    assert isinstance(await _resolve(reg), Unavailable)


async def test_healthy_provider_resolves_wrapped() -> None:
    reg = _registry()
    reg.register(StubHarnessRunner())
    reg.activate(HARNESS_RUNNER_SLOT, "stub")
    runner = await _resolve(reg)
    assert isinstance(runner, GuardedHarnessRunner)
    assert runner.name == "stub"
    assert runner.slot == HARNESS_RUNNER_SLOT


async def test_session_lifecycle_and_send_roundtrip() -> None:
    reg = _registry()
    stub = StubHarnessRunner()
    reg.register(stub)
    reg.activate(HARNESS_RUNNER_SLOT, "stub")
    runner = await _resolve(reg)
    assert isinstance(runner, GuardedHarnessRunner)

    agent = AgentIdentity(name="tester")
    session_id = await runner.start_session(agent, workdir="/tmp/w")
    response = await runner.send(session_id, [{"role": "user", "content": "hi"}])
    assert response["content"] == "stub:hi"

    events = [e async for e in runner.stream(session_id)]
    assert events[-1]["type"] == "done"

    await runner.stop(session_id)
    assert session_id not in stub.sessions


async def test_crashing_provider_send_returns_envelope_not_exception() -> None:
    reg = _registry()
    reg.register(StubHarnessRunner(crash_on_send=True))
    reg.activate(HARNESS_RUNNER_SLOT, "stub")
    runner = await _resolve(reg)
    assert isinstance(runner, GuardedHarnessRunner)
    session_id = await runner.start_session(AgentIdentity(name="tester"), workdir="/tmp/w")
    response = await runner.send(session_id, [{"role": "user", "content": "hi"}])
    assert response["blocked"] is True
    assert "harness_error" in response["reason"]
