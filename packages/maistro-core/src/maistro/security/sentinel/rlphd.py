"""RLPHD — glass-box predictive approval, confidence threshold (SPEC-248 / ADR-068 §E)."""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from typing import Literal, Protocol

COLD_START_THETA = 0.7
DEFAULT_SURPRISE_GAIN = 0.3
DEFAULT_CONFIRM_GAIN = 0.03
DEFAULT_LEARNING_RATE = 0.1
# Confidence-gap floor for the weight update: |p - theta| scales how much a
# decision moves each trait (a confident-wrong prediction teaches the most), but
# a pure |p - theta| would slow early learning to a crawl while the model is
# still empty (cold-start p is constant). The floor keeps it bootstrapping.
DEFAULT_CONF_GAP_FLOOR = 0.1


@dataclass(frozen=True)
class RlphdVerdict:
    """The outcome of one RLPHD prediction at a delegated-approval gate."""

    p: float
    theta: float
    auto_acted: bool


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass(frozen=True)
class RlphdModel:
    """A per-(principal, action-class) glass-box predictor: an explicit, inspectable weight vector."""

    feature_weights: dict[str, float] = field(default_factory=dict)

    def predict(self, features: dict[str, float]) -> float:
        """p = sigmoid(weighted sum of features) — pure, fully reproducible."""
        weighted_sum = sum(
            weight * features.get(name, 0.0) for name, weight in self.feature_weights.items()
        )
        return _sigmoid(weighted_sum)

    def update(
        self,
        features: dict[str, float],
        decision: Literal["approve", "deny"],
        predicted_p: float,
        *,
        learning_rate: float = DEFAULT_LEARNING_RATE,
        theta: float | None = None,
        conf_gap_floor: float = DEFAULT_CONF_GAP_FLOOR,
    ) -> RlphdModel:
        """Pure dual-signal weight update: nudges weights toward the realized decision.

        When ``theta`` is supplied, the step on each trait is scaled by the
        confidence gap ``|predicted_p - theta|`` — how confidently Ralph acted.
        A confident prediction that the user overturns carries the most signal, so
        its traits move the most; a borderline call (``p ≈ theta``) moves them
        little. ``conf_gap_floor`` keeps the empty model bootstrapping. Without
        ``theta`` the update is the unscaled gradient step (legacy behaviour)."""
        actual = 1.0 if decision == "approve" else 0.0
        error = actual - predicted_p
        gap_scale = abs(predicted_p - theta) + conf_gap_floor if theta is not None else 1.0
        eff_lr = learning_rate * gap_scale
        new_weights = dict(self.feature_weights)
        for name in features:
            base = new_weights.get(name, 0.0)
            new_weights[name] = base + eff_lr * error * features[name]
        return dataclasses.replace(self, feature_weights=new_weights)


def is_surprise(decision: Literal["approve", "deny"], predicted_p: float, theta: float) -> bool:
    """A surprise is a deny RLPHD would have auto-acted on, or an approve it wouldn't have."""
    if decision == "deny":
        return predicted_p >= theta
    return predicted_p < theta


def update_theta(
    theta: float,
    predicted_p: float,
    decision: Literal["approve", "deny"],
    *,
    surprise_gain: float = DEFAULT_SURPRISE_GAIN,
    confirm_gain: float = DEFAULT_CONFIRM_GAIN,
) -> float:
    """Surprise-weighted threshold update: surprises move theta more than confirmations."""
    actual = 1.0 if decision == "approve" else 0.0
    gain = surprise_gain if is_surprise(decision, predicted_p, theta) else confirm_gain
    delta = gain * (predicted_p - actual)
    return min(1.0, max(0.0, theta + delta))


class RlphdThresholdStore(Protocol):
    """Per-(principal, action-class, gate) adaptive theta and opt-in flag."""

    async def get_theta(self, principal_id: str, action_class: str, gate: str) -> float:
        """Return the current adaptive theta, or the cold-start default if unset."""
        ...

    async def set_theta(
        self, principal_id: str, action_class: str, gate: str, theta: float
    ) -> None:
        """Persist an updated theta."""
        ...

    async def opted_in(self, principal_id: str, action_class: str) -> bool:
        """Whether this (principal, action_class) has opted in to RLPHD auto-acting."""
        ...


@dataclass
class InMemoryRlphdThresholdStore:
    """An in-memory RlphdThresholdStore, mirroring InMemoryElevationStore's DI convention."""

    thetas: dict[tuple[str, str, str], float] = field(default_factory=dict)
    opt_ins: set[tuple[str, str]] = field(default_factory=set)

    async def get_theta(self, principal_id: str, action_class: str, gate: str) -> float:
        """Return the stored theta, or COLD_START_THETA if this key has never been set."""
        return self.thetas.get((principal_id, action_class, gate), COLD_START_THETA)

    async def set_theta(
        self, principal_id: str, action_class: str, gate: str, theta: float
    ) -> None:
        """Store the updated theta for this key."""
        self.thetas[(principal_id, action_class, gate)] = theta

    async def opted_in(self, principal_id: str, action_class: str) -> bool:
        """Whether this key is in the opt-in set (default: opted-out)."""
        return (principal_id, action_class) in self.opt_ins
