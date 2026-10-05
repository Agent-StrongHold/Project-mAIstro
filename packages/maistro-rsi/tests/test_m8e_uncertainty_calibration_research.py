"""M8-E research harness — uncertainty, calibration, abstention, escalation.

Issue #904 (epic M8-E), initiative #879. Leaves: #930 (self-consistency /
semantic-entropy-style variation signals), #931 (historical Run-outcome
calibration), #932 (heterogeneous-model disagreement and verifier signals),
#933 (abstention / ask-for-help / confidence-triggered escalation policies).

This module is a RESEARCH ARTIFACT, not product code. It implements the
metric machinery the M8-E contract demands — discrimination (AUROC/AUPRC),
calibration error (ECE), Brier score, risk-coverage, outcome-based historical
calibration, variation-based agreement signals, and an abstention-policy
utility frontier — so each leaf's benchmark procedure is reproducible before
any provider experiment is run.

Trust boundary (the epic's contract, enforced by construction):

- Every number produced here is ADVISORY EVIDENCE. Nothing in this module
  reads or writes a Goal, a Run authority, a routing decision, or a
  Warden/HITL/delegation control. It imports nothing from ``maistro`` at all,
  so it cannot become an authority by accident (M8 guardrail 1).
- Observed outcomes are the only judge. Self-reported confidence is treated
  as one signal among several and is always scored against ground truth,
  never trusted as truth (the epic: "Calibration must be judged against
  observed outcomes, not model self-report alone").
- Dataclasses are frozen: evidence cannot be mutated into authorization
  after the fact.

The experiment records and terminal dispositions live in
``docs/research/904-uncertainty-calibration-abstention.md``. The synthetic
corpora below are deterministic fixtures for validating the metric math —
they are NOT experimental results and must never be quoted as evidence about
real models.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import pytest

#: Explicit evidence-only contract marker. Asserted by a test so it cannot
#: silently rot; nothing outside this module may treat M8-E output as
#: authorization (ADR-068 authorization paths and Warden/HITL remain canonical).
ADVISORY_ONLY = True


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UncertaintyObservation:
    """One judged decision: signals on the left, the observed outcome on the right.

    ``claimed`` is the model/Agent self-reported confidence in [0, 1] — a
    signal, never the truth. ``success`` is the observed outcome and the only
    judge. ``signals`` carries additional uncertainty evidence, each in
    [0, 1] and oriented so that *higher means predicted success* (so a
    disagreement-style signal must be inverted before storage, which keeps
    every downstream metric unambiguous).
    """

    context: str
    claimed: float
    success: bool
    signals: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.claimed <= 1.0:
            raise ValueError(f"claimed confidence {self.claimed} outside [0, 1]")
        for name, value in self.signals.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"signal {name!r}={value} outside [0, 1]")


@dataclass(frozen=True)
class ReliabilityBin:
    """One equal-width bin of the reliability diagram."""

    lower: float
    upper: float
    count: int
    mean_claimed: float
    empirical_accuracy: float


@dataclass(frozen=True)
class RiskCoverageCurve:
    """Selective-prediction curve: risk among the k most-confident decisions."""

    points: tuple[tuple[float, float], ...]  # (coverage, risk), coverage ascending
    aurc: float


@dataclass(frozen=True)
class EscalationCosts:
    """Utility model for the abstention/defer policy frontier (#933).

    ``defer_cost`` is the cost of routing a decision to a human or another
    destination instead of answering. Destinations (stronger model,
    specialist Agent, verifier, HITL) differ in cost and in the quality of
    the answer they eventually produce; measuring destination quality needs
    real cascade outcome data (#915), so the frontier models deferral as a
    single measured cost and never simulates an authority acting.
    """

    correct_reward: float = 1.0
    wrong_penalty: float = -1.0
    defer_cost: float = -0.2


@dataclass(frozen=True)
class PolicyPoint:
    """Measured outcome of one threshold of the defer policy. Evidence only."""

    threshold: float
    expected_utility: float
    answer_rate: float
    unsafe_action_rate: float  # wrong answers / all decisions
    defer_rate: float
    unnecessary_deferral_rate: float  # deferred but would have succeeded / all


# ---------------------------------------------------------------------------
# Calibration metrics (epic contract: judged against observed outcomes)
# ---------------------------------------------------------------------------


def m8e_brier(observations: Sequence[UncertaintyObservation]) -> float:
    """Brier score of the self-reported confidence against observed outcomes."""
    if not observations:
        raise ValueError("brier score needs at least one observation")
    return sum((o.claimed - float(o.success)) ** 2 for o in observations) / len(observations)


def m8e_ece(observations: Sequence[UncertaintyObservation], n_bins: int = 10) -> float:
    """Expected calibration error over equal-width bins of claimed confidence."""
    if not observations:
        raise ValueError("ece needs at least one observation")
    if n_bins <= 0:
        raise ValueError("n_bins must be positive")
    total = len(observations)
    ece = 0.0
    for lower, upper in _bin_edges(n_bins):
        bucket = [o for o in observations if lower <= o.claimed < upper]
        if not bucket:
            continue
        mean_claimed = sum(o.claimed for o in bucket) / len(bucket)
        accuracy = sum(float(o.success) for o in bucket) / len(bucket)
        ece += (len(bucket) / total) * abs(accuracy - mean_claimed)
    return ece


def m8e_reliability_curve(
    observations: Sequence[UncertaintyObservation], n_bins: int = 10
) -> tuple[ReliabilityBin, ...]:
    """Reliability diagram bins (claimed confidence vs empirical accuracy)."""
    if not observations:
        raise ValueError("reliability curve needs at least one observation")
    if n_bins <= 0:
        raise ValueError("n_bins must be positive")
    bins: list[ReliabilityBin] = []
    for lower, upper in _bin_edges(n_bins):
        bucket = [o for o in observations if lower <= o.claimed < upper]
        if not bucket:
            continue
        bins.append(
            ReliabilityBin(
                lower=lower,
                upper=upper,
                count=len(bucket),
                mean_claimed=sum(o.claimed for o in bucket) / len(bucket),
                empirical_accuracy=sum(float(o.success) for o in bucket) / len(bucket),
            )
        )
    return tuple(bins)


def _bin_edges(n_bins: int) -> list[tuple[float, float]]:
    width = 1.0 / n_bins
    edges = [(i * width, (i + 1) * width) for i in range(n_bins)]
    # The top edge is inclusive so claimed == 1.0 is binned rather than dropped.
    lower, upper = edges[-1]
    edges[-1] = (lower, math.nextafter(upper, math.inf))
    return edges


def m8e_signal_scores(
    observations: Sequence[UncertaintyObservation],
    signal: Callable[[UncertaintyObservation], float] | None = None,
) -> list[float]:
    """Project observations to error-prediction scores; default is self-report."""
    if signal is None:
        return [o.claimed for o in observations]
    return [signal(o) for o in observations]


def m8e_auroc(
    observations: Sequence[UncertaintyObservation],
    signal: Callable[[UncertaintyObservation], float] | None = None,
) -> float:
    """AUROC for error prediction: P(higher score | success) over ties by mid-rank."""
    if not observations:
        raise ValueError("auroc needs at least one observation")
    scores = m8e_signal_scores(observations, signal)
    outcomes = [o.success for o in observations]
    positives = sum(outcomes)
    negatives = len(outcomes) - positives
    if positives == 0 or negatives == 0:
        raise ValueError("auroc is undefined when one outcome class is absent")
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    midranks = _midranks([scores[i] for i in order])
    rank_of = dict(zip(order, midranks, strict=True))
    positive_rank_sum = sum(rank_of[i] for i, ok in enumerate(outcomes) if ok)
    u = positive_rank_sum - positives * (positives + 1) / 2
    return u / (positives * negatives)


def m8e_auprc(
    observations: Sequence[UncertaintyObservation],
    signal: Callable[[UncertaintyObservation], float] | None = None,
) -> float:
    """Average precision for success prediction under the given signal.

    Ties are treated group-wise (one PR point per distinct score), so a
    fully tied signal degenerates to the prevalence instead of depending
    on sort order.
    """
    if not observations:
        raise ValueError("auprc needs at least one observation")
    scores = m8e_signal_scores(observations, signal)
    positives = sum(o.success for o in observations)
    if positives == 0:
        raise ValueError("auprc is undefined when no observation succeeded")
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    average_precision = 0.0
    seen_positive = 0
    seen = 0
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        group = order[i : j + 1]
        group_positives = sum(observations[k].success for k in group)
        seen += len(group)
        seen_positive += group_positives
        if group_positives:
            average_precision += (seen_positive / seen) * (group_positives / positives)
        i = j + 1
    return average_precision


def m8e_risk_coverage(
    observations: Sequence[UncertaintyObservation],
    signal: Callable[[UncertaintyObservation], float] | None = None,
) -> RiskCoverageCurve:
    """Risk vs coverage for answering only on the most confident decisions."""
    if not observations:
        raise ValueError("risk-coverage needs at least one observation")
    scores = m8e_signal_scores(observations, signal)
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    points: list[tuple[float, float]] = []
    errors = 0
    for k, index in enumerate(order, start=1):
        if not observations[index].success:
            errors += 1
        points.append((k / len(order), errors / k))
    return RiskCoverageCurve(
        points=tuple(points),
        aurc=sum(risk for _, risk in points) / len(points),
    )


def _midranks(sorted_scores: list[float]) -> list[float]:
    """Average (mid) ranks for an ascending score list, ties sharing a rank."""
    ranks: list[float] = []
    i = 0
    n = len(sorted_scores)
    while i < n:
        j = i
        while j + 1 < n and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        average = (i + j) / 2 + 1  # ranks are 1-based
        ranks.extend([average] * (j - i + 1))
        i = j + 1
    return ranks


# ---------------------------------------------------------------------------
# Variation and disagreement signals (#930, #932)
# ---------------------------------------------------------------------------


def m8e_agreement(answers: Sequence[str]) -> float:
    """Agreement among repeated samples: 1 - normalized entropy of the answer multiset.

    A deterministic, embedding-free proxy for the self-consistency /
    semantic-entropy family (#930): identical answers score 1.0, a uniform
    spread over n distinct answers scores 0.0.
    """
    if not answers:
        raise ValueError("agreement needs at least one answer")
    counts = Counter(answers)
    n = len(answers)
    entropy = -sum((c / n) * math.log(c / n) for c in counts.values())
    max_entropy = math.log(n)
    if max_entropy == 0.0:  # single sample carries no variation evidence
        return 1.0
    return 1.0 - entropy / max_entropy


def m8e_heterogeneous_disagreement(answers_by_model: Mapping[str, str]) -> float:
    """Pairwise disagreement rate across independently trained model families (#932)."""
    if not answers_by_model:
        raise ValueError("disagreement needs at least one model family")
    families = sorted(answers_by_model)
    if len(families) == 1:
        # One family alone provides no cross-family evidence; that absence is
        # reported as 0.0 (no disagreement observed), never as confidence.
        return 0.0
    pairs = 0
    disagreements = 0
    for i, left in enumerate(families):
        for right in families[i + 1 :]:
            pairs += 1
            if answers_by_model[left] != answers_by_model[right]:
                disagreements += 1
    return disagreements / pairs


# ---------------------------------------------------------------------------
# Historical outcome calibration (#931)
# ---------------------------------------------------------------------------


def m8e_historical_calibration(
    observations: Sequence[UncertaintyObservation], prior_strength: float = 2.0
) -> dict[str, float]:
    """Per-context Beta-smoothed success rate from observed outcomes.

    The frequency/Bayesian baseline of leaf #931: a context's calibrated
    confidence is its observed success rate shrunk toward 0.5 by a symmetric
    ``prior_strength`` Beta prior, so thin contexts cannot pose as well
    calibrated. Callers must fit on a temporally earlier split only —
    :func:`m8e_temporal_split` exists to make that split cheap and explicit.
    """
    if prior_strength <= 0.0:
        raise ValueError("prior_strength must be positive")
    successes: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    for o in observations:
        totals[o.context] += 1
        successes[o.context] += float(o.success)
    alpha = prior_strength / 2
    return {
        context: (successes[context] + alpha) / (totals[context] + prior_strength)
        for context in totals
    }


def m8e_temporal_split(
    observations: Sequence[UncertaintyObservation], train_fraction: float
) -> tuple[tuple[UncertaintyObservation, ...], tuple[UncertaintyObservation, ...]]:
    """Order-preserving chronological split, so calibration never sees its future."""
    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must be in (0, 1)")
    if not observations:
        raise ValueError("split needs at least one observation")
    cut = max(1, math.floor(len(observations) * train_fraction))
    return tuple(observations[:cut]), tuple(observations[cut:])


def m8e_blend(self_report: float, historical: float, weight: float) -> float:
    """Convex blend of self-report and historical evidence (weight on historical)."""
    if not 0.0 <= weight <= 1.0:
        raise ValueError("weight must be in [0, 1]")
    if not 0.0 <= self_report <= 1.0 or not 0.0 <= historical <= 1.0:
        raise ValueError("confidence inputs must be in [0, 1]")
    return weight * historical + (1.0 - weight) * self_report


# ---------------------------------------------------------------------------
# Abstention / defer policy frontier (#933)
# ---------------------------------------------------------------------------


def m8e_policy_scores(
    observations: Sequence[UncertaintyObservation],
    historical_weight: float = 1.0,
    prior_strength: float = 2.0,
) -> list[float]:
    """Calibrated policy scores: historical evidence blended over self-report.

    With ``historical_weight=1.0`` (default) the policy ignores self-report
    entirely and acts purely on observed-outcome calibration per context —
    the epic requires history, not self-report, to drive any escalation
    decision.
    """
    historical = m8e_historical_calibration(observations, prior_strength)
    return [m8e_blend(o.claimed, historical[o.context], historical_weight) for o in observations]


def m8e_policy_frontier(
    observations: Sequence[UncertaintyObservation],
    scores: Sequence[float],
    thresholds: Sequence[float],
    costs: EscalationCosts | None = None,
) -> tuple[PolicyPoint, ...]:
    """Measured utility frontier of the answer-vs-defer policy over thresholds.

    ``scores[i]`` is the (calibrated) confidence for ``observations[i]``; the
    policy answers when the score is at least the threshold and defers
    otherwise. Every returned field is a measurement — the frontier proposes,
    it never acts. Defer destinations and their authority remain exclusively
    with the canonical Warden/HITL/delegation controls.
    """
    if len(observations) != len(scores):
        raise ValueError("scores must align with observations")
    if not observations:
        raise ValueError("frontier needs at least one observation")
    if costs is None:
        costs = EscalationCosts()
    total = len(observations)
    points: list[PolicyPoint] = []
    for threshold in thresholds:
        utility = 0.0
        answered = 0
        wrong_answers = 0
        deferred = 0
        deferred_would_succeed = 0
        for o, score in zip(observations, scores, strict=True):
            if score >= threshold:
                answered += 1
                if o.success:
                    utility += costs.correct_reward
                else:
                    utility += costs.wrong_penalty
                    wrong_answers += 1
            else:
                deferred += 1
                utility += costs.defer_cost
                if o.success:
                    deferred_would_succeed += 1
        points.append(
            PolicyPoint(
                threshold=threshold,
                expected_utility=utility / total,
                answer_rate=answered / total,
                unsafe_action_rate=wrong_answers / total,
                defer_rate=deferred / total,
                unnecessary_deferral_rate=deferred_would_succeed / total,
            )
        )
    return tuple(points)


def m8e_apply_overconfidence_drift(
    observations: Sequence[UncertaintyObservation],
    shift: float,
    rng: random.Random,
    noise: float = 0.05,
) -> list[UncertaintyObservation]:
    """Simulate model drift: claimed confidence inflates, true skill does not.

    Returns *new* observations with the same observed outcomes but inflated
    self-report, so callers can measure threshold robustness under drift —
    a threshold tuned on yesterday's calibration silently answers more
    wrong decisions after the model becomes overconfident.
    """
    if shift < 0.0 or noise < 0.0:
        raise ValueError("drift shift and noise must be non-negative")
    drifted: list[UncertaintyObservation] = []
    for o in observations:
        inflated = min(1.0, o.claimed + shift + rng.uniform(0.0, noise))
        drifted.append(UncertaintyObservation(o.context, inflated, o.success, dict(o.signals)))
    return drifted


# ---------------------------------------------------------------------------
# Deterministic synthetic corpora — fixtures for the metric math, NOT results
# ---------------------------------------------------------------------------


def m8e_synthetic_corpus(seed: int = 904, n: int = 400) -> list[UncertaintyObservation]:
    """A fixed synthetic corpus where self-report is honest and skill varies by context.

    Deterministic under ``seed``; exists only so the metrics and policies
    above have a reproducible fixture. It says nothing about any real model.
    """
    rng = random.Random(seed)
    skill = {"coding": 0.9, "research": 0.7, "tool-use": 0.5}
    corpus: list[UncertaintyObservation] = []
    for i in range(n):
        context = sorted(skill)[i % len(skill)]
        claimed = min(1.0, max(0.0, rng.gauss(skill[context], 0.08)))
        success = rng.random() < skill[context]
        corpus.append(UncertaintyObservation(context, claimed, success))
    return corpus


# ---------------------------------------------------------------------------
# Tests: calibration metrics
# ---------------------------------------------------------------------------


class TestCalibrationMetrics:
    def test_brier_hand_values(self) -> None:
        half = [UncertaintyObservation("c", 0.5, s) for s in (True, False)]
        assert m8e_brier(half) == pytest.approx(0.25)
        perfect = [
            UncertaintyObservation("c", 1.0, True),
            UncertaintyObservation("c", 0.0, False),
        ]
        assert m8e_brier(perfect) == pytest.approx(0.0)
        with pytest.raises(ValueError, match="at least one"):
            m8e_brier([])

    def test_ece_perfectly_calibrated_corpus_is_near_zero(self) -> None:
        # Claimed equals the bin's empirical accuracy by construction, so the
        # ECE collapses to 0. The extremes exercise the inclusive top edge.
        observations = [
            UncertaintyObservation("c", 0.0, False),
            UncertaintyObservation("c", 1.0, True),
        ]
        assert m8e_ece(observations, n_bins=10) == pytest.approx(0.0)

    def test_ece_constant_overconfidence_is_measured(self) -> None:
        # Claims 1.0, succeeds half the time: |accuracy - confidence| = 0.5.
        observations = [UncertaintyObservation("c", 1.0, i % 2 == 0) for i in range(20)]
        assert m8e_ece(observations, n_bins=10) == pytest.approx(0.5)

    def test_ece_rejects_degenerate_bins(self) -> None:
        observations = [UncertaintyObservation("c", 0.5, True)]
        with pytest.raises(ValueError, match="positive"):
            m8e_ece(observations, n_bins=0)

    def test_reliability_bins_partition_the_corpus(self) -> None:
        observations = m8e_synthetic_corpus()
        bins = m8e_reliability_curve(observations, n_bins=10)
        assert sum(b.count for b in bins) == len(observations)
        edges = [b.lower for b in bins] + [bins[-1].upper]
        assert edges == sorted(edges)
        for b in bins:
            assert 0.0 <= b.empirical_accuracy <= 1.0
            assert b.lower <= b.mean_claimed < b.upper
        # Claimed == 1.0 must be binned, not dropped (top edge inclusive).
        edge_case = [UncertaintyObservation("c", 1.0, True)]
        assert m8e_reliability_curve(edge_case, n_bins=10)[0].count == 1

    def test_auroc_separation_extremes(self) -> None:
        separated = [
            UncertaintyObservation("c", 0.9, True),
            UncertaintyObservation("c", 0.8, True),
            UncertaintyObservation("c", 0.2, False),
            UncertaintyObservation("c", 0.1, False),
        ]
        assert m8e_auroc(separated) == pytest.approx(1.0)
        inverted = [
            UncertaintyObservation("c", 0.1, True),
            UncertaintyObservation("c", 0.2, True),
            UncertaintyObservation("c", 0.8, False),
            UncertaintyObservation("c", 0.9, False),
        ]
        assert m8e_auroc(inverted) == pytest.approx(0.0)

    def test_auroc_all_ties_is_chance(self) -> None:
        tied = [
            UncertaintyObservation("c", 0.5, True),
            UncertaintyObservation("c", 0.5, False),
        ]
        assert m8e_auroc(tied) == pytest.approx(0.5)

    def test_auroc_single_class_is_undefined_not_zero(self) -> None:
        only_successes = [UncertaintyObservation("c", 0.5, True)]
        with pytest.raises(ValueError, match="undefined"):
            m8e_auroc(only_successes)

    def test_auprc_perfect_and_tied_baseline(self) -> None:
        separated = [
            UncertaintyObservation("c", 0.9, True),
            UncertaintyObservation("c", 0.1, False),
            UncertaintyObservation("c", 0.1, False),
        ]
        assert m8e_auprc(separated) == pytest.approx(1.0)
        # A fully tied signal carries no ranking information: group-wise
        # averaging degenerates to a single PR point at the prevalence (2/3).
        tied = [UncertaintyObservation("c", 0.5, s) for s in (True, True, False)]
        assert m8e_auprc(tied) == pytest.approx(2 / 3)

    def test_risk_coverage_is_monotone_in_coverage_and_sums(self) -> None:
        observations = m8e_synthetic_corpus()
        curve = m8e_risk_coverage(observations)
        coverages = [c for c, _ in curve.points]
        assert coverages == sorted(coverages)
        assert len(curve.points) == len(observations)
        final_errors = sum(not o.success for o in observations) / len(observations)
        assert curve.points[-1][1] == pytest.approx(final_errors)
        assert 0.0 <= curve.aurc <= curve.points[-1][1] + 1e-9


# ---------------------------------------------------------------------------
# Tests: variation and disagreement signals (#930, #932)
# ---------------------------------------------------------------------------


class TestVariationSignals:
    def test_agreement_extremes(self) -> None:
        assert m8e_agreement(["a", "a", "a"]) == pytest.approx(1.0)
        assert m8e_agreement(["a", "b", "c"]) == pytest.approx(0.0)
        with pytest.raises(ValueError, match="at least one"):
            m8e_agreement([])

    def test_agreement_partial_spread_lies_between_extremes(self) -> None:
        partial = m8e_agreement(["a", "a", "b"])
        assert 0.0 < partial < 1.0
        # A 2-1 split is less varied than a 1-1-1 spread.
        assert partial > m8e_agreement(["a", "b", "c"])

    def test_heterogeneous_disagreement_bounds(self) -> None:
        assert m8e_heterogeneous_disagreement({"m1": "a", "m2": "a", "m3": "a"}) == 0.0
        assert m8e_heterogeneous_disagreement({"m1": "a", "m2": "b", "m3": "c"}) == 1.0
        # One family alone: no cross-family evidence, reported as absence.
        assert m8e_heterogeneous_disagreement({"m1": "a"}) == 0.0
        with pytest.raises(ValueError, match="model family"):
            m8e_heterogeneous_disagreement({})

    def test_disagreement_can_be_the_better_error_predictor(self) -> None:
        # Synthetic by design: a context where self-report is confidently
        # wrong while families disagree. The harness must be able to *rank*
        # the signals — that ranking is exactly what leaves #930/#932 compare
        # on real data.
        observations = [
            UncertaintyObservation("trap", 0.95, False, {"family_agree": 0.1}),
            UncertaintyObservation("trap", 0.90, False, {"family_agree": 0.2}),
            UncertaintyObservation("plain", 0.55, True, {"family_agree": 0.9}),
            UncertaintyObservation("plain", 0.60, True, {"family_agree": 0.8}),
        ]
        auroc_claim = m8e_auroc(observations)
        auroc_family = m8e_auroc(observations, signal=lambda o: o.signals["family_agree"])
        assert auroc_family > auroc_claim
        assert auroc_family == pytest.approx(1.0)

    def test_disagreement_signal_feeds_risk_coverage(self) -> None:
        # An inverted agreement signal (disagreement first) must rank risk
        # worse than the agreement signal itself — the projection is coherent.
        observations = [
            UncertaintyObservation("c", 0.9, True, {"agreement": 0.9}),
            UncertaintyObservation("c", 0.4, False, {"agreement": 0.1}),
        ]
        good = m8e_risk_coverage(observations, signal=lambda o: o.signals["agreement"])
        bad = m8e_risk_coverage(observations, signal=lambda o: 1.0 - o.signals["agreement"])
        assert bad.aurc > good.aurc


# ---------------------------------------------------------------------------
# Tests: historical outcome calibration (#931)
# ---------------------------------------------------------------------------


class TestHistoricalCalibration:
    def test_prior_shrinks_thin_contexts_toward_half(self) -> None:
        single_success = [UncertaintyObservation("rare", 1.0, True)]
        calibrated = m8e_historical_calibration(single_success, prior_strength=10.0)
        assert calibrated["rare"] < 1.0  # one success cannot pose as certainty
        assert calibrated["rare"] > 0.5  # ...but it does move the estimate up
        raw = m8e_historical_calibration(single_success, prior_strength=0.1)
        assert raw["rare"] > calibrated["rare"]  # weaker prior, less shrinkage

    def test_estimates_converge_to_observed_rate(self) -> None:
        observations = [UncertaintyObservation("steady", 0.8, i % 10 < 7) for i in range(1000)]
        calibrated = m8e_historical_calibration(observations, prior_strength=2.0)
        assert calibrated["steady"] == pytest.approx(0.7, abs=0.02)

    def test_temporal_split_is_disjoint_ordered_and_leakage_free(self) -> None:
        observations = m8e_synthetic_corpus(n=50)
        train, holdout = m8e_temporal_split(observations, 0.6)
        assert len(train) + len(holdout) == len(observations)
        # Disjoint (by equality; the records carry a mapping and are unhashable)
        assert all(row not in holdout for row in train)
        # Order preserved: calibration fits on the past, evaluation on the
        # future, and no record is evaluated before it is fitted.
        assert train == tuple(observations[: len(train)])
        assert holdout == tuple(observations[len(train) :])
        calibrated = m8e_historical_calibration(train)
        # A holdout context unseen by the fit cannot silently receive a rate.
        unseen = m8e_historical_calibration(train)
        assert set(calibrated) == set(unseen) == {o.context for o in train}

    def test_split_rejects_degenerate_fractions(self) -> None:
        observations = [UncertaintyObservation("c", 0.5, True)]
        for bad in (0.0, 1.0, -0.5):
            with pytest.raises(ValueError, match="train_fraction"):
                m8e_temporal_split(observations, bad)

    def test_blend_is_convex_and_validated(self) -> None:
        assert m8e_blend(0.9, 0.1, 1.0) == pytest.approx(0.1)  # history only
        assert m8e_blend(0.9, 0.1, 0.0) == pytest.approx(0.9)  # self-report only
        assert m8e_blend(0.9, 0.1, 0.5) == pytest.approx(0.5)
        with pytest.raises(ValueError, match="weight"):
            m8e_blend(0.9, 0.1, 1.5)
        with pytest.raises(ValueError, match="confidence inputs"):
            m8e_blend(1.5, 0.1, 0.5)


# ---------------------------------------------------------------------------
# Tests: abstention / defer policy frontier (#933)
# ---------------------------------------------------------------------------


class TestAbstentionPolicy:
    def test_threshold_dominates_always_answer(self) -> None:
        # Hand-built corpus, hand-checked arithmetic: "good" succeeds always,
        # "coin" is a 50/50 context. Wrong answers cost twice the reward, so
        # answering the coin context is worth 0.5*1 - 0.5*2 = -0.5 per
        # decision while deferring costs -0.2 — an asymmetric-cost world in
        # which calibrated deferral must strictly dominate always answering.
        observations = [UncertaintyObservation("good", 0.9, True) for _ in range(20)]
        observations += [UncertaintyObservation("coin", 0.5, i % 2 == 0) for i in range(20)]
        scores = m8e_policy_scores(observations)
        costs = EscalationCosts(correct_reward=1.0, wrong_penalty=-2.0, defer_cost=-0.2)
        frontier = m8e_policy_frontier(observations, scores, [0.0, 0.6], costs)
        baseline, defer = frontier
        # Baseline: (20 - 20) from good + (10 - 20) from coin over 40 = 0.25.
        assert baseline.expected_utility == pytest.approx(0.25)
        assert baseline.unsafe_action_rate == pytest.approx(0.25)
        # Defer the coin context: 20*1 + 20*(-0.2) = 16 over 40 = 0.4.
        assert defer.expected_utility == pytest.approx(0.4)
        assert defer.unsafe_action_rate == pytest.approx(0.0)
        assert defer.unnecessary_deferral_rate == pytest.approx(0.25)
        assert defer.expected_utility > baseline.expected_utility

    def test_answer_and_defer_rates_are_monotone_in_threshold(self) -> None:
        observations = m8e_synthetic_corpus()
        scores = m8e_policy_scores(observations)
        thresholds = [0.0, 0.25, 0.5, 0.75, 1.0]
        frontier = m8e_policy_frontier(observations, scores, thresholds)
        answer_rates = [p.answer_rate for p in frontier]
        defer_rates = [p.defer_rate for p in frontier]
        assert answer_rates == sorted(answer_rates, reverse=True)
        assert defer_rates == sorted(defer_rates)

    def test_degenerate_thresholds(self) -> None:
        observations = m8e_synthetic_corpus(n=50)
        scores = m8e_policy_scores(observations)
        costs = EscalationCosts()
        baseline = m8e_policy_frontier(observations, scores, [0.0], costs)[0]
        assert baseline.answer_rate == pytest.approx(1.0)
        assert baseline.defer_rate == pytest.approx(0.0)
        everything = m8e_policy_frontier(observations, scores, [1.1], costs)[0]
        assert everything.answer_rate == pytest.approx(0.0)
        assert everything.defer_rate == pytest.approx(1.0)
        assert everything.expected_utility == pytest.approx(costs.defer_cost)

    def test_overconfidence_drift_raises_unsafe_rate_at_fixed_threshold(self) -> None:
        observations = m8e_synthetic_corpus()
        scores_before = m8e_policy_scores(observations)
        threshold = 0.5
        before = m8e_policy_frontier(observations, scores_before, [threshold])
        drifted = m8e_apply_overconfidence_drift(observations, shift=0.3, rng=random.Random(7))
        scores_after = m8e_policy_scores(drifted)
        after = m8e_policy_frontier(drifted, scores_after, [threshold])
        # Historical calibration absorbs the drift in self-report (weight=1),
        # so unsafe actions must NOT silently rise — recalibration is the
        # defense, and the harness can measure its absence too.
        after_selfreport = m8e_policy_frontier(drifted, [o.claimed for o in drifted], [threshold])[
            0
        ]
        assert after[0].unsafe_action_rate <= before[0].unsafe_action_rate + 1e-9
        assert after_selfreport.unsafe_action_rate > before[0].unsafe_action_rate

    def test_frontier_rejects_misaligned_scores(self) -> None:
        observations = [UncertaintyObservation("c", 0.5, True)]
        with pytest.raises(ValueError, match="align"):
            m8e_policy_frontier(observations, [], [0.5])
        with pytest.raises(ValueError, match="at least one"):
            m8e_policy_frontier([], [], [0.5])

    def test_drift_is_deterministic_under_a_seed(self) -> None:
        observations = m8e_synthetic_corpus(n=20)
        first = m8e_apply_overconfidence_drift(observations, 0.2, random.Random(904))
        second = m8e_apply_overconfidence_drift(observations, 0.2, random.Random(904))
        assert first == second
        other = m8e_apply_overconfidence_drift(observations, 0.2, random.Random(905))
        assert first != other
        with pytest.raises(ValueError, match="non-negative"):
            m8e_apply_overconfidence_drift(observations, -0.1, random.Random(1))


# ---------------------------------------------------------------------------
# Tests: the evidence-only trust boundary holds by construction
# ---------------------------------------------------------------------------


class TestEvidenceOnlyContract:
    def test_harness_declares_itself_advisory(self) -> None:
        assert ADVISORY_ONLY is True

    def test_observations_reject_out_of_range_confidence(self) -> None:
        with pytest.raises(ValueError, match="claimed"):
            UncertaintyObservation("c", 1.5, True)
        with pytest.raises(ValueError, match="signal"):
            UncertaintyObservation("c", 0.5, True, {"x": 2.0})

    def test_evidence_records_are_frozen(self) -> None:
        o = UncertaintyObservation("c", 0.5, True, {"s": 0.5})
        with pytest.raises(AttributeError):
            o.success = False  # type: ignore[misc]
        point = PolicyPoint(0.5, 0.0, 1.0, 0.0, 0.0, 0.0)
        with pytest.raises(AttributeError):
            point.expected_utility = 100.0  # type: ignore[misc]

    def test_policy_outputs_are_measurements_not_actions(self) -> None:
        observations = m8e_synthetic_corpus(n=30)
        scores = m8e_policy_scores(observations)
        for point in m8e_policy_frontier(observations, scores, [0.0, 0.7]):
            for value in vars(point).values():
                assert not callable(value)
            assert set(vars(point)) == {
                "threshold",
                "expected_utility",
                "answer_rate",
                "unsafe_action_rate",
                "defer_rate",
                "unnecessary_deferral_rate",
            }
