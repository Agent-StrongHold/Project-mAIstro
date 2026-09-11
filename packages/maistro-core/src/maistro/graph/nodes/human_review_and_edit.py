"""`human.review_and_edit` — pause until the user redlines a structured payload.

Generalizes `human.approve_draft`'s binary approve/reject/modify verdict into
a structured diff: the human can supply a list of field-level edits instead
of (or alongside) a flat replacement blob. Used for "redline a contract /
invoice" flows where the reviewer needs to call out specific field changes
rather than just swap in a whole new draft.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal, cast

from pydantic import BaseModel, Field

from . import register_node
from .base import (
    PAUSE_AWAITING_HUMAN_REVIEW,
    BaseNode,
    NodeContext,
    pause_until,
    preserved_hitl_deadline,
)


class FieldEdit(BaseModel):
    path: str = Field(description="Dotted path into the document, e.g. 'terms.price'")
    old_value: Any = None
    new_value: Any = None
    note: str = ""


class ReviewAndEditIn(BaseModel):
    document: dict[str, Any] = Field(description="The document to review")
    document_kind: str = Field(
        default="generic",
        description="contract | invoice | generic",
    )
    title: str = Field(default="", description="Short label for the document (UI heading)")
    timeout_seconds: int = Field(default=86_400)


ReviewAndEditVerdict = Literal["approved", "rejected", "edited", "timed_out"]


class ReviewAndEditOut(BaseModel):
    verdict: ReviewAndEditVerdict = "approved"
    edits: list[FieldEdit] = Field(default_factory=list)
    reviewer_note: str = ""
    timed_out: bool = False


@register_node
class HumanReviewAndEditNode(BaseNode[ReviewAndEditIn, ReviewAndEditOut]):
    kind: ClassVar[str] = "human.review_and_edit"
    kind_category: ClassVar = "hitl"
    input_schema: ClassVar[type[BaseModel]] = ReviewAndEditIn
    output_schema: ClassVar[type[BaseModel]] = ReviewAndEditOut
    cost_hint: ClassVar[float] = 0.0
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Human: review and edit"
    description: ClassVar[str] = (
        "Pause and surface a document (contract, invoice, etc.) for human "
        "redlining. Downstream branches on approved/rejected/edited, with a "
        "structured list of field-level edits when redlined."
    )

    async def _execute(self, inputs: ReviewAndEditIn, ctx: NodeContext) -> ReviewAndEditOut:
        answers = (ctx.metadata or {}).get("hitl_answers") or {}
        resumed = answers.get(ctx.node_id)
        if resumed is not None:
            # Fail closed (#329 / ADR-090726-9a4e): the same class of fix as
            # human.approve_draft — a missing, empty, or non-string verdict
            # key must not count as approval of the document under review; it
            # falls through to the pause below and the node stays pending.
            verdict = resumed.get("verdict")
            if isinstance(verdict, str) and verdict.strip():
                # `cast` states what pydantic still enforces at runtime: an
                # unknown verdict string fails the node rather than approving.
                raw_edits = resumed.get("edits") or []
                return ReviewAndEditOut(
                    verdict=cast(ReviewAndEditVerdict, verdict),
                    edits=[FieldEdit.model_validate(edit) for edit in raw_edits],
                    reviewer_note=str(resumed.get("reviewer_note") or ""),
                    timed_out=bool(resumed.get("timed_out", False)),
                )

        resume_at = preserved_hitl_deadline(resumed or {}, timeout_seconds=inputs.timeout_seconds)
        pause_until(
            PAUSE_AWAITING_HUMAN_REVIEW,
            resume_at=resume_at,
            metadata={
                "document": inputs.document,
                "document_kind": inputs.document_kind,
                "title": inputs.title,
                "timeout_seconds": inputs.timeout_seconds,
            },
        )
        return ReviewAndEditOut()  # unreachable
