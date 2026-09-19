"""Safety wrapper for ``harness_runner`` providers (SPEC-208 §2).

``SafeHarnessRunner`` composes the existing trust-boundary primitives around any
inner :class:`~maistro.capabilities.slots.harness_runner.HarnessRunner` — no new
trust-boundary type is introduced:

- **Warden** scans every inbound ``messages`` payload *before* it reaches the
  foreign harness; a blocked payload raises ``HarnessInputBlocked``.
- An **ActionGate** (the Sentinel-shaped outbound seam) evaluates every action
  the harness reports — in both ``send()`` responses and ``stream()`` events —
  *before* maistro surfaces or acts on it; denied actions are dropped.

Process isolation (the sandbox) is the inner provider's responsibility; this
wrapper is the message/action envelope. A crashed inner provider still degrades
through the registry's ``SAFE_NOOP`` path — the wrapper adds policy, not a new
failure mode.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from maistro.agents.spec.agent_spec import AgentSpec
from maistro.capabilities.slots.harness_runner import HarnessInputBlocked, HarnessRunner
from maistro.capabilities.types import ProviderHealth
from maistro.security.warden.detector import Warden


@runtime_checkable
class ActionGate(Protocol):
    """Outbound policy seam — decides whether a harness-reported action may surface.

    A thin adapter over ``maistro.security.sentinel`` satisfies this; tests and
    homelab installs can supply a simpler gate. Kept structural so the capability
    layer does not hard-depend on the full Sentinel construction.
    """

    async def allow(self, action: dict[str, Any]) -> bool: ...


class DenyAllGate:
    """Fail-closed gate used when no outbound policy is available."""

    async def allow(self, action: dict[str, Any]) -> bool:
        return False


def _message_text(message: dict[str, Any]) -> str:
    """Serialize the WHOLE message for scanning, not just ``content``.

    An OpenAI-style message can carry prompt-injection text or executable
    arguments in ``tool_calls``, attachments, or any other structured field
    while ``content`` stays empty — scanning content alone handed the foreign
    harness the unscanned remainder (Codex, #262). JSON-serializing the full
    dict puts every string the harness will see in front of Warden.
    """
    import json

    content = message.get("content", "")
    content_text = content if isinstance(content, str) else str(content)
    extra_fields = {k: v for k, v in message.items() if k not in ("content", "role")}
    if not extra_fields:
        return content_text
    try:
        serialized = json.dumps(extra_fields, sort_keys=True, default=str)
    except (TypeError, ValueError):
        serialized = str(extra_fields)
    return f"{content_text}\n{serialized}" if content_text else serialized


class SafeHarnessRunner:
    """Wrap an inner ``HarnessRunner`` with Warden (inbound) + ActionGate (outbound)."""

    def __init__(
        self,
        inner: HarnessRunner,
        *,
        warden: Warden,
        gate: ActionGate | None = None,
    ) -> None:
        self._inner = inner
        self._warden = warden
        # A missing policy is a degraded, read-only harness, never an implicit
        # permission grant. Production composition should still supply a gate.
        self._gate: ActionGate = gate if gate is not None else DenyAllGate()

    # --- CapabilityProvider passthrough ---
    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def slot(self) -> str:
        return self._inner.slot

    @property
    def trust_tier(self) -> str:
        return self._inner.trust_tier

    def requires(self) -> tuple[str, ...]:
        return self._inner.requires()

    async def healthcheck(self) -> ProviderHealth:
        return await self._inner.healthcheck()

    # --- HarnessRunner ---
    async def start_session(self, agent_spec: AgentSpec, *, workdir: str) -> str:
        return await self._inner.start_session(agent_spec, workdir=workdir)

    async def send(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        await self._scan_inbound(messages)
        response = await self._inner.send(session_id, messages)
        return await self._filter_actions(response)

    async def stream(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        async for event in self._inner.stream(session_id):
            if (
                isinstance(event, dict)
                and event.get("type") in ("action", "tool_call")
                and not await self._allow_action(event)
            ):
                continue
            yield event

    async def stop(self, session_id: str) -> None:
        await self._inner.stop(session_id)

    # --- internals ---
    async def _scan_inbound(self, messages: list[dict[str, Any]]) -> None:
        for message in messages:
            verdict = await self._warden.scan(_message_text(message), "user_input")
            # Match the native agent path (agents/base.py): any UNCLEAN verdict is
            # refused, not just a hard `blocked` one — single-pattern injections
            # come back clean=False/blocked=False and must not reach the harness.
            if not verdict.clean:
                raise HarnessInputBlocked(verdict.flags)

    async def _allow_action(self, action: dict[str, Any]) -> bool:
        try:
            return await self._gate.allow(action)
        except Exception:
            # Policy dependencies are on the effect boundary. A broken policy
            # must remove authority rather than turn the wrapper into allow-all.
            import logging

            logging.getLogger("maistro.capabilities.harness").warning(
                "harness action policy failed; denying action", exc_info=True
            )
            return False

    async def _gate_list(self, items: list[Any]) -> list[Any]:
        allowed: list[Any] = []
        for item in items:
            if isinstance(item, dict) and await self._allow_action(item):
                allowed.append(item)
        return allowed

    async def _filter_actions(self, response: dict[str, Any]) -> dict[str, Any]:
        result = response
        # 1) A top-level `actions` list (maistro's native harness envelope).
        actions = result.get("actions")
        if isinstance(actions, list):
            result = {**result, "actions": await self._gate_list(actions)}
        # 2) OpenAI chat-completion tool calls under choices[].message.tool_calls
        #    (the shape Codex/Claude-style harnesses return) — these are
        #    executable and must be gated too (SPEC-208: gate every action).
        choices = result.get("choices")
        if isinstance(choices, list):
            new_choices: list[Any] = []
            for choice in choices:
                message = choice.get("message") if isinstance(choice, dict) else None
                if isinstance(message, dict) and isinstance(message.get("tool_calls"), list):
                    gated = await self._gate_list(message["tool_calls"])
                    choice = {**choice, "message": {**message, "tool_calls": gated}}
                new_choices.append(choice)
            result = {**result, "choices": new_choices}
        return result
