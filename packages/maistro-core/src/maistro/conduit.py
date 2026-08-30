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

from maistro.types.agent import AgentResponse
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


#: OpenAI's own finish_reason for a refusal, so a client that already handles
#: moderation needs no Maistro-specific case for a Gate block.
CONTENT_FILTER = "content_filter"

#: Where `route_request` names the agent that handled the turn (#223). Present
#: only when one did: a refusal, an empty roster or a turn with no message
#: never reached an agent, and a blank name would read as one that did.
DISPATCHED_AGENT_KEY = "agent"


def _stop_response(content: str, *, finish_reason: str = "stop") -> dict[str, Any]:
    """Build an OpenAI-compatible single-message response."""
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
    }


def _as_response(result: Any) -> dict[str, Any]:
    """The OpenAI-compatible shape for whatever an agent returned.

    An agent that already speaks the wire shape is passed through. Everything
    else is a *value* to be rendered, and the one that matters is
    `AgentResponse` — what every `BaseAgent.handle` returns.

    Rendering it was previously `str(result)`, which is why this exists. A
    dataclass with no `__str__` stringifies to its repr, so the assistant
    message a caller read back was::

        AgentResponse(content='the real answer', trace_id='', model_used='', ...

    with the answer buried inside it. The only agents that escaped were the
    ones returning a dict, and the only test covering the branch passed a plain
    string — so the branch looked exercised while the shape that actually
    travels it was never tried.

    `blocked` and `failed` are carried as finish reasons rather than dropped:
    a refusal is `content_filter`, which is OpenAI's own spelling, and a failure
    keeps `stop` (OpenAI has no reason for it) but says so in the content the
    agent already put there.
    """
    if isinstance(result, dict):
        return result
    if isinstance(result, AgentResponse):
        if result.blocked:
            return _stop_response(
                f"Request blocked: {result.block_reason}", finish_reason=CONTENT_FILTER
            )
        return _stop_response(result.content)
    return _stop_response(str(result))


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
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break

        if not last_user_msg:
            return _stop_response("No message provided.")

        # 1. Gate scan
        #
        # A scan that fails for its own reasons refuses the turn. A Gate that
        # raises must not become an open door — the exception would otherwise
        # propagate past the classifier and the agent, which is safe here but
        # is safe by accident: any caller that caught it and continued would be
        # dispatching unscanned input. Refusing makes the boundary hold at the
        # boundary. Note this is the opposite of how the Run is handled — a turn
        # is answered without a Run and refused without a scan — because the two
        # protect different things: one is a record, the other is the door.
        try:
            gate_result = await self.container.gate.process_input(last_user_msg, auth=auth)
        except Exception:
            logger.exception("Gate scan failed; refusing the turn")
            return _stop_response(
                "Request could not be screened and was not run.", finish_reason=CONTENT_FILTER
            )
        if gate_result.blocked:
            logger.warning("Gate blocked: %s", gate_result.block_reason)
            return _stop_response(
                f"Request blocked: {gate_result.block_reason}", finish_reason=CONTENT_FILTER
            )

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
            # The fallback rebinds the *name* as well as the agent. It used not
            # to, so `agent_name` went on naming the agent the registry asked
            # for rather than the one that ran — which only ever reached a log
            # line, and now reaches an Attempt's durable record (#223). A record
            # naming an agent that did not run is worse than one naming none.
            agent_name, agent = next(iter(self.container.agents.items()), ("", None))

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
                # Carried, not interpreted. The pipeline does not know what a
                # turn identity means; the agent is where the session is
                # written, so it is where the identity has to arrive (#327).
                turn_id=turn_id,
            )
        except Exception:
            # Logged and re-raised, not turned into an answer.
            #
            # Two reasons. The message used to be `f"Agent error: {exc}"`, and
            # an exception's text is not sanitized — a provider error carries
            # its endpoint, and can carry the key sent to it, straight into the
            # assistant message a client renders. And converting an outage into
            # a normal-looking answer is the same defect class `failed=True` on
            # `AgentResponse` exists to prevent: a caller that branches on
            # success reads "the LLM is down" as a reply.
            #
            # Nothing regresses for a well-behaved agent. `BaseAgent.handle`
            # catches its own exceptions and returns a failed `AgentResponse`
            # with a generic message, so this path is only reached by an agent
            # that deliberately raises — and such an agent's caller wants the
            # exception, because the type is what selects a status code.
            logger.exception("Agent %s failed", agent_name)
            raise

        response = _as_response(result)
        # Additive, and the same shape `run_id` is added in one level up: the
        # OpenAI fields a client parses are untouched, and this names the agent
        # that actually handled the turn for anyone recording what ran. Only
        # the dispatch path sets it — a refusal, an empty roster or a turn with
        # no message never reached an agent, so there is nothing to name and
        # the key is absent rather than blank.
        response[DISPATCHED_AGENT_KEY] = agent_name
        return response
