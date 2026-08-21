#!/usr/bin/env python3
"""Reproduce RLPHD's cold-start behaviour using the shipped constants.

Supporting artifact for docs/reviews/2026-07-29-rsi-containment-review.md §9.1.

Why this exists: ``RlphdModel.predict`` sums over its OWN weight dict, which
starts empty, so a fresh model returns ``sigmoid(0) = 0.5`` for every input
regardless of features. ``COLD_START_THETA`` is 0.7. Therefore ``p < theta``
always, and every promotion is reverted and flagged on a fresh state file --
which is why ``tools/run_rsi_isolated.sh`` ships ``--no-promotion-review``.

This answers "how many human approvals to escape that?" and, more importantly,
shows HOW it escapes: theta falls to meet a barely-moved p, so the model that
starts auto-keeping is still uninformative. It has also seen only positives, so
it cannot discriminate. And on a ``deny``, ``update_theta``'s delta is
``gain * (p - 0)`` -- positive -- so a reviewer who denies anything makes
convergence slower rather than faster.

Deliberately standalone (no maistro imports): it re-implements the update rules
from the constants so the numbers can be checked against the source by eye, and
so it keeps working if the package layout moves.

Run: python3 scripts/rlphd_cold_start_sim.py
"""

from __future__ import annotations

import math

# Shipped constants -- maistro.security.sentinel.rlphd
COLD_START_THETA = 0.7
DEFAULT_LEARNING_RATE = 0.1
DEFAULT_CONF_GAP_FLOOR = 0.1
# maistro_rsi.promotion_review.RlphdStateStore -- deliberately slower than the
# tool-call defaults (0.3 / 0.03): "a stable trust bar that drifts slowly".
THETA_SURPRISE_GAIN = 0.03
THETA_CONFIRM_GAIN = 0.003

# A typical promotion, per promotion_review.extract_features. Note judge_score
# defaults to 0.7 when the regression judge is UNAVAILABLE, which is also a
# plausible good score -- see the review's §9.4 R-5.
TYPICAL = {
    "bias": 1.0,
    "judge_score": 0.7,
    "composite": 0.6,
    "is_spec_completion": 0.0,
    "is_feature": 1.0,
}


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def predict(weights: dict[str, float], features: dict[str, float]) -> float:
    """RlphdModel.predict -- sums over the WEIGHT dict, so an empty model is 0.5."""
    return sigmoid(sum(w * features.get(n, 0.0) for n, w in weights.items()))


def is_surprise(decision: str, p: float, theta: float) -> bool:
    return p >= theta if decision == "deny" else p < theta


def step(
    weights: dict[str, float],
    theta: float,
    features: dict[str, float],
    decision: str,
) -> tuple[dict[str, float], float]:
    """One RlphdStateStore.record_decision: weight update, then a theta nudge."""
    p = predict(weights, features)
    actual = 1.0 if decision == "approve" else 0.0
    error = actual - p
    eff_lr = DEFAULT_LEARNING_RATE * (abs(p - theta) + DEFAULT_CONF_GAP_FLOOR)
    new_weights = dict(weights)
    for name, value in features.items():
        new_weights[name] = new_weights.get(name, 0.0) + eff_lr * error * value
    gain = THETA_SURPRISE_GAIN if is_surprise(decision, p, theta) else THETA_CONFIRM_GAIN
    new_theta = min(1.0, max(0.0, theta + gain * (p - actual)))
    return new_weights, new_theta


def run(decision: str, limit: int = 40) -> None:
    weights: dict[str, float] = {}
    theta = COLD_START_THETA
    print(f"\nall-'{decision}' reviewer, typical promotion:")
    print(f"{'n':>4} {'p':>8} {'theta':>8}  auto-keeps?")
    p = predict(weights, TYPICAL)
    for n in range(limit + 1):
        p = predict(weights, TYPICAL)
        acts = p >= theta
        if n % 2 == 0 or acts:
            print(f"{n:>4} {p:>8.4f} {theta:>8.4f}  {'YES' if acts else 'no'}")
        if acts:
            print(f"  -> escapes cold start after {n} human '{decision}' decisions")
            print(f"  -> theta moved {theta - COLD_START_THETA:+.4f}, p moved {p - 0.5:+.4f}")
            print("  -> i.e. it escaped by LOWERING THE BAR, not by learning to discriminate")
            return
        weights, theta = step(weights, theta, TYPICAL, decision)
    print(f"  -> still gated after {limit} '{decision}' decisions (p={p:.4f}, theta={theta:.4f})")


if __name__ == "__main__":
    run("approve")
    run("deny")
    print(
        "\nConclusion: the online path cannot produce a calibrated model. It needs a"
        "\nspanning, balanced label set fitted up front -- see the review's §9.3"
        "\nbootstrap interview."
    )
