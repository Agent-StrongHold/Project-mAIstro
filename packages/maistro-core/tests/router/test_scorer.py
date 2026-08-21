"""Tests for router scorer — normalization boundaries, over-quota filter, ordering."""

from __future__ import annotations

import math
from typing import ClassVar

import pytest

from maistro.router.scarcity import OVER_QUOTA_FLOOR
from maistro.router.scorer import _RAW_CEIL, _RAW_FLOOR, _normalize_cost, score_candidate

# ─── _normalize_cost boundaries ──────────────────────────────────────────────
#
# The domain is the REALISTIC band of raw scarcity costs, not the theoretical
# 1/ln(2) ceiling. Measured (2026-07): the old ceiling capped the cost term's
# influence at ~10% of the score at cost_weight=1.0, across a 1000x budget span.


class TestNormalizeCost:
    def test_zero_returns_zero(self):
        assert _normalize_cost(0.0) == 0.0

    def test_negative_returns_zero(self):
        assert _normalize_cost(-1.0) == 0.0

    def test_realistic_band_spans_zero_to_one(self):
        """The endpoints that actually occur map to the endpoints of [0, 1]."""
        assert _normalize_cost(_RAW_FLOOR) == pytest.approx(0.0, abs=0.01)
        assert _normalize_cost(_RAW_CEIL) == pytest.approx(1.0, abs=0.01)

    def test_mid_band_is_proportional(self):
        mid = (_RAW_FLOOR + _RAW_CEIL) / 2
        assert _normalize_cost(mid) == pytest.approx(0.5, abs=0.01)

    def test_paygo_is_above_every_in_budget_value(self):
        """Paid overage must never look cheaper than any free in-budget quota."""
        deep_exhaustion = 1.0 / math.log(2.0)  # theoretical in-budget max
        cheapest_paygo = _normalize_cost(OVER_QUOTA_FLOOR + 0.001)
        assert cheapest_paygo > _normalize_cost(deep_exhaustion)
        assert cheapest_paygo > 3.0

    def test_paygo_rate_ordering_preserved(self):
        assert _normalize_cost(OVER_QUOTA_FLOOR + 0.5) > _normalize_cost(OVER_QUOTA_FLOOR + 0.1)

    def test_large_budget_still_differentiates(self):
        """100M and 1B budgets produce DIFFERENT normalized costs (no floor clamp)."""
        raw_100m = 1.0 / math.log(100_000_000 * 0.9)
        raw_1b = 1.0 / math.log(1_000_000_000 * 0.9)
        norm_100m = _normalize_cost(raw_100m)
        norm_1b = _normalize_cost(raw_1b)
        assert norm_100m > norm_1b
        assert norm_100m > 0

    def test_small_budget_high_usage_near_one(self):
        """1K budget at 99% → near the top of the realistic band."""
        remaining = 1000 * 0.01
        raw = 1.0 / math.log(max(remaining, 2.0))
        result = _normalize_cost(raw)
        assert 0.8 < result <= 3.0

    def test_monotonic_across_the_full_domain(self):
        probes = [0.001, _RAW_FLOOR, 0.1, _RAW_CEIL, 0.5, 1.0, OVER_QUOTA_FLOOR + 0.01]
        normalized = [_normalize_cost(p) for p in probes]
        assert normalized == sorted(normalized)


class TestCostWeightActuallyWeighs:
    """Item-15 acceptance: the score delta between a cheap-and-good and an
    expensive-and-good model, tabulated at cost_weight 0.0 / 0.5 / 1.0.

    Under the old normalizer the maximum spread at cost_weight=1.0 was ~10%,
    while the docstring said "cost and quality weighted equally". These pin the
    new contract: ~2x at 1.0, ~sqrt(2) at 0.5, exactly 1x at 0.0.
    """

    @staticmethod
    def _score(cost_weight: float, usage_pct: float, free_tokens: int) -> float:
        class Routing:
            quality_weight = 1.0
            priority_multipliers: ClassVar[dict[str, float]] = {"standard": 1.0}

        Routing.cost_weight = cost_weight
        candidate = score_candidate(
            "m1",
            FakeModelCfg(quality=0.9),
            FakeProviderCfg(free_tokens=free_tokens),
            FakeIntent(),
            Routing(),
            usage_pct=usage_pct,
        )
        assert candidate is not None
        return candidate.score

    @pytest.mark.parametrize(
        ("cost_weight", "expected_ratio", "tolerance"),
        [
            (0.0, 1.0, 0.001),
            (0.5, 2.0**0.5, 0.15),
            (1.0, 2.0, 0.3),
        ],
    )
    def test_cheap_vs_expensive_score_ratio(self, cost_weight, expected_ratio, tolerance):
        cheap = self._score(cost_weight, usage_pct=0.0, free_tokens=1_000_000_000)
        expensive = self._score(cost_weight, usage_pct=0.99, free_tokens=10_000)
        assert cheap / expensive == pytest.approx(expected_ratio, abs=tolerance)


class TestQualityAdjustments:
    """Items 17-18: metadata absence must not outscore presence, and quality
    must not saturate into universal ties."""

    def test_unmatched_strengths_score_equals_no_strengths(self):
        """Declaring strengths that don't match this intent must cost nothing —
        the old 0.90 penalty made deleting the metadata field optimal."""

        class NoStrengthsCfg(FakeModelCfg):
            def __init__(self):
                super().__init__()
                self.strengths = []

        class UnmatchedCfg(FakeModelCfg):
            def __init__(self):
                super().__init__()
                self.strengths = ["poetry"]  # declared, not preferred by intent

        args = (FakeProviderCfg(free_tokens=10000), FakeIntent(), FakeRoutingCfg())
        none_declared = score_candidate("m1", NoStrengthsCfg(), *args, usage_pct=0.5)
        unmatched = score_candidate("m2", UnmatchedCfg(), *args, usage_pct=0.5)
        assert none_declared is not None and unmatched is not None
        assert unmatched.score == pytest.approx(none_declared.score)

    def test_matched_strengths_still_score_higher(self):
        class UnmatchedCfg(FakeModelCfg):
            def __init__(self):
                super().__init__()
                self.strengths = ["poetry"]

        args = (FakeProviderCfg(free_tokens=10000), FakeIntent(), FakeRoutingCfg())
        matched = score_candidate("m1", FakeModelCfg(), *args, usage_pct=0.5)
        unmatched = score_candidate("m2", UnmatchedCfg(), *args, usage_pct=0.5)
        assert matched is not None and unmatched is not None
        assert matched.score > unmatched.score

    def test_two_strong_models_do_not_saturate_into_a_tie(self):
        """The old double min(1.0, ...) clamp collapsed every strong model to
        quality exactly 1.0, and 1.0**anything == 1.0 — selection then fell
        through to list order. Distinct inputs must produce distinct scores."""
        args = (FakeProviderCfg(free_tokens=10000), FakeIntent(), FakeRoutingCfg())
        very_good = score_candidate("m1", FakeModelCfg(quality=0.95), *args, usage_pct=0.5)
        excellent = score_candidate("m2", FakeModelCfg(quality=1.0), *args, usage_pct=0.5)
        assert very_good is not None and excellent is not None
        assert excellent.score > very_good.score


# ─── score_candidate filter ─────────────────────────────────────────────────


class FakeModelCfg:
    def __init__(self, quality=0.8):
        self.quality = quality
        self.strengths = ["coding"]
        self.speed = 0.7
        self.litellm_id = "test-model"
        self.provider = "azure"
        self.tier = "pro"


class FakeProviderCfg:
    def __init__(self, free_tokens=10000, paygo=False):
        self.free_tokens = free_tokens
        self.billing_cycle = "daily"
        self.overage_cost_per_1k_input = 0.01 if paygo else 0
        self.overage_cost_per_1k_output = 0.02 if paygo else 0


class FakeIntent:
    tier = "standard"
    preferred_strengths: ClassVar[list[str]] = ["coding"]
    task_type = "code"


class FakeRoutingCfg:
    quality_weight = 1.0
    cost_weight = 0.4
    priority_multipliers: ClassVar[dict[str, float]] = {"standard": 1.0}


class TestScoreCandidate:
    def test_over_quota_no_paygo_returns_none(self):
        """Over quota without paygo → filtered (None), not scored."""
        result = score_candidate(
            "m1",
            FakeModelCfg(),
            FakeProviderCfg(free_tokens=1000, paygo=False),
            FakeIntent(),
            FakeRoutingCfg(),
            usage_pct=1.5,
        )
        assert result is None

    def test_over_quota_with_paygo_returns_penalized_score(self):
        """Over quota with paygo → scored, but penalized (lower than in-budget)."""
        in_budget = score_candidate(
            "m1",
            FakeModelCfg(),
            FakeProviderCfg(free_tokens=10000, paygo=True),
            FakeIntent(),
            FakeRoutingCfg(),
            usage_pct=0.5,
        )
        over_quota = score_candidate(
            "m1",
            FakeModelCfg(),
            FakeProviderCfg(free_tokens=10000, paygo=True),
            FakeIntent(),
            FakeRoutingCfg(),
            usage_pct=1.5,
        )
        assert in_budget is not None
        assert over_quota is not None
        assert over_quota.score < in_budget.score

    def test_lower_usage_scores_higher(self):
        """Less usage → cheaper → higher score."""
        low = score_candidate(
            "m1",
            FakeModelCfg(),
            FakeProviderCfg(free_tokens=10000),
            FakeIntent(),
            FakeRoutingCfg(),
            usage_pct=0.1,
        )
        high = score_candidate(
            "m1",
            FakeModelCfg(),
            FakeProviderCfg(free_tokens=10000),
            FakeIntent(),
            FakeRoutingCfg(),
            usage_pct=0.9,
        )
        assert low is not None and high is not None
        assert low.score > high.score

    def test_higher_quality_scores_higher(self):
        """Better quality → higher score at same cost."""
        good = score_candidate(
            "m1",
            FakeModelCfg(quality=0.95),
            FakeProviderCfg(free_tokens=10000),
            FakeIntent(),
            FakeRoutingCfg(),
            usage_pct=0.5,
        )
        bad = score_candidate(
            "m1",
            FakeModelCfg(quality=0.5),
            FakeProviderCfg(free_tokens=10000),
            FakeIntent(),
            FakeRoutingCfg(),
            usage_pct=0.5,
        )
        assert good is not None and bad is not None
        assert good.score > bad.score

    def test_cost_weight_zero_ignores_cost(self):
        """cost_weight=0 → same score regardless of usage."""

        class NoCostRouting:
            quality_weight = 1.0
            cost_weight = 0.0
            priority_multipliers: ClassVar[dict[str, float]] = {"standard": 1.0}

        cheap = score_candidate(
            "m1",
            FakeModelCfg(),
            FakeProviderCfg(free_tokens=10000),
            FakeIntent(),
            NoCostRouting(),
            usage_pct=0.1,
        )
        dear = score_candidate(
            "m1",
            FakeModelCfg(),
            FakeProviderCfg(free_tokens=10000),
            FakeIntent(),
            NoCostRouting(),
            usage_pct=0.9,
        )
        assert cheap is not None and dear is not None
        assert cheap.score == pytest.approx(dear.score, abs=0.001)
