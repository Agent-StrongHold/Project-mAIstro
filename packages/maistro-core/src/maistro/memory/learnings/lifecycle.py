"""Knowledge-stage lifecycle for learnings (M4-B1 / ADR-103).

The semantics this module enforces, and nothing more:

- ``MEMORY`` — execution/agent-local remembered evidence/context. Every newly
  stored learning starts here; the producing Run is already named by the
  provenance columns (#709).
- ``LEARNING`` — a claim inferred from that evidence.
- ``VALIDATED`` — a claim that survived independent evaluation. The evaluator
  is recorded on the row (``validated_by``) and in the transition ledger; the
  *independence* of the evaluator is a duty of the caller, not something a
  stage value can prove.
- ``REPERTOIRE`` — validated learning explicitly promoted for reuse. The
  promotion flips ``status`` to ``promoted`` so every existing promoted-only
  reader (``get_promoted``, prompt injection) keeps working unchanged.

This is deliberately *not* a runtime, a scheduler, or an execution authority.
The ladder lives as fields on the one ``Learning`` record and transitions on
the existing learning stores; nothing here reads or writes capabilities,
permissions, grants, or graph authority. A knowledge stage is metadata about
how a claim came to be believed — the Sentinel never consults it (ADR-103).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from maistro.types.memory import LEARNING_STAGE_ORDER, Learning, LearningStage

#: Inverse of ``LEARNING_STAGE_ORDER``: rank back to stage, for naming the
#: expected next rung in rejection messages.
_STAGE_BY_RANK: dict[int, LearningStage] = {
    rank: stage for stage, rank in LEARNING_STAGE_ORDER.items()
}

__all__ = [
    "InvalidStageTransition",
    "StageTransition",
    "plan_advance",
]


class InvalidStageTransition(ValueError):
    """A stage transition that the ladder forbids was attempted.

    Raised for unknown stages, backward moves, skips, and promotions that
    name no actor. The store surfaces it to the caller instead of silently
    keeping or half-applying the move: a transition that did not happen must
    not appear in the audit ledger, and a transition that did must not be
    deniable.
    """


@dataclass(frozen=True)
class StageTransition:
    """One durable, auditable ladder transition.

    ``actor`` names whoever or whatever performed the transition (an
    evaluator id for VALIDATED, a promotion actor for REPERTOIRE). ``reason``
    is free text for the audit ledger. Rows are append-only: the ledger is
    the provenance of how a claim came to be believed.
    """

    learning_id: int | None
    org_id: str
    from_stage: LearningStage
    to_stage: LearningStage
    actor: str
    reason: str = ""


def plan_advance(
    learning: Learning,
    *,
    to_stage: LearningStage,
    actor: str,
    reason: str = "",
) -> tuple[Learning, StageTransition]:
    """Validate one ladder step and return the updated Learning plus its record.

    Pure: no store, no I/O. The stores call this and then persist both the
    row update and the ledger row, so the in-memory, SQLite and PostgreSQL
    backends cannot drift on the rules.

    Rules (ADR-103):

    - forward-only: ``to_stage`` must sit exactly one rung above the current
      stage. Backward moves and skips raise ``InvalidStageTransition`` — a
      demotion would rewrite history the ledger already recorded, and a skip
      would let a claim reach the repertoire without the rung that gives the
      promotion its meaning.
    - ``actor`` is required for every transition: provenance without an actor
      is not provenance.
    - reaching ``VALIDATED`` stamps ``validated_by``; reaching ``REPERTOIRE``
      stamps ``promoted_by`` and flips ``status`` to ``promoted``.
    """
    if not isinstance(to_stage, LearningStage):
        raise InvalidStageTransition(
            f"unknown learning stage: {to_stage!r} (expected a LearningStage)"
        )
    if not actor or not actor.strip():
        raise InvalidStageTransition(
            "a stage transition must name its actor; anonymous provenance is no provenance"
        )

    current = learning.stage
    if current not in LEARNING_STAGE_ORDER:
        raise InvalidStageTransition(
            f"learning #{learning.id} carries an unknown stage {current!r}; "
            "refusing to build on a value the ladder does not define"
        )
    expected_next = LEARNING_STAGE_ORDER[current] + 1
    target = LEARNING_STAGE_ORDER[to_stage]
    if target != expected_next:
        if target < LEARNING_STAGE_ORDER[current]:
            raise InvalidStageTransition(
                f"cannot advance learning #{learning.id} from {current} to {to_stage}: "
                "transitions are forward-only; the ladder never demotes"
            )
        if expected_next in _STAGE_BY_RANK:
            raise InvalidStageTransition(
                f"cannot advance learning #{learning.id} from {current} to {to_stage}: "
                "transitions are forward-only and single-step "
                f"(expected {_STAGE_BY_RANK[expected_next]})"
            )
        raise InvalidStageTransition(
            f"cannot advance learning #{learning.id} from {current} to {to_stage}: "
            f"{current} is the top of the ladder"
        )

    updated = dataclasses.replace(learning, stage=to_stage)
    if to_stage is LearningStage.VALIDATED:
        updated.validated_by = actor
    elif to_stage is LearningStage.REPERTOIRE:
        updated.promoted_by = actor
        # The one behavioural promotion side effect: promoted-only readers
        # (`get_promoted`, prompt injection) select on `status`, so a
        # repertoire commit that did not flip it would promote nothing.
        updated.status = "promoted"

    transition = StageTransition(
        learning_id=learning.id,
        org_id=learning.org_id or "",
        from_stage=current,
        to_stage=to_stage,
        actor=actor,
        reason=reason,
    )
    return updated, transition
