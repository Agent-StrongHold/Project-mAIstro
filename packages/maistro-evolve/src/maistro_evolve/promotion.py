"""The one canonical candidate → independent evaluation → governed promotion
contract (#21, #854).

Every reusable activation decision — champion selection and promotion alike —
is derived from THIS module's policy, not from local booleans scattered across
``PopulationStore``/``EvolutionCycle``. The contract has three legs:

1. **Sufficient independent evidence.** A candidate is promotion-eligible only
   after each benchmark it scores carries at least ``min_samples_per_benchmark``
   independent samples (the production cycle's reconfirmation step —
   ``EvolutionCycle._reconfirm_candidates`` — is what actually produces repeat
   samples through the real ``Goal → Graph → Run`` cycle; the EMA fold in
   ``EvolutionCycle._fold_score`` is the declared statistical estimator, so a
   lucky first sample can never permanently determine fitness). Sample spread
   is bounded by ``max_sample_std``: evidence that swings between samples is
   noise, not evidence, and stays ineligible.

2. **Current, objective-bound evidence.** Every evaluation stamps the genome
   with the ``objective_version`` it was scored under (a deterministic digest
   of the benchmark set, the hard-gate thresholds, and the eval weights) and
   the ``evidence_cycle`` that produced it. Selection requires evidence within
   ``max_evidence_age_cycles`` of the current cycle; comparison requires
   candidate and incumbent to carry the SAME objective version — comparing
   scores measured under different objectives is meaningless, so it is refused
   rather than approximated. Freshness across cycles is the held-out property
   this contract declares: confirmation samples are taken by later, independent
   cycle evaluations, never by the same evaluation that selected the candidate.

3. **Explicit incumbent comparison.** Promotion never fires because it was
   called. The candidate must beat the current incumbent by at least
   ``min_promotion_margin`` under that shared objective — a worse or merely
   equal candidate is rejected with the reason recorded, no matter how late it
   was submitted.

On top of the shared eligibility legs, promotion additionally requires the
human approval gate (``approved_for_promotion`` — see ``PopulationStore._promote``)
and refuses candidates still pending fresh confirmation after a best-of-N
acceptance (the winner's-curse guard: a challenger that won a propose-then-verify
round against N siblings is exactly the candidate most likely to be a lucky
max, so it must gather post-acceptance samples before it can activate).
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from pydantic import BaseModel, Field

from .fitness import hard_gate_thresholds
from .types import EvalWeights, PipelineGenome

# harness_params keys that carry evaluation evidence. These live in
# ``harness_params`` (not as model fields) so serialized genomes written by
# older builds still load unchanged.
OBJECTIVE_VERSION_KEY = "objective_version"
EVIDENCE_CYCLE_KEY = "evidence_cycle"
SAMPLES_KEY = "eval_samples"
HISTORY_KEY = "eval_history"
BEST_OF_N_KEY = "best_of_n_pending"


def objective_version(
    target_benchmarks: list[str] | tuple[str, ...],
    weights: EvalWeights | None = None,
) -> str:
    """Deterministic identity of the evaluation objective.

    Two genomes may only be compared when their evidence was produced under the
    same objective. The objective is the immutable triple of (benchmarks
    scored, per-benchmark hard-gate thresholds, eval weights); its digest is
    stamped onto every evaluated genome so the promotion gate can enforce
    like-for-like comparison instead of trusting callers to keep the objective
    fixed.
    """
    payload = {
        "benchmarks": sorted(target_benchmarks),
        "gate_thresholds": hard_gate_thresholds(),
        "weights": (weights or EvalWeights()).model_dump(),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return f"objective-v1:{digest}"


class PromotionPolicy(BaseModel):
    """The declared evaluation/activation policy (#854 acceptance 1).

    Defaults are the contract; callers may tighten (never disable) the
    evidence requirements per deployment. Every field is part of the decision
    rule recorded with each promotion (see ``PromotionRecord.decision_rule``),
    so an activation can always be replayed against the policy that allowed it.
    """

    model_config = {"frozen": True}

    # Independent-evidence floor: each benchmark a candidate scores must carry
    # at least this many samples before the candidate may be selected as
    # champion or promoted. 1 would re-allow the lucky-first-sample defect.
    min_samples_per_benchmark: int = Field(default=2, ge=1)
    # A candidate must have been scored on at least this many benchmarks.
    min_benchmarks: int = Field(default=1, ge=1)
    # Uncertainty bound: with >=2 samples per benchmark, the population std of
    # a benchmark's sample history must not exceed this — evidence that swings
    # wider is nondeterminism, and selection on it is a lottery.
    max_sample_std: float = Field(default=0.2, gt=0.0)
    # Evidence currency: ``evidence_cycle`` must be within this many cycles of
    # the current cycle for the evidence to count as fresh. Stale evidence
    # must be re-confirmed by a new evaluation, never reused for activation.
    max_evidence_age_cycles: int = Field(default=10, ge=0)
    # Winner's-curse guard: a genome accepted by a best-of-N propose-then-verify
    # round (reflective_improve / hyper_mutate) stays promotion-ineligible until
    # it has gathered samples BEYOND the round that selected it.
    require_confirmation_after_best_of_n: bool = True
    # Declared margin: a candidate must exceed the incumbent's fitness by at
    # least this much, under the same objective version, to replace it.
    min_promotion_margin: float = Field(default=0.01, ge=0.0)
    # Objective versions whose evidence is accepted. Empty means "any recorded
    # version, but one MUST be recorded, and candidate/incumbent must match".
    # Pin a version to hard-fail evidence produced under a retired objective.
    objective_versions: tuple[str, ...] = ()


class EligibilityReport(BaseModel):
    """Why a genome is or is not eligible; every failure names its reason."""

    eligible: bool
    reasons: list[str] = []
    evidence: dict[str, Any] = {}


def _sample_std(values: list[float]) -> float:
    """Population std of a benchmark's sample history (0.0 for <2 samples)."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _evidence_summary(genome: PipelineGenome) -> dict[str, Any]:
    params = genome.harness_params
    return {
        "fitness_score": genome.fitness_score,
        "eval_scores": dict(genome.eval_scores),
        "eval_samples": dict(params.get(SAMPLES_KEY, {})),
        "objective_version": params.get(OBJECTIVE_VERSION_KEY),
        "evidence_cycle": params.get(EVIDENCE_CYCLE_KEY),
        "is_active": genome.is_active,
        "approved_for_promotion": genome.approved_for_promotion,
    }


def _sample_shortfalls(genome: PipelineGenome, policy: PromotionPolicy) -> list[str]:
    """Independent-evidence floor: enough samples on enough benchmarks."""
    reasons: list[str] = []
    samples: dict[str, int] = genome.harness_params.get(SAMPLES_KEY, {})
    for bench, score in sorted(genome.eval_scores.items()):
        n = samples.get(bench, 0)
        if n < policy.min_samples_per_benchmark:
            reasons.append(
                f"{bench}: {n} sample(s) < required "
                f"{policy.min_samples_per_benchmark} (score {score:.4f})"
            )
    if len(genome.eval_scores) < policy.min_benchmarks:
        reasons.append(
            f"scored on {len(genome.eval_scores)} benchmark(s) < required {policy.min_benchmarks}"
        )
    return reasons


def _uncertainty_breach(genome: PipelineGenome, policy: PromotionPolicy) -> list[str]:
    """Uncertainty bound: per-benchmark sample spread within policy."""
    reasons: list[str] = []
    history: dict[str, list[float]] = genome.harness_params.get(HISTORY_KEY, {})
    for bench in sorted(genome.eval_scores):
        values = history.get(bench, [])
        std = _sample_std(values)
        if len(values) >= 2 and std > policy.max_sample_std:
            reasons.append(
                f"{bench}: sample std {std:.4f} > uncertainty bound "
                f"{policy.max_sample_std} — evidence unstable"
            )
    return reasons


def _objective_stamp_violation(genome: PipelineGenome, policy: PromotionPolicy) -> list[str]:
    """Evidence must be stamped with (a pinned) objective version."""
    obj = genome.harness_params.get(OBJECTIVE_VERSION_KEY)
    if not obj:
        return ["evidence has no objective_version stamp"]
    if policy.objective_versions and obj not in policy.objective_versions:
        return [f"objective version {obj} not in policy-pinned {list(policy.objective_versions)}"]
    return []


def _evidence_age_violation(
    genome: PipelineGenome, policy: PromotionPolicy, current_cycle: int | None
) -> list[str]:
    """Evidence currency: measured within the policy's cycle window."""
    evidence_cycle = genome.harness_params.get(EVIDENCE_CYCLE_KEY)
    if evidence_cycle is None:
        return ["evidence has no evidence_cycle stamp"]
    if current_cycle is None:
        return []
    age = current_cycle - int(evidence_cycle)
    if age > policy.max_evidence_age_cycles:
        return [
            f"evidence from cycle {evidence_cycle} is {age} cycles old > "
            f"max {policy.max_evidence_age_cycles} — stale"
        ]
    return []


def _best_of_n_violation(genome: PipelineGenome, policy: PromotionPolicy) -> list[str]:
    """Winner's-curse guard: fresh confirmation beyond the best-of-N round."""
    pending: dict[str, Any] | None = genome.harness_params.get(BEST_OF_N_KEY)
    if not pending or not policy.require_confirmation_after_best_of_n:
        return []
    samples: dict[str, int] = genome.harness_params.get(SAMPLES_KEY, {})
    bench = pending.get("benchmark")
    at_acceptance = int((pending.get("samples_at_acceptance") or {}).get(bench, 0))
    n = samples.get(bench, 0)
    if n <= at_acceptance:
        return [
            f"best-of-N winner pending fresh confirmation: {bench} has {n} "
            f"sample(s), none taken after acceptance (had {at_acceptance})"
        ]
    return []


def selection_eligibility(
    genome: PipelineGenome,
    policy: PromotionPolicy,
    current_cycle: int | None = None,
) -> EligibilityReport:
    """Whether a genome may be SELECTED (champion APIs) under ``policy``.

    Selection gates: evaluated at all, sufficient independent samples per
    benchmark, objective version stamped (and pinned when the policy pins one),
    hard correctness/security gate passed, uncertainty within bounds, evidence
    current for the cycle, and — for best-of-N winners — fresh post-acceptance
    confirmation. Human approval is deliberately NOT a selection gate: it is a
    promotion gate (``promotion_eligibility``), so dashboards can display the
    best *evaluatable* candidate while activation stays gated.
    """
    if genome.fitness_score is None or not genome.eval_scores:
        return EligibilityReport(
            eligible=False,
            reasons=["not evaluated: no fitness/scores recorded"],
        )

    from .fitness import _check_hard_gate

    gate_ok, gate_failures = _check_hard_gate(genome)
    gate_reasons = [f"hard gate: {f}" for f in gate_failures] if not gate_ok else []

    reasons = [
        *_sample_shortfalls(genome, policy),
        *gate_reasons,
        *_uncertainty_breach(genome, policy),
        *_objective_stamp_violation(genome, policy),
        *_evidence_age_violation(genome, policy, current_cycle),
        *_best_of_n_violation(genome, policy),
    ]

    return EligibilityReport(
        eligible=not reasons,
        reasons=reasons,
        evidence=_evidence_summary(genome),
    )


def compare_with_incumbent(
    candidate: PipelineGenome,
    incumbent: PipelineGenome | None,
    policy: PromotionPolicy,
) -> EligibilityReport:
    """Whether ``candidate`` may REPLACE ``incumbent`` under ``policy``.

    The comparison is only defined when both evidences carry the SAME stamped
    objective version (one immutable objective — #854 acceptance 5) and the
    incumbent actually has comparable evidence; anything else is refused
    rather than approximated. A candidate must beat the incumbent's fitness by
    at least ``min_promotion_margin`` — calling ``promote()`` later is never
    sufficient on its own (#854 acceptance 6).
    """
    if incumbent is None:
        return EligibilityReport(eligible=True, reasons=[], evidence={})

    reasons: list[str] = []
    cand_obj = candidate.harness_params.get(OBJECTIVE_VERSION_KEY)
    inc_obj = incumbent.harness_params.get(OBJECTIVE_VERSION_KEY)

    if not cand_obj or not inc_obj:
        reasons.append("cannot compare: missing objective_version stamp on evidence")
    elif cand_obj != inc_obj:
        reasons.append(
            f"objective mismatch: candidate evidence under {cand_obj}, "
            f"incumbent evidence under {inc_obj} — not comparable"
        )

    if incumbent.fitness_score is None or not incumbent.eval_scores:
        reasons.append(
            f"incumbent {incumbent.id} has no comparable evaluation evidence — "
            "re-evaluate it or roll it back before promoting over it"
        )
    elif not reasons and candidate.fitness_score is not None:
        margin_observed = candidate.fitness_score - incumbent.fitness_score
        if margin_observed < policy.min_promotion_margin:
            reasons.append(
                f"candidate fitness {candidate.fitness_score:.4f} does not beat "
                f"incumbent {incumbent.id} fitness {incumbent.fitness_score:.4f} by "
                f"the required margin {policy.min_promotion_margin} "
                f"(observed margin {margin_observed:.4f})"
            )

    return EligibilityReport(
        eligible=not reasons,
        reasons=reasons,
        evidence={
            "candidate_fitness": candidate.fitness_score,
            "incumbent_id": incumbent.id,
            "incumbent_fitness": incumbent.fitness_score,
            "margin_required": policy.min_promotion_margin,
        },
    )


def promotion_eligibility(
    candidate: PipelineGenome,
    incumbent: PipelineGenome | None,
    policy: PromotionPolicy,
    current_cycle: int | None = None,
) -> EligibilityReport:
    """Whether ``candidate`` may be ACTIVATED (promoted) under ``policy``.

    Composition of the contract: full selection eligibility (independent
    evidence, gates, currency, confirmation) + the explicit human approval
    gate + a candidate must not already be the active incumbent + the
    incumbent comparison. This is the single check ``promote_audited`` runs —
    there is no other activation path.
    """
    reasons: list[str] = []

    selection = selection_eligibility(candidate, policy, current_cycle)
    reasons.extend(selection.reasons)

    if not candidate.approved_for_promotion:
        reasons.append(
            "not approved for promotion (approved_for_promotion=False) — "
            "human approval gate not satisfied"
        )
    if incumbent is not None and incumbent.id == candidate.id:
        reasons.append("candidate is already the active incumbent")

    comparison = compare_with_incumbent(candidate, incumbent, policy)
    reasons.extend(comparison.reasons)

    return EligibilityReport(
        eligible=not reasons,
        reasons=reasons,
        evidence={
            "selection": selection.evidence,
            "comparison": comparison.evidence,
        },
    )


class PromotionRecord(BaseModel):
    """The immutable decision record written with every committed promotion
    (#854 acceptance 8): exact candidate/incumbent ids, objective version, the
    evaluation evidence (sample counts per benchmark stand in for the
    evaluation Runs that produced them — the cycle records those counts on
    every eval), the decision rule that was applied, the approval state, and
    the genome that is active as a result."""

    candidate_id: str
    incumbent_id: str | None = None
    resulting_active_id: str
    objective_version: str | None = None
    approved: bool
    decision_rule: dict[str, Any]
    candidate_evidence: dict[str, Any]
    incumbent_evidence: dict[str, Any] | None = None
    comparison: dict[str, Any] = {}

    def to_json(self) -> str:
        return self.model_dump_json()


def build_promotion_record(
    candidate: PipelineGenome,
    incumbent: PipelineGenome | None,
    resulting_active: PipelineGenome,
    policy: PromotionPolicy,
    comparison: dict[str, Any],
) -> PromotionRecord:
    return PromotionRecord(
        candidate_id=candidate.id,
        incumbent_id=incumbent.id if incumbent is not None else None,
        resulting_active_id=resulting_active.id,
        objective_version=candidate.harness_params.get(OBJECTIVE_VERSION_KEY),
        approved=candidate.approved_for_promotion,
        decision_rule={
            "min_samples_per_benchmark": policy.min_samples_per_benchmark,
            "min_benchmarks": policy.min_benchmarks,
            "max_sample_std": policy.max_sample_std,
            "max_evidence_age_cycles": policy.max_evidence_age_cycles,
            "require_confirmation_after_best_of_n": policy.require_confirmation_after_best_of_n,
            "min_promotion_margin": policy.min_promotion_margin,
            "objective_versions": list(policy.objective_versions),
        },
        candidate_evidence=_evidence_summary(candidate),
        incumbent_evidence=_evidence_summary(incumbent) if incumbent is not None else None,
        comparison=comparison,
    )
