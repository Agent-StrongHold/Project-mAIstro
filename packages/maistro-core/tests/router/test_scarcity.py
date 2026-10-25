"""Tests for scarcity-based effective cost computation.

The router treats cost as a denominator (``quality^x / cost^cw``): a lower
effective cost yields a higher score. Therefore an over-quota provider that
still bills (paygo) must have a *higher* effective cost than any in-budget
free provider, otherwise paid overage would outrank free in-budget quota.
"""

from __future__ import annotations

import math

from maistro.router.scarcity import compute_effective_cost
from maistro.types.model import ProviderConfig


def _free_provider() -> ProviderConfig:
    return ProviderConfig(
        billing_cycle="daily",
        free_tokens=1_000_000,
        overage_cost_per_1k_input=0.0,
        overage_cost_per_1k_output=0.0,
    )


def _paygo_provider() -> ProviderConfig:
    return ProviderConfig(
        billing_cycle="daily",
        free_tokens=1_000_000,
        overage_cost_per_1k_input=2.0,
        overage_cost_per_1k_output=6.0,
    )


class TestOverQuotaScale:
    def test_over_quota_paygo_costs_more_than_in_budget_free(self) -> None:
        # Free provider with most of its budget consumed (worst in-budget case).
        in_budget_cost = compute_effective_cost(0.99, _free_provider())
        # Over-quota paygo provider.
        over_quota_cost = compute_effective_cost(1.0, _paygo_provider())
        assert over_quota_cost > in_budget_cost

    def test_over_quota_paygo_above_max_in_budget_ceiling(self) -> None:
        # The theoretical max in-budget scarcity cost is 1/ln(2) (remaining
        # floored at 2.0). Over-quota paygo must exceed that ceiling so that
        # no in-budget free provider can ever be more expensive.
        ceiling = 1.0 / math.log(2.0)
        over_quota_cost = compute_effective_cost(1.0, _paygo_provider())
        assert over_quota_cost > ceiling

    def test_over_quota_no_paygo_is_prohibitive(self) -> None:
        no_paygo = ProviderConfig(billing_cycle="daily", free_tokens=1000)
        assert compute_effective_cost(1.0, no_paygo) == 999.0

    def test_higher_overage_rate_costs_more(self) -> None:
        cheap = ProviderConfig(
            billing_cycle="daily",
            free_tokens=1000,
            overage_cost_per_1k_input=1.0,
            overage_cost_per_1k_output=1.0,
        )
        pricey = ProviderConfig(
            billing_cycle="daily",
            free_tokens=1000,
            overage_cost_per_1k_input=10.0,
            overage_cost_per_1k_output=10.0,
        )
        assert compute_effective_cost(1.0, pricey) > compute_effective_cost(1.0, cheap)

    def test_in_budget_free_unchanged_behaviour(self) -> None:
        # Fresh free budget remains cheap (well below the over-quota floor).
        fresh = compute_effective_cost(0.0, _free_provider())
        assert fresh < 1.0 / math.log(2.0)
        assert fresh > 0.0
