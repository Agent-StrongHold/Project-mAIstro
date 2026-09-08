"""#350 — magnitude pins for the model router (maistro-core).

The router's scoring formula (quality^(qw·p) / (1+normalized_cost)^cw), the
speed-bonus ladder, the priority multipliers, and the shipped default weights
decide which model serves production traffic. Existing tests assert direction
and ordering, or import the very constants they check — so mutations of the
MAGNITUDES survived (e.g. the old theoretical cost ceiling capped the cost term
at ~10% of the score while the docstring claimed "weighted equally").

Every constant here is pinned against an INDEPENDENTLY GOVERNED fixture
(``governed_magnitudes_router.json`` in this directory) whose numbers are
stated apart from the implementation, plus calibration tests that assert
literal expected values computed without the production constants — a mutated
constant cannot pass by dragging its own expectation along.

No production values are changed by this file; it only pins them.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import ClassVar

import pytest

from maistro.config import settings as settings_module
from maistro.router.scarcity import INELIGIBLE_COST, OVER_QUOTA_FLOOR
from maistro.router.scorer import (
    _NORM_CAP_IN_BUDGET,
    _RAW_CEIL,
    _RAW_FLOOR,
    score_candidate,
)
from maistro.router.speed import _MAX_SPEED, SPEED_WEIGHTS, compute_speed_bonus
from maistro.types.config import RoutingConfig as TypesRoutingConfig

_FIXTURE = json.loads(
    (Path(__file__).parent / "governed_magnitudes_router.json").read_text(encoding="utf-8")
)
_FX = _FIXTURE["entries"]


# ─── shipped routing defaults (two copies that must agree) ──────────────────


def test_default_weights_are_pinned_by_the_governed_fixture() -> None:
    expected = _FX["routing.default_weights"]["value"]
    cfg = TypesRoutingConfig()
    assert cfg.quality_weight == expected["quality_weight"]
    assert cfg.cost_weight == expected["cost_weight"]
    assert cfg.reserve_pct == expected["reserve_pct"]


def test_default_priority_multipliers_are_pinned_by_the_governed_fixture() -> None:
    assert (
        TypesRoutingConfig().priority_multipliers
        == _FX["routing.default_priority_multipliers"]["value"]
    )


def test_settings_routing_config_cannot_drift_from_types_config() -> None:
    # settings.py carries its own RoutingConfig for YAML-loaded Settings; the
    # two shipped defaults must stay identical or operator config and
    # programmatic config route differently at the same declared values.
    expected = _FX["routing.default_weights"]["value"]
    cfg = settings_module.RoutingConfig()
    assert cfg.quality_weight == expected["quality_weight"]
    assert cfg.cost_weight == expected["cost_weight"]
    assert cfg.reserve_pct == expected["reserve_pct"]
    assert cfg.priority_multipliers == _FX["routing.default_priority_multipliers"]["value"]


def test_priority_ladder_is_monotone_with_p2_neutral() -> None:
    mults = TypesRoutingConfig().priority_multipliers
    tiers = [mults[f"P{i}"] for i in range(6)]
    assert tiers == sorted(tiers, reverse=True)
    assert mults["P2"] == 1.0


# ─── speed bonus ladder ─────────────────────────────────────────────────────


def test_speed_weights_are_pinned_by_the_governed_fixture() -> None:
    assert _FX["speed.SPEED_WEIGHTS"]["value"] == SPEED_WEIGHTS


def test_max_speed_is_pinned_by_the_governed_fixture() -> None:
    assert _FX["speed._MAX_SPEED"]["value"] == _MAX_SPEED


def test_speed_bonus_calibrates_the_ladder_with_literal_values() -> None:
    # Full-speed automation earns exactly its 0.25 weight; half speed exactly
    # half; code/reasoning earn nothing however fast (quality is everything);
    # an unlisted task type earns nothing.
    assert compute_speed_bonus("automation", 2000) == pytest.approx(0.25)
    assert compute_speed_bonus("automation", 1000) == pytest.approx(0.125)
    assert compute_speed_bonus("chat", 2000) == pytest.approx(0.15)
    assert compute_speed_bonus("code", 2000) == 0.0
    assert compute_speed_bonus("reasoning", 2000) == 0.0
    assert compute_speed_bonus("unknown-task", 2000) == 0.0
    # beyond the anchor the bonus saturates rather than growing unbounded
    assert compute_speed_bonus("automation", 9000) == pytest.approx(0.25)


# ─── scorer cost band and strength multiplier ───────────────────────────────


def test_cost_band_is_pinned_by_the_governed_fixture() -> None:
    expected = _FX["scorer.cost_band"]["value"]
    assert pytest.approx(expected["raw_floor"], abs=1e-12) == _RAW_FLOOR
    assert pytest.approx(expected["raw_ceil"], abs=1e-12) == _RAW_CEIL
    assert expected["norm_cap_in_budget"] == _NORM_CAP_IN_BUDGET


def test_cost_band_is_derived_from_the_stated_budgets() -> None:
    # floor = 1/ln(1e9) (1B-token budget, barely used), ceil = 1/ln(100)
    # (10k budget at 99% consumed). A mutated literal (1e9 -> 1e6) breaks the
    # derivation even if the fixture row above were edited to match.
    assert pytest.approx(1.0 / math.log(1e9), abs=1e-12) == _RAW_FLOOR
    assert pytest.approx(1.0 / math.log(100.0), abs=1e-12) == _RAW_CEIL
    assert _RAW_FLOOR < _RAW_CEIL


def test_over_quota_floor_is_pinned_and_sits_above_the_in_budget_band() -> None:
    assert pytest.approx(_FX["scarcity.OVER_QUOTA_FLOOR"]["value"], abs=1e-12) == OVER_QUOTA_FLOOR
    assert pytest.approx(1.0 / math.log(2.0) + 1.0, abs=1e-12) == OVER_QUOTA_FLOOR
    # the invariant the floor exists for: paid overage starts strictly above
    # every raw in-budget cost, so free quota always wins
    assert OVER_QUOTA_FLOOR > _RAW_CEIL


def test_ineligible_cost_is_pinned_by_the_governed_fixture() -> None:
    assert _FX["scarcity.INELIGIBLE_COST"]["value"] == INELIGIBLE_COST


# ─── end-to-end score calibration with the shipped defaults ─────────────────
#
# One fixed scenario through score_candidate with the REAL RoutingConfig
# defaults, asserting literal outputs: quality 0.8 model, matched "coding"
# strength, task_type "code" (no speed bonus), 10k-token provider at 50% use.
#   adjusted_quality = 0.8 * 1.15                      = 0.92
#   raw cost         = 1/ln(5000)                      ≈ 0.117410
#   norm cost        = (0.117410-0.048255)/0.168892    ≈ 0.409448
#   score            = 0.92^0.6 / 1.409448^0.4         = 0.8292
# A mutation anywhere in the defaults, the band, or the strength multiplier
# moves at least one of these three literals.


class _ModelCfg:
    quality = 0.8
    strengths: ClassVar[list[str]] = ["coding"]
    tier = "standard"
    litellm_id = "lit/m"
    provider = "p"
    speed = 0


class _ProviderCfg:
    free_tokens = 10_000
    billing_cycle = "daily"
    overage_cost_per_1k_input = 0.0
    overage_cost_per_1k_output = 0.0


class _Intent:
    tier = "standard"
    preferred_strengths: ClassVar[list[str]] = ["coding"]
    task_type = "code"


class _NoStrengthCfg(_ModelCfg):
    strengths: ClassVar[list[str]] = ["bogus"]


def test_default_weights_calibrate_a_full_score_with_literal_values() -> None:
    candidate = score_candidate(
        "m1", _ModelCfg(), _ProviderCfg(), _Intent(), TypesRoutingConfig(), usage_pct=0.5
    )
    assert candidate is not None
    assert candidate.quality == pytest.approx(0.92)  # 0.8 * strength_mult 1.15
    assert candidate.effective_cost == pytest.approx(0.117410, abs=1e-6)
    assert candidate.score == pytest.approx(0.8292, abs=1e-4)


def test_strength_multiplier_calibration_matched_vs_unmatched() -> None:
    matched = score_candidate(
        "m1", _ModelCfg(), _ProviderCfg(), _Intent(), TypesRoutingConfig(), usage_pct=0.5
    )
    unmatched = score_candidate(
        "m1", _NoStrengthCfg(), _ProviderCfg(), _Intent(), TypesRoutingConfig(), usage_pct=0.5
    )
    assert matched is not None and unmatched is not None
    assert matched.quality == pytest.approx(0.92)  # exactly 1.15x
    assert unmatched.quality == pytest.approx(0.8)  # declared-but-unmatched == declaring nothing
    assert matched.score > unmatched.score
