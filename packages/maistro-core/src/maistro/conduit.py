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

from maistro.runs.model import Run, RunStatus
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


#: Key carrying how a turn ended, for a caller that has to record it (#131).
#:
#: Every failure path here returns a `finish_reason="stop"` assistant message —
#: a refusal, a dead agent and a real answer are the same shape by design, so
#: that an OpenAI-compatible client keeps working. That makes the outcome
#: unrecoverable from the response, and `Container.route_request` now has to
#: recover it: without this key every chat turn would close its canonical Run as
#: COMPLETED, including the blocked ones, which is the "canonical in shape only"
#: defect this seam exists to remove.
#:
#: Absent means completed. Additive to the response dict, so nothing reading
#: `choices[0]["message"]["content"]` is affected.
CONDUIT_OUTCOME = "maistro_outcome"

#: The turn produced an answer.
OUTCOME_COMPLETED = "completed"
#: The turn was refused before any agent ran — a Gate block, or a request with
#: nothing in it to route.
OUTCOME_REFUSED = "refused"
#: An agent ran and failed, or none could be found to run.
OUTCOME_FAILED = "failed"


#: How a turn's outcome closes its canonical Run. `refused` maps to CANCELLED
#: rather than FAILED because nothing executed: the request was turned away, and
#: recording that as a failure would make policy refusals indistinguishable from
#: agents that broke.
RUN_STATUS_BY_OUTCOME: dict[str, RunStatus] = {
    OUTCOME_COMPLETED: RunStatus.COMPLETED,
    OUTCOME_FAILED: RunStatus.FAILED,
    OUTCOME_REFUSED: RunStatus.CANCELLED,
}


def last_user_message(messages: list[dict[str, Any]]) -> str:
    """The most recent user message, or "" when there is none.

    Shared rather than inlined: the Run admitted for a turn must describe the
    same prompt the agent was handed, and two copies of this loop is how those
    quietly stop being the same prompt.
    """
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content", "") or "")
    return ""


def _stop_response(content: str, *, outcome: str = OUTCOME_COMPLETED) -> dict[str, Any]:
    """Build an OpenAI-compatible single-message response with finish_reason=stop."""
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        CONDUIT_OUTCOME: outcome,
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

    async def _admit_run(
        self,
        *,
        prompt: str,
        task_type: str,
        agent_name: str,
        session_id: str | None,
        request_id: str | None,
        user_id: str | None,
    ) -> Run | None:
        """Admit this turn as a canonical Run, or None if no spine is wired.

        Deliberately after routing rather than at the top of the pipeline. The
        Run's Graph node names the agent that will execute it, and at the top of
        the pipeline nothing has classified the request yet — a Run admitted
        there would name the intent registry's fallback agent on every turn,
        which is the exact defect `runs/wiring.py` already carries a comment
        about. The cost is that a turn refused before routing (an empty request,
        a Gate block) gets no Run: it is not work, and the record of a refusal
        at the trust boundary belongs to the Gate's audit trail, not the spine's.

        A missing admitter is not an error. `Container` can be built directly
        without a spine, and a chat path that started refusing requests because
        housekeeping was unwired would be a worse failure than an absent run_id.
        """
        admitter = self.container.chat_admitter
        if admitter is None:
            return None
        run: Run = await admitter.admit_chat_turn(
            prompt=prompt,
            task_type=task_type,
            agent_name=agent_name,
            session_id=session_id,
            request_id=request_id,
            user_id=user_id,
        )
        return run

    async def _close_run(self, run: Run | None, response: dict[str, Any]) -> dict[str, Any]:
        """Close the turn's Run and stamp its id onto the response.

        The assistant's answer is deliberately *not* copied onto the Run.
        Conversation content lives in `maistro.sessions`, which has its own TTL;
        duplicating it here would give the same user content two retentions and
        two places to honour a deletion request. The Run records that the turn
        happened and how it ended, which is what an execution identity is for.
        """
        admitter = self.container.chat_admitter
        if run is None or admitter is None:
            return response
        outcome = str(response.get(CONDUIT_OUTCOME, OUTCOME_COMPLETED))
        status = RUN_STATUS_BY_OUTCOME.get(outcome, RunStatus.COMPLETED)
        error = None
        if status is not RunStatus.COMPLETED:
            error = str(response["choices"][0]["message"]["content"])
        closed = await admitter.record_outcome(run.run_id, status, error=error)
        if not closed:
            # Not raised: the user's answer is already computed, and losing it
            # to a bookkeeping failure would be the worse trade. Logged loudly,
            # because a run_id the caller can resolve to a Run stuck mid-flight
            # is the divergence this seam exists to surface.
            logger.error(
                "Chat Run %s refused its closing transition to %s", run.run_id, status.value
            )
        return {**response, "run_id": run.run_id}

    async def route_request(
        self,
        messages: list[dict[str, Any]],
        *,
        auth: Any = None,
        session_id: str | None = None,
        intent_hint: str = "",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        last_user_msg = last_user_message(messages)

        if not last_user_msg:
            return _stop_response("No message provided.", outcome=OUTCOME_REFUSED)

        # 1. Gate scan
        gate_result = await self.container.gate.process_input(last_user_msg, auth=auth)
        if gate_result.blocked:
            logger.warning("Gate blocked: %s", gate_result.block_reason)
            return _stop_response(
                f"Request blocked: {gate_result.block_reason}", outcome=OUTCOME_REFUSED
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
            agent = next(iter(self.container.agents.values())) if self.container.agents else None

        if agent is None:
            return _stop_response("No agents available.", outcome=OUTCOME_FAILED)

        # 4. Determine execution tier
        intent = await determine_execution_tier(intent, agent)

        # 5. Admit the canonical Run for this turn (#131). One Run per turn; the
        # conversation travels in provenance. `agent.identity.name` rather than
        # the resolved `agent_name`, because the line above falls back to an
        # arbitrary agent when the resolved one is not registered, and the Run
        # must name the agent that actually ran.
        run = await self._admit_run(
            prompt=last_user_msg,
            task_type=intent.task_type,
            agent_name=getattr(getattr(agent, "identity", None), "name", "") or agent_name,
            session_id=session_id,
            request_id=request_id,
            user_id=getattr(auth, "user_id", None),
        )

        # 6. Dispatch to agent
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
            return await self._close_run(
                run, _stop_response(f"Agent error: {exc}", outcome=OUTCOME_FAILED)
            )

        if isinstance(result, dict):
            return await self._close_run(run, result)

        return await self._close_run(run, _stop_response(str(result)))
