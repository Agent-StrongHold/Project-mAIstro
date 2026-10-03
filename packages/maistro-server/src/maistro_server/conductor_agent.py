"""The roster a deployment with no agents still has (ADR-082426-2192, #142).

`Conduit.route_request` resolves an agent name and answers "No agents
available." when the map is empty. `maistro-server` has never built agents —
`settings.agents_dir` defaults to `""` — while `maistro.agents.conductor.run_task`
needs no roster at all: it picks a tier, resolves a model and calls the gateway.
That is why `/v1/chat/completions` works today on deployments that have
configured nothing, and why routing it naively through the Conduit would turn
every one of those turns into a refusal.

So the fallback is not a stub. It is the same executor the endpoint called
directly before, reached *through* the pipeline instead of around it, which is
the whole of what #142 asks for. What the turn gains on the way in is real: the
Gate scan, the session store, and a classifier whose tier now reaches `run_task`
rather than every turn running at the default.

This is meant to be outgrown. When a deployment can be expected to ship a
roster, `agents_dir` populates `Container.agents` and this stops being reached.
"""

from __future__ import annotations

from typing import Any

import structlog

from maistro.agents.conductor import run_task
from maistro.tasks.models import TaskCreate
from maistro.types.agent import AgentResponse

logger = structlog.get_logger()

#: The name this agent is registered under. Deliberately not a task type: the
#: intent registry maps task types to agent *names*, and a name it cannot
#: resolve falls through to `next(iter(agents.values()))` — which is this one
#: whenever it is the only entry, and correctly is not once a roster exists.
CONDUCTOR_AGENT_NAME = "conductor"


class ConductorAgent:
    """Executes a turn through `run_task`, the conductor pipeline.

    Shaped to what `Conduit.route_request` actually uses — `handle(...)`, and a
    `priority_tier` it deliberately does not have — rather than subclassing
    `BaseAgent`. Subclassing would inherit a strategy stack, a tool loop and a
    learning path that `run_task` already contains its own versions of, and
    running both would mean two context builders and two extraction passes over
    one answer.

    **No `priority_tier` attribute, on purpose.** `determine_execution_tier`
    replaces the classifier's tier with the agent's whenever the attribute
    exists — `hasattr`, not truthiness, so `None` would override just as
    firmly as a number. Its absence is the only way to say "no opinion", and
    honouring the classification is the point.
    """

    async def handle(
        self,
        messages: list[dict[str, Any]],
        auth: Any = None,
        *,
        intent: Any = None,
        session_id: str | None = None,
        classified_task_type: str = "",
        **_unused: Any,
    ) -> AgentResponse:
        """Run the conductor over the last user message.

        `**_unused` absorbs the arguments a full agent takes and this one has no
        use for (`model_override`, `status_callback`, `_delegation_depth`).
        Accepting and ignoring them keeps the call site in `Conduit` uniform;
        declaring them individually would suggest they do something here.
        """
        description = _last_user_message(messages)
        if not description:
            return AgentResponse(content="No message provided.", agent_name=CONDUCTOR_AGENT_NAME)

        task = TaskCreate(description=description, **_tier_kwargs(intent))
        try:
            result = await run_task(task)
        except Exception as exc:
            # Raised rather than swallowed. `Conduit.route_request` catches
            # around this dispatch, and the endpoint above maps the exception
            # *type* to 502/504 — both need the exception, not a string
            # describing it.
            await logger.awarning(
                "conductor_agent_failed",
                task_type=classified_task_type or None,
                error_type=type(exc).__name__,
            )
            raise

        return AgentResponse(
            content=result.final_answer or "Task completed successfully.",
            agent_name=CONDUCTOR_AGENT_NAME,
            intent_task_type=classified_task_type,
        )


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    """The text the turn is about, or empty.

    The whole message list is what the classifier saw, but `run_task` takes a
    single description — so this applies the same last-user-message rule the
    endpoint applied before, in one place rather than restated.
    """
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content:
            return content
    return ""


def _tier_kwargs(intent: Any) -> dict[str, Any]:
    """The classifier's tier, when it is one `TaskCreate` can carry.

    `TaskCreate.tier` is `int | None`, and `intent.tier` is not reliably an int
    at this seam: `determine_execution_tier` copies `agent.priority_tier` over
    it, and those are the `"P0"`-style labels. Checking rather than trusting
    keeps a classified turn from becoming a validation error — a worse outcome
    than the default tier, which is what every turn used before this existed.

    `bool` is excluded because it is an `int` in Python and `tier=True` would
    silently mean tier 1.
    """
    tier = getattr(intent, "tier", None)
    if isinstance(tier, bool) or not isinstance(tier, int):
        if tier is not None:
            logger.debug("conductor_agent_tier_not_numeric", tier=repr(tier))
        return {}
    return {"tier": tier}
