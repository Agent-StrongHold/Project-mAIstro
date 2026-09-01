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

from collections.abc import AsyncIterator
from typing import Any

from maistro.agents.spec.agent_spec import AgentSpec
from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.governed_invocation import GovernedInvocationExecutionService
from maistro.capabilities.invocation import CapabilityUnavailable, EffectNotApplied
from maistro.capabilities.providers.harness_safety import ActionGate, SafeHarnessRunner
from maistro.capabilities.registry import CapabilityRegistry
from maistro.capabilities.slots.harness_runner import SLOT_NAME, HarnessInputBlocked, HarnessRunner
from maistro.capabilities.types import Unavailable
from maistro.policy.engine import SequencePolicyEngine
from maistro.policy.gate import PolicyActionGate
from maistro.security.warden.detector import Warden


class HarnessSessionManager:
    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        warden: Warden,
        policy: SequencePolicyEngine | None = None,
    ) -> None:
        self._registry = registry
        self._warden = warden
        self._policy = policy
        self._sessions: dict[str, SafeHarnessRunner] = {}

    async def start(self, agent_spec: AgentSpec, *, workdir: str) -> str | Unavailable:
        """Resolve + start a safety-wrapped harness session, or ``Unavailable``."""
        provider = await self._registry.resolve(SLOT_NAME)
        if not isinstance(provider, HarnessRunner):
            return Unavailable(slot=SLOT_NAME, reason="no active harness_runner provider")
        session_id = await provider.start_session(agent_spec, workdir=workdir)
        gate: ActionGate | None = (
            PolicyActionGate(self._policy, key=session_id) if self._policy is not None else None
        )
        self._sessions[session_id] = SafeHarnessRunner(provider, warden=self._warden, gate=gate)
        return session_id

    async def send(
        self, session_id: str, messages: list[dict[str, Any]]
    ) -> dict[str, Any] | Unavailable:
        safe = self._sessions.get(session_id)
        if safe is None:
            return Unavailable(slot=SLOT_NAME, reason=f"unknown harness session: {session_id}")
        return await safe.send(session_id, messages)

    def _bound_session(
        self,
        session_id: str,
        binding: Binding,
    ) -> SafeHarnessRunner | Unavailable:
        safe = self._sessions.get(session_id)
        if safe is None:
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
        return safe

    async def _resolve_session_provider(
        self,
        safe: SafeHarnessRunner,
        binding: Binding,
    ) -> SafeHarnessRunner | Unavailable:
        if not self._registry.is_enabled(SLOT_NAME):
            return Unavailable(slot=SLOT_NAME, reason="harness_runner slot is disabled")
        if binding.provider_name and binding.provider_name != safe.name:
            return Unavailable(
                slot=SLOT_NAME,
                reason=(
                    f"Binding pins provider {binding.provider_name!r}, "
                    f"but session uses {safe.name!r}"
                ),
            )
        health = await safe.healthcheck()
        if not health.healthy:
            return Unavailable(slot=SLOT_NAME, reason=health.detail or "provider unhealthy")
        return safe

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

        The resolved provider is the already-created :class:`SafeHarnessRunner`
        for this session, so Warden and the per-session outbound ActionGate remain
        mandatory. The resolver re-checks slot enablement, provider health, and
        the Binding constraints that can be proven for an already-created session.

        Unreached: this is the one caller of the canonical Invocation seam and
        nothing calls it outside tests, so no harness turn in a running
        deployment crosses that seam. #55 is what will call it.
        """

        bound = self._bound_session(session_id, binding)
        if isinstance(bound, Unavailable):
            return bound
        safe = bound

        async def resolver(candidate: Binding) -> SafeHarnessRunner | Unavailable:
            return await self._resolve_session_provider(safe, candidate)

        executed = False

        async def executor(provider: ResolvedCapabilityProvider, request: Any) -> dict[str, Any]:
            nonlocal executed
            # Typed as ResolvedCapabilityProvider, not SafeHarnessRunner, because
            # that is what ProviderExecutor may pass: callable parameters are
            # contravariant, so narrowing the declaration here is unsound even
            # though `resolver` above only ever yields a SafeHarnessRunner. The
            # isinstance check turns that wiring assumption into a checked
            # invariant — if some future resolver returns a raw provider, this
            # raises instead of silently bypassing Warden and the ActionGate,
            # which is the whole point of routing harness turns through the safe
            # wrapper.
            if not isinstance(provider, SafeHarnessRunner):
                raise TypeError(
                    "harness Invocation must execute through SafeHarnessRunner; "
                    f"got {type(provider).__name__}"
                )
            if not isinstance(request, list):
                raise TypeError("harness Invocation request must be a message list")
            executed = True
            try:
                return await provider.send(session_id, request)
            except HarnessInputBlocked as exc:
                # Warden refuses before the foreign harness is called, so the
                # external effect is proven absent and a later retry is safe.
                raise EffectNotApplied("Warden blocked harness input before dispatch") from exc

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

    async def stream(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        safe = self._sessions.get(session_id)
        if safe is None:
            return
        async for event in safe.stream(session_id):
            yield event

    async def stop(self, session_id: str) -> None:
        safe = self._sessions.pop(session_id, None)
        if safe is not None:
            await safe.stop(session_id)

    def active_sessions(self) -> list[str]:
        return list(self._sessions)
