"""ADR-060 Tier 2 preference-residual calibration -- Persona/Workspace system.

Fits a Bradley-Terry preference model via logistic regression: given pairs
of (winner_features, loser_features) vectors for one persona,
P(winner beats loser) = sigmoid(w . (winner_features - loser_features)).
This is the standard reduction of Bradley-Terry to logistic regression on
paired feature differences, fit here by plain-Python batch gradient descent
rather than adding scikit-learn/numpy as a new dependency -- neither is used
anywhere else in this repo today, and there is no real pairwise-comparison
data source wired up yet to justify that dependency weight (see below).

Deliberately just the fitting/scoring mechanism ADR-060 specifies. Phase I's
actual thumbs +/- signal (services/persona_feedback.py) records a thumb on
ONE output, not an explicit A/B choice between two -- so there is no real
pairwise comparison data to feed this yet. Wiring a real pairwise-comparison
collection UI, real per-output features (e.g. rubric scores), and the
hill-climber-driven pending-review refinement proposals ADR-060 also
describes are their own follow-up efforts, not built here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ADR-060: a persona's preference model counts as "calibrated" once it
# predicts >=90% of held-out comparisons correctly.
CONVERGENCE_THRESHOLD = 0.9
MIN_COMPARISONS = 10
_LEARNING_RATE = 0.1
_ITERATIONS = 500


@dataclass(frozen=True)
class PreferenceComparison:
    """One pairwise choice: the persona output described by
    `winner_features` was preferred over the one described by
    `loser_features`. Both must share the same named dimensions
    (e.g. {"length": ..., "rubric_score": ...})."""

    winner_features: dict[str, float]
    loser_features: dict[str, float]


@dataclass(frozen=True)
class PreferenceModel:
    persona_template_id: str
    feature_names: list[str]
    weights: list[float]
    comparisons_seen: int
    holdout_accuracy: float
    calibrated: bool


def _sigmoid(z: float) -> float:
    # Numerically stable for large |z| in either direction.
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _fit_logistic_regression(
    features: list[list[float]],
    labels: list[int],
    *,
    learning_rate: float = _LEARNING_RATE,
    iterations: int = _ITERATIONS,
) -> list[float]:
    """Batch gradient descent, no regularization -- a plain, dependency-free
    logistic regression fit, adequate for the small pairwise-feature-diff
    problems this module fits."""
    n_features = len(features[0])
    weights = [0.0] * n_features
    n = len(features)
    for _ in range(iterations):
        gradients = [0.0] * n_features
        for row, label in zip(features, labels, strict=True):
            z = sum(w * x for w, x in zip(weights, row, strict=True))
            error = _sigmoid(z) - label
            for j, x in enumerate(row):
                gradients[j] += error * x
        weights = [w - learning_rate * (g / n) for w, g in zip(weights, gradients, strict=True)]
    return weights


def _predict(weights: list[float], row: list[float]) -> int:
    z = sum(w * x for w, x in zip(weights, row, strict=True))
    return 1 if _sigmoid(z) >= 0.5 else 0


def fit_preference_model(
    persona_template_id: str,
    comparisons: list[PreferenceComparison],
    *,
    holdout_fraction: float = 0.2,
) -> PreferenceModel | None:
    """Fit a persona's Bradley-Terry preference model from pairwise
    comparisons. Returns None when there isn't enough data to fit and hold
    out a meaningful split -- the caller should keep collecting feedback
    rather than trust an unfit model."""
    if len(comparisons) < MIN_COMPARISONS:
        return None

    feature_names = sorted(comparisons[0].winner_features.keys())
    features: list[list[float]] = []
    labels: list[int] = []
    for c in comparisons:
        diff = [c.winner_features[f] - c.loser_features[f] for f in feature_names]
        features.append(diff)
        labels.append(1)
        features.append([-d for d in diff])
        labels.append(0)

    # Deterministic split (the last N comparisons' both orientations) rather
    # than a random shuffle, so fits are reproducible across runs and tests.
    holdout_comparisons = max(1, int(len(comparisons) * holdout_fraction))
    holdout_rows = holdout_comparisons * 2
    train_features, test_features = features[:-holdout_rows], features[-holdout_rows:]
    train_labels, test_labels = labels[:-holdout_rows], labels[-holdout_rows:]

    weights = _fit_logistic_regression(train_features, train_labels)

    eval_features = test_features if test_features else train_features
    eval_labels = test_labels if test_labels else train_labels
    correct = sum(
        1
        for row, label in zip(eval_features, eval_labels, strict=True)
        if _predict(weights, row) == label
    )
    accuracy = correct / len(eval_labels)

    return PreferenceModel(
        persona_template_id=persona_template_id,
        feature_names=feature_names,
        weights=weights,
        comparisons_seen=len(comparisons),
        holdout_accuracy=accuracy,
        calibrated=accuracy >= CONVERGENCE_THRESHOLD,
    )
