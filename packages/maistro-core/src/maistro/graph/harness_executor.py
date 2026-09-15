"""Harness capability adapter (SPEC-208 §5 outbound).

Bridges the graph's provider-level ``NodeExecutor`` protocol to the
capability-framework :class:`~maistro.capabilities.HarnessSessionManager`.
The canonical durable Graph executor owns the Attempt around this adapter;
this class only drives one already-admitted capability turn and never creates
or advances Run, NodeRun, or Attempt lifecycle.

The manager already wraps the raw harness in Warden + policy gating, so this
adapter only has to (a) map the graph role onto an ``AgentSpec`` and (b)
normalize the response envelope — OpenAI ``choices`` shape *or* a flat
``{content, actions}`` shape — into :class:`~maistro.graph.types.HarnessOutput`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from maistro.agents.spec.agent_spec import AgentRole as SpecAgentRole
from maistro.agents.spec.agent_spec import AgentSpec
from maistro.capabilities import HarnessSessionManager, Unavailable
from maistro.graph.types import AgentRole, GraphBlackboard, HarnessOutput

# Best-effort graph-role → spec-role map. Graph roles that have no spec
# counterpart (HARNESS itself, PM-fleet roles) fall back to CODER — the harness
# is a general executor, so the spec role is only advisory context.
_ROLE_MAP: dict[AgentRole, SpecAgentRole] = {
    AgentRole.PLANNER: SpecAgentRole.PLANNER,
    AgentRole.CODER: SpecAgentRole.CODER,
    AgentRole.REVIEWER: SpecAgentRole.REVIEWER,
    AgentRole.SCOUT: SpecAgentRole.SCOUT,
}


class HarnessExecutionError(Exception):
    """Raised when a harness-backed node cannot complete its turn.

    Surfacing this (rather than returning a degraded output) lets the node's
    existing retry/circuit-breaker plumbing classify and record the failure.
    """


def _spec_role(role: AgentRole) -> SpecAgentRole:
    return _ROLE_MAP.get(role, SpecAgentRole.CODER)


def _extract_summary(envelope: dict[str, Any]) -> str:
    """Pull the assistant text from either envelope shape."""
    content = envelope.get("content")
    if isinstance(content, str) and content:
        return content
    choices = envelope.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            text = message.get("content")
            if isinstance(text, str):
                return text
    return ""


def _extract_actions(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    actions = envelope.get("actions")
    return [a for a in actions if isinstance(a, dict)] if isinstance(actions, list) else []


class HarnessNodeExecutor:
    """Provider adapter for one foreign-harness capability turn.

    Structurally satisfies :class:`maistro.graph.node.NodeExecutor`. One
    adapter instance may back many durable node Attempts; each :meth:`run`
    starts and stops its own harness session so nodes never share turn state.
    """

    def __init__(self, manager: HarnessSessionManager, *, workdir: str = ".") -> None:
        self._manager = manager
        self._workdir = workdir

    async def run(
        self,
        *,
        role: AgentRole,
        system_prompt: str,
        user_prompt: str,
        blackboard: GraphBlackboard | None,
        output_type: type[BaseModel],
    ) -> BaseModel:
        # This executor only produces HarnessOutput. Silently returning it for
        # a planner/coder/reviewer override marked the node successful while
        # _update_pipeline_state rejected the mismatched type, leaving plan/
        # code/review unset — an incomplete result with a green node. Refuse
        # loudly at dispatch instead (Codex, #262).
        if not issubclass(HarnessOutput, output_type):
            raise HarnessExecutionError(
                f"HarnessNodeExecutor produces HarnessOutput, but this node "
                f"requires {output_type.__name__}; wire a role-appropriate "
                "executor instead of the harness override."
            )
        spec = AgentSpec(
            role=_spec_role(role),
            task_id="graph-harness",
            subtask_id=role.value,
            description=user_prompt,
        )
        session = await self._manager.start(spec, workdir=self._workdir)
        if isinstance(session, Unavailable):
            raise HarnessExecutionError(f"harness unavailable: {session.reason}")

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            envelope = await self._manager.send(session, messages)
            if isinstance(envelope, Unavailable):
                raise HarnessExecutionError(f"harness session lost: {envelope.reason}")
            return HarnessOutput(
                summary=_extract_summary(envelope),
                actions=_extract_actions(envelope),
                raw=envelope,
            )
        finally:
            await self._manager.stop(session)


__all__ = ["HarnessExecutionError", "HarnessNodeExecutor"]
