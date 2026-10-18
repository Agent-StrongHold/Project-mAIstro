"""Fence decisions — park / redirect / accept as HITL records on waiting work.

The closed design loop (ADR-092926-7a01) is interruptible at pack-declared
fence points. When the loop cannot proceed on its own, the Run sits in
canonical ``waiting`` — a durable human pause on a NodeRun (#48, #737) — and
the person's decision is one of exactly three verbs, recorded as a
:class:`FenceDecision` (the ADR's ``FenceDecision`` kind: canonical owner
``maistro.runs``, identity ``fence_decision_id``):

- **park** — hold the Run in ``waiting`` without resolution. Goal, Rubric,
  eval records, and artifacts stay exactly as they are; resumption is a later
  decision on the same Run. Park is not cancel (#48 cancel terminalizes) and
  park does not defer the #737 deadline: the persisted deadline remains the
  deadline, so a parked fence whose decision window elapses is still timed out
  by rule.
- **redirect** — change direction by naming exactly one target:
  ``goal`` (desired outcome → new Goal revision, which cascades to a new
  Rubric revision and a new CreativeBrief version against that revision),
  ``rubric`` (scoring → new Rubric revision against the *same* Goal revision),
  or ``brief`` (creative guidance → new CreativeBrief version against the
  *same* Goal revision and Rubric identity). A redirect that cannot say which
  of the three targets it moves is not a valid redirect — it is three requests
  and must be decomposed before commit. No history is rewritten: prior Runs,
  NodeRuns, Attempts, eval scores, and decision records keep the exact
  revisions they consumed.
- **accept** — close the fence: the cited Rubric revision passed at the cited
  Goal revision, or the human overrides a failing gate with recorded
  rationale. Accept never grants authorization: Capability/Binding still
  govern every external effect, and this module neither consults nor produces
  grants.

Fence decisions extend the #48 waiting-NodeRun paths; they do not replace
answer/timeout/cancel and they mint no second lifecycle, bus, or pause
runtime. A park/redirect/accept is only valid against a Run that is *already*
durably waiting on a HITL pause — there is no UI-only pause on this path: no
waiting NodeRun evidence, no fence decision.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FenceDecisionKind(StrEnum):
    """The three fence verbs (ADR-092926-7a01 §8). Exactly these."""

    PARK = "park"
    REDIRECT = "redirect"
    ACCEPT = "accept"


class FenceRedirectTarget(StrEnum):
    """The one thing a redirect moves. Mixing targets in one blob is a
    spec violation: decompose before commit."""

    GOAL = "goal"
    RUBRIC = "rubric"
    BRIEF = "brief"


class FenceError(ValueError):
    """Base class for invalid fence decisions."""


class FenceNotWaitingError(FenceError):
    """The Run is not durably waiting on a human pause, so no fence decision
    can be recorded against it. This is the UI-only-pause refusal: product
    state cannot substitute for the waiting NodeRun evidence."""


class FenceRedirectTargetRequired(FenceError):
    """A redirect must name exactly one of goal / rubric / brief."""


class FenceAcceptRequiresRationale(FenceError):
    """Accepting over a failing Rubric gate requires recorded human rationale."""


_REDIRECT_IMPLIED_FIELDS: dict[FenceRedirectTarget, tuple[str, ...]] = {
    # target -> the revision fields exactly that redirect must name
    FenceRedirectTarget.GOAL: ("new_goal_revision", "new_rubric_revision", "new_brief_version"),
    FenceRedirectTarget.RUBRIC: ("new_rubric_revision",),
    FenceRedirectTarget.BRIEF: ("new_brief_version",),
}


def _validate_redirect_coherence(self: FenceDecision) -> None:
    """A redirect names exactly the revisions its target implies — no more."""
    if self.redirect_target is None:
        raise FenceRedirectTargetRequired(
            "a fence redirect must name exactly one target: goal, rubric, or brief"
        )
    implied = _REDIRECT_IMPLIED_FIELDS[self.redirect_target]
    for field_name in ("new_goal_revision", "new_rubric_revision", "new_brief_version"):
        present = getattr(self, field_name) is not None
        if present and field_name not in implied:
            raise FenceError(f"redirect-{self.redirect_target.value} must not name {field_name}")
        if not present and field_name in implied:
            raise FenceError(f"redirect-{self.redirect_target.value} must name {field_name}")
    if self.gate_passed is not None or self.failing_dimensions:
        raise FenceError("a redirect decision carries no gate citation")
    if self.rationale:
        raise FenceError("a redirect decision carries no override rationale")


def _validate_accept(self: FenceDecision) -> None:
    """An accept cites the gate, and a failing gate carries a rationale."""
    if self.gate_passed is None:
        raise FenceError("an accept decision must cite the Rubric gate result")
    if self.failing_dimensions and not self.rationale.strip():
        raise FenceAcceptRequiresRationale(
            "accepting over a failing Rubric gate requires recorded human rationale"
        )


class FenceDecision(BaseModel):
    """One person's park / redirect / accept decision on a waiting fence.

    Append-only evidence on the Run's durable state: a decision is never
    edited or deleted, and each record names the Goal/Rubric revisions the
    Run was bound to *at decision time* plus the revisions the decision
    minted (redirect) or cited (accept). Historical decisions therefore
    keep answering "what did the Run consume when this was decided".
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    fence_decision_id: str = Field(default_factory=lambda: uuid4().hex)
    run_id: str
    node_id: str
    node_run_id: str
    decision: FenceDecisionKind
    #: The redirect target. Must be ``None`` for park/accept and set for
    #: redirect — the explicitness IS the contract (no mixed blobs).
    redirect_target: FenceRedirectTarget | None = None
    #: Binding at decision time (what the Run was consuming when fenced).
    goal_id: str
    goal_revision: int = Field(ge=1)
    rubric_id: str
    rubric_revision: int = Field(ge=1)
    #: Redirect results — exactly the fields the target implies, ``None``
    #: otherwise. ``new_goal_revision`` cascades: a Goal redirect also names
    #: the Rubric revision re-bound onto it and the CreativeBrief version
    #: re-projected onto it.
    new_goal_revision: int | None = Field(default=None, ge=1)
    new_rubric_revision: int | None = Field(default=None, ge=1)
    new_brief_version: int | None = Field(default=None, ge=1)
    #: Accept citation: which Rubric revision the accept closes the loop with,
    #: and what the eval evidence said. ``failing_dimensions`` non-empty means
    #: the human is overriding a failing gate.
    gate_passed: bool | None = None
    failing_dimensions: tuple[str, ...] = Field(default_factory=tuple)
    #: Required, non-empty, when accepting over a failing gate. Recorded, not
    #: interpreted — the rationale is audit evidence for the override.
    rationale: str = ""
    decided_by: str
    decided_at: datetime

    @model_validator(mode="after")
    def _validate_decision(self) -> FenceDecision:
        if self.decision is FenceDecisionKind.REDIRECT:
            _validate_redirect_coherence(self)
            return self

        if self.redirect_target is not None:
            raise FenceError(f"a {self.decision.value} decision has no redirect target")
        if any(
            (
                self.new_goal_revision is not None,
                self.new_rubric_revision is not None,
                self.new_brief_version is not None,
            )
        ):
            raise FenceError(f"a {self.decision.value} decision mints no revisions")

        if self.decision is FenceDecisionKind.ACCEPT:
            _validate_accept(self)
        return self


def goal_revision_at_least(current: int, *, step: int = 1) -> int:
    """The next Goal revision for a redirect-goal — lineage moves forward."""
    if current < 1 or step < 1:
        raise ValueError("goal revisions advance from 1 in steps of at least 1")
    return current + step


def brief_version_at_least(current: int, *, step: int = 1) -> int:
    """The next CreativeBrief version for a redirect-brief / redirect-goal."""
    if current < 1 or step < 1:
        raise ValueError("brief versions advance from 1 in steps of at least 1")
    return current + step


def normalize_decision_time(at: datetime | None) -> datetime:
    """Normalize the decision clock; naive timestamps are refused."""
    moment = at if at is not None else datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("fence decision time must include a timezone")
    return moment.astimezone(UTC)


__all__ = [
    "FenceAcceptRequiresRationale",
    "FenceDecision",
    "FenceDecisionKind",
    "FenceError",
    "FenceNotWaitingError",
    "FenceRedirectTarget",
    "FenceRedirectTargetRequired",
    "brief_version_at_least",
    "goal_revision_at_least",
    "normalize_decision_time",
]
