"""harness_runner slot (SPEC-208): safety wrapper + SAFE_NOOP resolution.

Orchestration code never talks to a raw ``HarnessRunner`` provider. It calls
``resolve_harness_runner(...)``, which either returns a ``GuardedHarnessRunner``
(the provider wrapped so every inbound message passes a Warden-style scanner
and every reported action passes a Sentinel-style policy check) or a typed
``Unavailable`` — never an exception. A provider cannot bypass the wrapper
because the wrapper is applied at resolution time, outside the provider.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from maistro.capabilities.protocols import HarnessRunner
from maistro.capabilities.types import ProviderHealth, Unavailable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from maistro.capabilities.registry import CapabilityRegistry
    from maistro.types.agent import AgentIdentity

logger = logging.getLogger("maistro.capabilities.slots.harness")

HARNESS_RUNNER_SLOT = "harness_runner"

# Callable shapes (documented; injected, so Warden/Sentinel stay decoupled):
#   scan_message: Warden-style inbound scan — message dict in, True if safe.
#   allow_action: Sentinel-style outbound policy — action dict in, True if allowed.


def _blocked_envelope(reason: str) -> dict[str, Any]:
    return {"content": "", "blocked": True, "reason": reason, "actions": []}


class GuardedHarnessRunner:
    """Wraps any HarnessRunner with mandatory inbound-scan + outbound-policy.

    - ``send()``: every message goes through ``scan_message`` before the
      provider sees it; a flagged message short-circuits (provider not called).
    - Response envelopes and stream events that carry actions/tool calls go
      through ``allow_action`` before being surfaced; disallowed actions are
      stripped and reported under ``blocked_actions`` / as ``action_blocked``
      events.
    - Provider crashes degrade to an error envelope — never an exception.
    """

    def __init__(
        self,
        provider: HarnessRunner,
        *,
        scan_message: Callable[[dict[str, Any]], bool],
        allow_action: Callable[[dict[str, Any]], bool],
    ) -> None:
        self._provider = provider
        self._scan_message = scan_message
        self._allow_action = allow_action

    # --- CapabilityProvider passthrough ---
    @property
    def name(self) -> str:
        return self._provider.name

    @property
    def slot(self) -> str:
        return self._provider.slot

    @property
    def trust_tier(self) -> str:
        return self._provider.trust_tier

    def requires(self) -> tuple[str, ...]:
        return self._provider.requires()

    async def healthcheck(self) -> ProviderHealth:
        return await self._provider.healthcheck()

    # --- HarnessRunner (guarded) ---
    async def start_session(self, agent_spec: AgentIdentity, *, workdir: str) -> str:
        return await self._provider.start_session(agent_spec, workdir=workdir)

    async def send(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        for message in messages:
            if not self._scan_message(message):
                logger.warning(
                    "harness_runner[%s]: inbound message flagged; not forwarded",
                    self._provider.name,
                )
                return _blocked_envelope("inbound_message_flagged")
        try:
            response = await self._provider.send(session_id, messages)
        except Exception as exc:
            logger.warning("harness_runner[%s]: send failed: %s", self._provider.name, exc)
            return _blocked_envelope(f"harness_error: {exc}")
        return self._filter_response(response)

    async def stream(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        try:
            async for event in self._provider.stream(session_id):
                yield self._filter_event(event)
        except Exception as exc:
            logger.warning("harness_runner[%s]: stream failed: %s", self._provider.name, exc)
            yield {"type": "error", "blocked": True, "reason": f"harness_error: {exc}"}

    async def stop(self, session_id: str) -> None:
        try:
            await self._provider.stop(session_id)
        except Exception as exc:
            logger.warning("harness_runner[%s]: stop failed: %s", self._provider.name, exc)

    # --- outbound policy ---
    def _filter_response(self, response: dict[str, Any]) -> dict[str, Any]:
        actions = response.get("actions")
        if not isinstance(actions, list):
            return response
        allowed: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for action in actions:
            if isinstance(action, dict) and self._allow_action(action):
                allowed.append(action)
            else:
                blocked.append(action if isinstance(action, dict) else {"raw": action})
        filtered = dict(response)
        filtered["actions"] = allowed
        if blocked:
            logger.warning(
                "harness_runner[%s]: %d action(s) blocked by policy",
                self._provider.name,
                len(blocked),
            )
            filtered["blocked_actions"] = blocked
        return filtered

    def _filter_event(self, event: dict[str, Any]) -> dict[str, Any]:
        action = event.get("action")
        is_action_event = event.get("type") in ("action", "tool_call") or isinstance(action, dict)
        if not is_action_event:
            return event
        payload = action if isinstance(action, dict) else event
        if self._allow_action(payload):
            return event
        logger.warning("harness_runner[%s]: stream action blocked by policy", self._provider.name)
        return {"type": "action_blocked", "reason": "policy_denied", "blocked": True}


async def resolve_harness_runner(
    registry: CapabilityRegistry,
    *,
    scan_message: Callable[[dict[str, Any]], bool],
    allow_action: Callable[[dict[str, Any]], bool],
) -> GuardedHarnessRunner | Unavailable:
    """Resolve the harness_runner slot, SAFE_NOOP semantics.

    Absent slot, no provider, disabled slot, or unhealthy provider -> typed
    ``Unavailable``. A resolved provider is always returned wrapped in
    ``GuardedHarnessRunner`` — callers cannot obtain an unguarded provider here.
    """
    try:
        provider = await registry.resolve(HARNESS_RUNNER_SLOT)
    except KeyError:
        return Unavailable(slot=HARNESS_RUNNER_SLOT, reason="slot not defined")
    except Exception as exc:
        return Unavailable(slot=HARNESS_RUNNER_SLOT, reason=f"resolution failed: {exc}")
    if provider is None:
        return Unavailable(slot=HARNESS_RUNNER_SLOT, reason="no enabled healthy provider")
    if not isinstance(provider, HarnessRunner):
        return Unavailable(
            slot=HARNESS_RUNNER_SLOT,
            reason=f"provider '{provider.name}' does not implement HarnessRunner",
        )
    return GuardedHarnessRunner(provider, scan_message=scan_message, allow_action=allow_action)
