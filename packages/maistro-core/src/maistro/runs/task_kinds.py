"""Choosing the node kind a directly-submitted task admits as (#41).

`admission.py` builds the one-node Graph but refuses to invent the kind, because
the kind is a routing decision and routing already has an owner:
:mod:`maistro.agents.intents` holds the `task_type -> agent_name` table the
dispatcher has always consulted. This module is the missing half-step — from the
agent that table names to the node kind that can actually run it.

There is exactly one such kind. `agent.delegate_remote` with `peer_name` unset is
in-process delegation to a named agent, which is precisely what a submitted task
is: a description, an agent to hand it to, and a wait for the answer. Reusing it
is the point — a task that admits as a Run must execute through the same node the
rest of the graph layer already executes, or the Run is canonical in shape only.

The mapping is therefore total by construction: `IntentRegistry.resolve()` falls
back to a default agent rather than failing, so every task_type resolves. What
can still fail is an explicit `agent_id` naming nothing, and that failure belongs
to the agent layer at execution time, not to admission — admission's job is to
produce a Run that *can* run, and a delegation node with a wrong agent name runs
and reports the failure through the canonical Attempt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from maistro.agents.intents import IntentRegistry

#: The node kind every directly-submitted task admits as. In-process A2A
#: delegation to a named agent — see the module docstring for why there is
#: only one.
DELEGATE_NODE_KIND = "agent.delegate_remote"

#: Node name used when a task carries no better label.
DEFAULT_WORK_NAME = "task"


@dataclass(frozen=True)
class DirectWork:
    """The node kind, agent and parameters one submitted task admits as."""

    node_type: str
    agent_name: str
    name: str
    parameters: dict[str, Any] = field(default_factory=dict)


def _first_line(text: str, *, limit: int = 80) -> str:
    """A node name from a free-text description: first line, bounded."""
    line = text.strip().splitlines()[0].strip() if text.strip() else ""
    if not line:
        return DEFAULT_WORK_NAME
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def resolve_direct_work(
    *,
    description: str,
    task_type: str | None = None,
    agent_id: str | None = None,
    from_agent: str = "",
    timeout_seconds: int | None = None,
    registry: IntentRegistry | None = None,
) -> DirectWork:
    """Resolve one submitted task to the node kind and parameters that run it.

    ``agent_id`` wins when the submitter named an agent explicitly; otherwise
    ``task_type`` is resolved through the intent registry, which is total. The
    returned ``parameters`` are already shaped for ``agent.delegate_remote``'s
    input schema, so :func:`maistro.runs.admission.direct_work_graph` can take
    them unchanged.
    """
    resolver = registry if registry is not None else IntentRegistry()
    agent_name = (agent_id or "").strip() or resolver.resolve((task_type or "").strip())
    parameters: dict[str, Any] = {
        "from_agent": from_agent,
        "task": description,
        "to_agent": agent_name,
    }
    if timeout_seconds is not None:
        parameters["timeout_seconds"] = timeout_seconds
    return DirectWork(
        node_type=DELEGATE_NODE_KIND,
        agent_name=agent_name,
        name=_first_line(description),
        parameters=parameters,
    )


__all__ = [
    "DEFAULT_WORK_NAME",
    "DELEGATE_NODE_KIND",
    "DirectWork",
    "resolve_direct_work",
]
