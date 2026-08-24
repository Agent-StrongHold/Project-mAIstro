"""Meta hyperagent — proactive polls/scans; gated Jira writes become suggestions only.

**The pulse proposes work, and the caller's roster says who does it (#221).**

It used to do both. `autonomous_pulse_candidates` named an agent per candidate
— `program_manager`, `risk_dependency`, `reporting` — and `propose_autonomous_actions`
filtered each through `get_pm_def`, PM Fleet's six-name table. Those names only
mean something in a workspace whose persona materialized agents with them, so a
workspace running any other persona got a pulse proposing work none of its
agents could do: every action raised, every one was logged, nothing queued.

The roster now arrives as an argument. A capability is matched to the **first
agent in roster order that declares it**, which is a rule any roster can answer
— an ordered list and a set membership test, with no notion of a "primary"
agent that a wizard-authored persona would have no way to express. PM Fleet's
own order resolves every pulse capability to exactly the agent that was
hardcoded before, including `fetch_program_state`, which both `program_manager`
and `research` declare and which the old list gave to `program_manager`.

`maistro-core` stays product-agnostic either way (ADR-019): nothing here
imports a roster, and PM Fleet becomes one caller's argument.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from maistro.agents.pm_capabilities import (
    WORK_ITEM_LABELS,
    WorkItemType,
    autonomous_pulse_candidates,
    is_autonomous,
)
from maistro.agents.program_context import (
    ProgramContext,
    current_interview_question,
    interview_steps_for,
)
from maistro.agents.work_items import suggest_work_item


@dataclass(frozen=True)
class RosterAgent:
    """One agent a workspace actually has, and what it declares it can do.

    Deliberately two fields. The pulse asks a roster exactly one question —
    "who here can do this?" — and anything richer would be a shape only the
    roster that happens to have it could satisfy.
    """

    name: str
    capabilities: frozenset[str]


#: A workspace's agents, in the order they should be preferred. Order is
#: load-bearing: two agents may declare one capability, and the first wins.
AgentRoster = Sequence[RosterAgent]


def agent_for_capability(roster: AgentRoster, capability: str) -> str | None:
    """Who in this roster can do this, or None if nobody can.

    First declarer in roster order, rather than a "primary capability" match.
    A persona built by the wizard has no primary-capability field to consult,
    and a rule only PM Fleet can answer is the rule this issue exists to
    remove.
    """
    for agent in roster:
        if capability in agent.capabilities:
            return agent.name
    return None


@dataclass(frozen=True)
class ProposedAction:
    agent_id: str
    capability: str
    reason: str
    payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "capability": self.capability,
            "reason": self.reason,
            "payload": self.payload,
            "autonomous": is_autonomous(self.capability),
        }


@dataclass(frozen=True)
class WorkItemSuggestion:
    work_type: WorkItemType
    reason: str
    draft_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "work_type": self.work_type,
            "label": WORK_ITEM_LABELS[self.work_type],
            "reason": self.reason,
            "draft_id": self.draft_id,
        }


def interview_status(
    ctx: ProgramContext,
    *,
    use_case: str = "pm_fleet",
    custom_steps: tuple[dict[str, str], ...] | None = None,
) -> dict[str, Any]:
    """`use_case` selects which persona's interview script `total_steps` and
    the next question are drawn from (Persona/Workspace system) -- callers
    that never resolve a specific persona (the pre-Phase-B majority) keep
    getting the pm_fleet script via the default, unchanged. `custom_steps`
    (a persona's own declared `PersonaTemplate.interview`) takes priority
    over `use_case`'s canned script when given and non-empty."""
    steps = interview_steps_for(use_case, custom_steps)
    q = current_interview_question(ctx, use_case=use_case, custom_steps=custom_steps)
    if ctx.interview_complete:
        return {
            "complete": True,
            "step": len(steps),
            "total_steps": len(steps),
            "message": "Interview complete. Autonomous polls run automatically; Jira creates require your approval.",
        }
    if q is None:
        return {"complete": True, "step": 0, "total_steps": len(steps), "message": ""}
    return {
        "complete": False,
        "step": ctx.interview_step + 1,
        "total_steps": len(steps),
        "agent": q["agent"],
        "question": q["question"],
    }


def propose_autonomous_actions(
    ctx: ProgramContext,
    *,
    roster: AgentRoster,
    max_actions: int = 4,
) -> list[ProposedAction]:
    """Only polls, scans, and read-only sync — safe to queue without approval.

    ``roster`` is the workspace's own agents. A candidate whose capability
    nobody here declares is dropped rather than proposed: an action naming an
    agent this workspace does not have cannot run, and proposing it anyway
    puts the failure at queue time, one layer below where it is explicable.
    """
    if not ctx.interview_complete:
        return []

    ctx_payload = {
        "title": ctx.program_name or "program",
        "summary": ctx.summary,
        "program": ctx.program_name,
        "goals": ctx.goals,
        "tools": ctx.tools,
    }

    actions: list[ProposedAction] = []
    for capability, reason in autonomous_pulse_candidates(ctx.tools):
        if len(actions) >= max_actions:
            break
        agent_id = agent_for_capability(roster, capability)
        if agent_id is None:
            continue
        actions.append(
            ProposedAction(
                agent_id=agent_id,
                capability=capability,
                reason=reason,
                payload={**ctx_payload, "source": "hyperagent"},
            )
        )

    seen: set[tuple[str, str]] = set()
    unique: list[ProposedAction] = []
    for a in actions:
        key = (a.agent_id, a.capability)
        if key in seen:
            continue
        seen.add(key)
        unique.append(a)
    return unique[:max_actions]


def propose_work_item_suggestions(
    ctx: ProgramContext,
    user_id: str,
) -> list[WorkItemSuggestion]:
    """Gated Jira hierarchy — suggest only, never auto-queue create."""
    if not ctx.interview_complete:
        return []

    suggestions: list[WorkItemSuggestion] = []
    if ctx.goals and ctx.program_name:
        suggestions.append(
            WorkItemSuggestion(
                work_type="initiative",
                reason=f"Goal '{ctx.goals[0][:50]}' may need a tracked initiative in Jira",
            )
        )
    if ctx.program_name and len(suggestions) < 3:
        suggestions.append(
            WorkItemSuggestion(
                work_type="epic",
                reason=f"Break down '{ctx.program_name}' into an epic under your initiative",
            )
        )
    return suggestions


def build_suggestion_draft(
    user_id: str,
    work_type: WorkItemType,
    ctx: ProgramContext,
    reason: str,
    hint: str = "",
) -> tuple[WorkItemSuggestion, Any]:
    draft = suggest_work_item(user_id, work_type, ctx, reason=reason, hint=hint)
    suggestion = WorkItemSuggestion(work_type=work_type, reason=reason, draft_id=draft.id)
    return suggestion, draft


def propose_actions(
    ctx: ProgramContext,
    *,
    roster: AgentRoster,
    max_actions: int = 3,
    include_interview: bool = True,
) -> list[ProposedAction]:
    """Backward-compatible: autonomous actions only (no gated creates)."""
    if include_interview and not ctx.interview_complete:
        q = current_interview_question(ctx)
        if q:
            return [
                ProposedAction(
                    agent_id="intake",
                    capability="route_to_pm_agent",
                    reason="Complete program interview so agents understand your context",
                    payload={"awaiting": "interview_answer", "question": q["question"]},
                )
            ]
        return []
    return propose_autonomous_actions(ctx, roster=roster, max_actions=max_actions)
