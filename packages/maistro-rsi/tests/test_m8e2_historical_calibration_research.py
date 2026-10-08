"""M8-E2 research harness — historical Run-outcome calibration of confidence.

Leaf #931 (epic #904, initiative #879). Hypothesis under study: historical
success/failure evidence by task/model/tool context can produce better
calibrated confidence estimates than prompt-time self-report alone.

This module is a RESEARCH ARTIFACT, not product code. The epic-level harness
(``test_m8e_uncertainty_calibration_research.py``) already implements one
Beta-smoothed history estimator plus the shared metric math; this leaf module
is the *comparative study* that leaf defines: it fits several estimator
families — frequency, Bayesian (Beta posterior), Platt scaling, histogram-bin
recalibration, and a small logistic model over self-report + history features
— and scores every one of them, alongside the raw-self-report and
no-confidence baselines, on held-out data under a strict chronological split.

Feature shape. The estimators consume the outcome seam's rows (ADR-017,
``packages/maistro-core/src/maistro/memory/outcomes.py``): a canonical Run
outcome records ``task_type``, ``model_used``, tool-call presence, and the
observed ``success`` bit. :class:`RunOutcome` mirrors that shape and adds the
prompt-time self-reported confidence, so every estimator input is (context,
self-report, observed outcome) — the exact triple the epic's benchmark
procedure names for this leaf.

What is measured (the leaf's Measure list, one test class each):

- expected calibration error and Brier score (:class:`TestMetricArithmetic`);
- error discrimination, AUROC/AUPRC (:class:`TestMetricArithmetic`);
- data volume required (:class:`TestDataVolume`);
- drift sensitivity (:class:`TestDriftSensitivity`);
- subgroup/task-family calibration (:class:`TestSubgroupCalibration`);
- maintenance cost (:class:`TestMaintenanceCost`).

Trust boundary (epic contract, enforced by construction):

- Observed outcomes are the only judge. Self-reported confidence is one
  signal among several and is always scored against ground truth.
- Every number produced here is ADVISORY EVIDENCE. Nothing in this module
  reads or writes a Goal, a Run authority, a routing decision, or a
  Warden/HITL/delegation control; it imports nothing from ``maistro`` at all
  (M8 guardrails 1-2), and every record is a frozen dataclass, so evidence
  cannot be mutated into authorization after the fact.
- Confidence remains advisory until separately adopted: the estimators return
  plain floats in [0, 1] and nothing else — no actions, no thresholds with
  authority, no routing decisions.

The synthetic corpora below are deterministic fixtures for validating the
study machinery and isolating its variables. They are NOT experimental
results about real models and must never be quoted as such; the disposition
recorded in ``docs/research/931-historical-outcome-calibration.md`` therefore
stays WATCH until the study runs on a real exported outcome corpus.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import pytest

#: Explicit evidence-only contract marker. Asserted by a test so it cannot
#: silently rot; nothing outside this module may treat M8-E2 output as
#: authorization (ADR-068 authorization paths and Warden/HITL remain canonical).
ADVISORY_ONLY = True


# ---------------------------------------------------------------------------
# Data model — the canonical outcome seam's shape, plus the self-report signal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunOutcome:
    """One judged Run: context features, the self-report, the observed outcome.

    Field names track the canonical outcome row (ADR-017 outcome store:
    ``task_type``, ``model_used``, ``tool_calls``, ``success``); ``claimed``
    is the prompt-time self-reported confidence in [0, 1] — a signal, never
    the truth — and ``seq`` is the Run's arrival order, which the temporal
    split requires so calibration can never see its own future.
    """

    task_family: str
    model_family: str
    claimed: float
    success: bool
    toolset: str = ""
    seq: int = 0

    def __post_init__(self) -> None:
        if not 0.0 <= self.claimed <= 1.0:
            raise ValueError(f"claimed confidence {self.claimed} outside [0, 1]")
        if self.seq < 0:
            raise ValueError("seq must be a non-negative arrival index")

    def context(self, *, model: bool = True, tool: bool = False) -> str:
        """The context key an estimator conditions on.

        The leaf names task/model/tool context, so the axes are selectable:
        calibration may be keyed on task family alone or on the full
        task/model/toolset key — coarser keys pool more data per cell, which
        is exactly the volume/subgroup trade the study measures.
        """
        parts = [self.task_family]
        if model:
            parts.append(self.model_family)
        if tool:
            parts.append(self.toolset or "no-tools")
        return "|".join(parts)


# ---------------------------------------------------------------------------
# Metrics — ECE, Brier, and tie-aware error discrimination
# ---------------------------------------------------------------------------


def m8e2_brier(scores: Sequence[float], outcomes: Sequence[bool]) -> float:
    """Brier score: mean squared error of predicted probabilities."""
    if not scores:
        raise ValueError("brier needs at least one observation")
    if len(scores) != len(outcomes):
        raise ValueError("score/outcome length mismatch")
    return sum((p - float(y)) ** 2 for p, y in zip(scores, outcomes, strict=True)) / len(scores)


def m8e2_ece(scores: Sequence[float], outcomes: Sequence[bool], n_bins: int = 10) -> float:
    """Expected calibration error over equal-width bins (top edge inclusive).

    |mean confidence - empirical accuracy| per bin, weighted by bin mass.
    """
    if n_bins <= 0:
        raise ValueError("n_bins must be positive")
    if not scores:
        raise ValueError("ece needs at least one observation")
    total = 0.0
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        idx = [i for i, p in enumerate(scores) if (lo <= p < hi) or (b == n_bins - 1 and p == 1.0)]
        if not idx:
            continue
        conf = sum(scores[i] for i in idx) / len(idx)
        acc = sum(float(outcomes[i]) for i in idx) / len(idx)
        total += (len(idx) / len(scores)) * abs(conf - acc)
    return total


def _midranks(scores: Sequence[float]) -> list[float]:
    """Average ranks, so tied scores contribute their midrank (tie-aware)."""
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        mid = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = mid
        i = j + 1
    return ranks


def m8e2_auroc(scores: Sequence[float], outcomes: Sequence[bool]) -> float:
    """Tie-aware AUROC of the scores as an error/success discriminator."""
    n_pos = sum(float(y) for y in outcomes)
    n_neg = len(outcomes) - n_pos
    if n_pos == 0 or n_neg == 0:
        raise ValueError("auroc needs both outcome classes")
    ranks = _midranks(scores)
    rank_sum_pos = sum(r for r, y in zip(ranks, outcomes, strict=True) if y)
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def m8e2_auprc(scores: Sequence[float], outcomes: Sequence[bool]) -> float:
    """Average precision over score-sorted tie groups (tie-group aware)."""
    n_pos = sum(float(y) for y in outcomes)
    if n_pos == 0 or n_pos == len(outcomes):
        raise ValueError("auprc needs both outcome classes")
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    ap = 0.0
    seen_pos = 0.0
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        group = order[i : j + 1]
        group_pos = sum(float(outcomes[k]) for k in group)
        seen_pos += group_pos
        precision = seen_pos / (j + 1)
        ap += precision * group_pos
        i = j + 1
    return ap / n_pos


# ---------------------------------------------------------------------------
# Temporal integrity — the leakage guard every fit below depends on
# ---------------------------------------------------------------------------


def m8e2_temporal_split(
    observations: Sequence[RunOutcome], train_fraction: float
) -> tuple[tuple[RunOutcome, ...], tuple[RunOutcome, ...]]:
    """Order-preserving chronological split: earlier Runs train, later Runs judge.

    Fitting historical calibration on anything newer than the evaluation
    window leaks the future into the fit — the leaf's central validity
    requirement. This is the only split the study uses.
    """
    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must be in (0, 1)")
    if not observations:
        raise ValueError("split needs at least one observation")
    ordered = sorted(observations, key=lambda o: o.seq)
    cut = max(1, math.floor(len(ordered) * train_fraction))
    return tuple(ordered[:cut]), tuple(ordered[cut:])


# ---------------------------------------------------------------------------
# Estimator families
# ---------------------------------------------------------------------------


class M8E2Estimator:
    """A fitted probability estimator: ``predict`` returns a float in [0, 1].

    Everything an estimator knows comes from ``fit``; predictions are plain
    floats and nothing else (evidence-only contract).
    """

    def predict(self, observation: RunOutcome) -> float:
        raise NotImplementedError

    def predict_all(self, observations: Sequence[RunOutcome]) -> list[float]:
        return [self.predict(o) for o in observations]


@dataclass(frozen=True)
class CalibrationCost:
    """The maintenance ledger the leaf's Measure list requires.

    ``stored_floats`` is the fitted state size (what a production system
    would persist and reload), ``contexts_tracked`` the cardinality of the
    context table (the state-explosion hazard), ``train_observations`` the
    fit cost, and ``retrain_policy`` the recorded freshness trigger — a
    frozen calibrator's quality is only as good as its retraining discipline
    (measured by :class:`TestDriftSensitivity`).
    """

    estimator: str
    stored_floats: int
    contexts_tracked: int
    train_observations: int
    retrain_policy: str


class BaseRateEstimator(M8E2Estimator):
    """The no-confidence baseline: always predict the train base rate."""

    def __init__(self) -> None:
        self._rate = 0.5

    def fit(self, train: Sequence[RunOutcome]) -> BaseRateEstimator:
        if not train:
            raise ValueError("fit needs at least one observation")
        self._rate = sum(float(o.success) for o in train) / len(train)
        return self

    def predict(self, observation: RunOutcome) -> float:
        return self._rate

    def cost(self) -> CalibrationCost:
        return CalibrationCost("base-rate", 1, 0, 0, "refit on corpus append")


class SelfReportEstimator(M8E2Estimator):
    """The raw-model-confidence baseline: predict the self-report unchanged.

    Not fitted — it is the baseline the leaf compares every learned
    estimator against, and the thing the epic's contract says must be
    *judged*, not trusted. ``fit`` accepts and ignores the training split so
    every estimator shares one factory interface.
    """

    def fit(self, train: Sequence[RunOutcome]) -> SelfReportEstimator:
        if not train:
            raise ValueError("fit needs at least one observation")
        return self

    def predict(self, observation: RunOutcome) -> float:
        return observation.claimed

    def cost(self) -> CalibrationCost:
        return CalibrationCost("self-report", 0, 0, 0, "none (no fit)")


class _ContextTable(M8E2Estimator):
    """Shared machinery for the per-context frequency/Bayesian estimators."""

    def __init__(self, *, min_context_samples: int = 1) -> None:
        if min_context_samples < 1:
            raise ValueError("min_context_samples must be >= 1")
        self._min = min_context_samples
        self._rates: dict[str, float] = {}
        self._counts: dict[str, int] = {}
        self._base_rate = 0.5
        self._name = "context-table"

    def _fit_table(self, train: Sequence[RunOutcome], key: Callable[[RunOutcome], str]) -> None:
        if not train:
            raise ValueError("fit needs at least one observation")
        self._base_rate = sum(float(o.success) for o in train) / len(train)
        successes: dict[str, float] = {}
        counts: dict[str, int] = {}
        for o in train:
            k = key(o)
            counts[k] = counts.get(k, 0) + 1
            successes[k] = successes.get(k, 0.0) + float(o.success)
        self._counts = counts
        self._rates = {k: successes[k] / counts[k] for k in counts}

    def _context_rate(self, observation: RunOutcome) -> float:
        """The context's estimated rate, or the pooled base rate when thin/unknown.

        ``min_context_samples`` is the volume knob: a context with fewer than
        that many training Rows cannot pose as calibrated and falls back to
        the base rate (the data-volume requirement, measured directly by
        :class:`TestDataVolume`).
        """
        k = self._key(observation)
        if self._counts.get(k, 0) < self._min:
            return self._base_rate
        return self._rates[k]

    def _key(self, observation: RunOutcome) -> str:
        """The context axis this table conditions on (task and model axes by default)."""
        return observation.context()

    def predict(self, observation: RunOutcome) -> float:
        return self._context_rate(observation)

    def _table_cost(self) -> CalibrationCost:
        return CalibrationCost(
            self._name,
            len(self._rates) + 1,
            len(self._rates),
            sum(self._counts.values()),
            "refit when drift monitor fires or corpus doubles",
        )

    def context_counts(self) -> dict[str, int]:
        """Training rows per tracked context (thinness = shrinkage need)."""
        return dict(self._counts)


class FrequencyEstimator(_ContextTable):
    """Plain per-context empirical success rate (the frequency model)."""

    def __init__(self, *, min_context_samples: int = 1) -> None:
        super().__init__(min_context_samples=min_context_samples)
        self._name = "frequency"

    def fit(self, train: Sequence[RunOutcome]) -> FrequencyEstimator:
        self._fit_table(train, lambda o: o.context())
        return self

    def cost(self) -> CalibrationCost:
        return self._table_cost()


class BayesEstimator(_ContextTable):
    """Beta-Binomial posterior mean per context (the Bayesian model).

    ``prior_strength`` pseudo-observations shrink each context's rate toward
    the *pooled train base rate* (empirical-Bayes style, so an imbalanced
    corpus is not shrunk toward a fictitious 0.5), which is exactly the
    thin-cell protection raw frequency lacks. ``prior_strength=0`` with a
    saturated context degenerates to the frequency estimator.
    """

    def __init__(self, prior_strength: float = 20.0) -> None:
        super().__init__()
        if prior_strength < 0.0:
            raise ValueError("prior_strength must be >= 0")
        self._prior = prior_strength
        self._name = "bayes"

    def fit(self, train: Sequence[RunOutcome]) -> BayesEstimator:
        self._fit_table(train, lambda o: o.context())
        if self._prior > 0.0:
            self._rates = {
                k: (self._rates[k] * self._counts[k] + self._base_rate * self._prior)
                / (self._counts[k] + self._prior)
                for k in self._rates
            }
        return self

    def cost(self) -> CalibrationCost:
        return self._table_cost()


class PlattCalibrator(M8E2Estimator):
    """Platt scaling: a 1-D logistic recalibration of the self-report.

    The classic parametric calibration model — it can only move the
    intercept/slope of the self-report, so it fixes systematic
    over/under-confidence while (being monotone) leaving the self-report's
    ranking, hence its discrimination, untouched.
    """

    def __init__(self, ridge: float = 1.0, iters: int = 50) -> None:
        self._ridge = ridge
        self._iters = iters
        self._a = 0.0
        self._b = 0.0

    def fit(self, train: Sequence[RunOutcome]) -> PlattCalibrator:
        if not train:
            raise ValueError("fit needs at least one observation")
        xs = [o.claimed for o in train]
        ys = [float(o.success) for o in train]
        self._a, self._b = 0.0, 0.0
        for _ in range(self._iters):
            pa, pb = self._a, self._b
            grads = [0.0, 0.0]
            hess = [0.0, 0.0, 0.0]
            for x, y in zip(xs, ys, strict=True):
                p = _sigmoid(self._a + self._b * x)
                w = max(p * (1.0 - p), 1e-6)
                err = p - y
                grads[0] += err
                grads[1] += err * x
                hess[0] += w
                hess[1] += w * x
                hess[2] += w * x * x
            h00, h01, h11 = hess[0] + self._ridge, hess[1], hess[2] + self._ridge
            det = h00 * h11 - h01 * h01
            if abs(det) < 1e-12:
                break
            # Newton step on the penalized log-loss; h1 maps to the bias coord.
            self._a -= (h11 * grads[0] - h01 * grads[1]) / det
            self._b -= (h00 * grads[1] - h01 * grads[0]) / det
            if abs(self._a - pa) < 1e-10 and abs(self._b - pb) < 1e-10:
                break
        return self

    def predict(self, observation: RunOutcome) -> float:
        return _sigmoid(self._a + self._b * observation.claimed)

    def cost(self) -> CalibrationCost:
        return CalibrationCost("platt", 2, 0, 0, "refit when self-report drift monitor fires")


class HistogramCalibrator(M8E2Estimator):
    """Histogram-bin recalibration: each self-report bin maps to its observed rate.

    The nonparametric calibration model. Unlike Platt it can bend the
    mapping per bin, at the price of ``n_bins`` pieces of fitted state and
    bin-edge sensitivity — the flexibility/maintenance trade recorded in the
    cost ledger.
    """

    def __init__(self, n_bins: int = 10) -> None:
        if n_bins <= 0:
            raise ValueError("n_bins must be positive")
        self._n_bins = n_bins
        self._bin_rates: dict[int, float] = {}
        self._base_rate = 0.5

    def fit(self, train: Sequence[RunOutcome]) -> HistogramCalibrator:
        if not train:
            raise ValueError("fit needs at least one observation")
        self._base_rate = sum(float(o.success) for o in train) / len(train)
        sums: dict[int, float] = {}
        counts: dict[int, int] = {}
        for o in train:
            b = self._bin(o.claimed)
            counts[b] = counts.get(b, 0) + 1
            sums[b] = sums.get(b, 0.0) + float(o.success)
        self._bin_rates = {b: sums[b] / counts[b] for b in counts}
        return self

    def _bin(self, claimed: float) -> int:
        b = min(int(claimed * self._n_bins), self._n_bins - 1)
        return max(b, 0)

    def predict(self, observation: RunOutcome) -> float:
        return self._bin_rates.get(self._bin(observation.claimed), self._base_rate)

    def cost(self) -> CalibrationCost:
        return CalibrationCost(
            "histogram",
            len(self._bin_rates) + 1,
            0,
            0,
            "refit when self-report drift monitor fires",
        )


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


class LogisticHistoryModel(M8E2Estimator):
    """Logistic regression over self-report + historical evidence features.

    The leaf's "logistic" family and its blend test in one model: features
    are [bias, self-report, context history rate, experience mass,
    self-report * history], so the fit can learn to trust history, the
    self-report, or any mixture — and the study reads the learned weights to
    report which evidence source the data actually supports. Fitted by
    damped Newton (IRLS) with a ridge penalty: deterministic, and stable
    even on (near-)separable fixtures where unregularized Newton diverges.
    """

    DIM = 5

    def __init__(self, ridge: float = 1.0, iters: int = 40) -> None:
        self._ridge = ridge
        self._iters = iters
        self._w = [0.0] * self.DIM
        self._table = FrequencyEstimator()
        self._counts: dict[str, int] = {}
        self._base_rate = 0.5

    def fit(self, train: Sequence[RunOutcome]) -> LogisticHistoryModel:
        if not train:
            raise ValueError("fit needs at least one observation")
        self._table.fit(train)
        self._counts = self._table.context_counts()
        self._base_rate = self._table.predict(train[0]) if train else 0.5
        # The base rate IS the frequency prediction for an unseen context, so
        # recover it directly from the fitted table's pooled rate.
        total = sum(self._counts.values())
        self._base_rate = sum(float(o.success) for o in train) / total if total else 0.5
        rows = [self._features(o) for o in train]
        ys = [float(o.success) for o in train]
        self._w = [0.0] * self.DIM
        for _ in range(self._iters):
            grads = [0.0] * self.DIM
            hess = [[0.0] * self.DIM for _ in range(self.DIM)]
            for row, y in zip(rows, ys, strict=True):
                p = _sigmoid(sum(w * x for w, x in zip(self._w, row, strict=True)))
                p = min(max(p, 1e-6), 1.0 - 1e-6)
                wgt = p * (1.0 - p)
                err = p - y
                for i in range(self.DIM):
                    grads[i] += err * row[i]
                    for j in range(i, self.DIM):
                        hess[i][j] += wgt * row[i] * row[j]
            for i in range(self.DIM):
                hess[i][i] += self._ridge
                for j in range(i):
                    hess[i][j] = hess[j][i]
            # Damped Newton (IRLS) step: the Hessian is a sum over rows, so
            # the raw step H⁻¹g is already correctly scaled — do not average
            # it, which would shrink every step by 1/n and underfit.
            step = _solve_symmetric(hess, grads)
            new_w = [w - s for w, s in zip(self._w, step, strict=True)]
            delta = max(abs(a - b) for a, b in zip(new_w, self._w, strict=True))
            self._w = new_w
            if delta < 1e-10:
                break
        return self

    def _features(self, observation: RunOutcome) -> list[float]:
        hist = self._table.predict(observation)
        mass = math.log1p(self._counts.get(observation.context(), 0)) / math.log1p(50.0)
        return [1.0, observation.claimed, hist, mass, observation.claimed * hist]

    def predict(self, observation: RunOutcome) -> float:
        row = self._features(observation)
        return _sigmoid(sum(w * x for w, x in zip(self._w, row, strict=True)))

    def cost(self) -> CalibrationCost:
        return CalibrationCost(
            "logistic-history",
            self.DIM + len(self._table._rates) + 1,
            len(self._table._rates),
            sum(self._counts.values()),
            "refit when drift monitor fires or corpus doubles",
        )

    def weights(self) -> tuple[float, ...]:
        """The learned evidence weights — which source the data supported."""
        return tuple(self._w)


def _solve_symmetric(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for a small dense system."""
    n = len(b)
    m = [[*row[:], b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            m[col][col] += 1e-9
            piv = col
        m[col], m[piv] = m[piv], m[col]
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


# ---------------------------------------------------------------------------
# Study machinery — learning curves, drift, subgroup reports
# ---------------------------------------------------------------------------


EstimatorFactory = Callable[[], M8E2Estimator]


def m8e2_learning_curve(
    train: Sequence[RunOutcome],
    test: Sequence[RunOutcome],
    factory: EstimatorFactory,
    sizes: Sequence[int],
) -> list[tuple[int, float]]:
    """Held-out Brier as a function of training volume — the data-volume curve.

    Sizes larger than ``train`` clamp to ``len(train)``; the curve is what
    "data volume required" is read off: the smallest size at which the
    estimator's held-out Brier drops below the baseline it must beat.
    """
    curve: list[tuple[int, float]] = []
    for size in sizes:
        if size <= 0:
            raise ValueError("sizes must be positive")
        sub = train[: min(size, len(train))]
        if not sub:
            continue
        model = factory().fit(sub)
        scores = model.predict_all(test)
        outcomes = [o.success for o in test]
        curve.append((len(sub), m8e2_brier(scores, outcomes)))
    return curve


def m8e2_overconfidence_drift(observations: Sequence[RunOutcome], delta: float) -> list[RunOutcome]:
    """A drifted copy: self-reports shift up by ``delta`` (capped at 1.0).

    Outcomes are held fixed — the deployed world changed how confidently the
    model speaks, not how well it works, which is precisely the drift a
    frozen calibration model silently stops correcting.
    """
    if delta < 0.0:
        raise ValueError("delta must be >= 0")
    return [
        RunOutcome(
            o.task_family,
            o.model_family,
            min(1.0, o.claimed + delta),
            o.success,
            o.toolset,
            o.seq,
        )
        for o in observations
    ]


def m8e2_rate_drift(
    observations: Sequence[RunOutcome], flip_fraction: float, seed: int
) -> list[RunOutcome]:
    """A drifted copy: later outcomes flip toward failure (base-rate drift).

    The ``flip_fraction`` of *the latest* Runs are re-judged as failures —
    the deployed world's difficulty moved under a frozen context table.
    """
    if not 0.0 <= flip_fraction <= 1.0:
        raise ValueError("flip_fraction must be in [0, 1]")
    rng = random.Random(seed)
    n_flip = math.floor(len(observations) * flip_fraction)
    drifted = list(observations)
    for i in range(len(drifted) - n_flip, len(drifted)):
        if drifted[i].success:
            drifted[i] = RunOutcome(
                drifted[i].task_family,
                drifted[i].model_family,
                drifted[i].claimed,
                False,
                drifted[i].toolset,
                drifted[i].seq,
            )
    _ = rng  # seed kept for signature symmetry; flip selection is deterministic
    return drifted


@dataclass(frozen=True)
class GroupCalibration:
    """One subgroup's calibration record (a task family, a model family…)."""

    group: str
    count: int
    ece: float
    brier: float


def m8e2_group_calibration(
    observations: Sequence[RunOutcome],
    scores: Sequence[float],
    key: Callable[[RunOutcome], str],
    n_bins: int = 10,
) -> list[GroupCalibration]:
    """Per-subgroup calibration — the aggregate can hide the miscalibrated."""
    if len(observations) != len(scores):
        raise ValueError("score/observation length mismatch")
    buckets: dict[str, list[int]] = {}
    for i, o in enumerate(observations):
        buckets.setdefault(key(o), []).append(i)
    report = []
    for group, idx in sorted(buckets.items()):
        g_scores = [scores[i] for i in idx]
        g_outcomes = [observations[i].success for i in idx]
        report.append(
            GroupCalibration(
                group,
                len(idx),
                m8e2_ece(g_scores, g_outcomes, n_bins),
                m8e2_brier(g_scores, g_outcomes),
            )
        )
    return report


def m8e2_worst_group(report: Sequence[GroupCalibration]) -> GroupCalibration:
    """The subgroup with the worst (largest) calibration error."""
    if not report:
        raise ValueError("report needs at least one group")
    return max(report, key=lambda g: g.ece)


# ---------------------------------------------------------------------------
# Deterministic fixture corpora — study inputs, NOT experimental results
# ---------------------------------------------------------------------------


#: Task-family base rates for the history-informative corpus: a wide spread,
#: so knowing the context is worth a lot and per-instance self-report noise
#: is worth little.
_HISTORY_RATES = {
    "coding": 0.90,
    "research": 0.70,
    "synthesis": 0.45,
    "extraction": 0.20,
}

#: Model-family effect on the same rates: an additive context axis the
#: history estimators can pool over.
_MODEL_EFFECT = {"strong": 0.04, "weak": -0.12}


def m8e2_history_informative_corpus(
    seed: int = 931, n: int = 2400, report_noise: float = 0.22
) -> list[RunOutcome]:
    """A corpus where context determines skill and self-report is a noisy proxy.

    Round-robin contexts keep every family represented in both temporal
    halves, so the history-vs-self-report comparison is never confounded by
    unseen-context fallbacks. Self-report tracks the context's true rate
    with Gaussian noise ``report_noise`` — informative, but strictly worse
    than knowing the context's realized success rate.
    """
    rng = random.Random(seed)
    contexts = [(t, m) for t in _HISTORY_RATES for m in _MODEL_EFFECT]
    corpus: list[RunOutcome] = []
    for i in range(n):
        task, model = contexts[i % len(contexts)]
        rate = min(0.98, max(0.02, _HISTORY_RATES[task] + _MODEL_EFFECT[model]))
        claimed = min(1.0, max(0.0, rng.gauss(rate, report_noise)))
        success = rng.random() < rate
        corpus.append(RunOutcome(task, model, claimed, success, "", i))
    return corpus


def m8e2_selfreport_informative_corpus(
    seed: int = 9312, n: int = 1600, report_noise: float = 0.05
) -> list[RunOutcome]:
    """A corpus where every context shares one base rate but self-report is sharp.

    The control: history can only recover the shared base rate (the
    no-confidence baseline), so any real signal must come from the
    self-report — and estimators that read it should dominate.
    """
    rng = random.Random(seed)
    base = 0.60
    corpus: list[RunOutcome] = []
    for i in range(n):
        # Each Run draws a latent difficulty; the self-report observes it
        # almost exactly, and the outcome realizes it.
        latent = min(0.95, max(0.05, rng.gauss(base, 0.18)))
        claimed = min(1.0, max(0.0, rng.gauss(latent, report_noise)))
        success = rng.random() < latent
        corpus.append(RunOutcome("uniform", "m", claimed, success, "", i))
    return corpus


def m8e2_overconfident_selfreport_corpus(
    seed: int = 9313, n: int = 1600, inflation: float = 0.30
) -> list[RunOutcome]:
    """A corpus whose self-report is systematically inflated by ``inflation``.

    The recalibration target: raw self-report should show large ECE, and the
    calibration models (Platt, histogram) should remove most of it without
    needing any context table.
    """
    rng = random.Random(seed)
    rates = {"coding": 0.75, "research": 0.55, "extraction": 0.30}
    contexts = list(rates)
    corpus: list[RunOutcome] = []
    for i in range(n):
        task = contexts[i % len(contexts)]
        success = rng.random() < rates[task]
        claimed = min(1.0, max(0.0, rng.gauss(rates[task] + inflation, 0.05)))
        corpus.append(RunOutcome(task, "m", claimed, success, "", i))
    return corpus


def m8e2_thin_context_corpus(
    seed: int = 9314, n_contexts: int = 40, per_context: int = 6
) -> list[RunOutcome]:
    """Many barely-populated contexts — where shrinkage earns its keep.

    Rows are interleaved round-robin across contexts, so a temporal split
    leaves every context a few training rows on both sides — a block layout
    would make the whole second half unseen and exercise only the fallback.
    """
    rng = random.Random(seed)
    streams: list[list[RunOutcome]] = []
    for c in range(n_contexts):
        # Deterministic per-context rate spread over [0.2, 0.8].
        rate = 0.2 + 0.6 * ((c * 7) % n_contexts) / n_contexts
        rows: list[RunOutcome] = []
        for _ in range(per_context):
            claimed = min(1.0, max(0.0, rng.gauss(rate, 0.15)))
            rows.append(RunOutcome(f"task-{c}", "m", claimed, rng.random() < rate))
        streams.append(rows)
    corpus: list[RunOutcome] = []
    seq = 0
    for i in range(per_context):
        for rows in streams:
            o = rows[i]
            corpus.append(RunOutcome(o.task_family, o.model_family, o.claimed, o.success, "", seq))
            seq += 1
    return corpus


def m8e2_reversal_corpus(seed: int = 9315, n: int = 800) -> list[RunOutcome]:
    """A corpus whose context skill reverses mid-stream — the leakage trap.

    ``volatile`` succeeds 80% of the time in the first half and 20% in the
    second; ``steady`` stays at 0.5. A fit trained on the future and judged
    on the past scores *better* than the honest direction — the inflation a
    shuffled or reversed split hides.
    """
    rng = random.Random(seed)
    corpus: list[RunOutcome] = []
    for i in range(n):
        task = ("volatile", "steady")[i % 2]
        rate = 0.5 if task == "steady" else (0.8 if i < n / 2 else 0.2)
        corpus.append(RunOutcome(task, "m", 0.5, rng.random() < rate, "", i))
    return corpus


# ---------------------------------------------------------------------------
# Tests: metric arithmetic (hand-checked)
# ---------------------------------------------------------------------------


class TestMetricArithmetic:
    def test_brier_hand_values(self) -> None:
        assert m8e2_brier([0.5, 0.5], [True, False]) == pytest.approx(0.25)
        assert m8e2_brier([1.0, 0.0], [True, False]) == pytest.approx(0.0)
        assert m8e2_brier([0.0, 1.0], [True, False]) == pytest.approx(1.0)
        with pytest.raises(ValueError, match="at least one"):
            m8e2_brier([], [])

    def test_ece_perfect_calibration_is_zero(self) -> None:
        # Predictions equal the bin's empirical accuracy by construction.
        assert m8e2_ece([0.0, 1.0], [False, True], n_bins=10) == pytest.approx(0.0)

    def test_ece_constant_overconfidence_is_measured(self) -> None:
        scores = [1.0] * 20
        outcomes = [i % 2 == 0 for i in range(20)]
        assert m8e2_ece(scores, outcomes, n_bins=10) == pytest.approx(0.5)

    def test_ece_top_edge_is_inclusive(self) -> None:
        assert m8e2_ece([1.0], [True], n_bins=10) == pytest.approx(0.0)
        assert m8e2_ece([1.0], [False], n_bins=10) == pytest.approx(1.0)

    def test_ece_rejects_degenerate_bins(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            m8e2_ece([0.5], [True], n_bins=0)

    def test_auroc_separation_extremes(self) -> None:
        perfect = m8e2_auroc([0.9, 0.8, 0.2, 0.1], [True, True, False, False])
        assert perfect == pytest.approx(1.0)
        inverted = m8e2_auroc([0.1, 0.2, 0.8, 0.9], [True, True, False, False])
        assert inverted == pytest.approx(0.0)
        # All-tied scores are chance, exactly.
        tied = m8e2_auroc([0.5] * 4, [True, True, False, False])
        assert tied == pytest.approx(0.5)

    def test_auroc_needs_both_classes(self) -> None:
        with pytest.raises(ValueError, match="both"):
            m8e2_auroc([0.5, 0.6], [True, True])

    def test_auprc_tie_groups_share_precision(self) -> None:
        # Scores [0.9, 0.9, 0.1, 0.1] with outcomes [T, F, T, F]: the top tie
        # group has precision 0.5 and recalls 1 of 2 positives; the second
        # group has precision 0.5 and recalls the other. AP = 0.5.
        assert m8e2_auprc([0.9, 0.9, 0.1, 0.1], [True, False, True, False]) == (pytest.approx(0.5))

    def test_auprc_degenerates_to_prevalence_when_tied(self) -> None:
        assert m8e2_auprc([0.5] * 4, [True, True, False, False]) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Tests: temporal integrity (the leakage guard)
# ---------------------------------------------------------------------------


class TestTemporalIntegrity:
    def test_split_is_order_preserving_and_exhaustive(self) -> None:
        corpus = m8e2_history_informative_corpus(n=200)
        train, test = m8e2_temporal_split(corpus, 0.7)
        assert len(train) + len(test) == 200
        assert max(o.seq for o in train) < min(o.seq for o in test)
        assert [o.seq for o in train] == sorted(o.seq for o in train)
        assert {o.seq for o in train}.isdisjoint({o.seq for o in test})

    def test_split_rejects_bad_fractions_and_empty(self) -> None:
        one = [RunOutcome("t", "m", 0.5, True)]
        for bad in (0.0, 1.0, -0.5, 1.5):
            with pytest.raises(ValueError, match="train_fraction"):
                m8e2_temporal_split(one, bad)
        with pytest.raises(ValueError, match="at least one"):
            m8e2_temporal_split([], 0.5)

    def test_leakage_inflates_measured_quality(self) -> None:
        """The honest direction must be the worse-looking one here.

        With a mid-stream reversal, the frequency estimator trained on the
        *later* half and judged on the *earlier* half looks better than the
        legitimate fit — that inflation is exactly what a shuffled or
        future-leaking split would report. The study's split makes the
        honest direction the only one it produces.
        """
        corpus = m8e2_reversal_corpus()
        train, test = m8e2_temporal_split(corpus, 0.5)
        honest = m8e2_brier(
            FrequencyEstimator().fit(train).predict_all(test),
            [o.success for o in test],
        )
        leaky = m8e2_brier(
            FrequencyEstimator().fit(test).predict_all(train),
            [o.success for o in train],
        )
        assert leaky < honest


# ---------------------------------------------------------------------------
# Tests: estimator baselines and shrinkage
# ---------------------------------------------------------------------------


class TestEstimatorBaselines:
    def test_base_rate_estimator_is_constant(self) -> None:
        corpus = m8e2_history_informative_corpus(n=120)
        train, test = m8e2_temporal_split(corpus, 0.5)
        model = BaseRateEstimator().fit(train)
        base = sum(float(o.success) for o in train) / len(train)
        assert model.predict(test[0]) == pytest.approx(base)
        assert len({model.predict(o) for o in test}) == 1

    def test_self_report_baseline_is_identity(self) -> None:
        o = RunOutcome("t", "m", 0.73, True)
        assert SelfReportEstimator().predict(o) == pytest.approx(0.73)

    def test_frequency_recovers_context_rates(self) -> None:
        corpus = m8e2_history_informative_corpus(n=4000, seed=31)
        train, test = m8e2_temporal_split(corpus, 0.5)
        model = FrequencyEstimator().fit(train)
        for task, rate in _HISTORY_RATES.items():
            for model_family, effect in _MODEL_EFFECT.items():
                probe = RunOutcome(task, model_family, 0.5, True)
                expected = min(0.98, max(0.02, rate + effect))
                assert model.predict(probe) == pytest.approx(expected, abs=0.05)
        _ = test

    def test_unseen_context_falls_back_to_base_rate(self) -> None:
        corpus = m8e2_history_informative_corpus(n=400)
        train, _ = m8e2_temporal_split(corpus, 0.5)
        model = FrequencyEstimator().fit(train)
        stranger = RunOutcome("never-seen", "m", 0.5, True)
        base = sum(float(o.success) for o in train) / len(train)
        assert model.predict(stranger) == pytest.approx(base)

    def test_min_context_samples_fallback(self) -> None:
        corpus = m8e2_thin_context_corpus(per_context=3)
        train, _ = m8e2_temporal_split(corpus, 0.5)
        model = FrequencyEstimator(min_context_samples=100).fit(train)
        base = sum(float(o.success) for o in train) / len(train)
        assert all(model.predict(o) == pytest.approx(base) for o in train[:10])
        with pytest.raises(ValueError, match="min_context_samples"):
            FrequencyEstimator(min_context_samples=0)

    def test_bayes_shrinks_thin_contexts_toward_base_rate(self) -> None:
        corpus = m8e2_thin_context_corpus()
        train, _ = m8e2_temporal_split(corpus, 0.5)
        freq = FrequencyEstimator().fit(train)
        bayes = BayesEstimator(prior_strength=8.0).fit(train)
        base = sum(float(o.success) for o in train) / len(train)
        for o in train[:20]:
            f, b = freq.predict(o), bayes.predict(o)
            assert abs(b - base) <= abs(f - base) + 1e-12

    def test_bayes_converges_to_frequency_with_enough_data(self) -> None:
        corpus = m8e2_history_informative_corpus(n=6000, seed=77)
        train, _ = m8e2_temporal_split(corpus, 0.5)
        freq = FrequencyEstimator().fit(train)
        bayes = BayesEstimator(prior_strength=2.0).fit(train)
        gaps = [abs(freq.predict(o) - bayes.predict(o)) for o in train[::20]]
        assert max(gaps) < 0.03


# ---------------------------------------------------------------------------
# Tests: the central comparison — history vs self-report vs blends
# ---------------------------------------------------------------------------


def _heldout_scores(
    corpus: list[RunOutcome],
    factory: EstimatorFactory,
    train_fraction: float = 0.5,
) -> tuple[list[float], list[bool]]:
    train, test = m8e2_temporal_split(corpus, train_fraction)
    model = factory().fit(train)
    return model.predict_all(test), [o.success for o in test]


def _heldout_brier(
    corpus: list[RunOutcome], factory: EstimatorFactory, train_fraction: float = 0.5
) -> float:
    scores, outcomes = _heldout_scores(corpus, factory, train_fraction)
    return m8e2_brier(scores, outcomes)


class TestHistoryVersusSelfReport:
    def test_history_beats_self_report_when_context_determines_skill(self) -> None:
        corpus = m8e2_history_informative_corpus()
        self_report = _heldout_brier(corpus, SelfReportEstimator)
        no_confidence = _heldout_brier(corpus, BaseRateEstimator)
        frequency = _heldout_brier(corpus, FrequencyEstimator)
        bayes = _heldout_brier(corpus, lambda: BayesEstimator(prior_strength=20.0))
        logistic = _heldout_brier(corpus, LogisticHistoryModel)
        assert frequency < self_report
        assert bayes < self_report
        assert logistic < self_report
        # And every learned estimator clears the no-confidence baseline.
        assert max(frequency, bayes, logistic) < no_confidence

    def test_history_improves_error_discrimination_too(self) -> None:
        corpus = m8e2_history_informative_corpus()
        sr_scores, outcomes = _heldout_scores(corpus, SelfReportEstimator)
        hist_scores, _ = _heldout_scores(corpus, lambda: BayesEstimator(20.0))
        assert m8e2_auroc(hist_scores, outcomes) > m8e2_auroc(sr_scores, outcomes)
        assert m8e2_auprc(hist_scores, outcomes) > m8e2_auprc(sr_scores, outcomes)

    def test_self_report_wins_when_contexts_share_a_base_rate(self) -> None:
        corpus = m8e2_selfreport_informative_corpus()
        self_report = _heldout_brier(corpus, SelfReportEstimator)
        no_confidence = _heldout_brier(corpus, BaseRateEstimator)
        frequency = _heldout_brier(corpus, FrequencyEstimator)
        # History can only recover the shared base rate: it collapses to the
        # no-confidence baseline, and the sharp self-report beats both.
        assert frequency == pytest.approx(no_confidence, abs=0.01)
        assert self_report < no_confidence

    def test_logistic_learns_to_weight_the_informative_signal(self) -> None:
        """The blend model reads its own weights correctly on both corpora.

        On the history corpus the history weight should dominate the
        self-report weight; on the self-report corpus the reverse.
        """
        history_corpus = m8e2_history_informative_corpus()
        train, _ = m8e2_temporal_split(history_corpus, 0.5)
        history_fit = LogisticHistoryModel().fit(train)
        hist_w, claim_w = history_fit.weights()[2], history_fit.weights()[1]
        assert hist_w > claim_w

        report_corpus = m8e2_selfreport_informative_corpus()
        train2, _ = m8e2_temporal_split(report_corpus, 0.5)
        report_fit = LogisticHistoryModel().fit(train2)
        hist_w2, claim_w2 = report_fit.weights()[2], report_fit.weights()[1]
        assert claim_w2 > hist_w2

    def test_bayes_beats_frequency_on_thin_contexts(self) -> None:
        corpus = m8e2_thin_context_corpus()
        frequency = _heldout_brier(corpus, FrequencyEstimator)
        bayes = _heldout_brier(corpus, lambda: BayesEstimator(prior_strength=5.0))
        assert bayes < frequency


class TestRecalibration:
    def test_platt_reduces_ece_of_overconfident_selfreport(self) -> None:
        corpus = m8e2_overconfident_selfreport_corpus()
        train, test = m8e2_temporal_split(corpus, 0.5)
        outcomes = [o.success for o in test]
        raw = SelfReportEstimator().predict_all(test)
        platt = PlattCalibrator().fit(train).predict_all(test)
        assert m8e2_ece(platt, outcomes) < m8e2_ece(raw, outcomes) / 2
        # Platt is monotone in the self-report, so ranking — and therefore
        # discrimination — is preserved exactly.
        assert m8e2_auroc(platt, outcomes) == pytest.approx(m8e2_auroc(raw, outcomes))

    def test_histogram_recalibration_also_reduces_ece(self) -> None:
        corpus = m8e2_overconfident_selfreport_corpus()
        train, test = m8e2_temporal_split(corpus, 0.5)
        outcomes = [o.success for o in test]
        raw = SelfReportEstimator().predict_all(test)
        hist = HistogramCalibrator(n_bins=10).fit(train).predict_all(test)
        assert m8e2_ece(hist, outcomes) < m8e2_ece(raw, outcomes) / 2

    def test_recalibration_on_honest_selfreport_cannot_hurt_discrimination(
        self,
    ) -> None:
        corpus = m8e2_selfreport_informative_corpus()
        train, test = m8e2_temporal_split(corpus, 0.5)
        outcomes = [o.success for o in test]
        raw = SelfReportEstimator().predict_all(test)
        platt = PlattCalibrator().fit(train).predict_all(test)
        assert m8e2_auroc(platt, outcomes) == pytest.approx(m8e2_auroc(raw, outcomes))
        # And on a well-behaved corpus the recalibration stays harmless.
        assert m8e2_brier(platt, outcomes) <= m8e2_brier(raw, outcomes) + 0.02


# ---------------------------------------------------------------------------
# Tests: data volume required
# ---------------------------------------------------------------------------


class TestDataVolume:
    def test_learning_curve_crosses_the_selfreport_baseline(self) -> None:
        """The volume threshold exists: thin history is much worse than nothing.

        At one training row per context the frequency estimator's rates are
        0/1 coin-flips and its held-out Brier is far worse than the raw
        self-report; past ~a hundred rows per corpus pass it wins and keeps
        improving with volume. The crossing point is the corpus volume the
        disposition's INCUBATE trigger quantifies.
        """
        corpus = m8e2_history_informative_corpus()
        train, test = m8e2_temporal_split(corpus, 0.5)
        outcomes = [o.success for o in test]
        baseline = m8e2_brier(SelfReportEstimator().predict_all(test), outcomes)
        curve = m8e2_learning_curve(
            train, test, FrequencyEstimator, [8, 64, 128, 256, 512, len(train)]
        )
        thin_brier = curve[0][1]
        full_brier = curve[-1][1]
        assert thin_brier > baseline, "thin slices must not look free"
        assert full_brier < baseline
        # Volume buys calibration: every size past the crossing beats the
        # baseline, and the full corpus is the best of the recorded curve.
        for size, brier in curve[2:]:
            assert brier < baseline, f"size {size} should clear the baseline"
        assert full_brier == min(b for _, b in curve)

    def test_min_context_samples_caps_thin_slice_damage(self) -> None:
        """The sample floor is the safety knob the volume threshold implies.

        Below the floor the estimator refuses to calibrate and predicts the
        pooled base rate — exactly the no-confidence estimator on the same
        prefix — so it cannot do worse than that baseline. Above it, the
        floor stops binding and the estimator coincides with the plain
        frequency fit.
        """
        corpus = m8e2_history_informative_corpus()
        train, test = m8e2_temporal_split(corpus, 0.5)
        floored_curve = m8e2_learning_curve(
            train, test, lambda: FrequencyEstimator(min_context_samples=50), [8]
        )
        unprotected_curve = m8e2_learning_curve(train, test, FrequencyEstimator, [8])
        base_curve = m8e2_learning_curve(train, test, BaseRateEstimator, [8])
        # At one row per context the raw MLE is worse than doing nothing;
        # the floor caps it exactly at the no-confidence baseline.
        assert unprotected_curve[0][1] > floored_curve[0][1]
        assert floored_curve[0][1] == pytest.approx(base_curve[0][1])
        # At full volume the floor no longer binds: same fit as unprotected.
        floored_full = m8e2_learning_curve(
            train, test, lambda: FrequencyEstimator(min_context_samples=50), [len(train)]
        )
        plain_full = m8e2_learning_curve(train, test, FrequencyEstimator, [len(train)])
        assert floored_full[0][1] == pytest.approx(plain_full[0][1])


# ---------------------------------------------------------------------------
# Tests: drift sensitivity
# ---------------------------------------------------------------------------


class TestDriftSensitivity:
    def test_frozen_platt_degrades_under_overconfidence_drift(self) -> None:
        corpus = m8e2_overconfident_selfreport_corpus()
        train, test = m8e2_temporal_split(corpus, 0.5)
        platt = PlattCalibrator().fit(train)
        clean = m8e2_ece(platt.predict_all(test), [o.success for o in test])
        drifted = m8e2_overconfidence_drift(test, 0.25)
        frozen = m8e2_ece(platt.predict_all(drifted), [o.success for o in drifted])
        assert frozen > clean * 2
        # A refit on the drifted stream recovers most of the loss — the
        # maintenance cost is real but payable.
        d_train, d_test = m8e2_temporal_split(drifted, 0.5)
        refit = PlattCalibrator().fit(d_train)
        recovered = m8e2_ece(refit.predict_all(d_test), [o.success for o in d_test])
        assert recovered < frozen
        assert recovered < clean * 2

    def test_frozen_frequency_table_degrades_under_base_rate_drift(self) -> None:
        """A base-rate shift strands the frozen context table; a fresher fit
        trained on the drifted window itself recovers most of the gap — the
        retraining discipline the cost ledger's ``retrain_policy`` records.
        """
        corpus = m8e2_history_informative_corpus(n=1600, seed=4)
        train, test = m8e2_temporal_split(corpus, 0.5)
        frozen = FrequencyEstimator().fit(train)
        drifted = m8e2_rate_drift(test, flip_fraction=0.5, seed=4)
        before = m8e2_brier(frozen.predict_all(test), [o.success for o in test])
        after = m8e2_brier(frozen.predict_all(drifted), [o.success for o in drifted])
        assert after > before
        # The latest window is fully drifted, so a table fitted on the
        # drifted portion of the stream is measurably fresher than the
        # frozen one on exactly the same evaluation rows.
        eval_window = drifted[600:]
        eval_outcomes = [o.success for o in eval_window]
        stale = m8e2_brier(frozen.predict_all(eval_window), eval_outcomes)
        fresh = m8e2_brier(
            FrequencyEstimator().fit(drifted[200:600]).predict_all(eval_window),
            eval_outcomes,
        )
        assert fresh < stale / 2

    def test_drift_helpers_preserve_identity_and_order(self) -> None:
        corpus = m8e2_history_informative_corpus(n=60)
        shifted = m8e2_overconfidence_drift(corpus, 0.1)
        assert [o.seq for o in shifted] == [o.seq for o in corpus]
        assert [o.success for o in shifted] == [o.success for o in corpus]
        assert all(
            s.claimed == min(1.0, o.claimed + 0.1) for s, o in zip(shifted, corpus, strict=True)
        )
        flipped = m8e2_rate_drift(corpus, flip_fraction=0.5, seed=9)
        assert [o.seq for o in flipped] == [o.seq for o in corpus]
        late = flipped[len(flipped) // 2 :]
        early = flipped[: len(flipped) // 2]
        assert all(not o.success for o in late if o.success)
        assert early == corpus[: len(corpus) // 2]
        with pytest.raises(ValueError, match="flip_fraction"):
            m8e2_rate_drift(corpus, flip_fraction=1.5, seed=1)


# ---------------------------------------------------------------------------
# Tests: subgroup / task-family calibration
# ---------------------------------------------------------------------------


class TestSubgroupCalibration:
    def test_aggregate_ece_hides_the_worst_family(self) -> None:
        """Two families, opposite-signed miscalibration, one shared bin.

        Both claim 0.6; ``underconfident`` succeeds 0.8 of the time,
        ``overconfident`` 0.4. Pooled, the bin's accuracy is 0.6 — exactly
        its confidence — so aggregate ECE collapses to ~0 while each family
        is off by 0.2. The Simpson-style cancellation the subgroup report
        exists to surface.
        """
        observations: list[RunOutcome] = []
        for i in range(20):
            observations.append(RunOutcome("underconfident", "m", 0.6, i < 16, "", i))
        for i in range(20):
            observations.append(RunOutcome("overconfident", "m", 0.6, i < 8, "", i))
        scores = SelfReportEstimator().predict_all(observations)
        outcomes = [o.success for o in observations]
        aggregate = m8e2_ece(scores, outcomes)
        report = m8e2_group_calibration(observations, scores, lambda o: o.task_family, n_bins=10)
        worst = m8e2_worst_group(report)
        assert {g.group for g in report} == {"underconfident", "overconfident"}
        assert worst.ece == pytest.approx(0.2)
        assert aggregate < worst.ece / 2

    def test_group_report_partitions_and_counts(self) -> None:
        corpus = m8e2_history_informative_corpus(n=400)
        train, test = m8e2_temporal_split(corpus, 0.5)
        model = BayesEstimator(20.0).fit(train)
        scores = model.predict_all(test)
        report = m8e2_group_calibration(test, scores, lambda o: o.task_family, n_bins=5)
        assert sum(g.count for g in report) == len(test)
        assert len(report) == len(_HISTORY_RATES)
        with pytest.raises(ValueError, match="length mismatch"):
            m8e2_group_calibration(test, scores[:-1], lambda o: o.task_family)
        with pytest.raises(ValueError, match="at least one"):
            m8e2_worst_group([])

    def test_per_group_brier_beats_aggregate_on_the_informative_corpus(self) -> None:
        """History's advantage should show *within* every family, not just overall."""
        corpus = m8e2_history_informative_corpus()
        train, test = m8e2_temporal_split(corpus, 0.5)
        sr_scores = SelfReportEstimator().predict_all(test)
        hist_scores = BayesEstimator(20.0).fit(train).predict_all(test)
        sr_groups = {
            g.group: g.brier
            for g in m8e2_group_calibration(test, sr_scores, lambda o: o.task_family)
        }
        hist_groups = {
            g.group: g.brier
            for g in m8e2_group_calibration(test, hist_scores, lambda o: o.task_family)
        }
        for task in _HISTORY_RATES:
            assert hist_groups[task] < sr_groups[task]


# ---------------------------------------------------------------------------
# Tests: maintenance cost
# ---------------------------------------------------------------------------


class TestMaintenanceCost:
    def test_state_size_scales_with_context_cardinality(self) -> None:
        small = FrequencyEstimator().fit(m8e2_history_informative_corpus(n=400, seed=11))
        many = m8e2_thin_context_corpus(n_contexts=200, per_context=4)
        wide = FrequencyEstimator().fit(many)
        assert wide.cost().contexts_tracked == 200
        assert wide.cost().contexts_tracked > small.cost().contexts_tracked
        assert wide.cost().stored_floats == wide.cost().contexts_tracked + 1
        # High cardinality means thin cells: the state-explosion hazard that
        # forces shrinkage (or the sample-floor fallback) in production.
        counts = wide.context_counts()
        assert max(counts.values()) <= 4

    def test_estimator_cost_ledgers_are_accurate(self) -> None:
        corpus = m8e2_history_informative_corpus(n=600)
        train, _ = m8e2_temporal_split(corpus, 0.5)
        assert BaseRateEstimator().fit(train).cost().stored_floats == 1
        assert SelfReportEstimator().cost().stored_floats == 0
        assert PlattCalibrator().fit(train).cost().stored_floats == 2
        bins = HistogramCalibrator(n_bins=5).fit(train)
        assert bins.cost().stored_floats == len(bins._bin_rates) + 1
        logistic = LogisticHistoryModel().fit(train)
        cost = logistic.cost()
        assert cost.stored_floats == LogisticHistoryModel.DIM + len(logistic._table._rates) + 1
        assert cost.train_observations == len(train)
        for record in (
            BaseRateEstimator().fit(train).cost(),
            PlattCalibrator().fit(train).cost(),
            bins.cost(),
            logistic.cost(),
        ):
            assert record.retrain_policy

    def test_cost_records_are_frozen(self) -> None:
        corpus = m8e2_history_informative_corpus(n=60)
        record = FrequencyEstimator().fit(corpus).cost()
        with pytest.raises(AttributeError):
            record.stored_floats = 0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tests: evidence-only contract
# ---------------------------------------------------------------------------


class TestEvidenceOnlyContract:
    def test_harness_declares_itself_advisory(self) -> None:
        assert ADVISORY_ONLY is True

    def test_run_outcomes_reject_bad_rows(self) -> None:
        with pytest.raises(ValueError, match="claimed"):
            RunOutcome("t", "m", 1.5, True)
        with pytest.raises(ValueError, match="claimed"):
            RunOutcome("t", "m", -0.1, True)
        with pytest.raises(ValueError, match="seq"):
            RunOutcome("t", "m", 0.5, True, seq=-1)

    def test_records_are_frozen(self) -> None:
        o = RunOutcome("t", "m", 0.5, True)
        with pytest.raises(AttributeError):
            o.success = False  # type: ignore[misc]
        with pytest.raises(AttributeError):
            o.claimed = 0.9  # type: ignore[misc]

    def test_predictions_are_plain_probabilities_not_policies(self) -> None:
        corpus = m8e2_history_informative_corpus(n=400)
        train, test = m8e2_temporal_split(corpus, 0.5)
        estimators: list[M8E2Estimator] = [
            BaseRateEstimator().fit(train),
            FrequencyEstimator().fit(train),
            BayesEstimator(20.0).fit(train),
            PlattCalibrator().fit(train),
            HistogramCalibrator().fit(train),
            LogisticHistoryModel().fit(train),
        ]
        for model in estimators:
            for o in test[:50]:
                p = model.predict(o)
                assert isinstance(p, float)
                assert 0.0 <= p <= 1.0

    def test_context_keys_respect_requested_axes(self) -> None:
        o = RunOutcome("coding", "strong", 0.5, True, toolset="shell")
        assert o.context() == "coding|strong"
        assert o.context(tool=True) == "coding|strong|shell"
        assert o.context(model=False, tool=True) == "coding|shell"
        assert RunOutcome("t", "m", 0.5, True).context(tool=True) == "t|m|no-tools"

    def test_fixture_corpora_are_deterministic(self) -> None:
        a = m8e2_history_informative_corpus(seed=5, n=100)
        b = m8e2_history_informative_corpus(seed=5, n=100)
        assert a == b
        c = m8e2_history_informative_corpus(seed=6, n=100)
        assert a != c
