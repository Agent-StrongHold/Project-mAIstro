"""Promotion evidence rules for learnings (M4-B3 / ADR-100126-b3c7).

One home for the answer to "may this learning be promoted?". A learning is a
claim the system interpolates into future prompts and skill mutations; the
promoter gate, the store twins' `check_auto_promotions` and the approval UI all
need the same verdict, and each keeping its own copy is how the backends
drifted before (`learning_scope`, `learning_contract` exist for the same
reason).

The rule is evidence-based, not plausibility-based: an LLM may *distill* the
text of a learning, but distillation is a claim about evidence, never evidence
itself. Only a source Run id or an evaluation record can qualify a learning for
promotion.
"""

from __future__ import annotations

from maistro.types.memory import EpistemicType, Learning

#: Minimum measured confidence for promotion. A learning promoted on a
#: majority-failing evidence base would be a regression engine, so the floor is
#: a strict majority of recorded outcomes in favour.
DEFAULT_MIN_PROMOTION_CONFIDENCE = 0.5

_EVIDENCE_SOURCES = ("run_id", "evidence_run_ids", "evaluation_ids")


def has_source_evidence(learning: Learning) -> bool:
    """True when the learning names at least one source Run or evaluation.

    The producer provenance (`run_id`, #709) counts: a learning stored inside a
    real execution names it, and that execution's outcome is evidence. The
    consolidated lists count because they survive rewording — that is the point
    of keeping them.
    """
    return bool(learning.run_id or learning.evidence_run_ids or learning.evaluation_ids)


def outcome_confidence(success: int, failure: int) -> float | None:
    """Empirical evidence strength from outcome counters; `None` before any outcome.

    The normative rule the SQL twins restate in their `mark_outcome` UPDATE:
    measured outcomes replace whatever prior an imported claim arrived with,
    because a measurement outranks a report.
    """
    total = success + failure
    if total == 0:
        return None
    return success / total


def promotion_blockers(
    learning: Learning,
    *,
    min_confidence: float = DEFAULT_MIN_PROMOTION_CONFIDENCE,
) -> list[str]:
    """Why this learning may not be promoted yet; empty when it may.

    The whole gate in one function so the verdict cannot differ between the
    in-memory store, the SQL twins and the promoter:

    - source Run/evaluation IDs are required — hit_count only says the text was
      *retrieved*, not that it was *right*;
    - confidence must be measured and strictly above `min_confidence` — an
      exactly-at-floor evidence base is tied, not majority-positive, so it is a
      blocker, not a pass; unmeasured is a blocker too;
    - a COUNTERFACTUAL claim additionally needs an evaluation: "it would have
      worked" is exactly the claim only an evaluation can test, and an INFERRED
      (LLM-distilled) claim still needs ordinary validation evidence —
      distillation shapes the wording, never the warrant.
    """
    blockers: list[str] = []
    if not has_source_evidence(learning):
        blockers.append("no_source_run_or_evaluation_ids")
    if learning.confidence is None:
        blockers.append("confidence_unmeasured")
    elif learning.confidence <= min_confidence:
        blockers.append("confidence_below_threshold")
    if learning.epistemic_type == EpistemicType.COUNTERFACTUAL and not learning.evaluation_ids:
        blockers.append("counterfactual_without_evaluation")
    return blockers


def merge_applicability(existing: Learning, incoming: Learning) -> None:
    """Fold `incoming`'s applicability and evidence into `existing`, in place.

    The consolidation half of M4-B3: dedup and rewording replace *what a row
    says*, and must never replace *what it rests on*. Applicability lists union
    (a reworded claim keeps every context any of its versions named), evidence
    ids union (the surviving text stays accountable to every Run that taught
    it), and confidence keeps the strongest measured value. The incoming
    producer (`incoming.run_id`) folds into the evidence list whenever it is
    not already the surviving row's producer — the SQL twins' dedup keeps the
    original producer on the row, and the Run that supplied the reworded text
    must still be answerable. `existing.run_id` itself is *not* touched here —
    each store's dedup path already owns that decision (#709).
    """
    existing.works_when = _union(existing.works_when, incoming.works_when)
    existing.avoid_in = _union(existing.avoid_in, incoming.avoid_in)
    extra_runs = list(incoming.evidence_run_ids)
    if incoming.run_id and incoming.run_id != existing.run_id:
        extra_runs.append(incoming.run_id)
    existing.evidence_run_ids = _union(existing.evidence_run_ids, extra_runs)
    existing.evaluation_ids = _union(existing.evaluation_ids, incoming.evaluation_ids)
    measured = outcome_confidence(existing.success_after_use, existing.failure_after_use)
    if measured is not None:
        # A measurement outranks a report: an incoming prior (REPORTED or any
        # other unvalidated claim) must not raise a confidence the outcome
        # counters paid for, or a mostly-failing row could ride a 0.9 prior
        # through the promotion gate. Restate the ratio so the row cannot
        # drift from its counters, matching the stores' `mark_outcome`.
        existing.confidence = measured
    elif incoming.confidence is not None:
        existing.confidence = (
            incoming.confidence
            if existing.confidence is None
            else max(existing.confidence, incoming.confidence)
        )


def _union(current: list[str], extra: list[str]) -> list[str]:
    """Order-preserving union; blank entries are noise, not context."""
    seen = set(current)
    for item in extra:
        if item and item not in seen:
            seen.add(item)
            current.append(item)
    return current
