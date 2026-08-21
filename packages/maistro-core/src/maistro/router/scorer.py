"""Model scoring: quality^(qw*p) / (1 + normalized_cost)^cw, with speed and
strength adjustments folded into quality. This line, scorer.score_candidate's
docstring, and README.md state the same formula on purpose — they drifted into
three different ones once before.

Cost normalization:
  Raw effective_cost from scarcity is 1/ln(remaining_tokens), and the range
  REACHABLE in practice is narrow: ~0.048 (a 1B-token budget untouched) to
  ~0.217 (a small budget 99% consumed). The old normalizer divided by the
  theoretical ceiling 1/ln(2) ≈ 1.44 — reachable only with ~2 tokens left —
  which compressed every realistic cost into [0.03, 0.15] and capped the cost
  term's influence at ~10% of the score even at cost_weight=1.0. The docstring
  claimed "cost and quality weighted equally"; measurement said otherwise.

  Now raw cost maps against the realistic band [_RAW_FLOOR, _RAW_CEIL] →
  [0, 1], so at cost_weight=1.0 a fresh huge-budget provider (denominator 1.0)
  genuinely scores 2x a nearly-exhausted small one (denominator 2.0).

Over-quota handling:
  Models over quota without paygo are FILTERED (return None, not scored with a
  sentinel). Models over quota with paygo are normalized above every in-budget
  value, so free quota always wins while paid access stays rankable.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from maistro.router.scarcity import INELIGIBLE_COST, OVER_QUOTA_FLOOR, compute_effective_cost
from maistro.router.speed import compute_speed_bonus

if TYPE_CHECKING:
    from maistro.types.config import RoutingConfig
    from maistro.types.intent import Intent
    from maistro.types.model import ModelCandidate, ModelConfig, ProviderConfig

# The band of raw scarcity costs reachable with realistic budgets:
#   floor — 1B-token daily budget, barely used (cheapest realistic supply)
#   ceil  — a small (10k) budget at 99% consumption (remaining ≈ 100)
# Providers between these map linearly onto [0, 1]; the old theoretical
# ceiling 1/ln(2) sat 6x above the ceil and neutered the cost term.
_RAW_FLOOR = 1.0 / math.log(1e9)  # ≈ 0.048
_RAW_CEIL = 1.0 / math.log(100.0)  # ≈ 0.217

# In-budget normalization cap: deeper exhaustion than _RAW_CEIL keeps rising
# linearly up to here, so a provider running on fumes is strongly penalized
# but still strictly cheaper than any paid overage (which starts above it).
_NORM_CAP_IN_BUDGET = 3.0


def _normalize_cost(raw_cost: float) -> float:
    """Map raw effective_cost into the scoring domain.

    [0, 1]      — the realistic in-budget band (see module docstring)
    (1, 3]      — in-budget but deeply exhausted (remaining < ~100 tokens)
    > 3         — over-quota paygo: strictly above every in-budget value,
                  ordered by overage rate

    Monotonic in raw cost throughout, so providers with 100M and 1B budgets
    still differentiate (raw 0.054 vs 0.048 → distinct points near 0).
    """
    if raw_cost <= 0:
        return 0.0
    if raw_cost >= OVER_QUOTA_FLOOR:
        # Paid overage: anchor above the in-budget cap, keep rate ordering.
        return _NORM_CAP_IN_BUDGET + (raw_cost - OVER_QUOTA_FLOOR)
    scaled = (raw_cost - _RAW_FLOOR) / (_RAW_CEIL - _RAW_FLOOR)
    return min(max(scaled, 0.0), _NORM_CAP_IN_BUDGET)


def score_candidate(
    model_id: str,
    model_cfg: ModelConfig,
    provider_cfg: ProviderConfig,
    intent: Intent,
    routing_cfg: RoutingConfig,
    usage_pct: float,
) -> ModelCandidate | None:
    """Score a single model candidate. Returns None if ineligible (filtered).

    Formula: quality^(quality_weight * priority_mult) / (1 + normalized_cost)^cost_weight

    cost_weight semantics (with normalization against the realistic band):
      0.0 → cost ignored entirely (pure quality routing)
      0.5 → the cheapest/most expensive in-budget spread is worth ~√2 in score
      1.0 → that spread is worth 2x — cost and quality genuinely trade off
    """
    from maistro.types.model import ModelCandidate

    quality_weight = routing_cfg.quality_weight
    cost_weight = routing_cfg.cost_weight
    priority_mult = routing_cfg.priority_multipliers.get(intent.tier, 1.0)

    quality_exponent = max(0.1, quality_weight * priority_mult)

    # --- Quality ---
    preferred = set(intent.preferred_strengths)
    model_strengths = set(model_cfg.strengths)
    base_quality = model_cfg.quality

    # Declared-but-unmatched strengths score the same as declaring nothing.
    # The old 0.90 penalty made deleting the strengths field strictly optimal
    # for operators — metadata absence must never outscore metadata presence.
    strength_mult = 1.15 if preferred & model_strengths else 1.0

    # No clamp to 1.0 on either step: clamping meant every strong model
    # saturated at exactly 1.0 (and 1.0**anything == 1.0), so ties were the
    # rule and selection fell through to list order. Quality above 1.0 is
    # fine — it's an ordering signal, not a probability.
    quality = base_quality * strength_mult

    speed_bonus = compute_speed_bonus(intent.task_type, model_cfg.speed)
    adjusted_quality = quality * (1.0 + speed_bonus)

    # --- Cost ---
    effective_cost = compute_effective_cost(usage_pct, provider_cfg)

    has_paygo = (
        provider_cfg.overage_cost_per_1k_input > 0 or provider_cfg.overage_cost_per_1k_output > 0
    )
    if effective_cost >= INELIGIBLE_COST:
        return None  # Filtered — no quota, no paygo

    norm_cost = _normalize_cost(effective_cost)

    # --- Score ---
    q_factor = adjusted_quality**quality_exponent
    # (1 + norm_cost) so cost=0 doesn't divide by zero; denominator spans
    # [1, 2] across the realistic band, up to 4 on fumes, beyond for paygo.
    c_factor = (1.0 + norm_cost) ** cost_weight
    score = q_factor / c_factor

    return ModelCandidate(
        model_id=model_id,
        litellm_id=model_cfg.litellm_id or model_id,
        provider=model_cfg.provider,
        score=round(score, 4),
        quality=round(adjusted_quality, 3),
        effective_cost=round(effective_cost, 6),
        usage_pct=round(usage_pct, 4),
        tier=model_cfg.tier,
        has_paygo=has_paygo,
    )
