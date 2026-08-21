"""`human.approve_draft` — pause until the user approves/rejects a draft.

A specialization of human.ask_question with three fixed outcomes
(approve / reject / modify) and a structured `draft` payload so downstream
nodes can branch on the verdict.

This is the node form of the "draft → confirm" gate baked into the Phase 1
PM-fleet flow (Jira ticket drafts have to be approved by a human before
they're posted).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from . import register_node
from .base import BaseNode, NodeContext, now_utc, pause_until


class ApproveDraftIn(BaseModel):
    draft: dict[str, Any] = Field(description="The draft object to review")
    draft_kind: str = Field(
        default="generic",
        description="jira_ticket | confluence_page | email | release_note | generic",
    )
    title: str = Field(default="", description="Short label for the draft (UI heading)")
    timeout_seconds: int = Field(default=86_400)


class ApproveDraftOut(BaseModel):
    verdict: Literal["approved", "rejected", "modified", "timed_out"] = "approved"
    modified_draft: dict[str, Any] | None = None
    reviewer_note: str = ""
    timed_out: bool = False


@register_node
class HumanApproveDraftNode(BaseNode[ApproveDraftIn, ApproveDraftOut]):
    kind: ClassVar[str] = "human.approve_draft"
    kind_category: ClassVar = "hitl"
    input_schema: ClassVar[type[BaseModel]] = ApproveDraftIn
    output_schema: ClassVar[type[BaseModel]] = ApproveDraftOut
    cost_hint: ClassVar[float] = 0.0
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Human: approve a draft"
    description: ClassVar[str] = (
        "Pause and surface a draft (Jira ticket, release note, etc.) for "
        "human review. Downstream branches on approved/rejected/modified."
    )

    async def _execute(self, inputs: ApproveDraftIn, ctx: NodeContext) -> ApproveDraftOut:
        answers = (ctx.metadata or {}).get("hitl_answers") or {}
        resumed = answers.get(ctx.node_id)
        if resumed is not None:
            verdict = resumed.get("verdict", "approved")
            return ApproveDraftOut(
                verdict=verdict,
                modified_draft=resumed.get("modified_draft"),
                reviewer_note=str(resumed.get("reviewer_note") or ""),
                timed_out=bool(resumed.get("timed_out", False)),
            )

        resume_at = now_utc() + timedelta(seconds=inputs.timeout_seconds)
        pause_until(
            "awaiting_human_approval",
            resume_at=resume_at,
            metadata={
                "draft": inputs.draft,
                "draft_kind": inputs.draft_kind,
                "title": inputs.title,
                "timeout_seconds": inputs.timeout_seconds,
            },
        )
        return ApproveDraftOut()  # unreachable
