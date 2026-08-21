"""services/preference_calibration.py -- ADR-060 Tier 2, Persona/Workspace system."""

from __future__ import annotations

from services.preference_calibration import (
    MIN_COMPARISONS,
    PreferenceComparison,
    fit_preference_model,
)


def test_insufficient_comparisons_returns_none() -> None:
    comparisons = [
        PreferenceComparison(winner_features={"quality": 1.0}, loser_features={"quality": 0.0})
        for _ in range(MIN_COMPARISONS - 1)
    ]
    assert fit_preference_model("pm_fleet", comparisons) is None


def test_cleanly_separable_signal_calibrates_above_threshold() -> None:
    """The winner always scores higher on `quality` -- a genuinely learnable
    signal, so the fit model should predict it near-perfectly."""
    comparisons = [
        PreferenceComparison(
            winner_features={"quality": 1.0}, loser_features={"quality": 0.0 + (i % 3) * 0.05}
        )
        for i in range(30)
    ]
    model = fit_preference_model("pm_fleet", comparisons)
    assert model is not None
    assert model.persona_template_id == "pm_fleet"
    assert model.feature_names == ["quality"]
    assert model.comparisons_seen == 30
    assert model.holdout_accuracy >= 0.9
    assert model.calibrated is True


def test_uncorrelated_signal_does_not_calibrate() -> None:
    """The feature has no real relationship to who won -- a model fit on
    noise should NOT claim to be calibrated just because it was fit."""
    comparisons = []
    for i in range(30):
        # Alternate which side "wins" independent of the feature values, so
        # there is nothing for the model to learn.
        if i % 2 == 0:
            comparisons.append(
                PreferenceComparison(
                    winner_features={"quality": 0.5}, loser_features={"quality": 0.5}
                )
            )
        else:
            comparisons.append(
                PreferenceComparison(
                    winner_features={"quality": 0.5}, loser_features={"quality": 0.5}
                )
            )
    model = fit_preference_model("pm_fleet", comparisons)
    assert model is not None
    # Identical features on both sides -- the model can't do better than a
    # coin flip, so it must not be reported as calibrated.
    assert model.calibrated is False


def test_multiple_features_are_sorted_and_all_present() -> None:
    comparisons = [
        PreferenceComparison(
            winner_features={"quality": 1.0, "brevity": 0.2},
            loser_features={"quality": 0.0, "brevity": 0.8},
        )
        for _ in range(12)
    ]
    model = fit_preference_model("pm_fleet", comparisons)
    assert model is not None
    assert model.feature_names == ["brevity", "quality"]
    assert len(model.weights) == 2
