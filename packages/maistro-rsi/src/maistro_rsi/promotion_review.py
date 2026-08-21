"""Checkpoint-time promotion review, backed by RLPHD (SPEC-248 / ADR-068 §E)
glass-box predictive approval — reused as-is from maistro-core's Sentinel,
pointed at a single shared action_class ("rsi_promotion") instead of
tool-call approval. Nothing about RLPHD's math is RSI-specific; only the
feature set and the action being gated are.

At each checkpoint, every promotion since the last review is scored with
``RlphdModel.predict()`` against small, interpretable features already
computed during scoring (the regression judge's score, composite, kind,
spec-completion). ``p < theta`` means the system doesn't have enough
confidence a human would approve, so the promotion is REVERTED NOW — so
nothing keeps building on top of it — but the original patch is SAVED to
``REPORT_DIR/flagged/``, queued for a human to later approve or deny.

That decision feeds back into ``RlphdModel.update()`` — the feature weights
are the primary, fast-moving signal (WHICH CHARACTERISTICS — judge_score,
composite, kind — actually predict approval is the "why," and that's where
most of the learning belongs). Theta also moves, but only a small fraction
as fast as tool-call RLPHD's default gain: a denial here is mostly a verdict
on the CODE a (possibly different) competitor model wrote, not on the
reviewer's own risk tolerance, so the trust bar should drift slowly as
evidence accumulates rather than swing sharply on any single decision.

A promotion superseded by later work (some later cycle already touched the
same file) cannot be cleanly reverted without unwinding dependent work — it's
observed (logged, features computed for calibration visibility) but never
queued for revert; supersession is a hard block on the whole revert path.

Persistence is one human-readable JSON file (``REPORT_DIR/rlphd_state.json``)
— glass-box means every weight is inspectable and hand-editable, not just
non-ML.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from maistro.security.sentinel.rlphd import COLD_START_THETA, RlphdModel
from maistro_evolve.improvement import ImprovementKind

# One fixed principal: RSI has no multiple-human-reviewer concept today, but
# RLPHD's per-(principal, action_class) scoping is kept intact so this slots
# into the same store/API a future multi-reviewer setup would use unchanged.
PRINCIPAL_ID = "rsi_operator"


# One global action class, not one per ImprovementKind. RLPHD's per-class
# cold start predicts p=0.5 (RlphdModel.predict sums over its OWN weight dict,
# which starts empty — the feature values don't matter until at least one
# update() has populated weights for them), which is below COLD_START_THETA
# (0.7) — so every NEW action_class's first-ever encounter always reverts.
# ImprovementKind has 9 members; splitting by kind would mean 9 independent
# cold starts before ANY kind calibrates, each needing its own human decisions
# to bootstrap. A single shared class converges from far fewer total
# decisions, and kind-sensitivity isn't lost — it's still one of the
# interpretable features (is_spec_completion / is_feature) the shared model
# learns to weight from real approve/deny evidence.
_ACTION_CLASS = "rsi_promotion"


def action_class_for(kind: ImprovementKind) -> str:
    """Kept as a function (not a bare constant) so a future split back into
    per-kind classes is a one-line change, not a call-site rewrite."""
    del kind  # kind is encoded as a feature, not the action class itself
    return _ACTION_CLASS


def extract_features(
    *, regression_judge_score: float | None, composite: float, kind: ImprovementKind
) -> dict[str, float]:
    """Small, interpretable feature set — every weight RLPHD learns over these
    stays human-readable in the persisted JSON. ``bias`` is the standard
    constant term so the sigmoid isn't forced through the origin."""
    return {
        "bias": 1.0,
        "judge_score": regression_judge_score if regression_judge_score is not None else 0.7,
        "composite": composite,
        "is_spec_completion": 1.0 if kind == ImprovementKind.SPEC else 0.0,
        "is_feature": 1.0 if kind == ImprovementKind.FEATURE else 0.0,
    }


def explain_prediction(
    features: dict[str, float], weights: dict[str, float]
) -> list[dict[str, Any]]:
    """Glass-box decomposition: how much did each feature contribute to p?

    Returns a list of ``{feature, value, weight, contribution}`` sorted by
    absolute contribution. ``contribution = weight * value`` — the signed term
    in the weighted sum before the sigmoid. The operator sees exactly WHY Ralph
    predicted p (which features pushed it up, which pushed it down).
    """
    # Annotated, not inferred: the mixed str/float values would otherwise make
    # this list[dict[str, object]] and abs(x["contribution"]) untypeable.
    items: list[dict[str, Any]] = []
    for name, val in features.items():
        w = weights.get(name, 0.0)
        items.append({"feature": name, "value": val, "weight": w, "contribution": w * val})
    items.sort(key=lambda x: abs(x["contribution"]), reverse=True)
    return items


@dataclass
class PendingReview:
    """One flagged-and-reverted promotion, queued for a human decision."""

    sha: str
    index: int
    target: str
    kind: str  # ImprovementKind.value — plain str for JSON round-tripping
    action_class: str
    features: dict[str, float]
    predicted_p: float
    theta: float
    flagged_at: str
    note: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> PendingReview:
        return cls(**json.loads(text))


class RlphdStateStore:
    """A single human-readable JSON file holding every action_class's glass-box
    model + adaptive theta. Loaded once, saved after every prediction or
    update — the file IS the durable state, no separate DB.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._models: dict[str, RlphdModel] = {}
        self._thetas: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for action_class, entry in data.get("models", {}).items():
            self._models[action_class] = RlphdModel(
                feature_weights=entry.get("feature_weights", {})
            )
        self._thetas.update(data.get("thetas", {}))

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "models": {
                ac: {"feature_weights": m.feature_weights} for ac, m in self._models.items()
            },
            "thetas": self._thetas,
        }
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def model_for(self, action_class: str) -> RlphdModel:
        return self._models.setdefault(action_class, RlphdModel())

    def theta_for(self, action_class: str) -> float:
        return self._thetas.get(action_class, COLD_START_THETA)

    def predict(self, action_class: str, features: dict[str, float]) -> tuple[float, float]:
        """Returns (p, theta) — does NOT persist; call after a decision to learn."""
        return self.model_for(action_class).predict(features), self.theta_for(action_class)

    # Theta moves only a small fraction as fast as the tool-call RLPHD
    # default (DEFAULT_SURPRISE_GAIN=0.3 / DEFAULT_CONFIRM_GAIN=0.03) — here,
    # a denial is mostly a verdict on the CODE a competitor wrote, not on the
    # reviewer's own risk tolerance, so the trust bar should drift, not swing,
    # in response. The feature weights (DEFAULT_LEARNING_RATE, unmodified)
    # stay the primary, fast-moving signal — see record_decision.
    _THETA_SURPRISE_GAIN = 0.03
    _THETA_CONFIRM_GAIN = 0.003

    def record_decision(
        self,
        action_class: str,
        features: dict[str, float],
        predicted_p: float,
        theta: float,
        decision: Literal["approve", "deny"],
    ) -> None:
        """Update the feature weights (the primary signal), and nudge theta
        only slightly.

        A human decision here is mostly evidence about WHICH CHARACTERISTICS
        predict approval (raise the weight on features present in an
        approved promotion, lower it for a denied one) — that's the "why,"
        and it's where most of the learning belongs. A denial is a verdict
        on the CODE a (possibly different) competitor model wrote, not on
        the reviewer's own risk tolerance, so unlike tool-call RLPHD, theta
        moves at a small fraction of the normal gain rather than swinging on
        every decision — a stable trust bar that drifts slowly as evidence
        accumulates, not one that reacts sharply to a single verdict.
        """
        from maistro.security.sentinel.rlphd import update_theta

        model = self.model_for(action_class)
        # Pass theta so the weight step scales with the confidence gap |p - theta|
        # (confident-wrong predictions teach the most); theta itself drifts via
        # update_theta below.
        updated = model.update(features, decision, predicted_p, theta=theta)
        self._models[action_class] = updated
        new_theta = update_theta(
            theta,
            predicted_p,
            decision,
            surprise_gain=self._THETA_SURPRISE_GAIN,
            confirm_gain=self._THETA_CONFIRM_GAIN,
        )
        self._thetas[action_class] = new_theta
        self.save()


def flag_for_review(
    flagged_dir: Path,
    review: PendingReview,
    patch_text: str,
) -> None:
    """Save the original patch + its review metadata — nothing is discarded,
    only kept out of the ratchet's forward path until a human rules on it."""
    flagged_dir.mkdir(parents=True, exist_ok=True)
    stem = review.sha[:12]
    (flagged_dir / f"{stem}.patch").write_text(patch_text, encoding="utf-8")
    (flagged_dir / f"{stem}.json").write_text(review.to_json(), encoding="utf-8")


def save_kept_review(
    kept_dir: Path,
    review: PendingReview,
    patch_text: str,
) -> None:
    """Persist a review record for an auto-KEPT promotion (p >= theta).

    Without this, the features/predicted_p/theta are only in logs and a human
    cannot override the auto-keep or feed their decision back to RLPHD. The
    ``kept/`` directory parallels ``flagged/`` — same shape (.patch + .json per
    sha), resolved the same way via ``resolve_review``.
    """
    kept_dir.mkdir(parents=True, exist_ok=True)
    stem = review.sha[:12]
    (kept_dir / f"{stem}.patch").write_text(patch_text, encoding="utf-8")
    (kept_dir / f"{stem}.json").write_text(review.to_json(), encoding="utf-8")


def load_pending_reviews(flagged_dir: Path) -> list[PendingReview]:
    """Every flagged item that hasn't yet been resolved (no matching
    ``.decision.json`` sidecar)."""
    if not flagged_dir.is_dir():
        return []
    out = []
    for meta_file in sorted(flagged_dir.glob("*.json")):
        if meta_file.name.endswith(".decision.json"):
            continue
        decision_file = meta_file.with_suffix(".decision.json")
        if decision_file.exists():
            continue
        try:
            out.append(PendingReview.from_json(meta_file.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return out


def load_kept_reviews(kept_dir: Path) -> list[PendingReview]:
    """Auto-kept promotions (p >= theta) that haven't been human-reviewed yet.
    Same shape as load_pending_reviews but reads from the ``kept/`` directory."""
    return load_pending_reviews(kept_dir)


def resolve_review(
    flagged_dir: Path,
    export_dir: Path,
    state_path: Path,
    sha: str,
    decision: Literal["approve", "deny"],
) -> PendingReview:
    """Apply a human's decision: update the RLPHD model/theta (learning for
    next time), and — on approve — move the saved patch into ``export_dir`` so
    the normal harvest/resume machinery picks it back up exactly like any
    other promotion. On deny, the patch stays in ``flagged_dir`` (audit trail),
    just marked resolved so it stops appearing as pending.
    """
    stem = sha[:12]
    meta_file = flagged_dir / f"{stem}.json"
    if not meta_file.is_file():
        raise FileNotFoundError(f"no pending review for sha {sha!r} in {flagged_dir}")
    review = PendingReview.from_json(meta_file.read_text(encoding="utf-8"))

    store = RlphdStateStore(state_path)
    store.record_decision(
        review.action_class, review.features, review.predicted_p, review.theta, decision
    )

    (flagged_dir / f"{stem}.decision.json").write_text(
        json.dumps({"decision": decision, "resolved_at": datetime.now(UTC).isoformat()}, indent=2),
        encoding="utf-8",
    )

    if decision == "approve":
        patch_file = flagged_dir / f"{stem}.patch"
        export_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(export_dir.glob("*.patch"))
        next_n = len(existing) + 1
        dest = export_dir / f"{next_n:04d}-approved-{stem[:8]}.patch"
        dest.write_text(patch_file.read_text(encoding="utf-8"), encoding="utf-8")

    return review


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
