"""Jira work-item drafts — suggest, clarify, edit, then confirm post."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from maistro.agents.pm_capabilities import (
    WORK_ITEM_LABELS,
    WORK_ITEM_PARENT,
    WorkItemType,
    agent_for_work_item,
    capability_for_work_item,
)
from maistro.agents.program_context import ProgramContext

DraftStatus = Literal["suggested", "clarifying", "ready", "posted", "cancelled"]


class ClarifyingQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    question: str
    answer: str = ""
    required: bool = True


class WorkItemFields(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    description: str = ""
    project_key: str = ""
    parent_key: str = ""
    issue_type: str = ""
    priority: str = "Medium"
    labels: list[str] = Field(default_factory=list)
    assignee: str = ""
    due_date: str = ""


class WorkItemDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str
    # Which ProgramContext (services/program_store.py's per-workspace key)
    # this draft was suggested under -- so a later confirm/post step reads
    # back the same context, not always the global "default" one. Defaults
    # to "default" for backward compatibility with drafts persisted before
    # this field existed.
    project_id: str = "default"
    work_type: WorkItemType
    agent_id: str
    capability: str
    status: DraftStatus = "suggested"
    suggestion_reason: str = ""
    clarifying_questions: list[ClarifyingQuestion] = Field(default_factory=list)
    fields: WorkItemFields = Field(default_factory=WorkItemFields)
    jira_preview: dict[str, Any] = Field(default_factory=dict)
    posted_issue_key: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _questions_for(work_type: WorkItemType, ctx: ProgramContext) -> list[ClarifyingQuestion]:
    program = ctx.program_name or "the program"
    base = [
        ClarifyingQuestion(
            id="summary",
            question=f"What should the {WORK_ITEM_LABELS[work_type]} title be in Jira?",
            required=True,
        ),
        ClarifyingQuestion(
            id="description",
            question="Describe the outcome, scope, and definition of done.",
            required=True,
        ),
    ]
    parent = WORK_ITEM_PARENT[work_type]
    if parent is not None:
        base.append(
            ClarifyingQuestion(
                id="parent_key",
                question=f"Parent {WORK_ITEM_LABELS[parent]} Jira key (e.g. PROJ-123) — required before posting.",
                required=True,
            )
        )
    else:
        base.append(
            ClarifyingQuestion(
                id="project_key",
                question="Jira project key for this initiative (e.g. PLAT)?",
                required=True,
            )
        )
    if work_type == "initiative":
        base.append(
            ClarifyingQuestion(
                id="goal_alignment",
                question=f"How does this initiative advance '{program}' goals?",
                required=False,
            )
        )
    if work_type in ("user_story", "dev_task"):
        base.append(
            ClarifyingQuestion(
                id="acceptance",
                question="What are the acceptance criteria?",
                required=False,
            )
        )
    return base


def suggest_work_item(
    user_id: str,
    work_type: WorkItemType,
    ctx: ProgramContext,
    *,
    reason: str = "",
    hint: str = "",
    parent_key: str = "",
) -> WorkItemDraft:
    """Start gated flow — never posts to Jira."""
    cap = capability_for_work_item(work_type)
    fields = WorkItemFields(
        issue_type=WORK_ITEM_LABELS[work_type],
        project_key=_guess_project_key(ctx),
        parent_key=parent_key,
    )
    if work_type == "initiative" and ctx.program_name:
        fields.summary = hint or ctx.program_name
        fields.description = ctx.summary or (ctx.goals[0] if ctx.goals else "")
    elif hint:
        fields.summary = hint
    elif ctx.goals:
        fields.summary = f"{WORK_ITEM_LABELS[work_type]}: {ctx.goals[0][:80]}"

    questions = _questions_for(work_type, ctx)
    unanswered = [q for q in questions if q.required and not q.answer]
    status: DraftStatus = "clarifying" if unanswered else "ready"

    now = _now()
    return WorkItemDraft(
        id=uuid4().hex[:12],
        user_id=user_id,
        project_id=ctx.project_id,
        work_type=work_type,
        agent_id=agent_for_work_item(work_type),
        capability=cap,
        status=status,
        suggestion_reason=reason or f"Suggested {WORK_ITEM_LABELS[work_type]} from program context",
        clarifying_questions=questions,
        fields=fields,
        jira_preview=_build_jira_preview(work_type, fields),
        created_at=now,
        updated_at=now,
    )


def apply_clarifying_answers(draft: WorkItemDraft, answers: dict[str, str]) -> WorkItemDraft:
    """Merge answers and prefill editable fields."""
    questions = []
    fields = draft.fields.model_copy()
    for q in draft.clarifying_questions:
        ans = answers.get(q.id, q.answer).strip()
        questions.append(q.model_copy(update={"answer": ans}))
        if q.id == "summary" and ans:
            fields.summary = ans
        elif q.id == "description" and ans:
            fields.description = ans
        elif q.id == "parent_key" and ans:
            fields.parent_key = ans.upper()
        elif q.id == "project_key" and ans:
            fields.project_key = ans.upper()
        elif q.id == "goal_alignment" and ans and not fields.description:
            fields.description = ans
        elif q.id == "acceptance" and ans:
            fields.description = f"{fields.description}\n\nAcceptance:\n{ans}".strip()

    required_open = any(q.required and not q.answer for q in questions)
    status: DraftStatus = "ready" if not required_open else "clarifying"
    now = _now()
    return draft.model_copy(
        update={
            "clarifying_questions": questions,
            "fields": fields,
            "status": status,
            "jira_preview": _build_jira_preview(draft.work_type, fields),
            "updated_at": now,
        }
    )


def update_draft_fields(draft: WorkItemDraft, updates: dict[str, Any]) -> WorkItemDraft:
    fields = draft.fields.model_copy(update={k: v for k, v in updates.items() if v is not None})
    return draft.model_copy(
        update={
            "fields": fields,
            "jira_preview": _build_jira_preview(draft.work_type, fields),
            "updated_at": _now(),
        }
    )


def confirm_post_stub(draft: WorkItemDraft) -> tuple[WorkItemDraft, dict[str, Any]]:
    """Simulate Jira create after user confirmation."""
    if draft.status != "ready":
        msg = "Complete clarifying questions before posting to Jira."
        raise ValueError(msg)
    if not draft.fields.summary.strip():
        raise ValueError("Summary is required before posting.")

    from maistro.tools.pm_stubs import stub_create_work_item

    result = stub_create_work_item(
        draft.work_type,
        draft.fields.model_dump(),
        draft.capability,
    )
    key = str(result.get("issue_key", "STUB-0"))
    now = _now()
    posted = draft.model_copy(
        update={
            "status": "posted",
            "posted_issue_key": key,
            "jira_preview": {**draft.jira_preview, "posted": True, "issue_key": key},
            "updated_at": now,
        }
    )
    return posted, result


def _guess_project_key(ctx: ProgramContext) -> str:
    for tool in ctx.tools:
        if "proj" in tool.lower():
            parts = tool.split("-")
            for p in parts:
                if p.isupper() and 2 <= len(p) <= 6:
                    return p
    if ctx.program_name:
        return "".join(w[0] for w in ctx.program_name.split()[:3]).upper()[:4] or "PM"
    return "PM"


def _build_jira_preview(work_type: WorkItemType, fields: WorkItemFields) -> dict[str, Any]:
    return {
        "issue_type": fields.issue_type or WORK_ITEM_LABELS[work_type],
        "summary": fields.summary,
        "description": fields.description,
        "project_key": fields.project_key,
        "parent_key": fields.parent_key or None,
        "priority": fields.priority,
        "labels": fields.labels,
        "assignee": fields.assignee or None,
        "due_date": fields.due_date or None,
        "will_post": True,
    }
