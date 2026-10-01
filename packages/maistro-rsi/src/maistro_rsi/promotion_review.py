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
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from maistro.security.sentinel.rlphd import COLD_START_THETA, RlphdModel
from maistro_evolve.improvement import ImprovementKind
from maistro_rsi.sensitive_paths import matches_sensitive_pattern

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


# ── the non-judgment vs judgment split (#110 / M4-A3) ────────────────────────
#
# A candidate that cleared the quarantine scan, the protected correctness
# gates and the mechanical ratchets carries DECISIVE deterministic evidence:
# promoting it needs no LLM and no human. Only candidates whose surface or
# evidence is sensitive/ambiguous escalate to the approval inbox.

ReviewPath = Literal["mechanical", "judgment"]
ReviewDecision = Literal["approve", "reject", "revise", "resume"]

DECISIONS: tuple[ReviewDecision, ...] = ("approve", "reject", "revise", "resume")

#: "deny" is the v1 name for ``reject`` — kept as a spelled-out alias so
#: existing CLI invocations, API callers and on-disk decision files keep
#: working unchanged.
_DECISION_ALIASES: dict[str, ReviewDecision] = {"deny": "reject"}


def normalize_decision(raw: str) -> ReviewDecision:
    """Map ``deny`` → ``reject`` and validate; unknown verbs are a caller bug
    (raise rather than silently treating one as another)."""
    decision = _DECISION_ALIASES.get(raw, raw)
    if decision not in DECISIONS:
        raise ValueError(f"unknown review decision {raw!r}; expected one of {DECISIONS}")
    return decision  # narrowed to the Literal by the membership check


#: The composite floor under which a promotion's mechanical evidence counts as
#: decisive enough to promote WITHOUT any judgment review. Same number as
#: RLPHD's cold-start theta on purpose: it is this system's existing answer to
#: "how confident must the evidence be before acting without a human" — the
#: mechanical path just measures that confidence deterministically (gates +
#: ratchets) instead of predicting it.
MECHANICAL_COMPOSITE_FLOOR = COLD_START_THETA


@dataclass(frozen=True)
class PromotionClassification:
    """Which path a promotion takes, and exactly why — recorded verbatim so
    the split itself is auditable, not folklore."""

    review_path: ReviewPath
    reason: str
    sensitive_paths: tuple[str, ...] = ()
    governance_override: bool = False


def classify_promotion(
    *,
    touched_paths: Sequence[str],
    judge_score: float | None,
    composite: float,
    governance_override: bool = False,
) -> PromotionClassification:
    """Route one promotion: mechanical (non-judgment) or judgment (escalate).

    Fail-closed (#110: no required judgment gate may be bypassed):
    - any touched path on the containment surface (the SAME matcher the
      quarantine gate escalates on — ``matches_sensitive_pattern``) is
      sensitive and takes the judgment path;
    - a promotion that exercised the test-inventory shrink override is
      ambiguous by governance (a human already made a judgment call on its
      oracle — they get to see the promotion too);
    - evidence below the decisiveness floor is ambiguous and takes the
      judgment path.
    Only the survivors take the mechanical path — and those need no judge at
    all, not even the predictive one.
    """
    sensitive = tuple(sorted(p for p in touched_paths if matches_sensitive_pattern(p)))
    if sensitive:
        return PromotionClassification(
            review_path="judgment",
            reason=f"sensitive_surface:{','.join(sensitive)}",
            sensitive_paths=sensitive,
            governance_override=governance_override,
        )
    if not sensitive and not touched_paths:
        # Fail closed: a promotion whose touched files cannot be determined is
        # not evidence-clean — it takes the judgment path, never the fast one.
        return PromotionClassification(
            review_path="judgment",
            reason="no_file_evidence:touch_surface_undeterminable",
            governance_override=governance_override,
        )
    if governance_override:
        return PromotionClassification(
            review_path="judgment",
            reason="test_inventory_shrink_override",
            governance_override=True,
        )
    if composite < MECHANICAL_COMPOSITE_FLOOR:
        return PromotionClassification(
            review_path="judgment",
            reason=f"weak_mechanical_evidence:composite={composite:.3f}"
            f"<{MECHANICAL_COMPOSITE_FLOOR:.3f}",
        )
    return PromotionClassification(
        review_path="mechanical",
        reason="quarantine_clean_gates_green_ratchets_green",
    )


def extract_features(
    *, regression_judge_score: float | None, composite: float, kind: ImprovementKind
) -> dict[str, float | None]:
    """Small, interpretable feature set — every weight RLPHD learns over these
    stays human-readable in the persisted JSON. ``bias`` is the standard
    constant term so the sigmoid isn't forced through the origin."""
    return {
        "bias": 1.0,
        # None means the judge never ran or was unavailable — stored as None
        # explicitly, never coerced to a passing number (#307). The old 0.7
        # default laundered an unavailable judge into a "good" feature.
        "judge_score": regression_judge_score,
        "composite": composite,
        "is_spec_completion": 1.0 if kind == ImprovementKind.SPEC else 0.0,
        "is_feature": 1.0 if kind == ImprovementKind.FEATURE else 0.0,
    }


def _known_features(features: dict[str, float | None]) -> dict[str, float]:
    """RlphdModel is float-only: an unset (None) feature is NO evidence, so it
    contributes nothing to the weighted sum and its weight learns nothing —
    dropped before predict/update rather than coerced to any number (#307)."""
    return {name: value for name, value in features.items() if value is not None}


def explain_prediction(
    features: dict[str, float | None], weights: dict[str, float]
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
        contribution = w * val if val is not None else 0.0
        items.append({"feature": name, "value": val, "weight": w, "contribution": contribution})
    items.sort(key=lambda x: abs(x["contribution"]), reverse=True)
    return items


@dataclass
class PendingReview:
    """One promotion in the review inbox: either flagged-and-reverted (awaiting
    a ruling) or auto-kept (recorded for override/calibration). New fields are
    additive with defaults so pre-split on-disk JSON keeps loading."""

    sha: str
    index: int
    target: str
    kind: str  # ImprovementKind.value — plain str for JSON round-tripping
    action_class: str
    features: dict[str, float | None]
    predicted_p: float
    theta: float
    flagged_at: str
    note: str = ""
    # ── #110: which path the promotion took, and why ──
    review_path: ReviewPath = "judgment"
    classification_reason: str = ""
    sensitive_paths: list[str] = field(default_factory=list)
    governance_override: bool = False
    # Times a reviewer sent the candidate back for another attempt (revise) —
    # the inbox slot stays open for the revised candidate.
    revision: int = 0
    # True once a reviewer resumed the candidate onto the forward path while
    # the review itself stays open (resume ≠ approve: no verdict yet).
    resumed: bool = False

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

    def predict(self, action_class: str, features: dict[str, float | None]) -> tuple[float, float]:
        """Returns (p, theta) — does NOT persist; call after a decision to learn.
        None-valued features (e.g. judge_score when the judge was unavailable)
        contribute nothing — see _known_features."""
        return (
            self.model_for(action_class).predict(_known_features(features)),
            self.theta_for(action_class),
        )

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
        features: dict[str, float | None],
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
        updated = model.update(_known_features(features), decision, predicted_p, theta=theta)
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
    ``.decision.json`` sidecar). Revision/resume event sidecars are bookkeeping,
    not resolutions — those items stay pending by design."""
    if not flagged_dir.is_dir():
        return []
    out = []
    for meta_file in sorted(flagged_dir.glob("*.json")):
        if meta_file.name.endswith((".decision.json", ".revise.json", ".resume.json")):
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


def _policy_snapshot(review: PendingReview) -> dict[str, Any]:
    """The evidence/policy state a decision was made against — persisted with
    every decision so a later reader can reconstruct WHY without logs (#110)."""
    return {
        "action_class": review.action_class,
        "predicted_p": review.predicted_p,
        "theta": review.theta,
        "features": dict(review.features),
        "review_path": review.review_path,
        "classification_reason": review.classification_reason,
        "sensitive_paths": list(review.sensitive_paths),
        "governance_override": review.governance_override,
        "revision": review.revision,
        "resumed": review.resumed,
    }


def _export_patch(export_dir: Path, stem: str, patch_text: str) -> Path:
    """Copy the patch into ``export_dir`` (the harvest/resume forward path).
    Idempotent: a resumed-then-approved patch is exported once, named for its
    first exit."""
    export_dir.mkdir(parents=True, exist_ok=True)
    existing = [
        p for p in sorted(export_dir.glob("*.patch")) if p.name.endswith(f"{stem[:8]}.patch")
    ]
    if existing:
        return existing[0]
    next_n = len(sorted(export_dir.glob("*.patch"))) + 1
    dest = export_dir / f"{next_n:04d}-approved-{stem[:8]}.patch"
    dest.write_text(patch_text, encoding="utf-8")
    return dest


def _read_patch(flagged_dir: Path, stem: str) -> str:
    """The saved patch text, or "" when none was persisted (a metadata-only
    record still resolves — there is just nothing to export)."""
    patch_file = flagged_dir / f"{stem}.patch"
    if not patch_file.is_file():
        return ""
    return patch_file.read_text(encoding="utf-8")


def resolve_review(
    flagged_dir: Path,
    export_dir: Path,
    state_path: Path,
    sha: str,
    decision: str,
    *,
    reason: str = "",
    records_dir: Path | None = None,
) -> PendingReview:
    """Apply a reviewer decision to one inbox item — deterministically (#110).

    - ``approve``: train RLPHD (an approve verdict), resolve the item, and
      re-queue its patch into ``export_dir`` so the normal harvest/resume
      machinery picks it back up exactly like any other promotion.
    - ``reject`` (v1 name: ``deny``): train RLPHD (a deny verdict), resolve the
      item; the patch stays in ``flagged_dir`` (audit trail), never exported.
    - ``revise``: send the candidate back for another attempt — NO RLPHD
      update (a revise is not an approve/deny verdict on the evidence), the
      patch is NOT exported, and the item STAYS pending with its revision
      counter bumped so the inbox keeps holding a slot for the revised
      candidate. First revise wins: a repeated revise is a no-op returning the
      recorded state.
    - ``resume``: put the reverted candidate back on the forward path (patch
      exported for harvest) WITHOUT a verdict — the review stays open for a
      later approve/reject. No RLPHD update. Idempotent: an already-resumed
      item is returned unchanged.

    Every decision persists a durable record embedding the reviewer's decision
    AND the policy/evidence snapshot it was made against (features, predicted
    p, theta, classification). When ``records_dir`` is given, the decision and
    resulting-version link are also written into the sha's promotion record.
    """
    verb = normalize_decision(decision)
    stem = sha[:12]
    meta_file = flagged_dir / f"{stem}.json"
    if not meta_file.is_file():
        raise FileNotFoundError(f"no pending review for sha {sha!r} in {flagged_dir}")
    review = PendingReview.from_json(meta_file.read_text(encoding="utf-8"))
    resolved_at = datetime.now(UTC).isoformat()

    if verb == "revise":
        revise_file = flagged_dir / f"{stem}.revise.json"
        if review.revision > 0 and revise_file.is_file():
            return review  # first revise wins — deterministic under retries
        review.revision += 1
        review.note = f"revision requested: {reason or 'no reason given'}"
        meta_file.write_text(review.to_json(), encoding="utf-8")
        revise_file.write_text(
            json.dumps(
                {
                    "decision": "revise",
                    "reason": reason,
                    "recorded_at": resolved_at,
                    "revision": review.revision,
                    "policy_snapshot": _policy_snapshot(review),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if records_dir is not None:
            link_review_decision(
                records_dir,
                sha,
                decision={
                    "outcome": "revise_requested",
                    "reason": reason,
                    "revision": review.revision,
                    "at": resolved_at,
                    "rlphd_trained": False,
                },
            )
        return review

    if verb == "resume":
        if review.resumed:
            return review  # idempotent — the candidate is already on the forward path
        patch_text = _read_patch(flagged_dir, stem)
        export_path = _export_patch(export_dir, stem, patch_text) if patch_text else None
        review.resumed = True
        meta_file.write_text(review.to_json(), encoding="utf-8")
        (flagged_dir / f"{stem}.resume.json").write_text(
            json.dumps(
                {
                    "decision": "resume",
                    "reason": reason,
                    "recorded_at": resolved_at,
                    "export_patch": export_path.name if export_path else None,
                    "policy_snapshot": _policy_snapshot(review),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if records_dir is not None:
            link_review_decision(
                records_dir,
                sha,
                decision={
                    "outcome": "resumed",
                    "reason": reason,
                    "at": resolved_at,
                    "rlphd_trained": False,
                },
                version={"export_patch": export_path.name} if export_path else None,
            )
        return review

    return _resolve_verdict(
        flagged_dir,
        export_dir,
        state_path,
        sha,
        review,
        verb,  # the only verbs left are approve/reject
        reason=reason,
        resolved_at=resolved_at,
        records_dir=records_dir,
    )


def _resolve_verdict(
    flagged_dir: Path,
    export_dir: Path,
    state_path: Path,
    sha: str,
    review: PendingReview,
    verb: Literal["approve", "reject"],
    *,
    reason: str,
    resolved_at: str,
    records_dir: Path | None,
) -> PendingReview:
    """approve / reject: a real verdict — train RLPHD, settle the item, and
    (on approve) re-queue the patch for the harvest/resume machinery."""
    stem = sha[:12]
    store = RlphdStateStore(state_path)
    # RLPHD's verdict vocabulary is v1 (approve/deny); reject maps onto deny.
    store.record_decision(
        review.action_class,
        review.features,
        review.predicted_p,
        review.theta,
        "approve" if verb == "approve" else "deny",
    )

    export_path: Path | None = None
    if verb == "approve":
        patch_text = _read_patch(flagged_dir, stem)
        if patch_text:
            export_path = _export_patch(export_dir, stem, patch_text)

    (flagged_dir / f"{stem}.decision.json").write_text(
        json.dumps(
            {
                "decision": verb,
                "reason": reason,
                "resolved_at": resolved_at,
                "review": asdict(review),
                "policy_snapshot": _policy_snapshot(review),
                "rlphd_trained": True,
                "export_patch": export_path.name if export_path else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if records_dir is not None:
        link_review_decision(
            records_dir,
            sha,
            decision={
                "outcome": verb,
                "reason": reason,
                "at": resolved_at,
                "rlphd_trained": True,
            },
            version={"export_patch": export_path.name} if export_path else None,
        )

    return review


# ── promotion records (#110): candidate ↔ evaluation ↔ decision ↔ version ───


@dataclass
class PromotionRecord:
    """The durable link-record for one promotion: the candidate commit, the
    evaluation evidence it was accepted on (the trace-note verdict/reward from
    the evaluation runs), the classification and every decision (initial and
    human), and the resulting version (the baseline lineage it produced —
    promotion sha when kept, revert sha when escalated, export patch when a
    reviewer re-queues it)."""

    candidate: dict[str, Any]
    evaluation: dict[str, Any]
    classification: dict[str, Any]
    decision: dict[str, Any]
    version: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> PromotionRecord:
        return cls(**json.loads(text))


def promotions_dir(report_dir: Path) -> Path:
    return report_dir / "promotions"


def _record_path(records_dir: Path, sha: str) -> Path:
    return records_dir / f"{sha[:12]}.json"


def write_promotion_record(records_dir: Path, record: PromotionRecord) -> Path:
    records_dir.mkdir(parents=True, exist_ok=True)
    path = _record_path(records_dir, record.candidate["sha"])
    path.write_text(record.to_json(), encoding="utf-8")
    return path


def load_promotion_record(records_dir: Path, sha: str) -> PromotionRecord | None:
    path = _record_path(records_dir, sha)
    if not path.is_file():
        return None
    try:
        return PromotionRecord.from_json(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def link_review_decision(
    records_dir: Path,
    sha: str,
    *,
    decision: dict[str, Any],
    version: dict[str, Any] | None = None,
) -> None:
    """Merge a reviewer decision (and any resulting-version link) into the
    sha's promotion record. A missing record is left missing — the reviewer
    inbox also persists the decision sidecar, so the audit trail survives even
    for promotions reviewed by an older writer that wrote no record."""
    record = load_promotion_record(records_dir, sha)
    if record is None:
        return
    record.decision.update(decision)
    if version:
        record.version.update(version)
    write_promotion_record(records_dir, record)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
