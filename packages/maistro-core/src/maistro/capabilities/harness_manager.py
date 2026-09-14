"""End-to-end driver for the ``harness_runner`` slot (SPEC-208).

``HarnessSessionManager`` is the glue between the capability slot, the safety
wrapper, and the sequence policy engine — the piece both the outbound graph node
and the inbound ``/v1/harness/sessions`` route build on:

- resolves the active ``harness_runner`` provider from the ``CapabilityRegistry``
  (respecting enable/health/fallback);
- wraps it in :class:`SafeHarnessRunner` — Warden scans every inbound message, and
  when a :class:`SequencePolicyEngine` is supplied a per-session
  :class:`PolicyActionGate` gates every outbound action (cumulative/sequence
  budgets across the whole session);
- when the slot is absent, disabled, or unhealthy it degrades to a typed
  ``Unavailable`` (SAFE_NOOP) — it never raises for a missing harness;
- canonical execution can route a session turn through
  ``Binding -> policy -> Invocation`` without bypassing the existing safety wrapper.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from maistro.agents.spec.agent_spec import AgentSpec
from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.governed_invocation import GovernedInvocationExecutionService
from maistro.capabilities.invocation import CapabilityUnavailable, EffectNotApplied
from maistro.capabilities.providers.harness_safety import (
    ActionGate,
    SafeHarnessRunner,
)
from maistro.capabilities.registry import CapabilityRegistry
from maistro.capabilities.slots.harness_runner import SLOT_NAME, HarnessInputBlocked, HarnessRunner
from maistro.capabilities.types import Unavailable
from maistro.policy.engine import SequencePolicyEngine
from maistro.policy.gate import PolicyActionGate
from maistro.security.warden.detector import Warden


@dataclass(frozen=True)
class _Session:
    """Durable session metadata; the provider is resolved for each operation."""

    provider_name: str


class HarnessSessionManager:
    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        warden: Warden,
        policy: SequencePolicyEngine | None = None,
        gate_factory: Callable[[str], ActionGate] | None = None,
        invocation_service: GovernedInvocationExecutionService | None = None,
        invocation_binding: Binding | None = None,
    ) -> None:
        self._registry = registry
        self._warden = warden
        self._policy = policy
        self._gate_factory = gate_factory
        self._invocation_service = invocation_service
        self._invocation_binding = invocation_binding
        self._sessions: dict[str, _Session] = {}

    def _gate(self, session_id: str) -> ActionGate | None:
        if self._gate_factory is not None:
            return self._gate_factory(session_id)
        if self._policy is not None:
            return PolicyActionGate(self._policy, key=session_id)
        # SafeHarnessRunner supplies a DenyAllGate for this degraded case.
        return None

    async def _safe_for_session(self, session_id: str) -> SafeHarnessRunner | Unavailable:
        session = self._sessions.get(session_id)
        if session is None:
            return Unavailable(slot=SLOT_NAME, reason=f"unknown harness session: {session_id}")
        provider = await self._registry.resolve(SLOT_NAME)
        if not isinstance(provider, HarnessRunner):
            return Unavailable(slot=SLOT_NAME, reason="harness_runner is unavailable")
        if provider.name != session.provider_name:
            return Unavailable(
                slot=SLOT_NAME,
                reason=(f"harness session provider {session.provider_name!r} is no longer active"),
            )
        return SafeHarnessRunner(provider, warden=self._warden, gate=self._gate(session_id))

    async def start(self, agent_spec: AgentSpec, *, workdir: str) -> str | Unavailable:
        """Resolve + start a safety-wrapped harness session, or ``Unavailable``."""
        if self._invocation_service is not None and self._invocation_binding is not None:
            return await self._start_invocation(agent_spec, workdir=workdir)
        provider = await self._registry.resolve(SLOT_NAME)
        if not isinstance(provider, HarnessRunner):
            return Unavailable(slot=SLOT_NAME, reason="no active harness_runner provider")
        session_id = await provider.start_session(agent_spec, workdir=workdir)
        self._sessions[session_id] = _Session(provider_name=provider.name)
        return session_id

    async def _start_invocation(self, agent_spec: AgentSpec, *, workdir: str) -> str | Unavailable:
        service = self._invocation_service
        binding = self._invocation_binding
        assert service is not None and binding is not None
        selected_name = ""

        async def resolver(_binding: Binding) -> HarnessRunner | Unavailable:
            nonlocal selected_name
            provider = await self._registry.resolve(SLOT_NAME)
            if not isinstance(provider, HarnessRunner):
                return Unavailable(slot=SLOT_NAME, reason="no active harness_runner provider")
            selected_name = provider.name
            return provider

        async def executor(provider: ResolvedCapabilityProvider, request: Any) -> str:
            if not isinstance(provider, HarnessRunner):
                raise TypeError("harness Invocation resolved a non-harness provider")
            payload = dict(request)
            return await provider.start_session(
                agent_spec,
                workdir=str(payload["workdir"]),
            )

        try:
            invocation = await service.invoke(
                binding=binding,
                run_id="harness-start",
                node_run_id="harness-start",
                attempt_id=uuid4().hex,
                effect_key=f"harness:start:{uuid4().hex}",
                request={"workdir": workdir},
                resolver=resolver,
                executor=executor,
            )
        except CapabilityUnavailable as exc:
            return Unavailable(slot=SLOT_NAME, reason=str(exc))
        if not isinstance(invocation.result, str) or not selected_name:
            return Unavailable(slot=SLOT_NAME, reason="harness Invocation returned no session")
        self._sessions[invocation.result] = _Session(provider_name=selected_name)
        return invocation.result

    async def send(
        self, session_id: str, messages: list[dict[str, Any]]
    ) -> dict[str, Any] | Unavailable:
        if self._invocation_service is not None and self._invocation_binding is not None:
            return await self.send_invocation(
                session_id,
                messages,
                binding=self._invocation_binding,
                run_id=f"harness:{session_id}",
                node_run_id=session_id,
                attempt_id=uuid4().hex,
                effect_key=f"harness:{session_id}:{uuid4().hex}",
                invocation_service=self._invocation_service,
            )
        safe = await self._safe_for_session(session_id)
        if isinstance(safe, Unavailable):
            return safe
        return await safe.send(session_id, messages)

    def _bound_session(
        self,
        session_id: str,
        binding: Binding,
    ) -> _Session | Unavailable:
        session = self._sessions.get(session_id)
        if session is None:
            return Unavailable(slot=SLOT_NAME, reason=f"unknown harness session: {session_id}")
        if binding.capability != SLOT_NAME:
            return Unavailable(
                slot=binding.capability,
                reason=f"Binding capability must be {SLOT_NAME!r} for a harness session",
            )
        if binding.config or binding.credential_refs:
            return Unavailable(
                slot=SLOT_NAME,
                reason=(
                    "cached harness session was not created with Binding config/credentials; "
                    "binding-scoped session creation is required"
                ),
            )
        return session

    async def send_invocation(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        binding: Binding,
        run_id: str,
        node_run_id: str,
        attempt_id: str,
        effect_key: str,
        invocation_service: GovernedInvocationExecutionService,
    ) -> dict[str, Any] | Unavailable:
        """Execute one harness turn through the canonical governed Invocation seam.

        The session stores only provider identity. The resolver rebuilds the
        safety wrapper at Invocation time, re-checking slot enablement, provider
        health, and Binding constraints before the foreign harness is called.
        """

        bound = self._bound_session(session_id, binding)
        if isinstance(bound, Unavailable):
            return bound

        async def resolver(candidate: Binding) -> SafeHarnessRunner | Unavailable:
            return await self._resolve_invocation_provider(session_id, candidate)

        async def executor(provider: ResolvedCapabilityProvider, request: Any) -> dict[str, Any]:
            return await self._execute_invocation_provider(session_id, provider, request)

        try:
            invocation = await invocation_service.invoke(
                binding=binding,
                run_id=run_id,
                node_run_id=node_run_id,
                attempt_id=attempt_id,
                effect_key=effect_key,
                request=messages,
                resolver=resolver,
                executor=executor,
            )
        except CapabilityUnavailable as exc:
            return Unavailable(slot=SLOT_NAME, reason=str(exc))
        executed = invocation.attempt_id == attempt_id
        result = invocation.result
        if not isinstance(result, dict):
            raise TypeError("harness Invocation result must be a response mapping")
        if not executed and result.get("actions"):
            # A completed Invocation can be reused for the same logical effect.
            # Its provider call and ActionGate already ran, so returning the
            # stored action list would make downstream consumers execute those
            # actions again without charging/rechecking the current gate.
            result = {**result, "actions": []}
        return result

    async def _resolve_invocation_provider(
        self, session_id: str, candidate: Binding
    ) -> SafeHarnessRunner | Unavailable:
        safe = await self._safe_for_session(session_id)
        if isinstance(safe, Unavailable):
            return safe
        if candidate.provider_name and candidate.provider_name != safe.name:
            return Unavailable(
                slot=SLOT_NAME,
                reason=(
                    f"Binding pins provider {candidate.provider_name!r}, "
                    f"but session uses {safe.name!r}"
                ),
            )
        health = await safe.healthcheck()
        if not health.healthy:
            return Unavailable(slot=SLOT_NAME, reason=health.detail or "provider unhealthy")
        return safe

    async def _execute_invocation_provider(
        self, session_id: str, provider: ResolvedCapabilityProvider, request: Any
    ) -> dict[str, Any]:
        if not isinstance(provider, SafeHarnessRunner):
            raise TypeError(
                "harness Invocation must execute through SafeHarnessRunner; "
                f"got {type(provider).__name__}"
            )
        if not isinstance(request, list):
            raise TypeError("harness Invocation request must be a message list")
        try:
            return await provider.send(session_id, request)
        except HarnessInputBlocked as exc:
            raise EffectNotApplied("Warden blocked harness input before dispatch") from exc

    async def stream(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        safe = await self._safe_for_session(session_id)
        if isinstance(safe, Unavailable):
            return
        async for event in safe.stream(session_id):
            yield event

    async def stop(self, session_id: str) -> None:
        safe = await self._safe_for_session(session_id)
        self._sessions.pop(session_id, None)
        if not isinstance(safe, Unavailable):
            await safe.stop(session_id)

    def active_sessions(self) -> list[str]:
        return list(self._sessions)
