"""M8-E1 research harness — self-consistency vs semantic entropy vs answer variation.

Issue #930 (leaf M8-E1), epic #904 (M8-E), initiative #879. Sibling of the
epic-level harness in ``test_m8e_uncertainty_calibration_research.py``, which
covered all four M8-E leaves with one aggregate sample-agreement stand-in; this
module is the leaf #930 deliverable: the *comparison* machinery for the three
variation-signal families the issue names, side by side against the raw
self-report baseline.

This module is a RESEARCH ARTIFACT, not product code. It imports nothing from
``maistro``, so it cannot become an authority by accident (M8 guardrails 1-2),
and every number it produces is ADVISORY EVIDENCE: it reads no Goal, writes no
Run authority, makes no routing decision, and touches no Warden/HITL/delegation
control (ADR-068 paths stay canonical).

The three signal families compared, each computed from k independent samples of
one decision:

- **self-consistency**: the modal answer's share of the samples (majority-vote
  confidence);
- **semantic entropy**: entropy over *semantic* clusters of the samples — the
  embedding-free stand-in clusters answers through a pluggable equivalence
  function (default: whitespace/case normalization), because this harness holds
  no embedding model. This is the seam where a real entailment/embedding
  clusterer would plug in;
- **answer variation**: simple disagreement metrics — pairwise disagreement and
  the distinct-answer ratio.

Measures implemented per the issue: error-prediction AUROC/AUPRC, calibration
error of the signal treated as a probability (ECE against observed outcomes),
token cost and latency accounting for k-fold sampling, sensitivity to sampling
temperature and model family, and rank correlation with task difficulty.

Honesty boundaries (M8 guardrail 3): the synthetic corpora below are
deterministic fixtures for validating the metric math and the comparison
procedure. They are NOT experimental results and must never be quoted as
evidence about real models. No provider corpus exists in this repository's
deterministic CI; the terminal disposition lives in
``docs/research/930-answer-variation-uncertainty-signals.md``.
"""

from __future__ import annotations

import ast
import math
import random
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

#: Explicit evidence-only contract marker. Asserted by a test so it cannot
#: silently rot; nothing outside this module may treat M8-E1 output as
#: authorization (ADR-068 authorization paths and Warden/HITL remain canonical).
ADVISORY_ONLY = True

#: Cost-model constants for generated corpora. A real experiment replaces these
#: with measured per-call token counts and latencies from the governed seam
#: (Binding -> Invocation -> gateway provider); the accounting shapes stay.
TOKENS_PER_SAMPLE = 48
PER_SAMPLE_LATENCY_MS = 700.0

#: Generated-corpus model families: different base skill and self-report bias,
#: so the harness can demonstrate family sensitivity on deterministic data.
FAMILY_SKILL = {"alpha": 0.80, "beta": 0.55}
FAMILY_CLAIMED_BIAS = {"alpha": 0.0, "beta": 0.1}

#: The comparison register: every confidence-oriented signal name the driver
#: scores. Each maps one SampledDecision to a confidence in [0, 1] where
#: higher means predicted success.
SIGNALS: tuple[str, ...] = (
    "self_report",
    "self_consistency",
    "semantic_confidence",
    "pairwise_agreement",
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SampledDecision:
    """One judged decision with its k independent sample answers.

    ``success`` is the observed outcome and the only judge. ``claimed`` is the
    single-sample self-reported confidence — a signal, never the truth.
    ``answers`` holds the k sampled answer strings the variation signals are
    computed from. Cost fields feed the sampling cost/latency accounting.
    """

    task_id: str
    family: str
    difficulty: float
    temperature: float
    claimed: float
    success: bool
    answers: tuple[str, ...]
    tokens_per_sample: int = TOKENS_PER_SAMPLE
    per_call_latency_ms: float = PER_SAMPLE_LATENCY_MS

    def __post_init__(self) -> None:
        if not self.answers:
            raise ValueError("a sampled decision needs at least one answer")
        if not 0.0 <= self.claimed <= 1.0:
            raise ValueError(f"claimed confidence {self.claimed} outside [0, 1]")
        if not 0.0 <= self.difficulty <= 1.0:
            raise ValueError(f"difficulty {self.difficulty} outside [0, 1]")
        if self.temperature <= 0.0:
            raise ValueError("temperature must be positive")
        if self.tokens_per_sample < 1:
            raise ValueError("tokens_per_sample must be positive")
        if self.per_call_latency_ms < 0.0:
            raise ValueError("per_call_latency_ms must be non-negative")


@dataclass(frozen=True)
class ComparisonRow:
    """Measured comparison row for one uncertainty signal. Evidence only."""

    signal: str
    error_auroc: float  # AUROC of (1 - confidence) at predicting failure
    error_auprc: float  # average precision of the same error score
    ece: float  # calibration error of the confidence treated as P(success)
    mean_confidence: float
    cost_multiple: float  # mean samples per decision vs the single-shot baseline


# ---------------------------------------------------------------------------
# Variation signals (#930): k samples -> confidence in [0, 1]
# ---------------------------------------------------------------------------


def _normalize(answer: str) -> str:
    """Default equivalence: collapse whitespace and case, nothing more.

    Deliberately conservative. Surface forms like ``1,000`` vs ``1000`` stay
    distinct unless the caller supplies a task-appropriate equivalence —
    folding punctuation is a judgment about the task's answer space, not
    something a generic harness may assume.
    """
    return " ".join(answer.lower().split())


def m8e1_self_consistency(answers: Sequence[str]) -> float:
    """Modal answer share: the self-consistency confidence (higher = agreement).

    A single sample carries no variation evidence and reports 1.0.
    """
    if not answers:
        raise ValueError("self-consistency needs at least one answer")
    return max(Counter(answers).values()) / len(answers)


def m8e1_pairwise_disagreement(answers: Sequence[str]) -> float:
    """Fraction of sample pairs that disagree (higher = more variation).

    The finite-sample disagreement rate over all C(k, 2) unordered pairs; a
    single sample has no pairs and reports 0.0 (no disagreement observed).
    """
    if not answers:
        raise ValueError("disagreement needs at least one answer")
    counts = Counter(answers)
    k = len(answers)
    total_pairs = k * (k - 1) // 2
    if total_pairs == 0:  # single sample carries no variation evidence
        return 0.0
    agreeing_pairs = sum(c * (c - 1) // 2 for c in counts.values())
    return (total_pairs - agreeing_pairs) / total_pairs


def m8e1_distinct_ratio(answers: Sequence[str]) -> float:
    """Distinct surface answers over k (higher = more variation)."""
    if not answers:
        raise ValueError("distinct ratio needs at least one answer")
    return len(set(answers)) / len(answers)


def m8e1_semantic_clusters(
    answers: Sequence[str], equivalence: Callable[[str], str] | None = None
) -> tuple[float, ...]:
    """Semantic-cluster probability masses, descending.

    ``equivalence`` maps an answer to its semantic identity; the default
    normalization is the embedding-free stand-in for entailment clustering.
    This function is the seam where a real entailment/embedding clusterer
    would plug in — everything downstream (entropy, confidence) consumes
    these masses and never sees raw strings.
    """
    if not answers:
        raise ValueError("semantic clustering needs at least one answer")
    resolve = equivalence if equivalence is not None else _normalize
    counts = Counter(resolve(a) for a in answers)
    total = len(answers)
    return tuple(sorted((c / total for c in counts.values()), reverse=True))


def m8e1_semantic_entropy(
    answers: Sequence[str], equivalence: Callable[[str], str] | None = None
) -> float:
    """Entropy (nats) over semantic-cluster masses: higher = more uncertain.

    Zero when all samples land in one semantic cluster; log(k) when the k
    samples spread uniformly over k distinct meanings.
    """
    masses = m8e1_semantic_clusters(answers, equivalence)
    return -sum(p * math.log(p) for p in masses)


def m8e1_semantic_confidence(
    answers: Sequence[str], equivalence: Callable[[str], str] | None = None
) -> float:
    """1 - normalized semantic entropy, oriented as confidence (higher = success).

    The discrete semantic-entropy signal of leaf #930 in the harness's
    confidence orientation. A single sample carries no variation evidence and
    reports 1.0, matching the other single-sample degenerate cases.
    """
    k = len(answers)
    if k == 0:
        raise ValueError("semantic confidence needs at least one answer")
    if k == 1:
        return 1.0
    entropy = m8e1_semantic_entropy(answers, equivalence)
    return 1.0 - entropy / math.log(k)


def m8e1_confidence(decision: SampledDecision, signal: str) -> float:
    """Project one decision to a confidence under a named signal.

    ``self_report`` is the single-sample baseline (one sample, no k-fold cost);
    the other three are sampled signals. Unknown names raise — a typo silently
    scoring the baseline would corrupt a comparison table.
    """
    if signal == "self_report":
        return decision.claimed
    if signal == "self_consistency":
        return m8e1_self_consistency(decision.answers)
    if signal == "semantic_confidence":
        return m8e1_semantic_confidence(decision.answers)
    if signal == "pairwise_agreement":
        return 1.0 - m8e1_pairwise_disagreement(decision.answers)
    raise ValueError(f"unknown signal {signal!r}; expected one of {SIGNALS}")


# ---------------------------------------------------------------------------
# Discrimination and calibration measures (#930)
# ---------------------------------------------------------------------------


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


def m8e1_auroc(confidences: Sequence[float], successes: Sequence[bool]) -> float:
    """AUROC of the confidence at predicting success, ties by mid-rank.

    Error-prediction AUROC is the same call with (1 - confidence) against the
    failure labels; the driver does exactly that, so the metric has one
    definition and one set of hand-checked extremes.
    """
    if not confidences or len(confidences) != len(successes):
        raise ValueError("confidences must align with outcomes")
    positives = sum(successes)
    negatives = len(successes) - positives
    if positives == 0 or negatives == 0:
        raise ValueError("auroc is undefined when one outcome class is absent")
    order = sorted(range(len(confidences)), key=lambda i: confidences[i])
    midranks = _midranks([confidences[i] for i in order])
    rank_of = dict(zip(order, midranks, strict=True))
    positive_rank_sum = sum(rank_of[i] for i, ok in enumerate(successes) if ok)
    u = positive_rank_sum - positives * (positives + 1) / 2
    return u / (positives * negatives)


def m8e1_average_precision(confidences: Sequence[float], successes: Sequence[bool]) -> float:
    """Average precision for success prediction, ties grouped per distinct score.

    A fully tied signal degenerates to the prevalence instead of depending on
    sort order — the honest chance baseline for a signal that separates nothing.
    """
    if not confidences or len(confidences) != len(successes):
        raise ValueError("confidences must align with outcomes")
    positives = sum(successes)
    if positives == 0:
        raise ValueError("average precision is undefined when no observation succeeded")
    order = sorted(range(len(confidences)), key=lambda i: -confidences[i])
    average_precision = 0.0
    seen_positive = 0
    seen = 0
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and confidences[order[j + 1]] == confidences[order[i]]:
            j += 1
        group = order[i : j + 1]
        group_positives = sum(successes[k] for k in group)
        seen += len(group)
        seen_positive += group_positives
        if group_positives:
            average_precision += (seen_positive / seen) * (group_positives / positives)
        i = j + 1
    return average_precision


def _bin_edges(n_bins: int) -> list[tuple[float, float]]:
    width = 1.0 / n_bins
    edges = [(i * width, (i + 1) * width) for i in range(n_bins)]
    lower, upper = edges[-1]
    edges[-1] = (lower, math.nextafter(upper, math.inf))  # confidence 1.0 is binned
    return edges


def m8e1_signal_ece(
    confidences: Sequence[float], successes: Sequence[bool], n_bins: int = 10
) -> float:
    """Calibration error of the signal treated as P(success).

    The issue's calibration measure for variation signals: an agreement score
    is only a *probability* if its empirical success rate matches it, bin by
    bin, against observed outcomes.
    """
    if not confidences or len(confidences) != len(successes):
        raise ValueError("confidences must align with outcomes")
    if n_bins <= 0:
        raise ValueError("n_bins must be positive")
    total = len(confidences)
    ece = 0.0
    for lower, upper in _bin_edges(n_bins):
        bucket = [
            (c, ok) for c, ok in zip(confidences, successes, strict=True) if lower <= c < upper
        ]
        if not bucket:
            continue
        mean_claimed = sum(c for c, _ in bucket) / len(bucket)
        accuracy = sum(float(ok) for _, ok in bucket) / len(bucket)
        ece += (len(bucket) / total) * abs(accuracy - mean_claimed)
    return ece


# ---------------------------------------------------------------------------
# Cost and latency accounting (#930)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SamplingCost:
    """Token bill of k-fold sampling against the single-shot baseline."""

    samples: int
    tokens_per_sample: int
    single_shot_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.samples * self.tokens_per_sample

    @property
    def cost_multiple(self) -> float:
        """Total sampled tokens over the single-shot token bill."""
        return self.total_tokens / self.single_shot_tokens


def m8e1_sampling_cost(
    samples: int, tokens_per_sample: int, single_shot_tokens: int | None = None
) -> SamplingCost:
    """Account the token cost of k samples vs the one-shot decision they replace.

    The comparison tables must carry this next to every AUROC point: a
    discrimination gain bought with k samples is a k-fold token bill, not a
    free upgrade.
    """
    if samples < 1:
        raise ValueError("samples must be at least 1")
    if tokens_per_sample < 1:
        raise ValueError("tokens_per_sample must be positive")
    baseline = tokens_per_sample if single_shot_tokens is None else single_shot_tokens
    if baseline < 1:
        raise ValueError("single_shot_tokens must be positive")
    return SamplingCost(
        samples=samples,
        tokens_per_sample=tokens_per_sample,
        single_shot_tokens=baseline,
    )


def m8e1_latency_ms(samples: int, per_call_ms: float, parallelism: int = 1) -> float:
    """Deterministic latency model: ceil(samples / parallelism) sequential rounds.

    A cost model, not a wall-clock measurement: the orchestrator's fan-out
    bounds k-fold latency at ceil(k / parallelism) times the per-call latency,
    and this function exists so the benchmark reports that bound honestly.
    """
    if samples < 1:
        raise ValueError("samples must be at least 1")
    if per_call_ms < 0.0:
        raise ValueError("per_call_ms must be non-negative")
    if parallelism < 1:
        raise ValueError("parallelism must be at least 1")
    rounds = math.ceil(samples / parallelism)
    return rounds * per_call_ms


# ---------------------------------------------------------------------------
# Difficulty correlation (#930)
# ---------------------------------------------------------------------------


def _rankdata(values: Sequence[float]) -> list[float]:
    """Mid-ranks for an arbitrary sequence, ties sharing the average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    midranks = _midranks([values[i] for i in order])
    rank_of = dict(zip(order, midranks, strict=True))
    return [rank_of[i] for i in range(len(values))]


def m8e1_spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Tie-aware Spearman rank correlation (Pearson on mid-ranks)."""
    if not xs or len(xs) != len(ys):
        raise ValueError("correlation needs aligned, non-empty sequences")
    if len(xs) < 2:
        raise ValueError("correlation needs at least two observations")
    rank_x = _rankdata(list(xs))
    rank_y = _rankdata(list(ys))
    n = len(xs)
    mean_x = sum(rank_x) / n
    mean_y = sum(rank_y) / n
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(rank_x, rank_y, strict=True))
    var_x = sum((a - mean_x) ** 2 for a in rank_x)
    var_y = sum((b - mean_y) ** 2 for b in rank_y)
    if var_x == 0.0 or var_y == 0.0:
        raise ValueError("correlation is undefined when one variable is constant")
    return cov / math.sqrt(var_x * var_y)


def m8e1_difficulty_error_correlation(
    decisions: Sequence[SampledDecision], signal: str = "semantic_confidence"
) -> float:
    """Spearman correlation of task difficulty with the signal's predicted error.

    The issue's difficulty measure: does the variation signal *rise* as tasks
    get harder? Predicted error is (1 - confidence), so a useful signal
    correlates positively with difficulty.
    """
    if not decisions:
        raise ValueError("difficulty correlation needs at least one decision")
    difficulties = [d.difficulty for d in decisions]
    predicted_error = [1.0 - m8e1_confidence(d, signal) for d in decisions]
    return m8e1_spearman(difficulties, predicted_error)


# ---------------------------------------------------------------------------
# Comparison driver (#930): the calibration-benchmark table
# ---------------------------------------------------------------------------


def m8e1_compare(decisions: Sequence[SampledDecision]) -> tuple[ComparisonRow, ...]:
    """Score every registered signal against observed outcomes, best first.

    Returns one :class:`ComparisonRow` per name in :data:`SIGNALS`, sorted by
    error-prediction AUROC descending. Every field is a measurement; the table
    proposes nothing and never acts.
    """
    if not decisions:
        raise ValueError("comparison needs at least one decision")
    successes = [d.success for d in decisions]
    rows: list[ComparisonRow] = []
    for signal in SIGNALS:
        confidences = [m8e1_confidence(d, signal) for d in decisions]
        error_scores = [1.0 - c for c in confidences]
        failures = [not s for s in successes]
        rows.append(
            ComparisonRow(
                signal=signal,
                error_auroc=m8e1_auroc(error_scores, failures),
                error_auprc=m8e1_average_precision(error_scores, failures),
                ece=m8e1_signal_ece(confidences, successes),
                mean_confidence=sum(confidences) / len(confidences),
                # Self-report consumes only the served single sample; sampled
                # signals pay the mean k-fold bill.
                cost_multiple=(
                    1.0
                    if signal == "self_report"
                    else sum(len(d.answers) for d in decisions) / len(decisions)
                ),
            )
        )
    # Stable sort: equal-AUROC signals keep the register order, so the table
    # is deterministic across runs and Python versions.
    return tuple(sorted(rows, key=lambda r: -r.error_auroc))


# ---------------------------------------------------------------------------
# Deterministic synthetic corpora — fixtures for the metric math, NOT results
# ---------------------------------------------------------------------------


def m8e1_variation_corpus(
    seed: int = 930,
    n: int = 240,
    k: int = 8,
    temperature: float = 1.0,
    family: str = "alpha",
    mirage_share: float = 0.0,
) -> list[SampledDecision]:
    """A fixed synthetic corpus of judged k-sample decisions.

    Per task: a difficulty draw sets skill (harder = lower); the observed
    outcome is drawn from skill; the k sample answers are drawn i.i.d. from a
    distribution whose gold mass is ``skill ** temperature`` — so temperature
    above 1 flattens the sample distribution (more variation, same skill) and
    below 1 sharpens it. ``mirage_share`` of the tasks are *mirage* tasks: the
    model converges confidently on a single wrong answer (success always
    false), the documented failure mode that agreement-family signals cannot
    see. Everything is deterministic under ``seed``.
    """
    if family not in FAMILY_SKILL:
        raise ValueError(f"unknown family {family!r}; expected one of {sorted(FAMILY_SKILL)}")
    if n < 1:
        raise ValueError("corpus needs at least one decision")
    if k < 1:
        raise ValueError("corpus needs at least one sample per decision")
    if temperature <= 0.0:
        raise ValueError("temperature must be positive")
    if not 0.0 <= mirage_share <= 1.0:
        raise ValueError("mirage_share must be in [0, 1]")
    base = FAMILY_SKILL[family]
    bias = FAMILY_CLAIMED_BIAS[family]
    mirage_n = math.floor(n * mirage_share)

    def clamp01(value: float) -> float:
        return min(1.0, max(0.0, value))

    corpus: list[SampledDecision] = []
    for i in range(n):
        rng = random.Random(f"{seed}:{i}")
        if i < mirage_n:
            # Mirage: converged on one wrong answer, confidently claimed.
            answers = tuple(f"wrong-{i}-a" if rng.random() < 0.9 else f"gold-{i}" for _ in range(k))
            corpus.append(
                SampledDecision(
                    task_id=f"t{i}",
                    family=family,
                    difficulty=0.9,
                    temperature=temperature,
                    claimed=0.95,
                    success=False,
                    answers=answers,
                )
            )
            continue
        difficulty = rng.random()
        skill = clamp01(base * (1.0 - 0.6 * difficulty))
        success = rng.random() < skill
        claimed = clamp01(rng.gauss(min(1.0, skill + bias), 0.08))
        p_gold = clamp01(skill**temperature)
        distractor_mass = (1.0 - p_gold) / 3
        cumulative = [
            p_gold,
            p_gold + distractor_mass,
            p_gold + 2 * distractor_mass,
        ]
        answers = []
        for _ in range(k):
            draw = rng.random()
            choice = sum(draw > edge for edge in cumulative)
            answers.append(f"gold-{i}" if choice == 0 else f"wrong-{i}-{choice - 1}")
        corpus.append(
            SampledDecision(
                task_id=f"t{i}",
                family=family,
                difficulty=difficulty,
                temperature=temperature,
                claimed=claimed,
                success=success,
                answers=tuple(answers),
            )
        )
    return corpus


# ---------------------------------------------------------------------------
# Tests: variation signal math
# ---------------------------------------------------------------------------


class TestVariationSignals:
    def test_self_consistency_extremes_and_partial(self) -> None:
        assert m8e1_self_consistency(["a", "a", "a"]) == pytest.approx(1.0)
        assert m8e1_self_consistency(["a", "b", "c"]) == pytest.approx(1 / 3)
        assert m8e1_self_consistency(["a", "a", "b"]) == pytest.approx(2 / 3)
        with pytest.raises(ValueError, match="at least one"):
            m8e1_self_consistency([])

    def test_pairwise_disagreement_hand_values(self) -> None:
        assert m8e1_pairwise_disagreement(["a", "a", "a"]) == pytest.approx(0.0)
        assert m8e1_pairwise_disagreement(["a", "a", "b"]) == pytest.approx(2 / 3)
        assert m8e1_pairwise_disagreement(["a", "b", "c"]) == pytest.approx(1.0)
        # Hand-checked: C(5,2)=10 pairs, only the two intra-count pairs agree.
        assert m8e1_pairwise_disagreement(["a", "a", "b", "b", "c"]) == pytest.approx(0.8)
        with pytest.raises(ValueError, match="at least one"):
            m8e1_pairwise_disagreement([])

    def test_disagreement_plus_agreement_probability_is_one(self) -> None:
        # The identity that makes the pairwise metric a probability: the
        # disagreement rate plus the chance two random samples agree is 1.
        answers = ["a", "a", "b", "b", "c"]
        counts = Counter(answers)
        k = len(answers)
        agreement = sum(c * (c - 1) for c in counts.values()) / (k * (k - 1))
        assert m8e1_pairwise_disagreement(answers) == pytest.approx(1.0 - agreement)

    def test_distinct_ratio_hand_values(self) -> None:
        assert m8e1_distinct_ratio(["a", "a", "b"]) == pytest.approx(2 / 3)
        assert m8e1_distinct_ratio(["a", "a", "a"]) == pytest.approx(1 / 3)
        assert m8e1_distinct_ratio(["a", "b", "c"]) == pytest.approx(1.0)
        with pytest.raises(ValueError, match="at least one"):
            m8e1_distinct_ratio([])

    def test_semantic_clusters_merge_equivalent_answers(self) -> None:
        # Surface forms differ; the semantic identity is shared by three.
        answers = ["1,000", "1000", "one thousand", "999"]
        equivalence = lambda a: {"1,000": "1000", "one thousand": "1000"}.get(a, a)  # noqa: E731
        assert m8e1_semantic_clusters(answers, equivalence) == pytest.approx((0.75, 0.25))
        # Without the equivalence, all four surface forms stay distinct.
        assert m8e1_semantic_clusters(answers) == pytest.approx((0.25, 0.25, 0.25, 0.25))

    def test_semantic_entropy_and_confidence_hand_values(self) -> None:
        answers = ["1,000", "1000", "one thousand", "999"]
        equivalence = lambda a: {"1,000": "1000", "one thousand": "1000"}.get(a, a)  # noqa: E731
        merged_entropy = m8e1_semantic_entropy(answers, equivalence)
        assert 0.0 < merged_entropy < math.log(4)
        # 1 - H/ln(k) with hand-checked binomial entropy H = -(3/4 ln 3/4 + 1/4 ln 1/4).
        expected = 1.0 - (-(0.75 * math.log(0.75) + 0.25 * math.log(0.25))) / math.log(4)
        assert m8e1_semantic_confidence(answers, equivalence) == pytest.approx(expected)
        # One cluster: zero entropy, full confidence. Uniform spread over k: full
        # entropy, zero confidence.
        assert m8e1_semantic_entropy(["a", "a"], equivalence) == pytest.approx(0.0)
        assert m8e1_semantic_confidence(["a", "a"], equivalence) == pytest.approx(1.0)
        assert m8e1_semantic_confidence(["a", "b", "c", "d"], equivalence) == pytest.approx(0.0)
        with pytest.raises(ValueError, match="at least one"):
            m8e1_semantic_confidence([], equivalence)

    def test_default_equivalence_normalizes_surface_noise(self) -> None:
        # Case and whitespace differences are the same meaning by default;
        # the default equivalence stays deliberately conservative beyond that.
        assert m8e1_semantic_clusters(["Yes", "yes ", "  YES"]) == pytest.approx((1.0,))
        assert m8e1_semantic_clusters(["1,000", "1000"]) == pytest.approx((0.5, 0.5))

    def test_equivalence_function_is_load_bearing(self) -> None:
        # The same samples score differently under different equivalence maps:
        # what counts as "the same meaning" is a modeling decision the
        # benchmark must report, not a property of the samples.
        answers = ["1,000", "1000"]
        merge = lambda a: "1000"  # noqa: E731
        split = lambda a: a  # noqa: E731
        assert m8e1_semantic_confidence(answers, merge) == pytest.approx(1.0)
        assert m8e1_semantic_confidence(answers, split) == pytest.approx(0.0)

    def test_polysemy_blind_spot_needs_meaning_aware_clustering(self) -> None:
        # Identical strings cannot be split by any string->id equivalence:
        # three "bank" samples are one cluster with full confidence even when
        # the model means different things. Real semantic entropy needs a
        # context-aware clusterer; pre-tagging answers with their sense shows
        # the seam this harness would plug it into.
        polysemous = ["bank", "bank", "bank"]
        assert m8e1_semantic_confidence(polysemous) == pytest.approx(1.0)
        sense_tagged = ["bank#river", "bank#money", "bank#river"]
        assert m8e1_semantic_confidence(sense_tagged) == pytest.approx(
            1.0 - (-(2 / 3 * math.log(2 / 3) + 1 / 3 * math.log(1 / 3))) / math.log(3)
        )

    def test_single_sample_reports_no_variation_evidence(self) -> None:
        # Every sampled signal on one sample: no disagreement observed, full
        # confidence — absence of evidence, not evidence of certainty.
        assert m8e1_self_consistency(["a"]) == pytest.approx(1.0)
        assert m8e1_pairwise_disagreement(["a"]) == pytest.approx(0.0)
        assert m8e1_distinct_ratio(["a"]) == pytest.approx(1.0)
        assert m8e1_semantic_confidence(["a"]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Tests: discrimination and calibration measures
# ---------------------------------------------------------------------------


class TestDiscriminationAndCalibration:
    def test_auroc_extremes_ties_and_single_class(self) -> None:
        assert m8e1_auroc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]) == pytest.approx(1.0)
        assert m8e1_auroc([0.1, 0.2, 0.8, 0.9], [True, True, False, False]) == pytest.approx(0.0)
        assert m8e1_auroc([0.5, 0.5], [True, False]) == pytest.approx(0.5)
        with pytest.raises(ValueError, match="undefined"):
            m8e1_auroc([0.5, 0.6], [True, True])
        with pytest.raises(ValueError, match="align"):
            m8e1_auroc([], [])
        with pytest.raises(ValueError, match="align"):
            m8e1_auroc([0.5], [True, False])

    def test_average_precision_extremes_and_tied_prevalence(self) -> None:
        assert m8e1_average_precision([0.9, 0.1, 0.1], [True, False, False]) == pytest.approx(1.0)
        # Fully tied: group-wise averaging degenerates to the prevalence (1/2).
        assert m8e1_average_precision([0.5, 0.5, 0.5, 0.5], [True, True, False, False]) == (
            pytest.approx(0.5)
        )
        with pytest.raises(ValueError, match="no observation succeeded"):
            m8e1_average_precision([0.5, 0.6], [False, False])

    def test_signal_ece_hand_values(self) -> None:
        # Constant 1.0 confidence with half the tasks succeeding: the top bin
        # (inclusive of 1.0) holds everything, |accuracy - confidence| = 0.5.
        half = [i % 2 == 0 for i in range(20)]
        assert m8e1_signal_ece([1.0] * 20, half) == pytest.approx(0.5)
        # Perfectly calibrated two-point fixture: ECE collapses to 0.
        assert m8e1_signal_ece([0.0, 1.0], [False, True]) == pytest.approx(0.0)
        with pytest.raises(ValueError, match="positive"):
            m8e1_signal_ece([0.5], [True], n_bins=0)
        with pytest.raises(ValueError, match="align"):
            m8e1_signal_ece([0.5, 0.6], [True])

    def test_signal_confidences_stay_bounded_on_corpus(self) -> None:
        for decision in m8e1_variation_corpus(n=60):
            for signal in SIGNALS:
                value = m8e1_confidence(decision, signal)
                assert 0.0 <= value <= 1.0, (signal, decision.task_id, value)


# ---------------------------------------------------------------------------
# Tests: synthetic corpora and the comparison table
# ---------------------------------------------------------------------------


class TestCorpusComparison:
    def test_corpus_is_deterministic_and_shaped(self) -> None:
        first = m8e1_variation_corpus(seed=930, n=40, k=5)
        second = m8e1_variation_corpus(seed=930, n=40, k=5)
        assert first == second
        other = m8e1_variation_corpus(seed=931, n=40, k=5)
        assert first != other
        assert len(first) == 40
        assert all(len(d.answers) == 5 for d in first)
        mixed = m8e1_variation_corpus(seed=930, n=60)
        assert any(d.success for d in mixed)
        assert any(not d.success for d in mixed)

    def test_corpus_rejects_degenerate_arguments(self) -> None:
        with pytest.raises(ValueError, match="family"):
            m8e1_variation_corpus(family="ghost")
        with pytest.raises(ValueError, match="at least one decision"):
            m8e1_variation_corpus(n=0)
        with pytest.raises(ValueError, match="at least one sample"):
            m8e1_variation_corpus(k=0)
        with pytest.raises(ValueError, match="temperature"):
            m8e1_variation_corpus(temperature=0.0)
        with pytest.raises(ValueError, match="mirage_share"):
            m8e1_variation_corpus(mirage_share=1.5)

    def test_comparison_rows_sorted_and_complete(self) -> None:
        rows = m8e1_compare(m8e1_variation_corpus(seed=930, n=80))
        assert [r.signal for r in rows] == sorted(
            [r.signal for r in rows],
            key=lambda s: -next(r.error_auroc for r in rows if r.signal == s),
        )
        assert {r.signal for r in rows} == set(SIGNALS)
        for row in rows:
            assert 0.0 <= row.error_auroc <= 1.0
            assert 0.0 <= row.error_auprc <= 1.0
            assert 0.0 <= row.ece <= 1.0
            assert 0.0 <= row.mean_confidence <= 1.0
        with pytest.raises(ValueError, match="at least one decision"):
            m8e1_compare([])

    def test_semantic_confidence_outranks_surface_self_consistency_under_synonym_noise(
        self,
    ) -> None:
        # Hand-built by construction: successes vary only in surface form of one
        # meaning; failures are genuinely different answers. Surface
        # self-consistency ties everything at 0.5 (error AUROC = chance);
        # semantic clustering separates the classes fully.
        decisions = [
            SampledDecision("s1", "alpha", 0.3, 1.0, 0.9, True, ("1,000", "1000")),
            SampledDecision("s2", "alpha", 0.3, 1.0, 0.9, True, ("one thousand", "1000")),
            SampledDecision("f1", "alpha", 0.3, 1.0, 0.9, False, ("wrong-a", "wrong-b")),
            SampledDecision("f2", "alpha", 0.3, 1.0, 0.9, False, ("wrong-c", "wrong-d")),
        ]
        merge_numbers = lambda a: {"1,000": "1000", "one thousand": "1000"}.get(a, a)  # noqa: E731
        surface = [m8e1_self_consistency(d.answers) for d in decisions]
        assert surface == [0.5, 0.5, 0.5, 0.5]
        assert m8e1_auroc([1.0 - c for c in surface], [not d.success for d in decisions]) == (
            pytest.approx(0.5)
        )
        semantic = [m8e1_semantic_confidence(d.answers, merge_numbers) for d in decisions]
        assert semantic == [1.0, 1.0, 0.0, 0.0]
        assert m8e1_auroc([1.0 - c for c in semantic], [not d.success for d in decisions]) == (
            pytest.approx(1.0)
        )

    def test_mirage_corpus_inverts_agreement_signals(self) -> None:
        # The documented blind spot: when repeated sampling *converges on a
        # wrong answer*, agreement is maximal exactly where the model fails, so
        # every confidence-oriented signal — including the variation family —
        # ranks error below chance. Repeated sampling detects indecision, not
        # confident convergence; that residual risk belongs to the
        # heterogeneous-family comparison (M8-E3, #932), not to k samples of
        # one model.
        decisions = [
            SampledDecision(f"m{i}", "alpha", 0.9, 1.0, 0.95, False, ("wrong",) * 4)
            for i in range(3)
        ] + [
            SampledDecision(
                f"h{i}", "alpha", 0.3, 1.0, 0.55, True, ("gold", "gold", "gold", "other")
            )
            for i in range(3)
        ]
        rows = m8e1_compare(decisions)
        by_signal = {r.signal: r for r in rows}
        assert by_signal["self_consistency"].error_auroc < 0.5
        assert by_signal["pairwise_agreement"].error_auroc < 0.5
        assert by_signal["self_report"].error_auroc < 0.5

    def test_temperature_sharpens_variation_discrimination(self) -> None:
        # Same difficulty/success stream (identical seed, same rng call order);
        # only the sample-distribution sharpness differs. Sharper samples =>
        # agreement tracks the outcome better => higher success AUROC for the
        # sampled signals. Self-report never sees the samples, so it is the
        # unchanged control.
        low = m8e1_variation_corpus(seed=930, n=200, k=8, temperature=0.6)
        high = m8e1_variation_corpus(seed=930, n=200, k=8, temperature=1.6)
        for signal in ("self_consistency", "semantic_confidence", "pairwise_agreement"):
            auroc_low = m8e1_auroc(
                [m8e1_confidence(d, signal) for d in low], [d.success for d in low]
            )
            auroc_high = m8e1_auroc(
                [m8e1_confidence(d, signal) for d in high], [d.success for d in high]
            )
            assert auroc_low > auroc_high, signal
        # The control: claimed confidence is temperature-independent here.
        assert [d.claimed for d in low] == [d.claimed for d in high]

    def test_model_family_changes_the_signal_landscape(self) -> None:
        alpha = m8e1_variation_corpus(seed=930, n=120, k=8, family="alpha")
        beta = m8e1_variation_corpus(seed=930, n=120, k=8, family="beta")
        alpha_rows = {r.signal: r for r in m8e1_compare(alpha)}
        beta_rows = {r.signal: r for r in m8e1_compare(beta)}
        # The lower-skill family scatters more: lower mean agreement.
        assert (
            beta_rows["self_consistency"].mean_confidence
            < alpha_rows["self_consistency"].mean_confidence
        )
        # ...and its signals separate outcomes less well (beta is the harder
        # family: more scatter compresses the confidence range).
        assert (
            beta_rows["semantic_confidence"].error_auroc
            < alpha_rows["semantic_confidence"].error_auroc
        )

    def test_variation_signals_track_task_difficulty(self) -> None:
        corpus = m8e1_variation_corpus(seed=930, n=240, k=8)
        observed_error = [float(not d.success) for d in corpus]
        # Generator truth: difficulty lowers skill, so difficulty correlates
        # with observed error (harness input sanity).
        assert m8e1_spearman([d.difficulty for d in corpus], observed_error) > 0.2
        # The issue's measure: predicted error from the variation signals must
        # rise with difficulty too.
        for signal in ("self_consistency", "semantic_confidence", "pairwise_agreement"):
            correlation = m8e1_difficulty_error_correlation(corpus, signal)
            assert correlation > 0.2, signal

    def test_spearman_hand_values_and_degenerate_inputs(self) -> None:
        assert m8e1_spearman([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]) == pytest.approx(1.0)
        assert m8e1_spearman([1.0, 2.0, 3.0], [30.0, 20.0, 10.0]) == pytest.approx(-1.0)
        # Ties average ranks: x ranks [1, 2.5, 2.5, 4] vs y ranks [3, 1, 2, 4]
        # give Pearson-on-ranks 1.5 / sqrt(4.5 * 5).
        assert m8e1_spearman([1.0, 2.0, 2.0, 4.0], [3.0, 1.0, 2.0, 4.0]) == pytest.approx(
            1.5 / math.sqrt(4.5 * 5.0)
        )
        with pytest.raises(ValueError, match="aligned"):
            m8e1_spearman([], [])
        with pytest.raises(ValueError, match="at least two"):
            m8e1_spearman([1.0], [2.0])
        with pytest.raises(ValueError, match="constant"):
            m8e1_spearman([1.0, 1.0], [1.0, 2.0])

    def test_comparison_is_deterministic_across_runs(self) -> None:
        decisions = m8e1_variation_corpus(seed=930, n=80)
        assert m8e1_compare(decisions) == m8e1_compare(decisions)


# ---------------------------------------------------------------------------
# Tests: sampling cost and latency accounting
# ---------------------------------------------------------------------------


class TestSamplingCost:
    def test_sampling_cost_hand_values(self) -> None:
        cost = m8e1_sampling_cost(samples=8, tokens_per_sample=48)
        assert cost.total_tokens == 384
        assert cost.cost_multiple == pytest.approx(8.0)  # k-fold vs one-shot
        explicit = m8e1_sampling_cost(samples=8, tokens_per_sample=48, single_shot_tokens=96)
        assert explicit.cost_multiple == pytest.approx(4.0)
        with pytest.raises(ValueError, match="at least 1"):
            m8e1_sampling_cost(samples=0, tokens_per_sample=48)
        with pytest.raises(ValueError, match="positive"):
            m8e1_sampling_cost(samples=2, tokens_per_sample=0)

    def test_latency_model_hand_values(self) -> None:
        assert m8e1_latency_ms(8, 700.0) == pytest.approx(5600.0)  # sequential bound
        assert m8e1_latency_ms(8, 700.0, parallelism=4) == pytest.approx(1400.0)
        assert m8e1_latency_ms(9, 700.0, parallelism=4) == pytest.approx(2100.0)  # ceil rounds up
        assert m8e1_latency_ms(1, 700.0) == pytest.approx(700.0)
        with pytest.raises(ValueError, match="at least 1"):
            m8e1_latency_ms(0, 700.0)
        with pytest.raises(ValueError, match="non-negative"):
            m8e1_latency_ms(2, -1.0)
        with pytest.raises(ValueError, match="parallelism"):
            m8e1_latency_ms(2, 700.0, parallelism=0)

    def test_comparison_rows_carry_the_sampling_cost(self) -> None:
        decisions = m8e1_variation_corpus(seed=930, n=30, k=6)
        rows = {r.signal: r for r in m8e1_compare(decisions)}
        # Every sampled signal pays the same k-fold bill; the self-report
        # baseline costs one sample by definition.
        assert rows["self_consistency"].cost_multiple == pytest.approx(6.0)
        assert rows["semantic_confidence"].cost_multiple == pytest.approx(6.0)
        assert rows["pairwise_agreement"].cost_multiple == pytest.approx(6.0)
        assert rows["self_report"].cost_multiple == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Tests: the evidence-only trust boundary holds by construction
# ---------------------------------------------------------------------------


class TestEvidenceOnlyContract:
    def test_harness_declares_itself_advisory(self) -> None:
        assert ADVISORY_ONLY is True

    def test_harness_imports_no_maistro_module(self) -> None:
        # Structural guardrail: this research artifact must stay import-free of
        # the product, so it cannot become an authority by accident (M8
        # guardrails 1-2). Asserted against this file's own AST.
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("maistro") for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("maistro")

    def test_records_are_frozen(self) -> None:
        decision = SampledDecision("t", "alpha", 0.5, 1.0, 0.5, True, ("a", "a"))
        with pytest.raises(AttributeError):
            decision.success = False  # type: ignore[misc]
        row = ComparisonRow("s", 0.5, 0.5, 0.0, 0.5, 1.0)
        with pytest.raises(AttributeError):
            row.error_auroc = 1.0  # type: ignore[misc]

    def test_sampled_decision_rejects_degenerate_records(self) -> None:
        with pytest.raises(ValueError, match="at least one answer"):
            SampledDecision("t", "alpha", 0.5, 1.0, 0.5, True, ())
        with pytest.raises(ValueError, match="claimed"):
            SampledDecision("t", "alpha", 0.5, 1.0, 1.5, True, ("a",))
        with pytest.raises(ValueError, match="difficulty"):
            SampledDecision("t", "alpha", 1.5, 1.0, 0.5, True, ("a",))
        with pytest.raises(ValueError, match="temperature"):
            SampledDecision("t", "alpha", 0.5, 0.0, 0.5, True, ("a",))
        with pytest.raises(ValueError, match="tokens_per_sample"):
            SampledDecision("t", "alpha", 0.5, 1.0, 0.5, True, ("a",), tokens_per_sample=0)
        with pytest.raises(ValueError, match="non-negative"):
            SampledDecision("t", "alpha", 0.5, 1.0, 0.5, True, ("a",), per_call_latency_ms=-1.0)

    def test_comparison_rows_are_measurements_not_actions(self) -> None:
        rows = m8e1_compare(m8e1_variation_corpus(seed=930, n=30))
        for row in rows:
            for value in vars(row).values():
                assert not callable(value)
            assert set(vars(row)) == {
                "signal",
                "error_auroc",
                "error_auprc",
                "ece",
                "mean_confidence",
                "cost_multiple",
            }

    def test_unknown_signal_raises_instead_of_falling_back(self) -> None:
        decision = SampledDecision("t", "alpha", 0.5, 1.0, 0.5, True, ("a", "a"))
        with pytest.raises(ValueError, match="unknown signal"):
            m8e1_confidence(decision, "vibes")
