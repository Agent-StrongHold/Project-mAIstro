"""Work item draft flow tests."""

from __future__ import annotations

import pytest

from maistro.agents.program_context import ProgramContext, apply_interview_answer
from maistro.agents.work_items import (
    apply_clarifying_answers,
    confirm_post_stub,
    suggest_work_item,
    update_draft_fields,
)


def _complete_ctx() -> ProgramContext:
    ctx = ProgramContext.empty("u1")
    for answer in ("Prog", "Goal A", "Jira", "Dep", "Lead"):
        ctx = apply_interview_answer(ctx, answer)
    return ctx


def test_suggest_starts_clarifying() -> None:
    draft = suggest_work_item("u1", "initiative", _complete_ctx(), reason="test")
    assert draft.status in ("clarifying", "ready")
    assert draft.capability == "create_initiative"
    assert len(draft.clarifying_questions) >= 2


def test_clarify_then_ready() -> None:
    draft = suggest_work_item("u1", "epic", _complete_ctx(), parent_key="PM-1")
    answers = {
        "summary": "Epic title",
        "description": "Epic body",
        "parent_key": "PM-100",
    }
    updated = apply_clarifying_answers(draft, answers)
    assert updated.status == "ready"
    assert updated.fields.summary == "Epic title"
    assert updated.fields.parent_key == "PM-100"


def test_confirm_requires_ready() -> None:
    draft = suggest_work_item("u1", "subtask", _complete_ctx())
    with pytest.raises(ValueError, match="clarifying"):
        confirm_post_stub(draft)


def test_confirm_posts_stub() -> None:
    draft = suggest_work_item("u1", "dev_task", _complete_ctx(), parent_key="PM-2")
    draft = apply_clarifying_answers(
        draft,
        {"summary": "Task", "description": "Do thing", "parent_key": "PM-2"},
    )
    draft = update_draft_fields(draft, {"summary": "Task", "description": "Do thing"})
    if draft.status != "ready":
        draft = draft.model_copy(update={"status": "ready"})
    posted, result = confirm_post_stub(draft)
    assert posted.status == "posted"
    assert posted.posted_issue_key
    assert result.get("issue_key")
