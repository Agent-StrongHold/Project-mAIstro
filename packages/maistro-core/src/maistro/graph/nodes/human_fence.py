"""`human.fence_decision` — the loop's park/redirect/accept gate (M7-A5).

A pack declares *where* its fences sit (`fence_points`, `pack.fenced` nodes —
#793); the loop runtime places this node at those points and it owns *how* the
fence waits: a durable human pause on a waiting NodeRun (#48, #737), decided
through the canonical store's `park_hitl` / `redirect_hitl` / `accept_hitl`.

The node is deliberately thin. It carries the fence's identity — the pack
fence point and the Goal/Rubric revisions the loop is consuming — into the
durable pause metadata, and on resume reports the recorded decision
downstream. It is not a second HITL bus and holds no state of its own: a
park keeps the pause (the node simply never resumes), and a redirect/accept
arrives exactly like any other human answer, stamped with the decision
written by the store.

Fail closed (#329 / ADR-090726-9a4e): only an answer the store *stamped* as
a recorded fence decision (`fence_decision: True`, written by the settlement
methods) may be read as a verdict. The plain answer path copies
caller-supplied keys verbatim — a resume payload naming its own `decision`
is a claim, not evidence, and leaves the fence pending rather than
interpreting the claim as a verdict.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from . import register_node
from .base import (
    PAUSE_AWAITING_HUMAN_DECISION,
    BaseNode,
    NodeContext,
    ReplaySemantics,
    hitl_resume_at,
    pause_until,
)


class FenceDecisionIn(BaseModel):
    fence_point: str = Field(
        description="The pack-declared fence point this gate sits at, e.g. evaluate.accept"
    )
    goal_id: str = Field(description="The Goal the loop consumes")
    goal_revision: int = Field(ge=1, description="The Goal revision the loop consumes")
    rubric_id: str = Field(description="The Rubric the loop scores against")
    rubric_revision: int = Field(ge=1, description="The Rubric revision the loop scores against")
    brief_version: int = Field(default=1, ge=1, description="The CreativeBrief version in force")
    timeout_seconds: int = Field(default=86_400)


class FenceDecisionOut(BaseModel):
    decision: str = "parked"
    redirect_target: str | None = None
    new_goal_revision: int | None = None
    new_rubric_revision: int | None = None
    new_brief_version: int | None = None
    gate_passed: bool | None = None
    failing_dimensions: list[str] = Field(default_factory=list)
    rationale: str = ""


def _hitl_answers(ctx: NodeContext) -> Mapping[str, Any]:
    """The recorded human answers this run carries, or none.

    A malformed metadata payload is treated as "no answer yet" rather than a
    crash: the fence must fail closed pending, never fail open on whatever a
    resume payload happens to carry.
    """
    answers = (ctx.metadata or {}).get("hitl_answers") or {}
    return answers if isinstance(answers, Mapping) else {}


@register_node  # noqa: V102 — instantiated by kind dispatch ("human.fence_decision"), not by name
class HumanFenceDecisionNode(BaseNode[FenceDecisionIn, FenceDecisionOut]):
    kind: ClassVar[str] = "human.fence_decision"
    kind_category: ClassVar = "hitl"
    input_schema: ClassVar[type[BaseModel]] = FenceDecisionIn
    output_schema: ClassVar[type[BaseModel]] = FenceDecisionOut
    cost_hint: ClassVar[float] = 0.0
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.EFFECT_KEY
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Human: design-loop fence (park / redirect / accept)"
    description: ClassVar[str] = (
        "Pause the loop at a pack-declared fence until a person parks, "
        "redirects (goal / rubric / brief), or accepts. Downstream nodes "
        "branch on the recorded decision."
    )

    async def _execute(self, inputs: FenceDecisionIn, ctx: NodeContext) -> FenceDecisionOut:
        resumed = _hitl_answers(ctx).get(ctx.node_id)
        if isinstance(resumed, Mapping):
            decision = resumed.get("decision")
            # Fail closed: only an answer stamped by the store's settlement
            # methods (`fence_decision: True`) is a recorded decision. The
            # plain answer path copies caller keys verbatim, so a bare
            # `decision` key is the answerer's claim — the store refuses it
            # at the pause, and this guard keeps the node honest even if such
            # a payload reaches durable state another way (e.g. persisted for
            # audit beside an expiry tick).
            if (
                resumed.get("fence_decision") is True
                and isinstance(decision, str)
                and decision.strip()
            ):
                redirect_target = resumed.get("redirect_target")
                return FenceDecisionOut(
                    decision=decision,
                    redirect_target=(
                        str(redirect_target) if isinstance(redirect_target, str) else None
                    ),
                    new_goal_revision=_optional_int(resumed.get("new_goal_revision")),
                    new_rubric_revision=_optional_int(resumed.get("new_rubric_revision")),
                    new_brief_version=_optional_int(resumed.get("new_brief_version")),
                    gate_passed=_optional_bool(resumed.get("gate_passed")),
                    failing_dimensions=[
                        str(dim) for dim in (resumed.get("failing_dimensions") or [])
                    ],
                    rationale=str(resumed.get("rationale") or ""),
                )

        resume_at = hitl_resume_at(ctx, inputs.timeout_seconds, resumed=resumed)
        pause_until(
            PAUSE_AWAITING_HUMAN_DECISION,
            resume_at=resume_at,
            metadata={
                "fence_point": inputs.fence_point,
                "goal_id": inputs.goal_id,
                "goal_revision": inputs.goal_revision,
                "rubric_id": inputs.rubric_id,
                "rubric_revision": inputs.rubric_revision,
                "brief_version": inputs.brief_version,
                "timeout_seconds": inputs.timeout_seconds,
            },
        )
        return FenceDecisionOut()  # unreachable


def _optional_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None
