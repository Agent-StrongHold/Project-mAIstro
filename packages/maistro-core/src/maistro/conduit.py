"""Conduit — the request pipeline through which all requests flow.

Every request enters through the Conduit. It orchestrates:
1. Intent classification (what does the user want?)
2. Agent dispatch (route to the right specialist)
3. Response formatting (OpenAI-compatible output)

The Conduit never executes tasks directly — it decides and delegates.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from maistro.types.intent import Intent

if TYPE_CHECKING:
    from maistro.container import Container

logger = logging.getLogger("maistro.conduit")


async def determine_execution_tier(intent: Intent, agent: Any = None) -> Intent:
    """Apply agent priority_tier override if set."""
    import dataclasses

    current_tier = intent.tier
    if agent is not None and hasattr(agent, "priority_tier"):
        current_tier = agent.priority_tier
    if current_tier != intent.tier:
        return dataclasses.replace(intent, tier=current_tier)
    return intent


def _stop_response(content: str) -> dict[str, Any]:
    """Build an OpenAI-compatible single-message response with finish_reason=stop."""
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def _apply_intent_hint(
    intent: Intent, intent_hint: str, task_types: Mapping[str, Any] | None = None
) -> Intent:
    """Override the classified task_type when a valid intent_hint is supplied.

    `intent.task_type`'s domain is the configured task types — the same mapping
    the classifier is handed and that `IntentRegistry.resolve` looks names up
    in. This used to match against `TIER_ORDER` instead, the model-size tiers
    `small/medium/large/frontier`, which is a different domain entirely. The
    effect was doubly wrong: `intent_hint="large"` wrote "large" into
    `task_type`, which resolves to no agent and silently falls through to the
    default one, while every legitimate hint ("code", "chat") matched nothing
    and was silently dropped. An unknown hint is now logged rather than
    swallowed, because a caller passing one is asking for behaviour they will
    otherwise never notice they did not get.
    """
    if not intent_hint:
        return intent
    import dataclasses

    for task_type in task_types or {}:
        if task_type.upper() == intent_hint.upper():
            return dataclasses.replace(intent, task_type=task_type)

    logger.warning(
        "Ignoring unknown intent_hint=%r; not one of the configured task types (%s)",
        intent_hint,
        ", ".join(sorted(task_types or {})) or "none configured",
    )
    return intent


class Conduit:
    """Request pipeline: classify → route → agent.handle → response."""

    def __init__(self, container: Container) -> None:
        self.container = container

    async def route_request(
        self,
        messages: list[dict[str, Any]],
        *,
        auth: Any = None,
        session_id: str | None = None,
        intent_hint: str = "",
    ) -> dict[str, Any]:
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break

        if not last_user_msg:
            return _stop_response("No message provided.")

        # 1. Gate scan
        gate_result = await self.container.gate.process_input(last_user_msg, auth=auth)
        if gate_result.blocked:
            logger.warning("Gate blocked: %s", gate_result.block_reason)
            return _stop_response(f"Request blocked: {gate_result.block_reason}")

        # 2. Classify intent
        intent = await self.container.classifier.classify(
            messages,
            self.container.config.task_types,
        )
        intent = _apply_intent_hint(intent, intent_hint, self.container.config.task_types)

        logger.info(
            "Classified: task_type=%s complexity=%s tier=%s",
            intent.task_type,
            intent.complexity,
            intent.tier,
        )

        # 3. Resolve agent
        agent_name = self.container.intent_registry.resolve(intent.task_type)
        agent = self.container.agents.get(agent_name)

        if agent is None:
            agent = next(iter(self.container.agents.values())) if self.container.agents else None

        if agent is None:
            return _stop_response("No agents available.")

        # 4. Determine execution tier
        intent = await determine_execution_tier(intent, agent)

        # 5. Dispatch to agent
        try:
            # `classified_task_type` is what reaches strategy construction, RCA
            # tagging and learning scope. Passing only `intent=` left it at its
            # "" default on every live request, so all three ran untyped and the
            # classifier's work above was discarded at the last step.
            result = await agent.handle(
                messages=messages,
                intent=intent,
                auth=auth,
                session_id=session_id,
                classified_task_type=intent.task_type,
            )
        except Exception as exc:
            logger.exception("Agent %s failed", agent_name)
            return _stop_response(f"Agent error: {exc}")

        if isinstance(result, dict):
            return result

        return _stop_response(str(result))
