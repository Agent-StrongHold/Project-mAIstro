"""Scarcity-based effective cost computation.

Cost = 1 / ln(remaining_daily_tokens)

Providers with larger budgets are naturally cheaper.
Cost rises smoothly as tokens get consumed — no cliffs.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from maistro.types.model import normalized_daily_budget

if TYPE_CHECKING:
    from maistro.types.model import ProviderConfig

# Max in-budget scarcity cost is 1/ln(2.0) (remaining floored at 2.0). Over-quota
# paid usage must sit strictly above this ceiling so free in-budget quota always
# wins on the router's cost-in-denominator score. Public: the scorer's
# normalizer anchors its paygo band on this same value — one constant, not two
# modules that happen to agree today.
OVER_QUOTA_FLOOR: float = 1.0 / math.log(2.0) + 1.0
_OVER_QUOTA_FLOOR = OVER_QUOTA_FLOOR  # backwards-compat alias

# Returned for over-quota-without-paygo providers; the scorer FILTERS on this
# (returns None) rather than scoring it. Shared constant, not a magic number
# duplicated across two modules — changing one side used to silently disable
# the filter.
INELIGIBLE_COST: float = 999.0


def _daily_budget(provider: ProviderConfig) -> float:
    """Normalize free_tokens to a daily budget regardless of billing cycle.

    Delegates to the single canonical formula (`maistro.types.model.
    normalized_daily_budget`, #1205) — scarcity is its production authority,
    not a second implementation. An unknown `provider.billing_cycle` raises
    `UnknownBillingCycleError` here instead of silently pricing the provider
    as a monthly plan.
    """
    return normalized_daily_budget(provider.free_tokens, provider.billing_cycle)


def compute_effective_cost(usage_pct: float, provider: ProviderConfig) -> float:
    """Compute effective cost based on token scarcity.

    cost = 1 / ln(remaining_daily_tokens)

    - Providers with large budgets are naturally cheap
    - Cost rises smoothly as tokens deplete
    - Over quota without paygo: INELIGIBLE_COST (the scorer filters, never scores)
    - Over quota with paygo: above the in-budget ceiling, scaled by overage rate
    - Zero free tokens: 1.0
    """
    has_paygo = provider.overage_cost_per_1k_input > 0 or provider.overage_cost_per_1k_output > 0

    if usage_pct >= 1.0:
        if has_paygo:
            # In-budget scarcity cost lives on the 1/ln(remaining) scale and
            # tops out at 1/ln(2) (remaining floored at 2.0). Paid overage must
            # always cost MORE than any in-budget free provider, otherwise the
            # router (which divides by cost) would prefer paying over using
            # free in-budget quota. Anchor the floor just above that ceiling,
            # then add a term proportional to the average overage rate so that
            # pricier providers rank below cheaper ones.
            avg_rate = (
                provider.overage_cost_per_1k_input + provider.overage_cost_per_1k_output
            ) / 2.0
            return _OVER_QUOTA_FLOOR + avg_rate
        return INELIGIBLE_COST

    daily = _daily_budget(provider)
    if daily <= 0:
        return 1.0

    remaining = daily * max(0.01, 1.0 - usage_pct)
    return 1.0 / math.log(max(remaining, 2.0))
