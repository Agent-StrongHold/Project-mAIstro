"""SPEC-248 RLPHD applied to RSI promotions: cold-start caution, weight-only
learning from decisions (theta stays fixed — see promotion_review.py's
record_decision docstring for why), glass-box persistence, and the
flag/resolve file lifecycle (nothing is discarded, only queued)."""

from __future__ import annotations

import json
from pathlib import Path

from maistro_evolve.improvement import ImprovementKind
from maistro_rsi.promotion_review import (
    COLD_START_THETA,
    PendingReview,
    RlphdStateStore,
    action_class_for,
    extract_features,
    flag_for_review,
    load_pending_reviews,
    resolve_review,
)


def test_action_class_is_shared_across_kinds() -> None:
    # Not one class per ImprovementKind (9 members would mean 9 independent
    # cold starts) — a single shared class, kind lives in the features instead.
    assert action_class_for(ImprovementKind.SPEC) == action_class_for(ImprovementKind.FEATURE)
    assert action_class_for(ImprovementKind.DOC) == "rsi_promotion"


def test_extract_features_shape_and_defaults() -> None:
    f = extract_features(regression_judge_score=0.3, composite=0.8, kind=ImprovementKind.SPEC)
    assert f == {
        "bias": 1.0,
        "judge_score": 0.3,
        "composite": 0.8,
        "is_spec_completion": 1.0,
        "is_feature": 0.0,
    }
    # judge never ran (None) -> neutral default, matching the judge's own
    # unavailable-fallback convention, not zero (which would read as "terrible").
    assert (
        extract_features(regression_judge_score=None, composite=0.5, kind=ImprovementKind.DOC)[
            "judge_score"
        ]
        == 0.7
    )


def test_cold_start_predicts_neutral_below_default_theta(tmp_path: Path) -> None:
    store = RlphdStateStore(tmp_path / "state.json")
    p, theta = store.predict("rsi_promotion", {"bias": 1.0, "judge_score": 0.9})
    # Empty feature_weights -> predict sums over ITS OWN (empty) weight dict,
    # not over the features given -> sigmoid(0) = 0.5, regardless of how good
    # the features look. Below the cold-start theta -> a first encounter of
    # any action class defaults to caution until it's been calibrated.
    assert p == 0.5
    assert theta == COLD_START_THETA
    assert p < theta


def test_approve_raises_weights_on_the_features_that_were_present(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    store = RlphdStateStore(state_path)
    features = {"bias": 1.0, "judge_score": 0.9, "composite": 0.85}
    p, theta = store.predict("rsi_promotion", features)
    store.record_decision("rsi_promotion", features, p, theta, "approve")

    reloaded = RlphdStateStore(state_path)
    new_weights = reloaded.model_for("rsi_promotion").feature_weights
    assert new_weights["judge_score"] > 0  # the feature that looked good gets credit


def test_approve_at_low_p_nudges_theta_down_a_little(tmp_path: Path) -> None:
    # A denial/approval is mostly a verdict on the CODE a competitor wrote,
    # not on the reviewer's own risk tolerance — theta should drift, not
    # swing, so it moves at a small fraction of the weight-learning rate.
    store = RlphdStateStore(tmp_path / "state.json")
    features = {"bias": 1.0, "judge_score": 0.9}
    p, theta_before = store.predict("rsi_promotion", features)
    store.record_decision("rsi_promotion", features, p, theta_before, "approve")
    theta_after = store.theta_for("rsi_promotion")
    assert theta_after < theta_before, "a surprise approval should still nudge theta down"
    assert theta_before - theta_after < 0.05, "the nudge must be small, not a swing"


def test_deny_lowers_weights_on_the_features_that_were_present(tmp_path: Path) -> None:
    store = RlphdStateStore(tmp_path / "state.json")
    features = {"bias": 1.0, "judge_score": 0.9}
    p, theta = store.predict("rsi_promotion", features)
    store.record_decision("rsi_promotion", features, p, theta, "deny")
    weights = store.model_for("rsi_promotion").feature_weights
    # Denied despite a good-looking judge_score -> that feature's apparent
    # predictive value gets pushed down, not up.
    assert weights["judge_score"] < 0


def test_state_persists_as_plain_human_readable_json(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = RlphdStateStore(path)
    features = {"bias": 1.0, "judge_score": 0.5}
    p, theta = store.predict("rsi_promotion", features)
    store.record_decision("rsi_promotion", features, p, theta, "deny")

    raw = json.loads(path.read_text(encoding="utf-8"))
    # Glass-box: every weight and theta is a plain float under a readable
    # key, not an opaque blob — a human could open this file and hand-edit it.
    assert "rsi_promotion" in raw["models"]
    assert isinstance(raw["models"]["rsi_promotion"]["feature_weights"]["judge_score"], float)
    assert isinstance(raw["thetas"]["rsi_promotion"], float)


def test_flag_and_load_pending_review(tmp_path: Path) -> None:
    flagged_dir = tmp_path / "flagged"
    review = PendingReview(
        sha="abc123def456",
        index=2,
        target="audit.py",
        kind="spec",
        action_class="rsi_promotion",
        features={"bias": 1.0},
        predicted_p=0.5,
        theta=0.7,
        flagged_at="2026-07-04T00:00:00+00:00",
    )
    flag_for_review(flagged_dir, review, "diff --git a/audit.py b/audit.py\n")

    assert (flagged_dir / "abc123def456.patch").is_file()
    pending = load_pending_reviews(flagged_dir)
    assert len(pending) == 1
    assert pending[0].sha == "abc123def456"


def test_resolved_review_no_longer_pending(tmp_path: Path) -> None:
    flagged_dir = tmp_path / "flagged"
    review = PendingReview(
        sha="abc123def456",
        index=2,
        target="audit.py",
        kind="spec",
        action_class="rsi_promotion",
        features={"bias": 1.0},
        predicted_p=0.5,
        theta=0.7,
        flagged_at="2026-07-04T00:00:00+00:00",
    )
    flag_for_review(flagged_dir, review, "diff text\n")
    resolve_review(
        flagged_dir, tmp_path / "export", tmp_path / "state.json", "abc123def456", "deny"
    )
    assert load_pending_reviews(flagged_dir) == []
    # Denied — the patch stays in flagged/ (audit trail), never moves to export.
    assert (flagged_dir / "abc123def456.patch").is_file()
    assert not (tmp_path / "export").exists()


def test_approve_moves_patch_into_export_dir(tmp_path: Path) -> None:
    flagged_dir = tmp_path / "flagged"
    review = PendingReview(
        sha="abc123def456",
        index=2,
        target="audit.py",
        kind="spec",
        action_class="rsi_promotion",
        features={"bias": 1.0},
        predicted_p=0.5,
        theta=0.7,
        flagged_at="2026-07-04T00:00:00+00:00",
    )
    flag_for_review(flagged_dir, review, "the original diff\n")
    export_dir = tmp_path / "export"
    resolve_review(flagged_dir, export_dir, tmp_path / "state.json", "abc123def456", "approve")
    exported = list(export_dir.glob("*.patch"))
    assert len(exported) == 1
    assert exported[0].read_text(encoding="utf-8") == "the original diff\n"


def test_resolve_review_unknown_sha_raises(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(FileNotFoundError):
        resolve_review(
            tmp_path / "flagged", tmp_path / "export", tmp_path / "state.json", "nosuchsha", "deny"
        )
