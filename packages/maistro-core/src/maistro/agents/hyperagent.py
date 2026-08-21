"""Meta hyperagent — proactive polls/scans; gated Jira writes become suggestions only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maistro.agents.pm_capabilities import (
    WORK_ITEM_LABELS,
    WorkItemType,
    autonomous_pulse_candidates,
    is_autonomous,
)
from maistro.agents.pm_fleet import get_pm_def
from maistro.agents.program_context import (
    ProgramContext,
    current_interview_question,
    interview_steps_for,
)
from maistro.agents.work_items import suggest_work_item


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
    max_actions: int = 4,
) -> list[ProposedAction]:
    """Only polls, scans, and read-only sync — safe to queue without approval."""
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
    for agent_id, capability, reason in autonomous_pulse_candidates(ctx.tools):
        if len(actions) >= max_actions:
            break
        if get_pm_def(agent_id) is None:
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
    return propose_autonomous_actions(ctx, max_actions=max_actions)
