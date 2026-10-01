"""Learning pipeline lifecycle: Memory -> Learning -> Validated -> Repertoire.

ADR-092 / EPIC M4-B. A learning extracted from memory is local belief; it
becomes validated knowledge only when an independent Gauntlet accepts the
outcome evidence later Runs recorded (#118), and joins the collective
repertoire only after that (#117). This module holds the pure transition,
decay, supersession and consolidation rules (#120). The stores apply them;
nothing here reaches into a store.
"""

from __future__ import annotations

from datetime import UTC, datetime

from maistro.types.memory import (
    ANTI_PATTERN_CONFIDENCE_FLOOR,
    ANTI_PATTERN_HALF_LIFE_DAYS,
    CONTRADICT_DELTA,
    EMPIRICAL_HALF_LIFE_DAYS,
    REINFORCE_DELTA,
    VALIDATED_CONFIDENCE_FLOOR,
    EpistemicType,
    Learning,
    LearningStage,
)

#: Row statuses that retire a learning from the live working set. Retired rows
#: are still readable -- institutional knowledge is retained, never deleted --
#: but they no longer decay (their confidence is historical record) and they
#: are skipped by consolidation sweeps.
TERMINAL_ROW_STATUSES: tuple[str, ...] = ("superseded", "consolidated")

_STAGE_ORDER: dict[LearningStage, int] = {
    LearningStage.MEMORY: 0,
    LearningStage.LEARNING: 1,
    LearningStage.VALIDATED: 2,
    LearningStage.REPERTOIRE: 3,
}


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
    """
    if to_stage is LearningStage.MEMORY:
        raise ValueError("MEMORY is the source tier; a Learning never carries it")
    current = _STAGE_ORDER.get(learning.stage, _STAGE_ORDER[LearningStage.LEARNING])
    target = _STAGE_ORDER[to_stage]
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
