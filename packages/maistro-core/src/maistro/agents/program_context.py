"""Per-user program context — projects, interview state, learned guidance."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InterviewTurn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str  # agent | user
    text: str
    at: str = ""


class ProgramProject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    status: str = "active"


class ProgramContext(BaseModel):
    """What a workspace's hyperagent knows about a user's program — grows via interview + guidance.

    Scoped by (user_id, project_id): a user can run this interview independently
    across multiple workspaces (Persona/Workspace system) rather than having
    exactly one program per user. ``project_id`` defaults to ``"default"`` so
    existing single-workspace callers are unaffected.
    """

    model_config = ConfigDict(extra="ignore")

    user_id: str
    project_id: str = "default"
    program_name: str = ""
    summary: str = ""
    goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    stakeholders: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    projects: list[ProgramProject] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    interview_complete: bool = False
    interview_step: int = 0
    interview_transcript: list[InterviewTurn] = Field(default_factory=list)
    guidance_log: list[str] = Field(default_factory=list)
    last_pulse_at: str | None = None
    updated_at: str = ""

    @staticmethod
    def empty(user_id: str, project_id: str = "default") -> ProgramContext:
        now = datetime.now(UTC).isoformat()
        return ProgramContext(user_id=user_id, project_id=project_id, updated_at=now)


# Per-persona (use_case) interview question sets — one question at a time
# until complete. "pm_fleet" is today's fixed intake script, unchanged;
# "_generic" is the fallback for any persona without its own template (e.g. a
# newly-authored persona that hasn't defined interview questions yet).
INTERVIEW_TEMPLATES: dict[str, tuple[dict[str, str], ...]] = {
    "pm_fleet": (
        {
            "field": "program_name",
            "agent": "intake",
            "question": "What program or initiative are you accountable for? Name it in one line.",
        },
        {
            "field": "goals",
            "agent": "intake",
            "question": "What outcomes must be true in the next 90 days? List the top 2-3.",
        },
        {
            "field": "tools",
            "agent": "intake",
            "question": "Which systems does the team use daily? (e.g. Jira, GitHub, Confluence, Slack)",
        },
        {
            "field": "constraints",
            "agent": "risk_dependency",
            "question": "What constraints or dependencies worry you most right now?",
        },
        {
            "field": "stakeholders",
            "agent": "program_manager",
            "question": "Who are the key stakeholders you report to or coordinate with?",
        },
    ),
    "_generic": (
        {
            "field": "program_name",
            "agent": "intake",
            "question": "What should we call this workspace?",
        },
        {
            "field": "goals",
            "agent": "intake",
            "question": "What outcomes matter most here? List the top 2-3.",
        },
        {
            "field": "tools",
            "agent": "intake",
            "question": "Which external systems or accounts does this involve?",
        },
        {
            "field": "constraints",
            "agent": "intake",
            "question": "Anything this workspace must never do?",
        },
    ),
}

# Backward-compat alias: the fixed PM Fleet script, unchanged, for callers
# that haven't been generalized to pass a use_case yet (e.g. maistro.agents.hyperagent).
INTERVIEW_STEPS: tuple[dict[str, str], ...] = INTERVIEW_TEMPLATES["pm_fleet"]

# Per-use_case finalization wording -- pm_fleet keeps its original PM-flavored
# summary label and open questions verbatim; any other use_case (including the
# generic fallback) gets neutral wording instead of leaking PM-specific
# "dependency"/"milestone" phrasing into e.g. a creative or author workspace.
_SUMMARY_LABEL: dict[str, str] = {"pm_fleet": "Program"}
_DEFAULT_SUMMARY_LABEL = "Workspace"

_FINALIZATION_OPEN_QUESTIONS: dict[str, list[str]] = {
    "pm_fleet": [
        "What is the single highest-risk dependency this month?",
        "Which milestone should we protect first?",
    ],
}
_DEFAULT_FINALIZATION_OPEN_QUESTIONS: list[str] = [
    "What's the most important thing to get right first?",
    "What should we check in on regularly?",
]


def interview_steps_for(
    use_case: str, custom_steps: tuple[dict[str, str], ...] | None = None
) -> tuple[dict[str, str], ...]:
    """Return a persona's own declared interview script (`custom_steps`,
    e.g. from a `PersonaTemplate.interview` -- Persona/Workspace system)
    when one is given and non-empty; otherwise the persona-specific canned
    script if `use_case` has one; otherwise the generic fallback. Callers
    that don't resolve a `PersonaTemplate` (every caller before this
    parameter existed) get the exact old behavior."""
    if custom_steps:
        return custom_steps
    return INTERVIEW_TEMPLATES.get(use_case, INTERVIEW_TEMPLATES["_generic"])


def current_interview_question(
    ctx: ProgramContext,
    use_case: str = "pm_fleet",
    custom_steps: tuple[dict[str, str], ...] | None = None,
) -> dict[str, str] | None:
    if ctx.interview_complete:
        return None
    steps = interview_steps_for(use_case, custom_steps)
    if ctx.interview_step >= len(steps):
        return None
    return steps[ctx.interview_step]


def apply_interview_answer(
    ctx: ProgramContext,
    answer: str,
    use_case: str = "pm_fleet",
    custom_steps: tuple[dict[str, str], ...] | None = None,
) -> ProgramContext:
    """Record an interview answer and advance the script."""
    answer = answer.strip()
    if not answer or ctx.interview_complete:
        return ctx

    steps = interview_steps_for(use_case, custom_steps)
    step_idx = ctx.interview_step
    if step_idx >= len(steps):
        return ctx.model_copy(update={"interview_complete": True})

    step = steps[step_idx]
    field = step["field"]
    now = datetime.now(UTC).isoformat()
    transcript = [
        *ctx.interview_transcript,
        InterviewTurn(role="agent", text=step["question"], at=now),
        InterviewTurn(role="user", text=answer, at=now),
    ]

    updates: dict[str, Any] = {
        "interview_transcript": transcript,
        "interview_step": step_idx + 1,
        "updated_at": now,
        "facts": [*ctx.facts, f"Interview ({field}): {answer}"],
    }

    if field == "program_name":
        updates["program_name"] = answer
        updates["projects"] = [
            *ctx.projects,
            ProgramProject(name=answer, description="Primary program from intake interview"),
        ]
    elif field == "goals":
        updates["goals"] = _split_lines(answer)
    elif field == "tools":
        updates["tools"] = _split_lines(answer)
    elif field == "constraints":
        updates["constraints"] = _split_lines(answer)
    elif field == "stakeholders":
        updates["stakeholders"] = _split_lines(answer)

    next_ctx = ctx.model_copy(update=updates)
    if next_ctx.interview_step >= len(steps):
        label = _SUMMARY_LABEL.get(use_case, _DEFAULT_SUMMARY_LABEL)
        summary = (
            f"{label}: {next_ctx.program_name}. "
            f"Goals: {', '.join(next_ctx.goals[:3])}. "
            f"Tools: {', '.join(next_ctx.tools[:4])}."
        )
        open_questions = _FINALIZATION_OPEN_QUESTIONS.get(
            use_case, _DEFAULT_FINALIZATION_OPEN_QUESTIONS
        )
        next_ctx = next_ctx.model_copy(
            update={
                "interview_complete": True,
                "summary": summary.strip(),
                "open_questions": list(open_questions),
            }
        )
    return next_ctx


def apply_guidance(ctx: ProgramContext, text: str) -> ProgramContext:
    """Learn from human guidance — append facts and open questions for the hyperagent."""
    text = text.strip()
    if not text:
        return ctx
    now = datetime.now(UTC).isoformat()
    facts = [*ctx.facts, f"Guidance: {text}"]
    open_q = list(ctx.open_questions)
    lowered = text.lower()
    if "?" in text:
        open_q.append(text)
    if any(w in lowered for w in ("risk", "blocker", "dependency")):
        open_q.append("Validate RAID entries against latest guidance")
    return ctx.model_copy(
        update={
            "guidance_log": [*ctx.guidance_log, text],
            "facts": facts[-50:],  # cap growth
            "open_questions": open_q[-20:],
            "updated_at": now,
        }
    )


def context_for_task(ctx: ProgramContext) -> dict[str, Any]:
    """Compact dict injected into PM task payloads."""
    return {
        "program_name": ctx.program_name,
        "summary": ctx.summary,
        "goals": ctx.goals,
        "constraints": ctx.constraints,
        "stakeholders": ctx.stakeholders,
        "tools": ctx.tools,
        "recent_guidance": ctx.guidance_log[-3:],
        "open_questions": ctx.open_questions[:5],
    }


def _split_lines(text: str) -> list[str]:
    parts: list[str] = []
    for line in text.replace(",", "\n").split("\n"):
        s = line.strip().lstrip("-•* ")
        if s:
            parts.append(s)
    return parts
