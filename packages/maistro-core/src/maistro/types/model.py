"""Model routing types.

Represents model configurations, provider configurations, scored candidates,
and the final model selection result. Used by the router and the API layer.

Also hosts the canonical billing-cycle vocabulary and the single daily-budget
normalization formula (#1205): the router's scarcity scorer and the quota
trackers must never grow a second, diverging copy of that arithmetic. Unknown
billing-cycle values fail explicitly here instead of silently meaning monthly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast, get_args

#: The supported billing-cycle vocabulary. Anything outside it must fail
#: explicitly (`validate_billing_cycle`), never fall through to "treat it as
#: monthly" — that silent fallback is what let a typo'd config read as a
#: valid monthly plan (#1205).
BillingCycle = Literal["daily", "monthly"]

SUPPORTED_BILLING_CYCLES: tuple[str, ...] = get_args(BillingCycle)


class UnknownBillingCycleError(ValueError):
    """A billing-cycle value outside `SUPPORTED_BILLING_CYCLES` was consumed."""


def validate_billing_cycle(billing_cycle: str) -> BillingCycle:
    """Return `billing_cycle` narrowed to the vocabulary, or raise.

    The boundary seam: `ProviderConfig.billing_cycle` arrives as an untyped
    config string, so every consumer that keys arithmetic or bucketing on it
    calls this first rather than string-comparing against one literal and
    silently treating the complement as monthly.
    """
    if billing_cycle not in SUPPORTED_BILLING_CYCLES:
        raise UnknownBillingCycleError(
            f"unsupported billing_cycle {billing_cycle!r}; "
            f"supported values: {', '.join(SUPPORTED_BILLING_CYCLES)}"
        )
    return cast(BillingCycle, billing_cycle)


def normalized_daily_budget(free_tokens: int, billing_cycle: str) -> float:
    """The one daily-budget formula: the authoritative implementation.

    A daily cycle's quota is already a per-day amount; a monthly cycle's is
    flattened to a per-day rate over a 30-day month. `router.scarcity` (the
    production authority for effective cost) and `quota.billing` both consume
    this function — a future caller that grows its own copy of the arithmetic
    resurrects a second quota interpretation, which #1205 exists to prevent.
    """
    if validate_billing_cycle(billing_cycle) == "daily":
        return float(free_tokens)
    return float(free_tokens) / 30.0


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for an LLM provider."""

    status: str = "active"
    billing_cycle: str = "monthly"
    free_tokens: int = 0
    overage_cost_per_1k_input: float = 0.0
    overage_cost_per_1k_output: float = 0.0
    data_sharing: bool = False
    data_sharing_notice: str = ""


@dataclass(frozen=True)
class ModelConfig:
    """Configuration for a single LLM model."""

    provider: str = ""
    litellm_id: str = ""
    tier: str = "small"
    quality: float = 0.5
    speed: int = 100
    modality: str = "text"
    strengths: tuple[str, ...] = ()
    context_window: int = 8192


@dataclass(frozen=True)
class ModelCandidate:
    """A scored model candidate during routing."""

    model_id: str
    litellm_id: str
    provider: str
    score: float
    quality: float
    effective_cost: float
    usage_pct: float
    tier: str
    has_paygo: bool = False


@dataclass(frozen=True)
class ModelSelection:
    """The result of model selection — the chosen model plus all candidates."""

    model_id: str
    litellm_id: str
    provider: str
    score: float
    reason: str
    candidates: tuple[ModelCandidate, ...] = ()
