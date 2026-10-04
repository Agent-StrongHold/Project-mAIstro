"""Learning lifecycle: the knowledge-stage ladder and the row dynamics.

Two complementary halves, one module.

*The knowledge-stage ladder* (M4-B1 / ADR-103): MEMORY -> LEARNING ->
VALIDATED -> REPERTOIRE as fields on the one ``Learning`` record, with
forward-only, single-step, actor-attributed transitions recorded as
:class:`StageTransition` audit rows. The ladder is deliberately *not* a
runtime, a scheduler, or an execution authority: nothing here reads or
writes capabilities, permissions, grants, or graph authority, and the
Sentinel never consults a stage (ADR-103). One reconciliation the merged
tree makes explicit: ``MEMORY`` names the episodic source tier the ladder
starts from -- per ADR-100126-9a4b a ``Learning`` row never *carries* it.
Every stored learning enters the ladder at ``LEARNING`` (the extracted
claim), so the rung between remembered evidence and claim is walked by
extraction, not by an unpromoted ``MEMORY``-stage row nothing advances.

*The row dynamics* (ADR-100126-9a4b / EPIC M4-B #118-#121): the pure
transition, decay, supersession and consolidation rules a learning's
evidence follows -- reinforce, contradict, decay toward the epistemic
floor, supersede, absorb, and the measured effectiveness a Gauntlet weighs
(#118). The stores apply these functions to their rows; nothing here
reaches into a store.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

from maistro.types.memory import (
    ANTI_PATTERN_CONFIDENCE_FLOOR,
    ANTI_PATTERN_HALF_LIFE_DAYS,
    CONTRADICT_DELTA,
    EMPIRICAL_HALF_LIFE_DAYS,
    LEARNING_STAGE_ORDER,
    REINFORCE_DELTA,
    VALIDATED_CONFIDENCE_FLOOR,
    EpistemicType,
    Learning,
    LearningStage,
)

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


@dataclasses.dataclass(frozen=True)
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


def _require_next_rung(learning: Learning, to_stage: LearningStage) -> LearningStage:
    """Return the current stage once ``to_stage`` is proven exactly one rung above.

    Raises :class:`InvalidStageTransition` for an unknown current stage, a
    backward move, or a skip. Split from :func:`plan_advance` so the rule
    stays one readable paragraph and the planner stays a short composition of
    check -> replace -> stamp -> record.
    """
    current = learning.stage
    if current not in LEARNING_STAGE_ORDER:
        raise InvalidStageTransition(
            f"learning #{learning.id} carries an unknown stage {current!r}; "
            "refusing to build on a value the ladder does not define"
        )
    expected_next = LEARNING_STAGE_ORDER[current] + 1
    target = LEARNING_STAGE_ORDER[to_stage]
    if target == expected_next:
        return current
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
    - reaching ``VALIDATED`` stamps ``validated_by``/``validated_at`` and
      lifts confidence to the validation floor (ADR-100126-9a4b: a validated
      learning cannot sit below the floor its Gauntlet acceptance earned);
      reaching ``REPERTOIRE`` stamps ``promoted_by`` and flips ``status`` to
      ``promoted``.
    """
    if not isinstance(to_stage, LearningStage):
        raise InvalidStageTransition(
            f"unknown learning stage: {to_stage!r} (expected a LearningStage)"
        )
    if not actor or not actor.strip():
        raise InvalidStageTransition(
            "a stage transition must name its actor; anonymous provenance is no provenance"
        )

    current = _require_next_rung(learning, to_stage)

    updated = dataclasses.replace(learning, stage=to_stage)
    if to_stage is LearningStage.VALIDATED:
        updated.validated_by = actor
        updated.validated_at = datetime.now(UTC)
        updated.confidence = max(updated.confidence, VALIDATED_CONFIDENCE_FLOOR)
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


#: Row statuses that retire a learning from the live working set. Retired rows
#: are still readable -- institutional knowledge is retained, never deleted --
#: but they no longer decay (their confidence is historical record) and they
#: are skipped by consolidation sweeps.
TERMINAL_ROW_STATUSES: tuple[str, ...] = ("superseded", "consolidated")


def confidence_floor(learning: Learning) -> float:
    """The lowest confidence this learning's epistemic type may decay to.

    Failure knowledge is structurally unforgettable, mirroring the episodic
    REGRET tier: an anti-pattern cost a real failure to learn, so a
    contradiction of it lowers confidence only to
    ``ANTI_PATTERN_CONFIDENCE_FLOOR``, never through it.
    """
    if learning.epistemic_type is EpistemicType.ANTI_PATTERN:
        return ANTI_PATTERN_CONFIDENCE_FLOOR
    return 0.0


def half_life_for(learning: Learning) -> float:
    """Decay half-life in days for this learning's epistemic type."""
    if learning.epistemic_type is EpistemicType.ANTI_PATTERN:
        return ANTI_PATTERN_HALF_LIFE_DAYS
    return EMPIRICAL_HALF_LIFE_DAYS


def reinforce(
    learning: Learning,
    delta: float = REINFORCE_DELTA,
    *,
    now: datetime | None = None,
) -> Learning:
    """Reinforce in place: later Runs confirmed the correction helped."""
    learning.reinforcement_count += 1
    learning.confidence = min(1.0, learning.confidence + delta)
    learning.last_confirmed_at = now or datetime.now(UTC)
    return learning


def contradict(learning: Learning, delta: float = CONTRADICT_DELTA) -> Learning:
    """Contradict in place: a later Run showed the correction wrong.

    Confidence falls toward the epistemic floor, never through it; the count
    is kept so a Gauntlet can weigh contradictions against reinforcements.
    """
    learning.contradiction_count += 1
    learning.confidence = max(confidence_floor(learning), learning.confidence - delta)
    return learning


def decay(
    learning: Learning,
    *,
    now: datetime,
    half_life_days: float | None = None,
) -> Learning:
    """Exponential confidence decay toward the epistemic floor.

    The clock anchors at ``last_confirmed_at`` when set, else ``created_at``:
    a learning a later Run just re-confirmed does not decay from its birth
    instant. Anti-patterns decay on the slow clock (120-day half-life versus
    30) because failure knowledge is the expensive kind.
    """
    anchor = learning.last_confirmed_at or learning.created_at
    elapsed_days = (now - anchor).total_seconds() / 86_400.0
    if elapsed_days <= 0:
        return learning
    half_life = half_life_days if half_life_days is not None else half_life_for(learning)
    floor = confidence_floor(learning)
    learning.confidence = floor + (learning.confidence - floor) * (
        0.5 ** (elapsed_days / half_life)
    )
    return learning


def advance_stage(
    learning: Learning,
    to_stage: LearningStage,
    *,
    now: datetime | None = None,
    gauntlet_name: str = "",
) -> Learning:
    """Move a learning one step down the pipeline ladder, forward only.

    ``MEMORY`` is the source tier and never a destination; steps cannot be
    skipped (a learning must be VALIDATED before it can reach REPERTOIRE) and
    cannot run backwards (un-validating is supersession, not a transition).
    Reaching VALIDATED records the Gauntlet provenance and lifts confidence to
    the validation floor; reaching REPERTOIRE flips the row status to
    ``promoted`` so existing promoted-only readers see it.

    This is the in-place variant the Gauntlet/promoter path uses on rows it
    already holds. :func:`plan_advance` is the actor-attributed store-path
    variant that also produces the audit :class:`StageTransition`; the two
    enforce the same ladder rules and stamp the same fields.
    """
    if to_stage is LearningStage.MEMORY:
        raise ValueError("MEMORY is the source tier; a Learning never carries it")
    current = LEARNING_STAGE_ORDER.get(learning.stage, LEARNING_STAGE_ORDER[LearningStage.LEARNING])
    target = LEARNING_STAGE_ORDER[to_stage]
    if target <= current:
        raise ValueError(f"stage only moves forward: {learning.stage} -> {to_stage}")
    if target > current + 1:
        raise ValueError(f"stage cannot skip: {learning.stage} -> {to_stage} (validate first)")
    learning.stage = to_stage
    if to_stage is LearningStage.VALIDATED:
        learning.validated_by = gauntlet_name
        learning.validated_at = now or datetime.now(UTC)
        learning.confidence = max(learning.confidence, VALIDATED_CONFIDENCE_FLOOR)
    if to_stage is LearningStage.REPERTOIRE:
        learning.status = "promoted"
    return learning


def commit_to_repertoire(learning: Learning, *, now: datetime | None = None) -> Learning:
    """The one door into the collective repertoire: through VALIDATED."""
    return advance_stage(learning, LearningStage.REPERTOIRE, now=now)


def supersede(old: Learning, new: Learning) -> Learning:
    """Retire ``old`` in favour of the already-stored ``new``, keeping both rows.

    A superseded learning is not deleted: ``supersedes``/``superseded_by`` name
    the lineage in both directions, so later Runs can still ask what used to be
    believed and which row replaced it.
    """
    if old.id is None or new.id is None:
        raise ValueError("supersession needs both rows already stored")
    new.supersedes = old.id
    old.superseded_by = new.id
    old.status = "superseded"
    return new


def absorb(survivor: Learning, absorbed: Learning) -> Learning:
    """Fold a consolidated duplicate's evidence into its survivor.

    The survivor inherits the union of trigger keys and the summed outcome
    counters -- the evidence belongs to the knowledge, not to whichever
    duplicate happened to hold it -- and the greater confidence. The absorbed
    row is retired as ``consolidated`` and points at its survivor.
    """
    survivor.trigger_keys = sorted(set(survivor.trigger_keys) | set(absorbed.trigger_keys))
    survivor.hit_count += absorbed.hit_count
    survivor.success_after_use += absorbed.success_after_use
    survivor.failure_after_use += absorbed.failure_after_use
    survivor.reinforcement_count += absorbed.reinforcement_count
    survivor.contradiction_count += absorbed.contradiction_count
    survivor.confidence = max(survivor.confidence, absorbed.confidence)
    absorbed.status = "consolidated"
    absorbed.superseded_by = survivor.id
    return survivor


def effectiveness(learning: Learning) -> float | None:
    """Measured effect on later Runs: (successes - failures) / uses.

    ``None`` when no later Run has used the learning yet: zero uses is "no
    measurement", not "no effect", and conflating the two would let an
    unmeasured learning pass as a neutral one.
    """
    uses = learning.success_after_use + learning.failure_after_use
    if uses == 0:
        return None
    return (learning.success_after_use - learning.failure_after_use) / uses


def trigger_key_overlap(a: list[str], b: list[str]) -> float:
    """Jaccard overlap of two trigger-key lists: the shared dedup/merge rule."""
    keys_a, keys_b = set(a), set(b)
    union = keys_a | keys_b
    if not union:
        return 0.0
    return len(keys_a & keys_b) / len(union)
